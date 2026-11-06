"""在展示或发布前校验构建结果清单。"""

from pathlib import Path

from config import MIRRORS, TIMEZONES, VERSIONS


def require(mapping, key, expected, prefix=""):
    name = f"{prefix}.{key}" if prefix else key
    if key not in mapping:
        raise ValueError(f"构建清单缺少 {name} 字段，请使用当前版本重新构建")
    value = mapping[key]
    # bool 是 int 的子类；精确类型检查避免 True 冒充整数。
    if type(value) is not expected:
        raise ValueError(f"构建清单 {name} 类型错误，应为 {expected.__name__}")
    if expected is str and not value:
        raise ValueError(f"构建清单 {name} 不能为空")
    return value


def validate(manifest):
    if type(manifest) is not dict:
        raise ValueError("构建清单必须是 JSON 对象，请使用当前版本重新构建")
    settings = require(manifest, "settings", dict)
    source = require(manifest, "source", dict)
    release = require(manifest, "release", dict)
    images = require(manifest, "images", list)
    require(manifest, "build_time", str)
    count = require(manifest, "target_count", int)
    if not 1 <= count <= 4 or not count <= len(images) <= count * 2:
        raise ValueError("构建清单机型数量或镜像数量不一致")
    for key in ("version", "hostname", "username", "mirror", "timezone"):
        require(settings, key, str, "settings")
    for key in ("vcpu", "memory", "disk"):
        if require(settings, key, int, "settings") <= 0:
            raise ValueError(f"构建清单 settings.{key} 必须为正整数")
    require(settings, "install_vm_tools", bool, "settings")
    if settings["version"] not in VERSIONS or settings["mirror"] not in MIRRORS or settings["timezone"] not in TIMEZONES:
        raise ValueError("构建清单包含不支持的系统版本、软件源或时区")
    require(source, "build", str, "source")
    require(release, "tag", str, "release")
    filenames = set()
    targets = set()
    for index, image in enumerate(images):
        prefix = f"images[{index}]"
        if type(image) is not dict:
            raise ValueError(f"构建清单 {prefix} 必须是对象")
        for key in ("target", "kind", "filename", "username", "size", "disk_gib"):
            require(image, key, str, prefix)
        size = require(image, "disk_bytes", int, prefix)
        filename = image["filename"]
        if size <= 0 or image["kind"] not in ("console", "ssh"):
            raise ValueError(f"构建清单 {prefix} 的容量或镜像类型无效")
        if Path(filename).name != filename or not filename.endswith(".ova") or filename.startswith("-"):
            raise ValueError(f"构建清单 {prefix}.filename 不是有效的 OVA 文件名")
        if filename in filenames:
            raise ValueError(f"构建清单重复列出镜像：{filename}")
        filenames.add(filename)
        targets.add(image["target"])
    if len(targets) != count:
        raise ValueError("构建清单机型数量与镜像列表不一致")
    return manifest
