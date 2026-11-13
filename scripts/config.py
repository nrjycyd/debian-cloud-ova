"""Actions 输入和内部构建入口共用的参数校验。"""

import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
VERSIONS = {"12": "bookworm", "13": "trixie"}
# 官方镜像变体：genericcloud 用云内核、镜像更小；generic 用标准内核、兼容性最好。
# KNOWN_VARIANTS 只用于校验清单和地址是否合法，与选择顺序无关。
KNOWN_VARIANTS = ("genericcloud", "generic")
# 选择顺序：按此顺序探测 latest 元数据，缺失则尝试下一个。
# 调整维护策略只需改这一行，例如：
#   交换优先级 -> ("generic", "genericcloud")
#   固定单一变体 -> ("genericcloud",)；直接写 "genericcloud" 也行（见 variant_policy）
VARIANTS = ("genericcloud",)
MIRRORS = {
    "official": ("官方源", ""),
    "tuna": ("清华大学", "https://mirrors.tuna.tsinghua.edu.cn/debian"),
    "ustc": ("中国科学技术大学", "https://mirrors.ustc.edu.cn/debian"),
    "aliyun": ("阿里云", "https://mirrors.aliyun.com/debian"),
    "huawei": ("华为云", "https://repo.huaweicloud.com/debian"),
}
TIMEZONES = (
    "UTC", "Asia/Shanghai", "Asia/Hong_Kong", "Asia/Singapore", "Asia/Tokyo",
    "Europe/London", "Europe/Berlin", "America/New_York",
)


def variant_policy(value):
    """把变体配置规范成元组并校验。

    允许直接写一个变体字符串（例如误写成 ``("genericcloud")``），避免字符串被
    逐字符遍历成 ``g``、``e`` 之类的伪变体；未知变体、空配置、重复项直接报错。
    """
    items = (value,) if isinstance(value, str) else tuple(value)
    if not items or len(set(items)) != len(items) or not set(items) <= set(KNOWN_VARIANTS):
        raise ValueError(f"VARIANTS 配置无效：{value!r}，应为 {KNOWN_VARIANTS} 的非空子集")
    return items


def integer(value, minimum, maximum, name):
    # Python 整数不会溢出，先限制输入长度再检查数值范围。
    text = str(value)
    if not re.fullmatch(r"[0-9]{1,32}", text):
        raise ValueError(f"{name} 必须是 {minimum}-{maximum} 之间的整数")
    number = int(text, 10)
    if not minimum <= number <= maximum:
        raise ValueError(f"{name} 必须在 {minimum}-{maximum} 之间")
    return number


def boolean(value, name):
    if value not in ("true", "false"):
        raise ValueError(f"{name} 必须为 true 或 false")
    return value == "true"


def validate(values, *, image=False):
    """规范化参数；image=True 时允许 SSH 镜像使用 root。"""
    result = dict(values)
    if result["version"] not in VERSIONS:
        raise ValueError("仅支持 Debian 12/13")
    for key, low, high in (("vcpu", 1, 64), ("memory", 256, 262144), ("disk", 2, 2048)):
        result[key] = integer(result[key], low, high, key)
    if not re.fullmatch(r"[a-zA-Z0-9][a-zA-Z0-9-]{0,62}", result["hostname"]):
        raise ValueError("主机名不合法（字母/数字/连字符，最多 63 字符）")
    if not re.fullmatch(r"[A-Za-z0-9@#%+=.,_-]+", result["password"]):
        raise ValueError("密码仅允许字母、数字和 @#%+=.,_-")
    for key in ("enable_ssh", "install_vm_tools"):
        result[key] = boolean(result[key], key)
    if result["timezone"] not in TIMEZONES:
        raise ValueError("不支持的时区")
    if result["mirror"] not in MIRRORS:
        raise ValueError("不支持的软件源")
    if image and result["enable_ssh"]:
        result["username"] = "root"
    elif result["username"] == "root":
        raise ValueError("console 镜像请填写普通用户名，SSH 镜像固定使用 root")
    if not re.fullmatch(r"[a-z_][a-z0-9_-]{0,31}", result["username"]):
        raise ValueError("用户名不合法（小写字母或下划线开头，最多 32 字符）")
    return result


def from_environment(env):
    keys = {
        "version": "TARGET_VERSION", "vcpu": "TARGET_VCPU", "memory": "TARGET_MEMORY",
        "disk": "TARGET_DISK", "hostname": "TARGET_HOSTNAME", "username": "TARGET_USERNAME",
        "password": "TARGET_PASSWORD", "enable_ssh": "TARGET_ENABLE_SSH",
        "install_vm_tools": "TARGET_INSTALL_VM_TOOLS", "timezone": "TARGET_TIMEZONE",
    }
    values = {key: env.get(variable, "") for key, variable in keys.items()}
    labels = {label: key for key, (label, _) in MIRRORS.items()}
    values["mirror"] = labels.get(env.get("TARGET_APT_MIRROR"))
    return validate(values)


def catalog():
    items = json.loads((ROOT / ".github/build-targets.json").read_text(encoding="utf-8"))
    labels = set()
    for item in items:
        label = item.get("label")
        # ESXi 描述允许更新版本范围，仅解析固定格式的 DGNU/vmx 后缀。
        match = re.fullmatch(r"ESXi .+ \+ DGNU ([0-9]+) \((vmx-[0-9]+)\)", label) if isinstance(label, str) else None
        if not match:
            raise ValueError(f"机型目录 label 格式不合法：{label}")
        if int(match[1]) != item.get("dgnu") or match[2] != item.get("vmx"):
            raise ValueError(f"机型目录 label 与 DGNU/vmx 字段不一致：{label}")
        if label in labels:
            raise ValueError(f"机型目录 label 重复：{label}")
        labels.add(label)
    return items


def select_targets(env):
    presets = {item["label"]: item for item in catalog()}
    selected, seen = [], set()
    for slot, key in enumerate(("TARGET_BUILD", "TARGET_BUILD_2", "TARGET_BUILD_3", "TARGET_BUILD_4"), 1):
        label = env.get(key, "")
        if slot > 1 and label in ("", "不构建"):
            continue
        if label not in presets:
            raise ValueError(f"构建目标 {slot} 无效，请从下拉框选择")
        item = presets[label]
        identity = (item["vmx"], item["os_type"])
        if identity not in seen:
            selected.append(item)
            seen.add(identity)
    return selected


def target(vmx, os_id, os_type):
    for item in catalog():
        if (item["vmx"], str(item["os_id"]), item["os_type"]) == (vmx, str(os_id), os_type):
            return item
    raise ValueError("无效的 ESXi / Guest OS 组合")
