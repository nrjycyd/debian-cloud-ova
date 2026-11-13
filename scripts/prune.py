"""保留最近若干版本的发布，清理更早的自动构建 Release。"""

import argparse
import json
import re
import subprocess
import sys


def gh(*args):
    result = subprocess.run(["gh", *args], check=True, capture_output=True, text=True)
    return result.stdout


def release_tags(version):
    """按 `<版本>-<build>` 命名筛选该版本的发布。"""
    pattern = re.compile(rf"{re.escape(version)}-[0-9]{{8}}-[0-9]+")
    items = json.loads(gh("release", "list", "--limit", "100", "--json", "tagName,createdAt"))
    return [item for item in items if pattern.fullmatch(item["tagName"])]


def prune(version, keep, expect_assets, dry_run=False):
    """保留最新的 keep 个发布；最新发布资产不全时拒绝清理。"""
    if keep < 1:
        raise ValueError("保留数量必须大于 0")
    if expect_assets < 1:
        raise ValueError("期望资产数量必须大于 0")
    items = sorted(release_tags(version), key=lambda item: item["createdAt"], reverse=True)
    if len(items) <= keep:
        return []
    newest = items[0]["tagName"]
    assets = json.loads(gh("release", "view", newest, "--json", "assets"))["assets"]
    if len(assets) != expect_assets:
        raise ValueError(f"最新发布 {newest} 只有 {len(assets)} 个资产，"
                         f"期望 {expect_assets} 个，暂不清理旧版本")
    deleted = [item["tagName"] for item in items[keep:]]
    if not dry_run:
        for tag in deleted:
            gh("release", "delete", tag, "--yes", "--cleanup-tag")
    return deleted


def main(argv):
    parser = argparse.ArgumentParser(description="保留最近若干版本的 Release")
    parser.add_argument("--version", required=True, help="Debian 版本，例如 13")
    parser.add_argument("--keep", type=int, default=2, help="保留最近几个版本")
    parser.add_argument("--expect-assets", type=int, required=True, help="最新发布的资产数量")
    parser.add_argument("--dry-run", action="store_true", help="只打印将删除的发布")
    args = parser.parse_args(argv)
    deleted = prune(args.version, args.keep, args.expect_assets, args.dry_run)
    if not deleted:
        print(f"[INFO] {args.version} 的发布数量未超过 {args.keep} 个，无需清理")
    else:
        action = "将删除" if args.dry_run else "已删除"
        print(f"[INFO] {action} {len(deleted)} 个旧发布：{', '.join(deleted)}")
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main(sys.argv[1:]))
    except (ValueError, KeyError, OSError, subprocess.CalledProcessError) as error:
        sys.exit(f"::error::{error}")
