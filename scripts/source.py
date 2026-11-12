"""固定 Debian 云镜像 build 并校验原始 qcow2。"""

import hashlib
import json
import re
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

from config import KNOWN_VARIANTS, VARIANTS, VERSIONS

BASE = "https://cloud.debian.org/images/cloud"


def fetch(url):
    for attempt in range(3):
        try:
            with urllib.request.urlopen(url, timeout=60) as response:
                return response.read()
        except urllib.error.HTTPError as error:
            # 4xx 说明官方地址已失效，重试没有意义；5xx 仍按网络错误重试。
            if error.code < 500 or attempt == 2:
                raise
            time.sleep(1 + attempt)
        except OSError:
            if attempt == 2:
                raise
            time.sleep(1 + attempt)


def image_name(version, variant):
    """Debian 官方镜像文件名前缀；变体随发布目录不同，不能写死。"""
    return f"debian-{version}-{variant}-amd64"


def resolve(version, variants=VARIANTS):
    codename = VERSIONS[version]
    missing = []
    for variant in variants:
        image = image_name(version, variant)
        url = f"{BASE}/{codename}/latest/{image}.json"
        try:
            metadata = json.loads(fetch(url))
        except urllib.error.HTTPError as error:
            if error.code != 404:
                raise ValueError(f"官方镜像信息获取失败（HTTP {error.code}）：{url}") from error
            missing.append((image, url))
            continue
        builds = [item["data"]["info"] for item in metadata["items"] if item.get("kind") == "Build"]
        if len(builds) != 1:
            raise ValueError("官方元数据缺少唯一的 Build 信息")
        info = builds[0]
        if any(info.get(key) != expected for key, expected in
               (("release", codename), ("arch", "amd64"), ("vendor", variant))):
            raise ValueError(f"官方镜像元数据与请求的 {image} 镜像不匹配")
        build = info["version"]
        if not re.fullmatch(r"[0-9]{8}-[0-9]+", build):
            raise ValueError("无法识别官方 build 号，停止构建")
        filename = f"{image}-{build}.qcow2"
        directory = f"{BASE}/{codename}/{build}"
        sums_url = f"{directory}/SHA512SUMS"
        try:
            checksums = fetch(sums_url).decode("utf-8")
        except urllib.error.HTTPError as error:
            raise ValueError(f"官方校验和获取失败（HTTP {error.code}）：{sums_url}") from error
        matches = [line.split()[0] for line in checksums.splitlines()
                   if len(line.split()) == 2 and line.split()[1].lstrip("*") == filename]
        if len(matches) != 1 or not re.fullmatch(r"[a-fA-F0-9]{128}", matches[0]):
            raise ValueError("官方校验和缺失或不唯一，停止构建")
        if missing:
            names = ", ".join(name for name, _ in missing)
            print(f"[WARN] 官方 latest 缺少 {names}，本次改用 {image}", file=sys.stderr)
        return {"debian_version": version, "build": build, "variant": variant,
                "url": f"{directory}/{filename}", "sha512": matches[0].lower()}
    raise ValueError("官方 latest 缺少全部已知变体："
                     + "、".join(url for _, url in missing) + "，停止构建")


def validate(source, version):
    if source["debian_version"] != version or not re.fullmatch(r"[0-9]{8}-[0-9]+", source["build"]):
        raise ValueError("源镜像版本不匹配")
    variant = source.get("variant")
    if variant not in KNOWN_VARIANTS:
        raise ValueError("源镜像变体无效")
    expected = (f"{BASE}/{VERSIONS[version]}/{source['build']}/"
                f"{image_name(version, variant)}-{source['build']}.qcow2")
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
    """只有完整且校验通过的下载才能成为可复用源镜像。"""
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
    # 仅用于查看源镜像元数据，不提供本地 OVA 构建入口。
    print(json.dumps(resolve(sys.argv[1]), ensure_ascii=False, indent=2))
