"""Fail with an actionable message before running the maintenance checks."""

import importlib
import sys

if sys.version_info < (3, 8):
    sys.exit("[ERROR] 检查工具要求 Python >=3.8，请使用受支持的 Debian/Ubuntu 系统解释器")
for name, package in (("yaml", "python3-yaml"), ("cloudinit", "cloud-init")):
    try:
        importlib.import_module(name)
    except ImportError:
        sys.exit(f"[ERROR] {sys.executable} 无法导入 {name}，请通过 apt 安装 {package} 并使用 /usr/bin/python3")
print(f"[INFO] 检查环境就绪：{sys.executable} / Python {sys.version.split()[0]}")
