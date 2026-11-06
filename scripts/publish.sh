#!/bin/bash
set -euo pipefail

ROOT=$(cd -- "$(dirname -- "${BASH_SOURCE[0]}")/.." && pwd)
NOTES="$RUNNER_TEMP/release-notes.md"
ASSET_LIST="$RUNNER_TEMP/ova-assets.txt"
python3 "$ROOT/scripts/report.py" release "$NOTES" > "$ASSET_LIST"
mapfile -t ASSETS < "$ASSET_LIST"
BUILD_VERSION="$TARGET_VERSION"

update_release() {
    gh release upload "$FINAL_TAG" "${ASSETS[@]}" --clobber
    # Keep older assets, but display only the latest successful build description.
    gh release edit "$FINAL_TAG" --title "Debian ${BUILD_VERSION} OVA - ${FINAL_TAG}" --notes-file "$NOTES"
}

if gh release view "$FINAL_TAG" >/dev/null 2>&1; then
    update_release
elif ! gh release create "$FINAL_TAG" "${ASSETS[@]}" \
    --target "$GITHUB_SHA" --title "Debian ${BUILD_VERSION} OVA - ${FINAL_TAG}" --notes-file "$NOTES"; then
    # Another publisher may have created the tag between view and create.
    # Only retry when the Release actually exists; propagate network/auth failures.
    gh release view "$FINAL_TAG" >/dev/null
    update_release
fi
echo "[INFO] Release 发布完成：$FINAL_TAG（${#ASSETS[@]} 份镜像）"
