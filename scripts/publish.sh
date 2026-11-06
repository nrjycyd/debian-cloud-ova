#!/bin/bash
set -euo pipefail

ROOT=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)
NOTES="$RUNNER_TEMP/release-notes.md"
ASSET_LIST="$RUNNER_TEMP/ova-assets.txt"
python3 "$ROOT/scripts/report.py" release "$NOTES" > "$ASSET_LIST"
mapfile -t ASSETS < "$ASSET_LIST"
OPTIONS=$(python3 "$ROOT/scripts/report.py" release-options)
mapfile -t RELEASE_OPTIONS <<< "$OPTIONS"
TITLE="${RELEASE_OPTIONS[0]}"
FLAGS=("${RELEASE_OPTIONS[@]:1}")

update_release() {
    gh release upload "$FINAL_TAG" "${ASSETS[@]}" --clobber
    # Keep older assets, but display only the latest successful build description.
    gh release edit "$FINAL_TAG" --title "$TITLE" "${FLAGS[@]}" --notes-file "$NOTES"
}

if gh release view "$FINAL_TAG" >/dev/null 2>&1; then
    update_release
elif gh release create "$FINAL_TAG" "${ASSETS[@]}" \
    --target "$GITHUB_SHA" --title "$TITLE" "${FLAGS[@]}" --notes-file "$NOTES"; then
    :
else
    CREATE_STATUS=$?
    # Another publisher may have created the tag between view and create.
    # Only retry when the Release actually exists; propagate network/auth failures.
    if ! gh release view "$FINAL_TAG" >/dev/null 2>&1; then
        echo "[ERROR] 创建 Release 失败（退出码 $CREATE_STATUS），未检测到可复用的 Release；原始错误见上方。" >&2
        exit "$CREATE_STATUS"
    fi
    echo '[INFO] Release 已由其他运行创建，继续更新。'
    update_release
fi
echo "[INFO] Release 发布完成：$FINAL_TAG（${#ASSETS[@]} 份镜像）"
