"""生成 cloud-init 与 OVF，访客机脚本从独立文件读取。"""

import json
import os
import secrets
import sys
from pathlib import Path
from string import Template

from config import MIRRORS, ROOT, target, validate
from source import validate as validate_source


def guest_file(name, destination):
    return {"path": destination, "owner": "root:root", "permissions": "0700",
            "content": (ROOT / "guest" / name).read_text(encoding="utf-8")}


def cloud_config(settings, source, preset, env):
    ssh = settings["enable_ssh"]
    user = {"name": settings["username"], "shell": "/bin/bash", "lock_passwd": False}
    if not ssh:
        user["sudo"] = "ALL=(ALL) NOPASSWD:ALL"
    provenance = {
        "source": source, "repository": env.get("GITHUB_REPOSITORY", ""),
        "commit": env.get("GITHUB_SHA", ""), "run_id": env.get("GITHUB_RUN_ID", ""),
        "run_attempt": env.get("GITHUB_RUN_ATTEMPT", ""), "target": preset,
        "settings": {key: value for key, value in settings.items() if key != "password"},
    }
    config = {
        "users": [user],
        "timezone": settings["timezone"],
        "growpart": {"mode": "auto", "devices": ["/"], "ignore_growroot_disabled": True},
        "resize_rootfs": True,
        # 此 chpasswd 格式已在 Debian 12 cloud-init 22.4.2 和 Debian 13 验证。
        "chpasswd": {"users": [{"name": settings["username"], "password": settings["password"], "type": "text"}],
                     "expire": False},
        "packages": ["cloud-init", "tzdata"] + (["open-vm-tools"] if settings["install_vm_tools"] else []),
        "write_files": [
            guest_file("configure-ssh.sh", "/usr/local/sbin/configure-ova-ssh"),
            guest_file("configure-ova.sh", "/usr/local/sbin/configure-ova"),
            {"path": "/etc/ova-build-info.json", "owner": "root:root", "permissions": "0644",
             "content": json.dumps(provenance, ensure_ascii=False, indent=2) + "\n"},
        ],
        "runcmd": [["/usr/local/sbin/configure-ova", str(ssh).lower(), str(settings["install_vm_tools"]).lower()]],
    }
    # console 沿用源镜像的 SSH 默认值，仅 SSH 镜像覆盖服务及认证策略。
    if ssh:
        config.update(ssh_pwauth=True, disable_root=False)
        config["packages"].append("openssh-server")
    bootcmd = []
    if settings["mirror"] != "official":
        config["apt"] = {"preserve_sources_list": True, "generate_mirrorlists": False}
        bootcmd.append(["cloud-init-per", "instance", "ova-domestic-apt", "/usr/bin/python3", "-c",
                        (ROOT / "guest/apt-mirrors.py").read_text(encoding="utf-8"), MIRRORS[settings["mirror"]][1]])
    if bootcmd:
        config["bootcmd"] = bootcmd
    return config


def main():
    action = sys.argv[1]
    if action == "cloud":
        # 参数顺序须与 debian-ova-creator.sh 的内部调用一致。
        keys = ("version", "vcpu", "memory", "disk", "hostname", "username", "password",
                "enable_ssh", "mirror", "install_vm_tools", "timezone")
        settings = validate(dict(zip(keys, sys.argv[4:])), image=True)
        preset = target(os.environ["VIRTUAL_SYSTEM_TYPE"], os.environ["OVF_OS_ID"], os.environ["OVF_OS_TYPE"])
        source = validate_source(json.loads(Path(os.environ["OVA_SOURCE_MANIFEST"]).read_text()), settings["version"])
        config = cloud_config(settings, source, preset, os.environ)
        # JSON 是 YAML 子集；cloud-config 标识使 cloud-init 按 YAML 解析。
        Path(sys.argv[2]).write_text("#cloud-config\n" + json.dumps(config, ensure_ascii=False, indent=2) + "\n")
        Path(sys.argv[3]).write_text(json.dumps({
            "instance-id": f"debian-{settings['version']}-{secrets.token_hex(8)}",
            "local-hostname": settings["hostname"],
        }) + "\n")
        print(f"{settings['vcpu']} {settings['memory']} {settings['disk']} {settings['username']} "
              f"{source['sha512']} {source['variant']}")
    elif action == "ovf":
        template = (ROOT / "templates/appliance.ovf").read_text(encoding="utf-8")
        Path(sys.argv[2]).write_text(Template(template).substitute(os.environ))
    else:
        raise ValueError("未知渲染操作")


if __name__ == "__main__":
    try:
        main()
    except (ValueError, KeyError, OSError) as error:
        sys.exit(f"[ERROR] {error}")
