#!/bin/bash
set -euo pipefail

# Internal Actions entry point; no local OVA build mode.
if [[ "${GITHUB_ACTIONS:-}" != true ]]; then
    echo '[ERROR] 请在 GitHub Actions 页面运行构建工作流。' >&2
    exit 1
fi
SCRIPT_DIR=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")" && pwd)
debver=''
vcpu=2
memory=1024
disk_size_gb=4
hostname=debian-cloud
username=debian
password=123456
enable_ssh=false
apt_mirror=official
install_vm_tools=true
guest_timezone=UTC

while getopts ":d:c:m:s:H:u:p:S:M:V:T:" opt; do
    case "$opt" in
        d) debver="$OPTARG" ;;
        c) vcpu="$OPTARG" ;;
        m) memory="$OPTARG" ;;
        s) disk_size_gb="$OPTARG" ;;
        H) hostname="$OPTARG" ;;
        u) username="$OPTARG" ;;
        p) password="$OPTARG" ;;
        S) enable_ssh="$OPTARG" ;;
        M) apt_mirror="$OPTARG" ;;
        V) install_vm_tools="$OPTARG" ;;
        T) guest_timezone="$OPTARG" ;;
        :) echo "[ERROR] Option -$OPTARG requires an argument" >&2; exit 1 ;;
        \?) echo "[ERROR] Invalid option -$OPTARG" >&2; exit 1 ;;
    esac
done


