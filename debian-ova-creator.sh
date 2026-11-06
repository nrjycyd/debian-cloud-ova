#!/bin/bash

set -e

# 此脚本仅作为 GitHub Actions 工作流的内部构建步骤使用。
if [[ "${GITHUB_ACTIONS:-}" != "true" ]]; then
    echo "[ERROR] 不再支持本地构建，请在 GitHub Actions 页面运行构建工作流。" >&2
    exit 1
fi

# 默认参数
debver=""
debarch="amd64"
vcpu=2
memory=1024
disk_size_gb=10
hostname="debian-cloud"
username="debian"
password="123456"
enable_ssh="false"

# 只读取顶层 virtual-size，避免匹配嵌套镜像信息中的同名字段。
get_virtual_size() {
    local image_info
    if ! image_info=$(qemu-img info --output=json "$1"); then
        echo "[ERROR] 无法读取镜像信息：$1" >&2
        return 1
    fi
    printf '%s\n' "$image_info" | python3 -c '
import json
import sys

try:
    size = json.load(sys.stdin)["virtual-size"]
    if type(size) is not int or not 0 < size <= 9223372036854775807:
        raise ValueError("virtual-size 必须为有效的正整数字节数")
except (ValueError, KeyError, TypeError) as error:
    sys.exit("[ERROR] 镜像容量 JSON 解析失败：" + str(error))
print(size)
'
}

# 解析工作流传入的内部构建参数
while getopts ":d:c:m:s:H:u:p:S:" opt; do
    case "$opt" in
        d) debver="$OPTARG" ;;
        c) vcpu="$OPTARG" ;;
        m) memory="$OPTARG" ;;
        s) disk_size_gb="$OPTARG" ;;
        H) hostname="$OPTARG" ;;
        u) username="$OPTARG" ;;
        p) password="$OPTARG" ;;
        S) enable_ssh="$OPTARG" ;;
        :) echo "[ERROR] Option -$OPTARG requires an argument" >&2; exit 1 ;;
        \?) echo "[ERROR] Invalid option -$OPTARG" >&2; exit 1 ;;
    esac
done

# Validate required parameters
if [[ -z "$debver" ]]; then
    echo "[ERROR] Debian version is required (-d)" >&2
    exit 1
fi

# Validate hardware parameters
if ! [[ "$vcpu" =~ ^[0-9]+$ ]] || [ "$vcpu" -lt 1 ]; then
    echo "[ERROR] vCPU count must be a positive integer" >&2
    exit 1
fi

if ! [[ "$memory" =~ ^[0-9]+$ ]] || [ "$memory" -lt 256 ]; then
    echo "[ERROR] Memory must be at least 256MB" >&2
    exit 1
fi

if ! [[ "$disk_size_gb" =~ ^[0-9]+$ ]] || [ "$disk_size_gb" -lt 2 ]; then
    echo "[ERROR] Disk size must be at least 2GB" >&2
    exit 1
fi

# 按十进制规范化，避免 Bash 将 08 等带前导零的参数当作八进制。
disk_size_gb=$((10#$disk_size_gb))

# Validate username/password characters（防换行符注入 chpasswd / YAML 破坏）
case "$enable_ssh" in
    true) username="root" ;;
    false)
        if [[ "$username" == "root" ]]; then
            echo "[ERROR] SSH 关闭时请使用普通用户名；root 登录请在构建面板启用 SSH。" >&2
            exit 1
        fi
        ;;
    *) echo "[ERROR] SSH option must be true or false" >&2; exit 1 ;;
esac
if ! [[ "$username" =~ ^[a-z_][a-z0-9_-]{0,31}$ ]]; then
    echo "[ERROR] Username must match [a-z_][a-z0-9_-]{0,31}" >&2
    exit 1
fi
if ! [[ "$password" =~ ^[A-Za-z0-9@#%+=.,_-]+$ ]]; then
    echo "[ERROR] Password contains invalid characters (allowed: letters/digits/@#%+=.,_-)" >&2
    exit 1
fi

# Map Debian version to codename
case "$debver" in
    11|bullseye)
        debver="11"
        debcodename="bullseye"
        ;;
    12|bookworm)
        debver="12"
        debcodename="bookworm"
        ;;
    13|trixie)
        debver="13"
        debcodename="trixie"
        ;;
    sid)
        debver="sid"
        debcodename="sid/daily"
        debarch="amd64-daily"
        ;;
    *)
        echo "[ERROR] Unsupported Debian version: $debver" >&2
        exit 1
        ;;
