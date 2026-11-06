"""Refresh static Actions target choices from the catalog, or check for drift."""

import re
import sys

from config import ROOT, catalog

path = ROOT / ".github/workflows/build-ova.yml"
original = path.read_text(encoding="utf-8")
updated = original
labels = [item["label"] for item in catalog()]
for key in ("build_target", "build_target_2", "build_target_3", "build_target_4"):
    choices = labels if key == "build_target" else ["不构建"] + labels
    pattern = rf"(      {key}:\n(?:        [^\n]*\n)*?        options:\n)(?:          - [^\n]*\n)+"
    updated, count = re.subn(pattern, lambda match: match[1] + "".join(f"          - '{label}'\n" for label in choices),
                            updated, count=1)
    if count != 1:
        sys.exit(f"找不到面板字段：{key}")
if "--check" in sys.argv:
    if updated != original:
        sys.exit("机型选项与目录不一致，请运行 python3 scripts/update-panel.py")
else:
    path.write_text(updated, encoding="utf-8")
