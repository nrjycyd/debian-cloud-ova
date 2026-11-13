"""仅发布 main 构建，沿用已固定的官方 build 标签。"""

import re
from config import VERSIONS
from manifest import validate as validate_manifest


def policy(ref, version, build):
    if version not in VERSIONS or not re.fullmatch(r"[0-9]{8}-[0-9]+", build):
        raise ValueError("发布版本或官方 build 号无效")
    if ref == "refs/heads/main":
        # tag 带版本前缀，避免 Debian 12/13 的 build 号相同而冲突。
        return {"tag": f"{version}-{build}"}
    raise ValueError("发布仅支持 main 分支，其他 ref 不允许发布")


def validate(manifest, env):
    validate_manifest(manifest)
    expected = policy(env.get("GITHUB_REF", ""), manifest["settings"]["version"], manifest["source"]["build"])
    if manifest["release"] != expected or env.get("FINAL_TAG") != expected["tag"]:
        raise ValueError("发布标签与当前分支不匹配，拒绝上传资产")
    if env["TARGET_VERSION"] != manifest["settings"]["version"]:
        raise ValueError("发布系统版本与构建清单不匹配")
    return expected
