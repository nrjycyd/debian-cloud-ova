#!/bin/bash

set -e

# 默认参数
debver=""
debarch="amd64"
vcpu=2
memory=1024
disk_size_gb=10
hostname="debian-cloud"
username="debian"
password="123456"
ssh_public_key=""

show_help() {
    cat << 'EOF'
Usage: debian-ova-creator.sh [options]

Debian Version Options:
  -d <version>         Debian version (REQUIRED)
                       Supported: 11, 12, 13, bullseye, bookworm, trixie, sid

Hardware Options:
  -c <vcpu>            Number of vCPUs (default: 2)
  -m <memory>          Memory in MB (default: 1024)
  -s <disk_gb>         Disk size in GB (default: 10)

Account Options:
  -H <hostname>        Hostname (default: debian-cloud)
  -u <username>        Default username (default: debian)
  -p <password>        User password (default: 123456)
  -k <ssh_key_file>    SSH public key file (optional)

Other Options:
  -h                   Show this help message

Examples:
  debian-ova-creator.sh -d bookworm
  debian-ova-creator.sh -d 12 -c 4 -m 2048 -s 20
EOF
}

# Parse command line arguments
while getopts ":d:c:m:s:H:u:p:k:h" opt; do
    case "$opt" in
        d) debver="$OPTARG" ;;
        c) vcpu="$OPTARG" ;;
        m) memory="$OPTARG" ;;
        s) disk_size_gb="$OPTARG" ;;
        H) hostname="$OPTARG" ;;
        u) username="$OPTARG" ;;
        p) password="$OPTARG" ;;
        k) ssh_public_key="$OPTARG" ;;
        h) show_help; exit 0 ;;
        :) echo "❌ Error: Option -$OPTARG requires an argument" >&2; exit 1 ;;
        \?) echo "❌ Error: Invalid option -$OPTARG" >&2; exit 1 ;;
    esac
done

# Validate required parameters
if [[ -z "$debver" ]]; then
    echo "❌ Error: Debian version is required (-d)" >&2
    show_help
    exit 1
fi

# Validate hardware parameters
if ! [[ "$vcpu" =~ ^[0-9]+$ ]] || [ "$vcpu" -lt 1 ]; then
    echo "❌ Error: vCPU count must be a positive integer" >&2
    exit 1
fi

if ! [[ "$memory" =~ ^[0-9]+$ ]] || [ "$memory" -lt 256 ]; then
    echo "❌ Error: Memory must be at least 256MB" >&2
    exit 1
fi

if ! [[ "$disk_size_gb" =~ ^[0-9]+$ ]] || [ "$disk_size_gb" -lt 2 ]; then
    echo "❌ Error: Disk size must be at least 2GB" >&2
    exit 1
fi

# Validate SSH key file if provided
if [[ -n "$ssh_public_key" ]] && [[ ! -f "$ssh_public_key" ]]; then
    echo "❌ Error: SSH public key file not found: $ssh_public_key" >&2
    exit 1
fi

# Validate username/password characters（防换行符注入 chpasswd / YAML 破坏）
if ! [[ "$username" =~ ^[a-z_][a-z0-9_-]{0,31}$ ]]; then
    echo "❌ Error: Username must match [a-z_][a-z0-9_-]{0,31}" >&2
    exit 1
fi
if ! [[ "$password" =~ ^[A-Za-z0-9@#%+=.,_-]+$ ]]; then
    echo "❌ Error: Password contains invalid characters (allowed: letters/digits/@#%+=.,_-)" >&2
    exit 1
fi

# Map Debian version to codename
case "$debver" in
    10|buster)
        debver="10"
        debcodename="buster"
        ;;
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
        echo "❌ Error: Unsupported Debian version: $debver" >&2
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

# Debian 10 及更早的云端镜像命名为 generic（genericcloud 命名自 Debian 11 起）
if [ "$DEBIAN_VERSION" = "10" ]; then
    FILE_NAME="debian-10-generic-${DEBIAN_ARCH}"
else
    FILE_NAME="debian-${DEBIAN_VERSION}-genericcloud-${DEBIAN_ARCH}"
fi

# ─── 固件显示名（仅影响最终 OVA 文件名，下载/内部引用仍用 FILE_NAME）───
case "${VIRTUAL_SYSTEM_TYPE%% *}" in
  vmx-14)                    ESXI_TAG="esxi67" ;;
  vmx-17|vmx-18|vmx-19)      ESXI_TAG="esxi7" ;;
  vmx-20|vmx-21)             ESXI_TAG="esxi8" ;;
  vmx-22)                    ESXI_TAG="esxi9" ;;
  *)                         ESXI_TAG="esxi$((${VIRTUAL_SYSTEM_TYPE#vmx-}/3+2))" ;;
