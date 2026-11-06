"""Fail with an actionable message before running the maintenance checks."""

import importlib
import sys

if sys.version_info < (3, 8):
    sys.exit("[ERROR] 检查工具要求 Python >=3.8，请使用受支持的 Debian/Ubuntu 系统解释器")
for name, package in (("yaml", "python3-yaml"), ("cloudinit", "cloud-init")):
    try:
        importlib.import_module(name)
    except ImportError:
        hint = ("当前为虚拟环境，请改用 /usr/bin/python3 scripts/check-environment.py"
                if sys.prefix != sys.base_prefix else
                f"请执行 sudo apt install {package}，再用 /usr/bin/python3 运行检查")
        sys.exit(f"[ERROR] {sys.executable} 无法导入 {name}。{hint}")
print(f"[INFO] 检查环境就绪：{sys.executable} / Python {sys.version.split()[0]}")