esac

# Set variables
DEBIAN_VERSION="${debver}"
DEBIAN_NAME="${debcodename}"
DEBIAN_ARCH="${debarch}"
# ESXi compatibility (由环境变量覆盖，workflow 传 esxi_hardware 选项)
# 6.7  -> vmx-14
# 7.0  -> vmx-15 / vmx-17 (7.0 U1+)
# 7.0 U2+ -> vmx-19
# 8.0  -> vmx-20
VIRTUAL_SYSTEM_TYPE="${VIRTUAL_SYSTEM_TYPE:-vmx-14}" # 默认 vmx-14 (esxi6.7)

FILE_NAME="debian-${DEBIAN_VERSION}-genericcloud-${DEBIAN_ARCH}"

# 固件显示名（仅影响最终 OVA 文件名，下载/内部引用仍用 FILE_NAME）
case "${VIRTUAL_SYSTEM_TYPE%% *}" in
  vmx-14|vmx-15)             ESXI_TAG="esxi6.7" ;;
  vmx-17|vmx-18|vmx-19)      ESXI_TAG="esxi7.0" ;;
  vmx-20|vmx-21)             ESXI_TAG="esxi8.0" ;;
  vmx-22)                    ESXI_TAG="esxi9.0" ;;
  *)                         ESXI_TAG="esxi$((${VIRTUAL_SYSTEM_TYPE#vmx-}/3+2)).0" ;;
esac
FILE_ORIG_EXT="qcow2"
FILE_DEST_EXT="vmdk"
FILE_SIGN_EXT="mf"
FILE_ORIG_URL="https://cloud.debian.org/images/cloud/${DEBIAN_NAME}/latest/${FILE_NAME}.${FILE_ORIG_EXT}"

# 默认 Guest OS 标识（可由 workflow 按 ESXi 兼容性覆盖，与系统版本独立）
OVF_OS_ID="${OVF_OS_ID:-96}"
OVF_OS_TYPE="${OVF_OS_TYPE:-debian11_64Guest}"

# Guest OS 显示标识（dgnuXX，由 OVF_OS_TYPE 推导，仅影响最终 OVA 文件名）
case "${OVF_OS_TYPE}" in
  debian9_64Guest)  GUEST_TAG="dgnu9" ;;
  debian10_64Guest) GUEST_TAG="dgnu10" ;;
  debian11_64Guest) GUEST_TAG="dgnu11" ;;
  debian12_64Guest) GUEST_TAG="dgnu12" ;;
  debian13_64Guest) GUEST_TAG="dgnu13" ;;
  *)                GUEST_TAG="dgnu$(echo "${OVF_OS_TYPE}" | grep -oE '[0-9]+' | head -1)" ;;
esac
# vmx 号（去掉前缀与选项说明），文件名精确到硬件版本 + Guest 标识
VMX_NUM="${VIRTUAL_SYSTEM_TYPE%% *}"
VMX_NUM="${VMX_NUM#vmx-}"
OUTPUT_NAME="debian${DEBIAN_VERSION}-generic-cloud-${ESXI_TAG}-vmx${VMX_NUM}-${GUEST_TAG}-${DEBIAN_ARCH}"
if [[ "$enable_ssh" == "true" ]]; then
    OUTPUT_NAME="${OUTPUT_NAME}-ssh"
else
    OUTPUT_NAME="${OUTPUT_NAME}-console"
fi

CURRENT_DATE=$(date +%Y%m%d)
disk_size_bytes=$((disk_size_gb * 1073741824))

echo "[INFO] Debian OVA Creator - Build Started"
echo "[INFO] Debian Version: $DEBIAN_VERSION"
echo "[INFO] Architecture: $DEBIAN_ARCH"
echo "[INFO] vCPU: $vcpu"
echo "[INFO] Memory: ${memory}MB"
echo "[INFO] Disk: ${disk_size_gb}GB"
echo "[INFO] Hostname: $hostname"
echo "[INFO] Username: $username"
echo "[INFO] SSH Enabled: $enable_ssh"
echo ""

# --- 区域 1: ConfigDrive ISO 生成 (NoCloud 模式) ---

# 生成 Cloud-Init config (user-data) 和 Meta-data 文件
CLOUD_CONFIG_FILE=$(mktemp)
META_CONFIG_FILE=$(mktemp)

