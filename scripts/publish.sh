#!/bin/bash
set -euo pipefail

ROOT=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)
NOTES="$RUNNER_TEMP/release-notes.md"
ASSET_LIST="$RUNNER_TEMP/ova-assets.txt"
python3 "$ROOT/scripts/report.py" release "$NOTES" > "$ASSET_LIST"
mapfile -t ASSETS < "$ASSET_LIST"
TITLE="Debian ${TARGET_VERSION} OVA - ${FINAL_TAG}"

update_release() {
    gh release upload "$FINAL_TAG" "${ASSETS[@]}" --clobber
    # 保留历史资产，正文仅展示本次成功构建的说明。
    gh release edit "$FINAL_TAG" --title "$TITLE" --prerelease=false --notes-file "$NOTES"
}

if gh release view "$FINAL_TAG" >/dev/null 2>&1; then
    update_release
elif gh release create "$FINAL_TAG" "${ASSETS[@]}" \
    --target "$GITHUB_SHA" --title "$TITLE" --prerelease=false --notes-file "$NOTES"; then
    :
else
    CREATE_STATUS=$?
    # 查询与创建之间可能有其他运行创建 Release；
    # 仅在确认已存在时重试，网络或认证失败保留原始错误。
    if ! gh release view "$FINAL_TAG" >/dev/null 2>&1; then
        echo "[ERROR] 创建 Release 失败（退出码 $CREATE_STATUS），未检测到可复用的 Release；原始错误见上方。" >&2
        exit "$CREATE_STATUS"
    fi
    echo '[INFO] Release 已由其他运行创建，继续更新。'
    update_release
fi
echo "[INFO] Release 发布完成：$FINAL_TAG（${#ASSETS[@]} 份镜像）"
