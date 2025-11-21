#!/usr/bin/env bash
set -e

###############################################
# Debian Cloud Image → OVA Builder (Final)
# With: cloud-init, HW config, OVF, MF, OVA
###############################################

# Default parameters
debver=""
debarch="amd64"
cpu_count=2
mem_size=512
disk_size=4
disk_type="scsi"        # scsi / ide
network_type="vmxnet3"  # e1000 / vmxnet3

# cloud-init params
ci_username="debian"
ci_password="123456"
ci_hostname="debian-cloud"

show_help() {
cat << EOF
Usage: $0 [options]

Required:
  -d <debian version>   Debian version (11/12/13/bookworm/trixie)

Hardware options:
  -c <cpu>              vCPU count (default: 2)
  -m <memory_mb>        Memory MB (default: 1024)
  -s <disk_gb>          Disk size GB (default: 10)
  --disk-type <type>    scsi | ide   (default: scsi)
  --network-type <type> vmxnet3 | e1000  (default: vmxnet3)

Cloud-init options:
  --username <user>     Default login user (default: debian)
  --password <pass>     User password
  --hostname <host>     VM Hostname

Example:
  $0 -d 13 -c 4 -m 4096 -s 20 --disk-type scsi --network-type vmxnet3 --username admin --password 1234
EOF
}

###############################
# Parse arguments
###############################
while [[ $# -gt 0 ]]; do
    case $1 in
        -d) debver="$2"; shift 2 ;;
        -c) cpu_count="$2"; shift 2 ;;
        -m) mem_size="$2"; shift 2 ;;
        -s) disk_size="$2"; shift 2 ;;
        --disk-type) disk_type="$2"; shift 2 ;;
        --network-type) network_type="$2"; shift 2 ;;
        --username) ci_username="$2"; shift 2 ;;
        --password) ci_password="$2"; shift 2 ;;
        --hostname) ci_hostname="$2"; shift 2 ;;
        -h|--help) show_help; exit 0 ;;
        *) echo "Unknown option: $1"; show_help; exit 1 ;;
    esac
done

[[ -z "$debver" ]] && { echo "Error: Debian version is required"; exit 1; }

###############################
# Map Debian version
###############################
case "$debver" in
    11|bullseye) debver="11"; debcodename="bullseye" ;;
    12|bookworm) debver="12"; debcodename="bookworm" ;;
    13|trixie)   debver="13"; debcodename="trixie" ;;
    *) echo "Unsupported version: $debver"; exit 1 ;;
esac

FILE_NAME="debian-$debver-genericcloud-amd64"
QCOW2_URL="https://cloud.debian.org/images/cloud/$debcodename/latest/$FILE_NAME.qcow2"

echo "===== BUILD CONFIG ====="
echo "Debian: $debcodename"
echo "CPU: $cpu_count"
echo "MEM: $mem_size MB"
echo "DISK: $disk_size GB"
echo "DISK TYPE: $disk_type"
echo "NET: $network_type"
echo "User: $ci_username"
echo "Pass: $ci_password"
echo "Hostname: $ci_hostname"
echo "========================"

###############################################
# 1. Download qcow2
###############################################
if [[ ! -f "$FILE_NAME.qcow2" ]]; then
    echo "[1/6] Downloading Debian cloud image..."
    wget -q --show-progress "$QCOW2_URL" -O "$FILE_NAME.qcow2"
fi

###############################################
# 2. cloud-init: user-data + meta-data + seed.iso
###############################################
echo "[2/6] Generating cloud-init seed.iso..."

cat > user-data <<EOF
#cloud-config
users:
  - name: ${ci_username}
    sudo: ALL=(ALL) NOPASSWD:ALL
    lock_passwd: false
    plain_text_passwd: "${ci_password}"
    shell: /bin/bash
chpasswd: { expire: false }
ssh_pwauth: true
hostname: ${ci_hostname}
EOF

echo "instance-id: iid-debian" > meta-data
echo "local-hostname: ${ci_hostname}" >> meta-data

genisoimage -o seed.iso -volid cidata -joliet -rock user-data meta-data >/dev/null

###############################################
# 3. Convert qcow2 → vmdk
###############################################
echo "[3/6] Convert qcow2 → vmdk..."
qemu-img convert -O vmdk "$FILE_NAME.qcow2" disk.vmdk

FILE_SIZE=$(wc -c disk.vmdk | awk '{print $1}')

###############################################
# 4. Prepare OVF hardware mappings
###############################################

# Disk controller ID
if [[ "$disk_type" == "ide" ]]; then
    disk_controller_type="5"  # IDE Controller
else
    disk_controller_type="6"  # SCSI Controller
fi

# NIC mapping
if [[ "$network_type" == "vmxnet3" ]]; then
    net_subtype="VmxNet3"
else
    net_subtype="E1000"
fi

###############################################
# 5. Generate OVF
###############################################
echo "[4/6] Creating OVF..."

cat > debian.ovf <<EOF
<?xml version="1.0" encoding="UTF-8"?>
<Envelope xmlns="http://schemas.dmtf.org/ovf/envelope/1">
  <References>
    <File ovf:id="file1" ovf:href="disk.vmdk" ovf:size="$FILE_SIZE"/>
    <File ovf:id="seed" ovf:href="seed.iso"/>
  </References>

  <DiskSection>
    <Disk ovf:diskId="vmdisk1" ovf:fileRef="file1" ovf:capacity="$((disk_size*1024*1024*1024))"/>
  </DiskSection>

  <NetworkSection>
    <Network ovf:name="VM Network"/>
  </NetworkSection>

  <VirtualSystem ovf:id="debian-$debver">
    <OperatingSystemSection ovf:id="96">
      <Description>Debian GNU/Linux $debver (64-bit)</Description>
    </OperatingSystemSection>

    <VirtualHardwareSection>
      <Item>
        <rasd:ResourceType>3</rasd:ResourceType>
        <rasd:VirtualQuantity>$cpu_count</rasd:VirtualQuantity>
      </Item>

      <Item>
        <rasd:ResourceType>4</rasd:ResourceType>
        <rasd:VirtualQuantity>$mem_size</rasd:VirtualQuantity>
        <rasd:AllocationUnits>byte * 2^20</rasd:AllocationUnits>
      </Item>

      <Item>
        <rasd:ResourceType>$disk_controller_type</rasd:ResourceType>
        <rasd:ElementName>${disk_type^} Controller 0</rasd:ElementName>
      </Item>

      <Item>
        <rasd:ResourceType>17</rasd:ResourceType>
        <rasd:HostResource>ovf:/disk/vmdisk1</rasd:HostResource>
      </Item>

      <Item>
        <rasd:ResourceType>10</rasd:ResourceType>
        <rasd:ResourceSubType>$net_subtype</rasd:ResourceSubType>
        <rasd:Connection>VM Network</rasd:Connection>
      </Item>

    </VirtualHardwareSection>
  </VirtualSystem>
</Envelope>
EOF

###############################################
# 6. Generate mf
###############################################
echo "[5/6] Generating manifest..."

sha256sum disk.vmdk > debian.mf
sha256sum debian.ovf >> debian.mf
sha256sum seed.iso >> debian.mf

###############################################
# 7. Pack OVA
###############################################
echo "[6/6] Creating OVA package..."
tar -cvf "debian-${debver}.ova" debian.ovf disk.vmdk seed.iso debian.mf >/dev/null

echo "======================================"
echo "OVA build complete → debian-${debver}.ova"
echo "======================================"