# 1. User-Data (Cloud-Config) 内容
cat > "$CLOUD_CONFIG_FILE" << 'EOFCONFIG'
#cloud-config
EOFCONFIG

cat >> "$CLOUD_CONFIG_FILE" << EOFCONFIG
users:
  - name: $username
    shell: /bin/bash
    lock_passwd: false
EOFCONFIG
if [[ "$enable_ssh" == "false" ]]; then
    cat >> "$CLOUD_CONFIG_FILE" << 'EOFCONFIG'
    sudo: ALL=(ALL) NOPASSWD:ALL
EOFCONFIG
fi
cat >> "$CLOUD_CONFIG_FILE" << EOFCONFIG

ssh_pwauth: $enable_ssh
disable_root: $([[ "$enable_ssh" == "true" ]] && echo false || echo true)

chpasswd:
  list: |
    $username:$password
  expire: false

packages:
  - cloud-init
  - open-vm-tools
  - openssh-server
EOFCONFIG

# 关闭模式在启动早期即屏蔽服务和 socket，避免安装包启动 SSH。
if [[ "$enable_ssh" == "false" ]]; then
    cat >> "$CLOUD_CONFIG_FILE" << 'EOFCONFIG'

bootcmd:
  - [ systemctl, mask, --now, ssh.service, ssh.socket ]
EOFCONFIG
fi
cat >> "$CLOUD_CONFIG_FILE" << 'EOFCONFIG'

write_files:
  - path: /usr/local/sbin/configure-ova-ssh
    owner: root:root
    permissions: '0700'
    content: |
      #!/bin/sh
      set -eu
      case "$1" in
        true)
          config=/etc/ssh/sshd_config
          if [ ! -f "$config.ova-backup" ]; then
            cp -p "$config" "$config.ova-backup"
          fi
          # 在主配置开头设置，确保先于其他配置文件中的默认认证选项生效。
          sed -i '/^# BEGIN OVA SSH$/,/^# END OVA SSH$/d' "$config"
          temp_config=$(mktemp)
          trap 'rm -f "$temp_config"' EXIT
          {
            printf '%s\n' '# BEGIN OVA SSH' 'PermitRootLogin yes' 'PasswordAuthentication yes' '# END OVA SSH'
            cat "$config"
          } > "$temp_config"
          install -m 0600 "$temp_config" "$config"
          mkdir -p /run/sshd
          ssh-keygen -A
          /usr/sbin/sshd -t
          effective=$(/usr/sbin/sshd -T -C user=root,host=localhost,addr=127.0.0.1)
          printf '%s\n' "$effective" | grep -qx 'permitrootlogin yes'
          printf '%s\n' "$effective" | grep -qx 'passwordauthentication yes'
          systemctl mask --now ssh.socket
          systemctl unmask ssh.service
          systemctl enable ssh.service
          systemctl restart ssh.service
          ;;
        false)
          systemctl disable ssh.service
          systemctl mask --now ssh.service ssh.socket
          ;;
        *) echo '[ERROR] Invalid SSH mode' >&2; exit 1 ;;
      esac

runcmd:
EOFCONFIG
cat >> "$CLOUD_CONFIG_FILE" << EOFCONFIG
  - [ /usr/local/sbin/configure-ova-ssh, "$enable_ssh" ]
EOFCONFIG
cat >> "$CLOUD_CONFIG_FILE" << 'EOFCONFIG'
  - [ systemctl, daemon-reload ]
  - [ systemctl, enable, open-vm-tools ]
  - [ systemctl, start, open-vm-tools ]
EOFCONFIG

# --- User-Data 结束 ---

# 2. Meta-data (必须包含 instance-id 和 hostname)
INSTANCE_ID="${FILE_NAME}-${CURRENT_DATE}-$(head /dev/urandom | tr -dc A-Za-z0-9 | head -c 8)"

cat > "$META_CONFIG_FILE" << EOFMETA
instance-id: ${INSTANCE_ID}
local-hostname: ${hostname}
EOFMETA
# --- Meta-data 结束 ---

# 3. 使用 cloud-localds 创建 ConfigDrive ISO
ISO_FILE_NAME="cidata.iso"
echo "[INFO] Generating NoCloud ConfigDrive ISO using cloud-localds: ${ISO_FILE_NAME}"

# cloud-localds 自动处理 ConfigDrive 格式，并将文件标记为 CIDATA
cloud-localds "$ISO_FILE_NAME" "$CLOUD_CONFIG_FILE" "$META_CONFIG_FILE"

