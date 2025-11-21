echo "完成! OVA文件: $FILE_NAME.ova"
echo "配置信息:"
echo "  Debian版本: $DEBIAN_VERSION"
echo "  vCPU数量: $vcpu"
echo "  内存大小: ${memory}MB"
echo "  磁盘大小: ${disk_size_gb}GB"
echo "  主机名: $hostname"
if [[ -n "$username" ]]; then
    echo "  默认用户: $username"
fi#!/bin/bash

# 默认参数
debver=""
debarch="amd64"
vcpu=2
memory=512
disk_size_gb=4
hostname="debianguest"
username=""
password=""
ssh_public_key=""
enable_cloudinit=true

show_help() {
    cat << EOF
Usage: $0 [options]

Debian版本选项:
  -d <debian_version>  指定Debian版本 (必需)
                       支持: "11", "12", "13", "bullseye", "bookworm", "trixie", "sid"

硬件参数选项:
  -c <vcpu>            虚拟CPU数量 (默认: 2)
  -m <memory>          内存大小(MB) (默认: 1024)
  -s <disk_size_gb>    磁盘容量(GB) (默认: 10)
                       例: 20 表示 20GB, 50 表示 50GB

账户配置选项:
  -H <hostname>        主机名 (默认: debianguest)
  -u <username>        默认用户名 (可选)
  -p <password>        默认用户密码 (可选)
  -k <ssh_public_key>  SSH公钥文件路径 (可选)

其他选项:
  -h                   显示帮助信息

示例:
  $0 -d bullseye -c 4 -m 2048 -s 20
  $0 -d 12 -c 2 -m 1024 -u debian -p mypassword -H myvm
  $0 -d bookworm -c 4 -m 4096 -s 50 -k ~/.ssh/id_rsa.pub -u ubuntu
EOF
}

while getopts ":d:c:m:s:H:u:p:k:h" opt; do
    case "$opt" in
        d)
            debver="$OPTARG"
            ;;
        c)
            vcpu="$OPTARG"
            ;;
        m)
            memory="$OPTARG"
            ;;
        s)
            disk_size_gb="$OPTARG"
            ;;
        H)
            hostname="$OPTARG"
            ;;
        u)
            username="$OPTARG"
            ;;
        p)
            password="$OPTARG"
            ;;
        k)
            ssh_public_key="$OPTARG"
            ;;
        h)
            show_help
            exit 0
            ;;
        :)
            echo "Error: 选项 -$OPTARG 需要一个参数" >&2
            show_help
            exit 1
            ;;
        \?)
            echo "Error: 无效选项 -$OPTARG" >&2
            show_help
            exit 1
            ;;
    esac
done

# 验证必需参数
if [[ -z "$debver" ]]; then
    echo "Error: Debian版本必需 (-d)" >&2
    show_help
    exit 1
fi

# 验证硬件参数
if ! [[ "$vcpu" =~ ^[0-9]+$ ]] || [ "$vcpu" -lt 1 ]; then
    echo "Error: vCPU数量必须是正整数" >&2
    exit 1
fi

if ! [[ "$memory" =~ ^[0-9]+$ ]] || [ "$memory" -lt 256 ]; then
    echo "Error: 内存大小必须至少256MB" >&2
    exit 1
fi

# 验证SSH公钥文件
if [[ -n "$ssh_public_key" ]] && [[ ! -f "$ssh_public_key" ]]; then
    echo "Error: SSH公钥文件不存在: $ssh_public_key" >&2
    exit 1
fi

# 处理Debian版本
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
        echo "Error: 不支持的版本 $debver" >&2
        show_help
        exit 1
        ;;
esac

DEBIAN_VERSION=${debver}
DEBIAN_NAME=${debcodename}
DEBIAN_ARCH=${debarch}
VIRTUAL_SYSTEM_TYPE=vmx-19

FILE_NAME=debian-$DEBIAN_VERSION-genericcloud-$DEBIAN_ARCH
FILE_ORIG_EXT=qcow2
FILE_DEST_EXT=vmdk
FILE_SIGN_EXT=mf
FILE_ORIG_URL=https://cdimage.debian.org/images/cloud/$DEBIAN_NAME/latest/$FILE_NAME.$FILE_ORIG_EXT