if (( OPTIND <= $# )); then
    echo '[ERROR] 不接受额外的位置参数' >&2
    exit 1
fi
: "${VIRTUAL_SYSTEM_TYPE:?缺少构建机型}"
: "${OVF_OS_ID:?缺少 Guest OS ID}"
: "${OVF_OS_TYPE:?缺少 Guest OS 标识}"
: "${OVA_SOURCE_MANIFEST:?缺少固定源镜像元数据}"
: "${OVA_SOURCE_IMAGE:?缺少已验证的源镜像}"
export VIRTUAL_SYSTEM_TYPE OVF_OS_ID OVF_OS_TYPE OVA_SOURCE_MANIFEST

DEBIAN_VERSION="$debver"
DEBIAN_ARCH=amd64
FILE_NAME="debian-${DEBIAN_VERSION}-genericcloud-${DEBIAN_ARCH}"
FILE_ORIG_EXT=qcow2
FILE_DEST_EXT=vmdk
FILE_SIGN_EXT=mf
ISO_FILE_NAME=cidata.iso
CURRENT_DATE=$(date -u +%Y%m%d)

# Always remove credentials in temporary user-data, including on failure.
BUILD_TEMP=$(mktemp -d)
CLOUD_CONFIG_FILE="$BUILD_TEMP/user-data"
META_CONFIG_FILE="$BUILD_TEMP/meta-data"
cleanup() {
    local status=$?
    trap - EXIT
    if ! rm -f -- "$CLOUD_CONFIG_FILE" "$META_CONFIG_FILE" "$ISO_FILE_NAME" "${FILE_NAME}.qcow2.part"; then
        echo "[WARN] 无法完全清理临时凭据或镜像文件，请检查：$BUILD_TEMP" >&2
    fi
    if ! rmdir -- "$BUILD_TEMP"; then
        echo "[WARN] 临时目录仍有残留，请检查：$BUILD_TEMP" >&2
    fi
    exit "$status"
}
trap cleanup EXIT

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

render_cloud_config() {
    local normalized
    normalized=$(python3 "$SCRIPT_DIR/scripts/render.py" cloud "$CLOUD_CONFIG_FILE" "$META_CONFIG_FILE" \
        "$debver" "$vcpu" "$memory" "$disk_size_gb" "$hostname" "$username" "$password" \
        "$enable_ssh" "$apt_mirror" "$install_vm_tools" "$guest_timezone")
    read -r vcpu memory disk_size_gb username EXPECTED_SOURCE_HASH <<< "$normalized"
    cloud-localds "$ISO_FILE_NAME" "$CLOUD_CONFIG_FILE" "$META_CONFIG_FILE"
    ISO_FILE_SIZE=$(wc -c < "$ISO_FILE_NAME")
}

prepare_source_copy() {
    local stamp="${FILE_NAME}.source.sha512"
    # The pristine download is verified once per batch; never modify it in place.
    if [[ ! -f "${FILE_NAME}.qcow2" || ! -f "$stamp" ]] || [[ "$(< "$stamp")" != "$EXPECTED_SOURCE_HASH" ]]; then
        cp --reflink=auto -- "$OVA_SOURCE_IMAGE" "${FILE_NAME}.qcow2.part"
        mv -- "${FILE_NAME}.qcow2.part" "${FILE_NAME}.qcow2"
        printf '%s\n' "$EXPECTED_SOURCE_HASH" > "$stamp"
        rm -f -- "${FILE_NAME}.vmdk" "${FILE_NAME}.growroot-prepared.sha256"
    fi
}

run_guestfish() {
    local command=(env LIBGUESTFS_BACKEND=direct guestfish)
    if [[ "$EUID" -ne 0 ]]; then
        command=(sudo -n "${command[@]}")
    fi
    "${command[@]}" "$@"
}

prepare_disk() {
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

    # 在首次开机之前关闭 initramfs growroot，避免无串口时卸载根分区引发 init panic。
    # 由上方 cloud-config 的 growpart/resize_rootfs 在系统服务阶段完成扩容。
    # 缓存绑定 qcow2 内容摘要；批量构建复用准备结果，源盘变化时重新准备并使 VMDK 失效。
    PREPARED_FILE="${FILE_NAME}.growroot-prepared.sha256"
    SOURCE_HASH=$(sha256sum "${FILE_NAME}.${FILE_ORIG_EXT}" | cut -d " " -f1)
    if [[ ! -f "$PREPARED_FILE" ]] || [[ "$(< "$PREPARED_FILE")" != "growroot-disabled-v1:$SOURCE_HASH" ]]; then
        echo "[INFO] Preparing cloud-init disk growth..."
        if ! PREPARE_RESULT=$(run_guestfish --rw --format=qcow2 \
            -a "${FILE_NAME}.${FILE_ORIG_EXT}" -i <<'EOFGUESTFS'
touch /etc/growroot-disabled
sync
is-file /etc/growroot-disabled
EOFGUESTFS
        ); then
            echo "[ERROR] 无法在镜像中禁用早期 growroot，停止构建。" >&2
            exit 1
        fi
        if [[ "$PREPARE_RESULT" != true ]]; then
            echo "[ERROR] growroot 禁用标记校验失败，停止构建。" >&2
            exit 1
        fi
        rm -f "${FILE_NAME}.${FILE_DEST_EXT}"
        SOURCE_HASH=$(sha256sum "${FILE_NAME}.${FILE_ORIG_EXT}" | cut -d " " -f1)
        printf 'growroot-disabled-v1:%s\n' "$SOURCE_HASH" > "$PREPARED_FILE"
    else
        echo "[INFO] Cloud-init disk growth preparation already cached"
    fi
}

convert_disk() {
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
}

verify_vmdk() {
    local stamp="${FILE_NAME}.growroot-verified.sha256" result
    FILE_DEST_SUM=$(sha256sum "${FILE_NAME}.${FILE_DEST_EXT}" | cut -d " " -f1)
    if [[ -f "$stamp" ]] && [[ "$(< "$stamp")" == "growroot-marker-v1:$FILE_DEST_SUM" ]]; then
        return
    fi
    # Reopen the converted disk in a separate read-only session. Do not infer
    # filesystem state from a successful write session or disk capacity alone.
    if ! result=$(run_guestfish --ro --format=vmdk -a "${FILE_NAME}.${FILE_DEST_EXT}" -i <<'EOFGUESTFS'
is-file /etc/growroot-disabled
filesize /etc/growroot-disabled
EOFGUESTFS
    ); then
        echo '[ERROR] 无法只读复核 VMDK 中的 growroot 标记，停止打包。' >&2
        exit 1
    fi
    if [[ "$result" != $'true\n0' ]]; then
        echo '[ERROR] VMDK 的 growroot 标记不存在或不是空文件，停止打包。' >&2
        exit 1
    fi
    printf 'growroot-marker-v1:%s\n' "$FILE_DEST_SUM" > "$stamp"
    echo '[INFO] VMDK growroot 标记已独立只读复核'
}

render_ovf() {
    export FILE_NAME FILE_DEST_EXT FILE_DEST_SIZE ISO_FILE_NAME ISO_FILE_SIZE disk_size_bytes
    export CURRENT_DATE DEBIAN_VERSION vcpu memory
    python3 "$SCRIPT_DIR/scripts/render.py" ovf "${FILE_NAME}.ovf"
}

package_ova() {
    FILE_OVF_SUM=$(sha256sum "${FILE_NAME}.ovf" | cut -d " " -f1)
    ISO_FILE_SUM=$(sha256sum "${ISO_FILE_NAME}" | cut -d " " -f1)

    cat > "${FILE_NAME}.${FILE_SIGN_EXT}" << MANIFEST
SHA256(${FILE_NAME}.${FILE_DEST_EXT})= ${FILE_DEST_SUM}
SHA256(${FILE_NAME}.ovf)= ${FILE_OVF_SUM}
SHA256(${ISO_FILE_NAME})= ${ISO_FILE_SUM}
MANIFEST


    # Write atomically so an interrupted tar cannot look like a completed OVA.
    tar -cf "${OUTPUT_NAME}.ova.part" "${FILE_NAME}.ovf" "${FILE_NAME}.${FILE_SIGN_EXT}" \
        "${FILE_NAME}.${FILE_DEST_EXT}" "$ISO_FILE_NAME"
    mv -- "${OUTPUT_NAME}.ova.part" "${OUTPUT_NAME}.ova"
    OVA_SIZE=$(du -h "${OUTPUT_NAME}.ova" | cut -f1)
}

render_cloud_config
# The shared validator rejects unsupported combinations before these mappings.
case "$VIRTUAL_SYSTEM_TYPE" in
    vmx-14|vmx-15) ESXI_TAG=esxi6.7 ;;
    vmx-17|vmx-18|vmx-19) ESXI_TAG=esxi7.0 ;;
    vmx-20|vmx-21) ESXI_TAG=esxi8.0 ;;
    vmx-22) ESXI_TAG=esxi9.0 ;;