rm -f "$CLOUD_CONFIG_FILE" "$META_CONFIG_FILE"

echo "[INFO] ConfigDrive ISO created successfully."

# 计算 ISO 文件大小，用于 OVF 引用
ISO_FILE_SIZE=$(wc -c "$ISO_FILE_NAME" | cut -d " " -f1)

# --- 区域 1: 结束 ---

# Download cloud image
if [ ! -f "${FILE_NAME}.${FILE_ORIG_EXT}" ]; then
    echo "[INFO] Downloading Debian cloud image..."
    wget -q "$FILE_ORIG_URL" -O "${FILE_NAME}.${FILE_ORIG_EXT}"
    echo "[INFO] Download completed"
else
    echo "[INFO] Cloud image already exists"
fi

# 扩容磁盘到指定大小（仅当小于目标时），保证 vmdk 虚拟大小与 OVF capacity 一致
CURRENT_BYTES=$(get_virtual_size "${FILE_NAME}.${FILE_ORIG_EXT}") || exit 1
TARGET_BYTES=$((disk_size_gb * 1073741824))
if [ "$CURRENT_BYTES" -gt "$TARGET_BYTES" ]; then
    CURRENT_GIB=$(awk -v bytes="$CURRENT_BYTES" 'BEGIN { printf "%.2f", bytes / 1073741824 }')
    echo "[WARN] 请求磁盘容量 ${disk_size_gb} GiB 小于源镜像容量 ${CURRENT_GIB} GiB，自动采用源镜像容量继续构建。"
    TARGET_BYTES=$CURRENT_BYTES
fi
disk_size_bytes=$TARGET_BYTES
ACTUAL_DISK_GIB=$(awk -v bytes="$TARGET_BYTES" 'BEGIN { printf "%.2f", bytes / 1073741824 }')
if [ "$CURRENT_BYTES" -lt "$TARGET_BYTES" ]; then
    qemu-img resize "${FILE_NAME}.${FILE_ORIG_EXT}" "${disk_size_gb}G"
    echo "[INFO] 磁盘已扩容到 ${disk_size_gb}G（开机后 cloud-init growpart 自动扩展根分区）"
fi

# Convert to VMDK format（缓存 VMDK 容量与目标不符时重新转换）
VMDK_BYTES=""
if [ -f "${FILE_NAME}.${FILE_DEST_EXT}" ]; then
    VMDK_BYTES=$(get_virtual_size "${FILE_NAME}.${FILE_DEST_EXT}") || exit 1
fi
if [ -f "${FILE_NAME}.${FILE_DEST_EXT}" ] && [ "$VMDK_BYTES" != "$TARGET_BYTES" ]; then
    echo "[WARN] VMDK 虚拟大小(${VMDK_BYTES})与目标(${TARGET_BYTES})不符，删除重转"
    rm -f "${FILE_NAME}.${FILE_DEST_EXT}"
fi
if [ ! -f "${FILE_NAME}.${FILE_DEST_EXT}" ]; then
    echo "[INFO] Converting image to VMDK format..."
    qemu-img convert -f "$FILE_ORIG_EXT" -O "$FILE_DEST_EXT" -o subformat=streamOptimized \
        "${FILE_NAME}.${FILE_ORIG_EXT}" "${FILE_NAME}.${FILE_DEST_EXT}"
    echo "[INFO] Conversion completed"
else
    echo "[INFO] VMDK file already exists"
fi

FINAL_VMDK_BYTES=$(get_virtual_size "${FILE_NAME}.${FILE_DEST_EXT}") || exit 1
if [ "$FINAL_VMDK_BYTES" != "$TARGET_BYTES" ]; then
    echo "[ERROR] VMDK 实际容量与目标容量不一致，停止打包。" >&2
    exit 1
fi
FILE_DEST_SIZE=$(wc -c "${FILE_NAME}.${FILE_DEST_EXT}" | cut -d " " -f1)

# --- 区域 2: OVF 配置修改 (禁止自动启动, 添加 ISO 引用) ---