esac
FILE_ORIG_EXT="qcow2"
FILE_DEST_EXT="vmdk"
FILE_SIGN_EXT="mf"
FILE_ORIG_URL="https://cloud.debian.org/images/cloud/${DEBIAN_NAME}/latest/${FILE_NAME}.${FILE_ORIG_EXT}"

# 默认 osType（可由环境变量覆盖，workflow 始终显式传值）；Debian 10 用 101/debian10_64Guest
case "${DEBIAN_VERSION}" in
  10) OVF_OS_ID="${OVF_OS_ID:-101}"; OVF_OS_TYPE="${OVF_OS_TYPE:-debian10_64Guest}" ;;
  *)  OVF_OS_ID="${OVF_OS_ID:-96}";  OVF_OS_TYPE="${OVF_OS_TYPE:-debian11_64Guest}" ;;
esac

# Guest OS 显示标识（dgnuXX，由 OVF_OS_TYPE 推导，仅影响最终 OVA 文件名）
case "${OVF_OS_TYPE}" in
  debian9_64Guest)  GUEST_TAG="dgnu9" ;;
  debian10_64Guest) GUEST_TAG="dgnu10" ;;
  debian11_64Guest) GUEST_TAG="dgnu11" ;;
  debian12_64Guest) GUEST_TAG="dgnu12" ;;
  debian13_64Guest) GUEST_TAG="dgnu13" ;;
  *)                GUEST_TAG="dgnu$(echo "${OVF_OS_TYPE}" | grep -oE '[0-9]+' | head -1)" ;;
esac
OUTPUT_NAME="debian${DEBIAN_VERSION}-generic-cloud-${ESXI_TAG}-${GUEST_TAG}-${DEBIAN_ARCH}"

CURRENT_DATE=$(date +%Y%m%d)
disk_size_bytes=$((disk_size_gb * 1073741824))

echo "╔════════════════════════════════════════╗"
echo "║      Debian OVA Creator - Build Started    ║"
echo "╠════════════════════════════════════════╣"
echo "║ Debian Version: $DEBIAN_VERSION"
echo "║ Architecture: $DEBIAN_ARCH"
echo "║ vCPU: $vcpu"
echo "║ Memory: ${memory}MB"
echo "║ Disk: ${disk_size_gb}GB"
echo "║ Hostname: $hostname"
echo "║ Username: $username"
echo "╚════════════════════════════════════════╝"
echo ""

# --- 区域 1: ConfigDrive ISO 生成 (NoCloud 模式) ---

# 生成 Cloud-Init config (user-data) 和 Meta-data 文件
CLOUD_CONFIG_FILE=$(mktemp)
META_CONFIG_FILE=$(mktemp)

# 1. User-Data (Cloud-Config) 内容
cat > "$CLOUD_CONFIG_FILE" << 'EOFCONFIG'
#cloud-config
EOFCONFIG

if [[ -n "$username" ]]; then
    cat >> "$CLOUD_CONFIG_FILE" << EOFCONFIG
users:
  - name: $username
    sudo: ALL=(ALL) NOPASSWD:ALL
    shell: /bin/bash
    lock_passwd: false

chpasswd:
  list: |
    $username:$password
  expire: false

packages:
  - cloud-init
  - open-vm-tools

runcmd:
  - [ systemctl, daemon-reload ]
  - [ systemctl, enable, open-vm-tools ]
  - [ systemctl, start, open-vm-tools ]
EOFCONFIG

    if [[ -n "$ssh_public_key" ]] && [[ -f "$ssh_public_key" ]]; then
        cat >> "$CLOUD_CONFIG_FILE" << 'EOFCONFIG'
    ssh_authorized_keys:
EOFCONFIG
        while IFS= read -r line; do
            echo "      - $line" >> "$CLOUD_CONFIG_FILE"
        done < "$ssh_public_key"
    fi
fi
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
echo "💿 Generating NoCloud ConfigDrive ISO using cloud-localds: ${ISO_FILE_NAME}"

