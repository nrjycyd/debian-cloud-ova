import copy
import unittest

from tests.support import sample_manifest
from manifest import validate
from report import release_notes, summary


class ManifestTests(unittest.TestCase):
    def test_current_format_and_password_display(self):
        manifest = sample_manifest()
        self.assertIs(validate(manifest), manifest)
        self.assertIn("密码：`123456`", release_notes(manifest, "123456"))
        self.assertNotIn("123456", str(manifest))

    def test_missing_fields_explain_which_format_failed(self):
        for key in ("settings", "source", "release", "images", "build_time", "target_count"):
            manifest = sample_manifest()
            del manifest[key]
            with self.subTest(key=key), self.assertRaisesRegex(ValueError, f"缺少 {key} 字段"):
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
        for changes in ({"filename": "../outside.ova"}, {"kind": "unknown"}, {"disk_bytes": 0}):
            manifest = copy.deepcopy(base)
            manifest["images"][0].update(changes)
            with self.subTest(changes=changes), self.assertRaises(ValueError):
                validate(manifest)
        manifest = copy.deepcopy(base)
        manifest["images"].append(copy.deepcopy(manifest["images"][0]))
        with self.assertRaisesRegex(ValueError, "重复"):
            validate(manifest)
