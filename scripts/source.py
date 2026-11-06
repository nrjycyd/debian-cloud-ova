"""Resolve one immutable Debian cloud build and verify its original qcow2."""

import hashlib
import json
import re
import sys
import time
import urllib.request
from pathlib import Path

from config import VERSIONS

BASE = "https://cloud.debian.org/images/cloud"


def fetch(url):
    for attempt in range(3):
        try:
            with urllib.request.urlopen(url, timeout=60) as response:
                return response.read()
        except OSError:
            if attempt == 2:
                raise
            time.sleep(1 + attempt)


def resolve(version):
    codename = VERSIONS[version]
    stem = f"debian-{version}-genericcloud-amd64"
    metadata = json.loads(fetch(f"{BASE}/{codename}/latest/{stem}.json"))
    builds = [item["data"]["info"] for item in metadata["items"] if item.get("kind") == "Build"]
    if len(builds) != 1:
        raise ValueError("官方元数据缺少唯一的 Build 信息")
    info = builds[0]
    if any(info.get(key) != expected for key, expected in
           (("release", codename), ("arch", "amd64"), ("vendor", "genericcloud"))):
        raise ValueError("官方镜像元数据与请求的镜像不匹配")
    build = info["version"]
    if not re.fullmatch(r"[0-9]{8}-[0-9]+", build):
        raise ValueError("无法识别官方 build 号，停止构建")
    filename = f"{stem}-{build}.qcow2"
    directory = f"{BASE}/{codename}/{build}"
    checksums = fetch(f"{directory}/SHA512SUMS").decode("utf-8")
    matches = [line.split()[0] for line in checksums.splitlines()
               if len(line.split()) == 2 and line.split()[1].lstrip("*") == filename]
    if len(matches) != 1 or not re.fullmatch(r"[a-fA-F0-9]{128}", matches[0]):
        raise ValueError("官方校验和缺失或不唯一，停止构建")
    return {"debian_version": version, "build": build, "url": f"{directory}/{filename}",
            "sha512": matches[0].lower()}


def validate(source, version):
    if source["debian_version"] != version or not re.fullmatch(r"[0-9]{8}-[0-9]+", source["build"]):
        raise ValueError("源镜像版本不匹配")
    expected = (f"{BASE}/{VERSIONS[version]}/{source['build']}/"
                f"debian-{version}-genericcloud-amd64-{source['build']}.qcow2")
    if source["url"] != expected or not re.fullmatch(r"[a-f0-9]{128}", source["sha512"]):
        raise ValueError("源镜像地址或摘要无效")
    return source


def digest(path):
    checksum = hashlib.sha512()
    with Path(path).open("rb") as stream:
        for block in iter(lambda: stream.read(4 * 1024 * 1024), b""):
            checksum.update(block)
    return checksum.hexdigest()


def download(source, destination):
    """Only a complete, verified file can become a reusable source image."""
    destination = Path(destination)
    if destination.is_file() and digest(destination) == source["sha512"]:
        return
    partial = destination.with_suffix(destination.suffix + ".part")
    try:
        for attempt in range(3):
            try:
                with urllib.request.urlopen(source["url"], timeout=120) as response, partial.open("wb") as output:
                    while block := response.read(4 * 1024 * 1024):
                        output.write(block)
                break
            except OSError:
                if attempt == 2:
                    raise
                time.sleep(1 + attempt)
        if digest(partial) != source["sha512"]:
            raise ValueError("源镜像 SHA512 与 Debian 官方摘要不符，停止构建")
        partial.replace(destination)
    finally:
        partial.unlink(missing_ok=True)


if __name__ == "__main__":
    # Internal diagnostics only; no local OVA build entry point.
    print(json.dumps(resolve(sys.argv[1]), ensure_ascii=False, indent=2))
