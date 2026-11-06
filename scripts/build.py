"""Build the selected variants; publish outputs only after the entire batch succeeds."""

import json
import os
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

from config import MIRRORS, ROOT, from_environment, select_targets
from source import download, resolve
from release import policy


def write_outputs(path, values):
    with Path(path).open("a", encoding="utf-8") as output:
        for key, value in values.items():
            output.write(f"{key}={value}\n")


def run_batch(env):
    if env.get("GITHUB_ACTIONS") != "true":
        raise ValueError("请通过 GitHub Actions 构建")
    settings = from_environment(env)
    targets = select_targets(env)
    work = Path(env["RUNNER_TEMP"])
    source = resolve(settings["version"])
    release = policy(env.get("GITHUB_REF", ""), settings["version"], source["build"])
    print(f"[INFO] Debian 官方源版本：{source['build']}；正在下载并校验 SHA512", flush=True)
    source_manifest = work / "debian-source.json"
    source_manifest.write_text(json.dumps(source, indent=2) + "\n")
    source_image = work / "debian-source.qcow2"
    download(source, source_image)
    manifest = {
        "source": source, "release": release,
        "settings": {key: value for key, value in settings.items() if key != "password"},
        "commit": env.get("GITHUB_SHA", ""), "run_id": env.get("GITHUB_RUN_ID", ""),
        "target_count": len(targets), "images": [],
    }
    for index, preset in enumerate(targets, 1):
        print(f"[INFO] 构建目标 {index}/{len(targets)}：{preset['label']}", flush=True)
        for ssh in ([False, True] if settings["enable_ssh"] else [False]):
            output = work / f"target-{index}-{ssh}.outputs"
            output.write_text("")
            image_env = dict(env, GITHUB_OUTPUT=str(output), VIRTUAL_SYSTEM_TYPE=preset["vmx"],
                             OVF_OS_ID=str(preset["os_id"]), OVF_OS_TYPE=preset["os_type"],
                             OVA_SOURCE_MANIFEST=str(source_manifest), OVA_SOURCE_IMAGE=str(source_image))
            arguments = ["bash", str(ROOT / "debian-ova-creator.sh")]
            for flag, value in (
                ("d", settings["version"]), ("c", settings["vcpu"]), ("m", settings["memory"]),
                ("s", settings["disk"]), ("H", settings["hostname"]), ("u", settings["username"]),
                ("p", settings["password"]), ("S", str(ssh).lower()), ("M", settings["mirror"]),
                ("V", str(settings["install_vm_tools"]).lower()), ("T", settings["timezone"]),
            ):
                arguments.extend([f"-{flag}", str(value)])
            subprocess.run(arguments, env=image_env, check=True)
            values = dict(line.split("=", 1) for line in output.read_text().splitlines())
            disk_bytes = int(values["ACTUAL_DISK_BYTES"])
            if manifest["images"] and manifest["images"][0]["disk_bytes"] != disk_bytes:
                raise ValueError("批量镜像的磁盘容量不一致")
            manifest["images"].append({
                "target": preset["label"], "kind": "ssh" if ssh else "console",
                "filename": values["OVA_FILE_NAME"], "size": values["OVA_FILE_SIZE"],
                "username": values["LOGIN_USERNAME"], "disk_bytes": disk_bytes,
                "disk_gib": values["ACTUAL_DISK_GIB"],
            })
    manifest["build_time"] = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M:%S UTC")
    path = work / "build-manifest.json"
    path.write_text(json.dumps(manifest, ensure_ascii=False, indent=2) + "\n")
    write_outputs(env["GITHUB_OUTPUT"], {"BUILD_MANIFEST": path, "FINAL_TAG": release["tag"]})
    print(f"[INFO] 全部构建完成：{len(manifest['images'])} 份镜像，软件源：{MIRRORS[settings['mirror']][0]}")


if __name__ == "__main__":
    try:
        run_batch(os.environ)
    except (ValueError, KeyError, OSError, subprocess.CalledProcessError) as error:
        sys.exit(f"::error::{error}")