OVF_OS_ID=96
OVF_OS_TYPE=debian11_64Guest

CURRENT_DATE=$(date +%Y%m%d)

# 构建user-data (仅当需要密码配置时)
USER_DATA=""
if [[ -n "$username" ]] || [[ -n "$password" ]]; then
    USER_DATA="#!/bin/cloud-config
"
    if [[ -n "$username" ]]; then
        USER_DATA+="users:
  - name: $username
    groups: sudo
    shell: /bin/bash
    sudo: ['ALL=(ALL) NOPASSWD:ALL']
"
        if [[ -n "$password" ]]; then
            USER_DATA+="    passwd: $(echo -n "$password" | mkpasswd -m sha-512 -stdin)
"
        fi
        if [[ -n "$ssh_public_key" ]]; then
            SSH_KEY=$(cat "$ssh_public_key")
            USER_DATA+="    ssh_authorized_keys:
      - $SSH_KEY
"
        fi
    fi
fi

# 对user-data进行base64编码
USER_DATA_B64=""
if [[ -n "$USER_DATA" ]]; then
    USER_DATA_B64=$(echo -n "$USER_DATA" | base64 -w0)
fi

# 下载镜像
if [ ! -f "$FILE_NAME.$FILE_ORIG_EXT" ]; then
    echo "下载 $FILE_NAME.$FILE_ORIG_EXT ..."
    wget "$FILE_ORIG_URL"
else
    echo "文件 $FILE_NAME.$FILE_ORIG_EXT 已存在"
fi

# 转换镜像格式
if [ ! -f "$FILE_NAME.$FILE_DEST_EXT" ]; then
    echo "转换镜像格式为 VMDK ..."
    qemu-img convert -f $FILE_ORIG_EXT -O $FILE_DEST_EXT -o subformat=streamOptimized "$FILE_NAME.$FILE_ORIG_EXT" "$FILE_NAME.$FILE_DEST_EXT"
else
    echo "文件 $FILE_NAME.$FILE_DEST_EXT 已存在"
fi

FILE_DEST_SIZE=$(wc -c "$FILE_NAME.$FILE_DEST_EXT" | cut -d " " -f1)
disk_size=$((disk_size_gb * 1073741824))
MEMORY_BYTES=$((memory * 1048576))