# Generate OVF configuration
echo "[INFO] Generating OVF configuration..."
cat > "${FILE_NAME}.ovf" << EOF
<?xml version="1.0" encoding="UTF-8"?>
<Envelope xmlns="http://schemas.dmtf.org/ovf/envelope/1" xmlns:cim="http://schemas.dmtf.org/wbem/wscim/1/common" xmlns:ovf="http://schemas.dmtf.org/ovf/envelope/1" xmlns:rasd="http://schemas.dmtf.org/wbem/wscim/1/cim-schema/2/CIM_ResourceAllocationSettingData" xmlns:vmw="http://www.vmware.com/schema/ovf" xmlns:vssd="http://schemas.dmtf.org/wbem/wscim/1/cim-schema/2/CIM_VirtualSystemSettingData" xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance">
  <References>
    <File ovf:href="${FILE_NAME}.${FILE_DEST_EXT}" ovf:id="file1" ovf:size="${FILE_DEST_SIZE}"/>
    <File ovf:href="${ISO_FILE_NAME}" ovf:id="file2" ovf:size="${ISO_FILE_SIZE}"/>
  </References>
  <DiskSection>
    <Info>Virtual disk information</Info>
    <Disk ovf:capacity="${disk_size_bytes}" ovf:capacityAllocationUnits="byte" ovf:diskId="vmdisk1" ovf:fileRef="file1" ovf:format="http://www.vmware.com/interfaces/specifications/vmdk.html#streamOptimized" ovf:populatedSize="0"/>
  </DiskSection>
  <NetworkSection>
    <Info>The list of logical networks</Info>
    <Network ovf:name="VM Network">
      <Description>The VM Network network</Description>
    </Network>
  </NetworkSection>
  <VirtualSystem ovf:id="${FILE_NAME}-${CURRENT_DATE}" vmw:ovf.powerOn="false"> <Info>A virtual machine</Info>
    <Name>${FILE_NAME}-${CURRENT_DATE}</Name>
    <OperatingSystemSection ovf:id="${OVF_OS_ID}" vmw:osType="${OVF_OS_TYPE}">
      <Info>The kind of installed guest operating system</Info>
      <Description>Debian GNU/Linux ${DEBIAN_VERSION} (64-bit)</Description>
    </OperatingSystemSection>
    <VirtualHardwareSection>
      <Info>Virtual hardware requirements</Info>
      <System>
        <vssd:ElementName>Virtual Hardware Family</vssd:ElementName>
        <vssd:InstanceID>0</vssd:InstanceID>
        <vssd:VirtualSystemIdentifier>${FILE_NAME}-${CURRENT_DATE}</vssd:VirtualSystemIdentifier>
        <vssd:VirtualSystemType>${VIRTUAL_SYSTEM_TYPE}</vssd:VirtualSystemType>
      </System>
      <Item>
        <rasd:AllocationUnits>hertz * 10^6</rasd:AllocationUnits>
        <rasd:Description>Number of Virtual CPUs</rasd:Description>
        <rasd:ElementName>${vcpu} virtual CPU(s)</rasd:ElementName>
        <rasd:InstanceID>1</rasd:InstanceID>
        <rasd:ResourceType>3</rasd:ResourceType>
        <rasd:VirtualQuantity>${vcpu}</rasd:VirtualQuantity>
      </Item>
      <Item>
        <rasd:AllocationUnits>byte * 2^20</rasd:AllocationUnits>
        <rasd:Description>Memory Size</rasd:Description>
        <rasd:ElementName>${memory}MB of memory</rasd:ElementName>
        <rasd:InstanceID>2</rasd:InstanceID>
        <rasd:ResourceType>4</rasd:ResourceType>
        <rasd:VirtualQuantity>${memory}</rasd:VirtualQuantity>
      </Item>
      <Item>
        <rasd:Address>0</rasd:Address>
        <rasd:Description>SCSI Controller</rasd:Description>
        <rasd:ElementName>SCSI Controller 0</rasd:ElementName>
        <rasd:InstanceID>3</rasd:InstanceID>
        <rasd:ResourceSubType>VirtualSCSI</rasd:ResourceSubType>
        <rasd:ResourceType>6</rasd:ResourceType>
      </Item>
      <Item>
        <rasd:AddressOnParent>0</rasd:AddressOnParent>
        <rasd:ElementName>Hard Disk 1</rasd:ElementName>
        <rasd:HostResource>ovf:/disk/vmdisk1</rasd:HostResource>
        <rasd:InstanceID>10</rasd:InstanceID>
        <rasd:Parent>3</rasd:Parent>
        <rasd:ResourceType>17</rasd:ResourceType>
      </Item>
      <Item>
        <rasd:Address>0</rasd:Address>
        <rasd:Description>IDE Controller</rasd:Description>
        <rasd:ElementName>IDE Controller 0</rasd:ElementName>
        <rasd:InstanceID>5</rasd:InstanceID>
        <rasd:ResourceType>5</rasd:ResourceType>
      </Item>
      <Item>
        <rasd:AddressOnParent>0</rasd:AddressOnParent>
        <rasd:AutomaticAllocation>false</rasd:AutomaticAllocation>
        <rasd:ElementName>CD/DVD Drive 1 (ConfigDrive)</rasd:ElementName>
        <rasd:HostResource>ovf:/file/file2</rasd:HostResource>
        <rasd:InstanceID>11</rasd:InstanceID>
        <rasd:Parent>5</rasd:Parent>
        <rasd:ResourceType>15</rasd:ResourceType>
      </Item>
      <Item>
        <rasd:AddressOnParent>7</rasd:AddressOnParent>
        <rasd:AutomaticAllocation>true</rasd:AutomaticAllocation>
        <rasd:Connection>VM Network</rasd:Connection>
        <rasd:Description>VmxNet3 ethernet adapter</rasd:Description>
        <rasd:ElementName>Ethernet 1</rasd:ElementName>
        <rasd:InstanceID>12</rasd:InstanceID>
        <rasd:ResourceSubType>VmxNet3</rasd:ResourceSubType>
        <rasd:ResourceType>10</rasd:ResourceType>
      </Item>
    </VirtualHardwareSection>
  </VirtualSystem>
