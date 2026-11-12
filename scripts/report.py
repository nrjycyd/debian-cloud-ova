"""从同一构建清单生成摘要与 Release 说明。"""

import json
import os
import re
import sys
from pathlib import Path

from config import MIRRORS
from release import validate as validate_release
from manifest import validate as validate_manifest


def short_target(target):
    """把工作流里的完整机型标签压成表格用的短标签，避免单元格折行。"""
    match = re.fullmatch(r"ESXi (.+?) \+ DGNU (\d+) \((vmx-\d+)\)", target)
    if not match:
        return target
    version, dgnu, vmx = match.groups()
    return f"{version.replace(' ', '')} · DGNU{dgnu} · {vmx.replace('-', '')}"


def image_table(manifest, password=""):
    # 文件名由 Release 的 Assets 展示，磁盘容量在构建配置里已列出，表格保持窄。
    lines = ["| 目标 | 模式 | 账号 | 密码 | 登录方式 | 大小 |",
             "| --- | --- | --- | --- | --- | --- |"]
    for image in manifest["images"]:
        login = "SSH 密码" if image["kind"] == "ssh" else "控制台"
        lines.append(f"| {short_target(image['target'])} | {image['kind']} | {image['username']} | "
                     f"{password} | {login} | {image['size']} |")
    return "\n".join(lines)


def release_notes(manifest, password):
    validate_manifest(manifest)
    settings = manifest["settings"]
    return f"""## Debian 云镜像 OVA

**构建配置：**
- Debian 版本：**{settings['version']}**
- Debian Build 号：**{manifest['source']['build']}**
- 源镜像变体：**{manifest['source']['variant']}**
- vCPU：**{settings['vcpu']}**
- 内存：**{settings['memory']}MB**
- 磁盘大小：**{manifest['images'][0]['disk_gib']} GB**
- 主机名：**{settings['hostname']}**
- 软件源：**{MIRRORS[settings['mirror']][0]}**
- 安装 open-vm-tools：**{str(settings['install_vm_tools']).lower()}**
- 时区：**{settings['timezone']}**
- 默认镜像：**console（普通用户，SSH 保持源镜像默认配置）**
- 构建时间：**{manifest['build_time']}**

{image_table(manifest, password)}

资产名：`debian<版本>-<变体>-<架构>-<ESXi>-vmx<版本>-<DGNU>-<console|ssh>.ova`，完整文件名见下方 Assets。

**快速开始：**
1. 从 Release 资产中下载 OVA 文件
2. 导入 VMware 或兼容的虚拟化平台

"""


def release_title(manifest):
    # 标题只保留版本与变体；build 号由 Release 的 tag 展示，避免标题过长。
    validate_manifest(manifest)
    return f"Debian {manifest['settings']['version']} · {manifest['source']['variant']}"


def summary(manifest, env):
    text = f"## Debian {env['TARGET_VERSION']} OVA 构建结果\n\n- 状态：{env['BUILD_STATUS']}\n"
    if manifest is None:
        return text + "\n构建未完成，请查看失败步骤的错误信息；本次未发布镜像。\n"
    validate_manifest(manifest)
    settings = manifest["settings"]
    text += (f"- 构建机型：{manifest['target_count']}\n"
             f"- 发布标签：{manifest['release']['tag']}\n"
             f"- 源镜像变体：{manifest['source']['variant']}\n"
             f"- 软件源：{MIRRORS[settings['mirror']][0]}\n"
             f"- 安装 open-vm-tools：{str(settings['install_vm_tools']).lower()}\n"
             f"- 时区：{settings['timezone']}\n"
             f"- 请求磁盘容量：{settings['disk']} GiB\n"
             f"- 实际磁盘容量：{manifest['images'][0]['disk_gib']} GiB\n\n")
    if env["BUILD_STATUS"] != "success":
        text += "构建已完成，但发布未成功完成，请检查发布步骤。\n\n"
    return text + image_table(manifest, env.get("TARGET_PASSWORD", "")) + "\n"


def main():
    manifest_path = os.environ.get("BUILD_MANIFEST", "")
    manifest = json.loads(Path(manifest_path).read_text()) if manifest_path else None
    if sys.argv[1] == "release":
        if manifest is None:
            raise ValueError("没有可发布的镜像")
        validate_release(manifest, os.environ)
        Path(sys.argv[2]).write_text(release_notes(manifest, os.environ["TARGET_PASSWORD"]))
        for image in manifest["images"]:
            filename = image["filename"]
            if Path(filename).name != filename or not filename.endswith(".ova") or not Path(filename).is_file():
                raise ValueError("发布资产不存在或文件名无效")
            print(filename)
    elif sys.argv[1] == "title":
        if manifest is None:
            raise ValueError("没有可发布的镜像")
        validate_release(manifest, os.environ)
        print(release_title(manifest))
    elif sys.argv[1] == "summary":
        if os.environ.get("GITHUB_STEP_SUMMARY"):
            with Path(os.environ["GITHUB_STEP_SUMMARY"]).open("a") as output:
                output.write(summary(manifest, os.environ))
    else:
        raise ValueError("未知报告类型")


if __name__ == "__main__":
    try:
        main()
    except (ValueError, KeyError, OSError) as error:
        sys.exit(f"::error::{error}")