esac
GUEST_TAG="dgnu${OVF_OS_TYPE#debian}"
GUEST_TAG="${GUEST_TAG%_64Guest}"
MODE=console
if [[ "$enable_ssh" == true ]]; then MODE=ssh; fi
OUTPUT_NAME="debian${DEBIAN_VERSION}-generic-cloud-${ESXI_TAG}-vmx${VIRTUAL_SYSTEM_TYPE#vmx-}-${GUEST_TAG}-${DEBIAN_ARCH}-${MODE}"

prepare_source_copy
prepare_disk
convert_disk
verify_vmdk
render_ovf
package_ova
echo "[INFO] 已生成 ${OUTPUT_NAME}.ova（$OVA_SIZE），磁盘 ${ACTUAL_DISK_GIB} GB"
if [[ -n "${GITHUB_OUTPUT:-}" ]]; then
    {
        printf 'ACTUAL_DISK_GIB=%s\nACTUAL_DISK_BYTES=%s\n' "$ACTUAL_DISK_GIB" "$TARGET_BYTES"
        printf 'LOGIN_USERNAME=%s\nSSH_ENABLED=%s\n' "$username" "$enable_ssh"
        printf 'OVA_FILE_NAME=%s\nOVA_FILE_SIZE=%s\n' "${OUTPUT_NAME}.ova" "$OVA_SIZE"
    } >> "$GITHUB_OUTPUT"
fi
