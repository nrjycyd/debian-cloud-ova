"""读取自动构建配置，校验后输出 Actions 需要的 TARGET_* 环境变量。"""

import json
import subprocess
import sys
from pathlib import Path

from config import ROOT, from_environment, select_targets
from source import resolve

PATH = ROOT / ".github/auto-build.json"


def environment(values):
    """把一个版本的配置转换成 TARGET_* 环境变量，并复用现有参数校验。"""
    targets = values.get("targets", [])
    if not isinstance(targets, list) or not 1 <= len(targets) <= 4:
        raise ValueError("自动构建配置的 targets 必须是 1-4 个机型标签")
    if len(set(map(str, targets))) != len(targets):
        raise ValueError("自动构建配置的 targets 不能重复")
    env = {
        "TARGET_VERSION": str(values.get("version", "")),
        "TARGET_BUILD": str(targets[0]),
        "TARGET_BUILD_2": str(targets[1]) if len(targets) > 1 else "",
        "TARGET_BUILD_3": str(targets[2]) if len(targets) > 2 else "",
        "TARGET_BUILD_4": str(targets[3]) if len(targets) > 3 else "",
        "TARGET_VCPU": str(values.get("vcpu", "")),
        "TARGET_MEMORY": str(values.get("memory", "")),
        "TARGET_DISK": str(values.get("disk", "")),
        "TARGET_HOSTNAME": str(values.get("hostname", "")),
        "TARGET_USERNAME": str(values.get("username", "")),
        "TARGET_PASSWORD": str(values.get("password", "")),
        "TARGET_ENABLE_SSH": "true" if values.get("enable_ssh") is True else "false",
        "TARGET_APT_MIRROR": str(values.get("apt_mirror", "")),
        "TARGET_INSTALL_VM_TOOLS": "true" if values.get("install_vm_tools") is True else "false",
        "TARGET_TIMEZONE": str(values.get("timezone", "")),
    }
    from_environment(env)
    select_targets(env)
    return env


def load(path=PATH):
    """读取配置，返回按声明顺序排列的各版本 TARGET_* 环境变量。"""
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    defaults = data.get("defaults", {})
    builds = data.get("builds")
    if not isinstance(defaults, dict):
        raise ValueError("自动构建配置的 defaults 必须是对象")
    if not isinstance(builds, list) or not builds:
        raise ValueError("自动构建配置的 builds 不能为空")
    envs, versions = [], set()
    for entry in builds:
        if not isinstance(entry, dict):
            raise ValueError("自动构建配置的 builds 每一项都必须是对象")
        env = environment({**defaults, **entry})
        if env["TARGET_VERSION"] in versions:
            raise ValueError("自动构建配置的版本不能重复")
        versions.add(env["TARGET_VERSION"])
        envs.append(env)
    return envs


def environment_for(version, path=PATH):
    for env in load(path):
        if env["TARGET_VERSION"] == version:
            return env
    raise ValueError(f"自动构建配置中没有 Debian {version}")


def render(env):
    return "".join(f"{key}={value}\n" for key, value in env.items())


def release_exists(tag):
    result = subprocess.run(["gh", "release", "view", tag], capture_output=True, text=True)
    return result.returncode == 0


def pending(path=PATH):
    """返回还没有发布过当前官方 build 的版本。"""
    versions = []
    for env in load(path):
        version = env["TARGET_VERSION"]
        build = resolve(version)["build"]
        if not release_exists(f"{version}-{build}"):
            versions.append(version)
    return versions


def main(argv):
    if "--check" in argv:
        load()
        print("自动构建配置有效")
        return 0
    if "--pending" in argv:
        print(json.dumps(pending()))
        return 0
    if "--env" in argv:
        sys.stdout.write(render(environment_for(argv[argv.index("--env") + 1])))
        return 0
    raise ValueError("未知参数，可用 --check / --pending / --env <版本>")


if __name__ == "__main__":
    try:
        sys.exit(main(sys.argv[1:]))
    except (ValueError, KeyError, OSError) as error:
        sys.exit(f"::error::{error}")
