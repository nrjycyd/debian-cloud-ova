"""Keep test builds out of the production Release namespace."""

import re
from config import VERSIONS


def policy(ref, version, build):
    if version not in VERSIONS or not re.fullmatch(r"[0-9]{8}-[0-9]+", build):
        raise ValueError("发布版本或官方 build 号无效")
    if ref == "refs/heads/main":
        return {"tag": build, "prerelease": False}
    if ref == "refs/heads/test":
        return {"tag": f"test-debian{version}-{build}", "prerelease": True}
    raise ValueError("发布仅支持 main 或 test 分支，其他 ref 不允许发布")


def validate(manifest, env):
    expected = policy(env.get("GITHUB_REF", ""), manifest["settings"]["version"], manifest["source"]["build"])
    if manifest["release"] != expected or env.get("FINAL_TAG") != expected["tag"]:
        raise ValueError("发布标签与当前分支不匹配，拒绝上传资产")
    if env["TARGET_VERSION"] != manifest["settings"]["version"]:
        raise ValueError("发布系统版本与构建清单不匹配")
    return expected