</Envelope>
EOF

# --- 区域 2: 结束 ---

# Generate manifest file
echo "[INFO] Generating checksum manifest..."
FILE_DEST_SUM=$(sha256sum "${FILE_NAME}.${FILE_DEST_EXT}" | cut -d " " -f1)
FILE_OVF_SUM=$(sha256sum "${FILE_NAME}.ovf" | cut -d " " -f1)
ISO_FILE_SUM=$(sha256sum "${ISO_FILE_NAME}" | cut -d " " -f1)

cat > "${FILE_NAME}.${FILE_SIGN_EXT}" << MANIFEST
SHA256(${FILE_NAME}.${FILE_DEST_EXT})= ${FILE_DEST_SUM}
SHA256(${FILE_NAME}.ovf)= ${FILE_OVF_SUM}
SHA256(${ISO_FILE_NAME})= ${ISO_FILE_SUM}
MANIFEST

# --- 区域 3: OVA 打包 (包含 ISO 文件) ---

# Package OVA file
echo "[INFO] Packaging OVA file..."
tar -cf "${OUTPUT_NAME}.ova" \
    "${FILE_NAME}.ovf" \
    "${FILE_NAME}.${FILE_SIGN_EXT}" \
    "${FILE_NAME}.${FILE_DEST_EXT}" \
    "${ISO_FILE_NAME}" # 关键：打包 ConfigDrive ISO

# --- 区域 3: 结束 ---

OVA_SIZE=$(du -h "${OUTPUT_NAME}.ova" | cut -f1)

# 删除 ConfigDrive ISO（已包含在 OVA 中），避免本地构建残留
rm -f "${ISO_FILE_NAME}"

echo ""
echo "[INFO] Build Successfully Completed!"
echo "[INFO] OVA File: ${OUTPUT_NAME}.ova"
echo "[INFO] File Size: ${OVA_SIZE}"
echo "[INFO] Debian Version: ${DEBIAN_VERSION}"
echo "[INFO] vCPU: ${vcpu}"
echo "[INFO] Memory: ${memory}MB"
echo "[INFO] Requested Disk: ${disk_size_gb} GiB"
echo "[INFO] Actual Disk: ${ACTUAL_DISK_GIB} GiB"
echo "[INFO] Hostname: ${hostname}"
echo "[INFO] Default User: ${username}"
echo "[INFO] SSH Enabled: ${enable_ssh}"
echo "[INFO] Config Method: NoCloud/ConfigDrive (ISO)"
echo "[INFO] Auto Start: Disabled"
echo ""

if [[ -n "${GITHUB_OUTPUT:-}" ]]; then
    printf 'ACTUAL_DISK_GIB=%s\nACTUAL_DISK_BYTES=%s\n' "$ACTUAL_DISK_GIB" "$TARGET_BYTES" >> "$GITHUB_OUTPUT"
    printf 'LOGIN_USERNAME=%s\nSSH_ENABLED=%s\n' "$username" "$enable_ssh" >> "$GITHUB_OUTPUT"
fi
