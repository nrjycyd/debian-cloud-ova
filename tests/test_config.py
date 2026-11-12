import sys
import copy
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "scripts"))
from tests.support import environment
from config import (VARIANTS, VERSIONS, catalog, from_environment, integer, select_targets,
                    target, validate)


class ConfigTests(unittest.TestCase):
    def test_source_variants_cover_supported_versions(self):
        # 源镜像变体按版本查表，漏配会让构建在下载前抛 KeyError。
        self.assertEqual(set(VARIANTS), set(VERSIONS))

    def test_catalog_rejects_label_drift_and_duplicates(self):
        items = catalog()
        changes = (
            ({"vmx": "vmx-22"}, "字段不一致"),
            ({"dgnu": 13}, "字段不一致"),
            ({"label": "ESXi 6.7 + DGNU 9 (vmx-14) FAKE"}, "格式不合法"),
            ({"label": None}, "格式不合法"),
        )
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            (root / ".github").mkdir()
            path = root / ".github/build-targets.json"
            with patch("config.ROOT", root):
                # 所有现有更新版本范围均须保持可用。
                path.write_text(json.dumps(items))
                self.assertEqual(catalog(), items)
                for change, error in changes:
                    modified = copy.deepcopy(items)
                    modified[0].update(change)
                    path.write_text(json.dumps(modified))
                    with self.subTest(change=change), self.assertRaisesRegex(ValueError, error):
                        catalog()
                path.write_text(json.dumps(items + [items[0]]))
                with self.assertRaisesRegex(ValueError, "label 重复"):
                    catalog()

    def test_integer_boundaries_and_overflow(self):
        for key, low, high in (("TARGET_VCPU", 1, 64), ("TARGET_MEMORY", 256, 262144), ("TARGET_DISK", 2, 2048)):
            for value in (str(low), str(high), "00" + str(low)):
                with self.subTest(key=key, value=value):
                    settings = from_environment(dict(environment(), **{key: value}))
                    self.assertIsInstance(settings[{"TARGET_VCPU": "vcpu", "TARGET_MEMORY": "memory", "TARGET_DISK": "disk"}[key]], int)
            for value in (str(low - 1), str(high + 1), "18446744073709551620", "9" * 5000,
                          "", "1.5", "$(touch /tmp/ova-injection)", "２", "4\n", "-2"):
                with self.subTest(key=key, value=value[:30]), self.assertRaises(ValueError):
                    from_environment(dict(environment(), **{key: value}))
        self.assertEqual(integer("08", 2, 2048, "disk"), 8)

    def test_user_and_image_policy(self):
        settings = from_environment(environment())
        self.assertEqual(settings["username"], "debian")
        raw = {**settings, "enable_ssh": "true", "install_vm_tools": "true"}
        self.assertEqual(validate(raw, image=True)["username"], "root")
        for key, value in (("TARGET_VERSION", "11"), ("TARGET_VERSION", "sid"), ("TARGET_USERNAME", "root"),
                           ("TARGET_PASSWORD", "bad\npassword"), ("TARGET_HOSTNAME", "$(whoami)"),
                           ("TARGET_TIMEZONE", "wrong"), ("TARGET_APT_MIRROR", "wrong"),
                           ("TARGET_ENABLE_SSH", "yes"), ("TARGET_INSTALL_VM_TOOLS", "yes")):
            with self.subTest(key=key), self.assertRaises(ValueError):
                from_environment(dict(environment(), **{key: value}))

    def test_all_targets_and_selection(self):
        self.assertEqual(len(catalog()), 25)
        for item in catalog():
            self.assertEqual(target(item["vmx"], item["os_id"], item["os_type"]), item)
        self.assertEqual(len(select_targets(environment())), 4)
        env = environment()
        env.update(TARGET_BUILD_2=env["TARGET_BUILD"], TARGET_BUILD_3="不构建", TARGET_BUILD_4="")
        self.assertEqual(len(select_targets(env)), 1)
        for slot in ("TARGET_BUILD", "TARGET_BUILD_2", "TARGET_BUILD_3", "TARGET_BUILD_4"):
            for value in ("$(whoami)", "vmx19-dgnu11", "bad\nvalue", "'", ";exit 0", "not a preset", "vmx-99", "--help"):
                with self.subTest(slot=slot, value=value), self.assertRaises(ValueError):
                    select_targets(dict(environment(), **{slot: value}))


if __name__ == "__main__":
    unittest.main()