# cloud-localds 自动处理 ConfigDrive 格式，并将文件标记为 CIDATA
cloud-localds "$ISO_FILE_NAME" "$CLOUD_CONFIG_FILE" "$META_CONFIG_FILE"

rm -f "$CLOUD_CONFIG_FILE" "$META_CONFIG_FILE"

echo "✅ ConfigDrive ISO created successfully."

# 计算 ISO 文件大小，用于 OVF 引用
ISO_FILE_SIZE=$(wc -c "$ISO_FILE_NAME" | cut -d " " -f1)

# --- 区域 1: 结束 ---

# Download cloud image
if [ ! -f "${FILE_NAME}.${FILE_ORIG_EXT}" ]; then
    echo "⬇️  Downloading Debian cloud image..."
    wget -q "$FILE_ORIG_URL" -O "${FILE_NAME}.${FILE_ORIG_EXT}"
    echo "✅ Download completed"
else
    echo "✅ Cloud image already exists"
fi

# 扩容磁盘到指定大小（仅当小于目标时），保证 vmdk 虚拟大小与 OVF capacity 一致
CURRENT_BYTES=$(qemu-img info --output=json "${FILE_NAME}.${FILE_ORIG_EXT}" | grep -oE '"virtual-size": [0-9]+' | grep -oE '[0-9]+')
TARGET_BYTES=$((disk_size_gb * 1073741824))
if [ "$CURRENT_BYTES" -lt "$TARGET_BYTES" ]; then
    qemu-img resize "${FILE_NAME}.${FILE_ORIG_EXT}" "${disk_size_gb}G"
    echo "✅ 磁盘已扩容到 ${disk_size_gb}G（开机后 cloud-init growpart 自动扩展根分区）"
fi

# Convert to VMDK format（本地重跑换 -s 时旧 vmdk 虚拟大小与目标不符，删除重转）
VMDK_BYTES=""
if [ -f "${FILE_NAME}.${FILE_DEST_EXT}" ]; then
    VMDK_BYTES=$(qemu-img info --output=json "${FILE_NAME}.${FILE_DEST_EXT}" | grep -oE '"virtual-size": [0-9]+' | grep -oE '[0-9]+')
fi
if [ -f "${FILE_NAME}.${FILE_DEST_EXT}" ] && [ "$VMDK_BYTES" != "$TARGET_BYTES" ]; then
    echo "⚠️ VMDK 虚拟大小(${VMDK_BYTES})与目标(${TARGET_BYTES})不符，删除重转"
    rm -f "${FILE_NAME}.${FILE_DEST_EXT}"
fi
if [ ! -f "${FILE_NAME}.${FILE_DEST_EXT}" ]; then
    echo "🔄 Converting image to VMDK format..."
    qemu-img convert -f "$FILE_ORIG_EXT" -O "$FILE_DEST_EXT" -o subformat=streamOptimized \
        "${FILE_NAME}.${FILE_ORIG_EXT}" "${FILE_NAME}.${FILE_DEST_EXT}"
    echo "✅ Conversion completed"
else
    echo "✅ VMDK file already exists"
fi

FILE_DEST_SIZE=$(wc -c "${FILE_NAME}.${FILE_DEST_EXT}" | cut -d " " -f1)

# --- 区域 2: OVF 配置修改 (禁止自动启动, 添加 ISO 引用) ---

# Generate OVF configuration
echo "📝 Generating OVF configuration..."
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
echo "🔐 Generating checksum manifest..."
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
echo "📦 Packaging OVA file..."
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
echo "╔════════════════════════════════════════╗"
echo "║      ✅ Build Successfully Completed!      ║"
echo "╠════════════════════════════════════════╣"
echo "║ OVA File: ${OUTPUT_NAME}.ova"
echo "║ File Size: ${OVA_SIZE}"
echo "║ Debian Version: ${DEBIAN_VERSION}"
echo "║ vCPU: ${vcpu}"
echo "║ Memory: ${memory}MB"
echo "║ Disk: ${disk_size_gb}GB"
echo "║ Hostname: ${hostname}"
echo "║ Default User: ${username}"
echo "║ Config Method: NoCloud/ConfigDrive (ISO)"
echo "║ Auto Start: Disabled 🚀"
echo "╚════════════════════════════════════════╝"
echo ""
