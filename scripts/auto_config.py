"""读取自动构建配置，校验后输出 Actions 需要的 TARGET_* 环境变量。"""

import json
import sys
from pathlib import Path

from config import ROOT, from_environment, select_targets

PATH = ROOT / ".github/auto-build.json"


def load(path=PATH):
    """把 JSON 配置转换成 TARGET_* 环境变量，并复用现有参数校验。"""
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    targets = data.get("targets", [])
    if not isinstance(targets, list) or not 1 <= len(targets) <= 4:
        raise ValueError("自动构建配置的 targets 必须是 1-4 个机型标签")
    if len(set(map(str, targets))) != len(targets):
        raise ValueError("自动构建配置的 targets 不能重复")
    env = {
        "TARGET_VERSION": str(data.get("version", "")),
        "TARGET_BUILD": str(targets[0]),
        "TARGET_BUILD_2": str(targets[1]) if len(targets) > 1 else "",
        "TARGET_BUILD_3": str(targets[2]) if len(targets) > 2 else "",
        "TARGET_BUILD_4": str(targets[3]) if len(targets) > 3 else "",
        "TARGET_VCPU": str(data.get("vcpu", "")),
        "TARGET_MEMORY": str(data.get("memory", "")),
        "TARGET_DISK": str(data.get("disk", "")),
        "TARGET_HOSTNAME": str(data.get("hostname", "")),
        "TARGET_USERNAME": str(data.get("username", "")),
        "TARGET_PASSWORD": str(data.get("password", "")),
        "TARGET_ENABLE_SSH": "true" if data.get("enable_ssh") is True else "false",
        "TARGET_APT_MIRROR": str(data.get("apt_mirror", "")),
        "TARGET_INSTALL_VM_TOOLS": "true" if data.get("install_vm_tools") is True else "false",
        "TARGET_TIMEZONE": str(data.get("timezone", "")),
    }
    from_environment(env)
    select_targets(env)
    return env


def render(env):
    return "".join(f"{key}={value}\n" for key, value in env.items())


def main(argv):
    if "--check" in argv:
        load()
        print("自动构建配置有效")
        return 0
    sys.stdout.write(render(load()))
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main(sys.argv[1:]))
    except (ValueError, KeyError, OSError) as error:
        sys.exit(f"::error::{error}")
