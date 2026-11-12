import copy
import unittest

from tests.support import sample_manifest
from config import catalog
from manifest import validate
from report import image_table, release_notes, release_title, short_target, summary


class ManifestTests(unittest.TestCase):
    def test_current_format_and_password_display(self):
        manifest = sample_manifest()
        variant = manifest["source"]["variant"]
        self.assertIs(validate(manifest), manifest)
        notes = release_notes(manifest, "123456")
        self.assertIn("| 目标 | 模式 | 账号 | 密码 | 登录方式 | 大小 |", notes)
        self.assertIn("| 123456 |", notes)
        self.assertIn(f"源镜像变体：{variant}", notes)
        self.assertIn("加装包：open-vm-tools", notes)
        self.assertIn("ssh 模式需等待 cloud-init 完成后执行 `ssh root@<虚拟机 IP>`", notes)
        self.assertNotIn("开机并使用以下凭据登录", notes)
        self.assertNotIn("默认镜像", notes)
        self.assertNotIn("资产名：", notes)
        self.assertNotIn("**", notes.split("**快速开始：**")[0])
        self.assertEqual(release_title(manifest), f"Debian 13 · {variant}")
        self.assertNotIn("123456", str(manifest))

    def test_image_table_stays_compact(self):
        table = image_table(sample_manifest(), "123456").splitlines()
        self.assertEqual(table[0], "| 目标 | 模式 | 账号 | 密码 | 登录方式 | 大小 |")
        for row in table[2:]:
            self.assertEqual(row.count("|"), 7)
            self.assertIn("| 123456 |", row)
        for item in catalog():
            short = short_target(item["label"])
            self.assertNotIn("ESXi", short)
            self.assertNotIn("(", short)
            self.assertEqual(short.count(" · "), 2)
            self.assertLessEqual(len(short), 30)
        self.assertEqual(short_target("未匹配的标签"), "未匹配的标签")

    def test_missing_fields_explain_which_format_failed(self):
        for key in ("settings", "source", "release", "images", "build_time", "target_count"):
            manifest = sample_manifest()
            del manifest[key]
            with self.subTest(key=key), self.assertRaisesRegex(ValueError, f"缺少 {key} 字段"):
                validate(manifest)
        for key in ("build", "variant"):
            manifest = sample_manifest()
            del manifest["source"][key]
            with self.subTest(key=f"source.{key}"), \
                    self.assertRaisesRegex(ValueError, f"缺少 source.{key} 字段"):
                validate(manifest)
        manifest = sample_manifest()
        del manifest["release"]
        for formatter in (lambda: release_notes(manifest, "123456"),
                          lambda: summary(manifest, {"TARGET_VERSION": "13", "BUILD_STATUS": "failure"})):
            with self.assertRaisesRegex(ValueError, "缺少 release 字段"):
                formatter()

    def test_wrong_types_and_incomplete_assets_fail_closed(self):
        base = sample_manifest()
        for group, key, value in (
            (None, "target_count", True), (None, "images", {}), (None, "settings", []),
            ("settings", "memory", "1024"), ("settings", "install_vm_tools", "true"),
            ("settings", "vcpu", True), ("settings", "memory", True), ("settings", "disk", True),
            ("settings", "install_vm_tools", 1),
            ("source", "build", None),
        ):
            manifest = copy.deepcopy(base)
            target = manifest[group] if group else manifest
            target[key] = value
            with self.subTest(group=group, key=key), self.assertRaises(ValueError):
                validate(manifest)
        manifest = copy.deepcopy(base)
        manifest["source"]["variant"] = "nocloud"
        with self.assertRaisesRegex(ValueError, "不是受支持的镜像变体"):
            validate(manifest)
        for changes in ({"filename": "../outside.ova"}, {"kind": "unknown"}, {"disk_bytes": 0}):
            manifest = copy.deepcopy(base)
            manifest["images"][0].update(changes)
            with self.subTest(changes=changes), self.assertRaises(ValueError):
                validate(manifest)
        manifest = copy.deepcopy(base)
        manifest["images"].append(copy.deepcopy(manifest["images"][0]))
        with self.assertRaisesRegex(ValueError, "重复"):
            validate(manifest)
