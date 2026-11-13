import json
import tempfile
import unittest
from pathlib import Path

from tests.support import ROOT
import auto_config


def default_config():
    return json.loads((ROOT / ".github/auto-build.json").read_text(encoding="utf-8"))


class AutoConfigTests(unittest.TestCase):
    def load_config(self, directory, **changes):
        data = default_config()
        data.update(changes)
        path = Path(directory) / "auto-build.json"
        path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
        return auto_config.load(path)

    def test_default_config_builds_console_and_ssh(self):
        env = auto_config.load()
        self.assertEqual(env["TARGET_VERSION"], "13")
        self.assertEqual(env["TARGET_ENABLE_SSH"], "true")
        self.assertEqual(env["TARGET_INSTALL_VM_TOOLS"], "true")
        self.assertEqual(env["TARGET_APT_MIRROR"], "清华大学")
        self.assertEqual(env["TARGET_TIMEZONE"], "Asia/Shanghai")
        self.assertEqual(env["TARGET_HOSTNAME"], "debian13")
        builds = [env[key] for key in ("TARGET_BUILD", "TARGET_BUILD_2", "TARGET_BUILD_3", "TARGET_BUILD_4")]
        self.assertEqual(len(builds), 4)
        self.assertTrue(all(label.startswith("ESXi") for label in builds))
        rendered = auto_config.render(env)
        self.assertEqual(len(rendered.splitlines()), 15)
        self.assertIn("TARGET_VERSION=13\n", rendered)
        self.assertEqual(auto_config.main(["--check"]), 0)

    def test_invalid_configs_are_rejected(self):
        cases = (
            ({"version": "11"}, "仅支持 Debian 12/13"),
            ({"targets": []}, "targets 必须是 1-4 个机型标签"),
            ({"targets": ["ESXi 6.7 + DGNU 9 (vmx-14)"] * 2}, "不能重复"),
            ({"targets": ["不存在的机型"]}, "构建目标 1 无效"),
            ({"targets": ["ESXi 6.7 + DGNU 9 (vmx-14)"] * 5}, "targets 必须是 1-4 个机型标签"),
            ({"apt_mirror": "不存在的源"}, "不支持的软件源"),
            ({"timezone": "Mars/Base"}, "不支持的时区"),
            ({"hostname": "bad host"}, "主机名不合法"),
            ({"password": "has space"}, "密码仅允许"),
            ({"vcpu": 0}, "vcpu 必须在 1-64 之间"),
            ({"targets": ["ESXi 6.7 U3 + DGNU 10 (vmx-15)"], "enable_ssh": False,
              "install_vm_tools": False}, None),
        )
        with tempfile.TemporaryDirectory() as directory:
            for changes, message in cases:
                with self.subTest(changes=changes):
                    if message is None:
                        env = self.load_config(directory, **changes)
                        self.assertEqual(env["TARGET_ENABLE_SSH"], "false")
                        self.assertEqual(env["TARGET_INSTALL_VM_TOOLS"], "false")
                    else:
                        with self.assertRaisesRegex(ValueError, message):
                            self.load_config(directory, **changes)

    def test_broken_json_is_reported(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "auto-build.json"
            path.write_text("{not json", encoding="utf-8")
            with self.assertRaises(ValueError):
                auto_config.load(path)