# 生成OVF配置文件
cat <<EOF | tee "$FILE_NAME.ovf" > /dev/null
<?xml version="1.0" encoding="UTF-8"?>
<Envelope xmlns="http://schemas.dmtf.org/ovf/envelope/1" xmlns:cim="http://schemas.dmtf.org/wbem/wscim/1/common" xmlns:ovf="http://schemas.dmtf.org/ovf/envelope/1" xmlns:rasd="http://schemas.dmtf.org/wbem/wscim/1/cim-schema/2/CIM_ResourceAllocationSettingData" xmlns:vmw="http://www.vmware.com/schema/ovf" xmlns:vssd="http://schemas.dmtf.org/wbem/wscim/1/cim-schema/2/CIM_VirtualSystemSettingData" xmlns:xsi="http://www.w3.org/2001/XMLSchema-instance">
  <References>
    <File ovf:href="$FILE_NAME.$FILE_DEST_EXT" ovf:id="file1" ovf:size="$FILE_DEST_SIZE"/>
  </References>
  <DiskSection>
    <Info>Virtual disk information</Info>
    <Disk ovf:capacity="$disk_size" ovf:capacityAllocationUnits="byte" ovf:diskId="vmdisk1" ovf:fileRef="file1" ovf:format="http://www.vmware.com/interfaces/specifications/vmdk.html#streamOptimized" ovf:populatedSize="0"/>
  </DiskSection>
  <NetworkSection>
    <Info>The list of logical networks</Info>
    <Network ovf:name="VM Network">
      <Description>The VM Network network</Description>
    </Network>
  </NetworkSection>
  <VirtualSystem ovf:id="$FILE_NAME-$CURRENT_DATE">
    <Info>A virtual machine</Info>
    <Name>$FILE_NAME-$CURRENT_DATE</Name>
    <OperatingSystemSection ovf:id="$OVF_OS_ID" vmw:osType="$OVF_OS_TYPE">
      <Info>The kind of installed guest operating system</Info>
      <Description>Debian GNU/Linux $DEBIAN_VERSION (64-bit)</Description>
    </OperatingSystemSection>

    <ProductSection ovf:required="false">
      <Info>Cloud-Init customization</Info>
      <Product>Debian GNU/Linux $DEBIAN_VERSION ($CURRENT_DATE)</Product>
      <Property ovf:key="instance-id" ovf:type="string" ovf:userConfigurable="true" ovf:value="id-ovf">
          <Label>A Unique Instance ID for this instance</Label>
          <Description>Specifies the instance id. This is required and used to determine if the machine should take "first boot" actions</Description>
      </Property>
      <Property ovf:key="hostname" ovf:type="string" ovf:userConfigurable="true" ovf:value="$hostname">
          <Description>Specifies the hostname for the appliance</Description>
      </Property>
      <Property ovf:key="public-keys" ovf:type="string" ovf:userConfigurable="true" ovf:value="">
          <Label>ssh public keys</Label>
          <Description>This field is optional, but indicates that the instance should populate the default user's 'authorized_keys' with this value</Description>
      </Property>
      <Property ovf:key="user-data" ovf:type="string" ovf:userConfigurable="true" ovf:value="$USER_DATA_B64">
          <Label>Encoded user-data</Label>
          <Description>Base64 encoded cloud-init user-data configuration</Description>
      </Property>
    </ProductSection>

    <VirtualHardwareSection ovf:transport="iso">
      <Info>Virtual hardware requirements</Info>
      <System>
        <vssd:ElementName>Virtual Hardware Family</vssd:ElementName>
        <vssd:InstanceID>0</vssd:InstanceID>
        <vssd:VirtualSystemIdentifier>$FILE_NAME-$CURRENT_DATE</vssd:VirtualSystemIdentifier>
        <vssd:VirtualSystemType>$VIRTUAL_SYSTEM_TYPE</vssd:VirtualSystemType>
      </System>
      <Item>
        <rasd:AllocationUnits>hertz * 10^6</rasd:AllocationUnits>
        <rasd:Description>Number of Virtual CPUs</rasd:Description>
        <rasd:ElementName>$vcpu virtual CPU(s)</rasd:ElementName>
        <rasd:InstanceID>1</rasd:InstanceID>
        <rasd:ResourceType>3</rasd:ResourceType>
        <rasd:VirtualQuantity>$vcpu</rasd:VirtualQuantity>
      </Item>
      <Item>
        <rasd:AllocationUnits>byte * 2^20</rasd:AllocationUnits>
        <rasd:Description>Memory Size</rasd:Description>
        <rasd:ElementName>${memory}MB of memory</rasd:ElementName>
        <rasd:InstanceID>2</rasd:InstanceID>
        <rasd:ResourceType>4</rasd:ResourceType>
        <rasd:VirtualQuantity>$memory</rasd:VirtualQuantity>
      </Item>
      <Item>
        <rasd:Address>0</rasd:Address>
        <rasd:Description>SCSI Controller</rasd:Description>
        <rasd:ElementName>SCSI Controller 0</rasd:ElementName>
        <rasd:InstanceID>3</rasd:InstanceID>
        <rasd:ResourceSubType>VirtualSCSI</rasd:ResourceSubType>
        <rasd:ResourceType>6</rasd:ResourceType>
      </Item>
      <Item ovf:required="false">
        <rasd:AutomaticAllocation>false</rasd:AutomaticAllocation>
        <rasd:ElementName>serial0</rasd:ElementName>
        <rasd:InstanceID>4</rasd:InstanceID>
        <rasd:ResourceSubType>vmware.serialport.device</rasd:ResourceSubType>
        <rasd:ResourceType>21</rasd:ResourceType>
        <vmw:Config ovf:required="false" vmw:key="yieldOnPoll" vmw:value="false" />
      </Item>
      <Item>
        <rasd:Address>1</rasd:Address>
        <rasd:Description>IDE Controller</rasd:Description>
        <rasd:ElementName>VirtualIDEController 1</rasd:ElementName>
        <rasd:InstanceID>5</rasd:InstanceID>
        <rasd:ResourceType>5</rasd:ResourceType>
      </Item>
      <Item>
        <rasd:Address>0</rasd:Address>
        <rasd:Description>IDE Controller</rasd:Description>
        <rasd:ElementName>VirtualIDEController 0</rasd:ElementName>
        <rasd:InstanceID>6</rasd:InstanceID>
        <rasd:ResourceType>5</rasd:ResourceType>
      </Item>
      <Item ovf:required="false">
        <rasd:AutomaticAllocation>false</rasd:AutomaticAllocation>
        <rasd:ElementName>VirtualVideoCard</rasd:ElementName>
        <rasd:InstanceID>7</rasd:InstanceID>
        <rasd:ResourceType>24</rasd:ResourceType>
        <vmw:Config ovf:required="false" vmw:key="enable3DSupport" vmw:value="false"/>
        <vmw:Config ovf:required="false" vmw:key="enableMPTSupport" vmw:value="false"/>
        <vmw:Config ovf:required="false" vmw:key="use3dRenderer" vmw:value="automatic"/>
        <vmw:Config ovf:required="false" vmw:key="useAutoDetect" vmw:value="false"/>
        <vmw:Config ovf:required="false" vmw:key="videoRamSizeInKB" vmw:value="4096"/>
      </Item>
      <Item ovf:required="false">
        <rasd:AutomaticAllocation>false</rasd:AutomaticAllocation>
        <rasd:ElementName>VirtualVMCIDevice</rasd:ElementName>
        <rasd:InstanceID>8</rasd:InstanceID>
        <rasd:ResourceSubType>vmware.vmci</rasd:ResourceSubType>
        <rasd:ResourceType>1</rasd:ResourceType>
        <vmw:Config ovf:required="false" vmw:key="allowUnrestrictedCommunication" vmw:value="false"/>
      </Item>
      <Item ovf:required="false">
        <rasd:AddressOnParent>0</rasd:AddressOnParent>
        <rasd:AutomaticAllocation>false</rasd:AutomaticAllocation>
        <rasd:ElementName>CD-ROM 1</rasd:ElementName>
        <rasd:InstanceID>9</rasd:InstanceID>
        <rasd:Parent>5</rasd:Parent>
        <rasd:ResourceSubType>vmware.cdrom.remotepassthrough</rasd:ResourceSubType>
        <rasd:ResourceType>15</rasd:ResourceType>
        <vmw:Config ovf:required="false" vmw:key="backing.exclusive" vmw:value="false"/>
      </Item>
      <Item>
        <rasd:AddressOnParent>0</rasd:AddressOnParent>
        <rasd:ElementName>Hard Disk 1</rasd:ElementName>
        <rasd:HostResource>ovf:/disk/vmdisk1</rasd:HostResource>
        <rasd:InstanceID>10</rasd:InstanceID>
        <rasd:Parent>3</rasd:Parent>
        <rasd:ResourceType>17</rasd:ResourceType>
        <vmw:Config ovf:required="false" vmw:key="backing.writeThrough" vmw:value="false"/>
      </Item>
      <Item ovf:required="false">
        <rasd:AddressOnParent>0</rasd:AddressOnParent>
        <rasd:AutomaticAllocation>false</rasd:AutomaticAllocation>
        <rasd:Description>Floppy Drive</rasd:Description>
        <rasd:ElementName>Floppy 1</rasd:ElementName>
        <rasd:InstanceID>11</rasd:InstanceID>
        <rasd:ResourceSubType>vmware.floppy.remotedevice</rasd:ResourceSubType>
        <rasd:ResourceType>14</rasd:ResourceType>
      </Item>
      <Item>
        <rasd:AddressOnParent>7</rasd:AddressOnParent>
        <rasd:AutomaticAllocation>true</rasd:AutomaticAllocation>
        <rasd:Connection>VM Network</rasd:Connection>
        <rasd:Description>VmxNet3 ethernet adapter on &quot;VM Network&quot;</rasd:Description>
        <rasd:ElementName>Ethernet 1</rasd:ElementName>
        <rasd:InstanceID>12</rasd:InstanceID>
        <rasd:ResourceSubType>VmxNet3</rasd:ResourceSubType>
        <rasd:ResourceType>10</rasd:ResourceType>
        <vmw:Config ovf:required="false" vmw:key="wakeOnLanEnabled" vmw:value="true"/>
      </Item>
      <vmw:Config ovf:required="false" vmw:key="cpuHotAddEnabled" vmw:value="false"/>
      <vmw:Config ovf:required="false" vmw:key="cpuHotRemoveEnabled" vmw:value="false"/>
      <vmw:Config ovf:required="false" vmw:key="firmware" vmw:value="bios"/>
      <vmw:Config ovf:required="false" vmw:key="virtualICH7MPresent" vmw:value="false"/>
      <vmw:Config ovf:required="false" vmw:key="virtualSMCPresent" vmw:value="false"/>
      <vmw:Config ovf:required="false" vmw:key="memoryHotAddEnabled" vmw:value="false"/>
      <vmw:Config ovf:required="false" vmw:key="nestedHVEnabled" vmw:value="false"/>
      <vmw:Config ovf:required="false" vmw:key="powerOpInfo.powerOffType" vmw:value="preset"/>
      <vmw:Config ovf:required="false" vmw:key="powerOpInfo.resetType" vmw:value="preset"/>
      <vmw:Config ovf:required="false" vmw:key="powerOpInfo.standbyAction" vmw:value="checkpoint"/>
      <vmw:Config ovf:required="false" vmw:key="powerOpInfo.suspendType" vmw:value="preset"/>
      <vmw:Config ovf:required="false" vmw:key="tools.afterPowerOn" vmw:value="true"/>
      <vmw:Config ovf:required="false" vmw:key="tools.afterResume" vmw:value="true"/>
      <vmw:Config ovf:required="false" vmw:key="tools.beforeGuestShutdown" vmw:value="true"/>
      <vmw:Config ovf:required="false" vmw:key="tools.beforeGuestStandby" vmw:value="true"/>
      <vmw:Config ovf:required="false" vmw:key="tools.syncTimeWithHost" vmw:value="false"/>
      <vmw:Config ovf:required="false" vmw:key="tools.toolsUpgradePolicy" vmw:value="manual"/>
    </VirtualHardwareSection>
  </VirtualSystem>
</Envelope>
EOF

# 生成签名文件
FILE_DEST_SUM=$(sha256sum "$FILE_NAME.$FILE_DEST_EXT" | cut -d " " -f1)
FILE_OVF_SUM=$(sha256sum "$FILE_NAME.ovf" | cut -d " " -f1)

cat <<EOF | tee "$FILE_NAME.$FILE_SIGN_EXT" > /dev/null
SHA256($FILE_NAME.$FILE_DEST_EXT)= $FILE_DEST_SUM
SHA256($FILE_NAME.ovf)= $FILE_OVF_SUM
EOF

# 打包OVA文件
echo "打包OVA文件..."
tar -vcf "$FILE_NAME.ova" \
         "$FILE_NAME.ovf" \
         "$FILE_NAME.$FILE_SIGN_EXT" \
         "$FILE_NAME.$FILE_DEST_EXT"

echo "完成! OVA文件: $FILE_NAME.ova"
echo "配置信息:"
echo "  Debian版本: $DEBIAN_VERSION"
echo "  vCPU数量: $vcpu"
echo "  内存大小: ${memory}MB"
echo "  磁盘大小: $disk_size 字节"
echo "  主机名: $hostname"
if [[ -n "$username" ]]; then
    echo "  默认用户: $username"
fi
