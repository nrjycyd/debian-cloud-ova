import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from tests.support import ROOT
import auto_config


def default_config():
    return json.loads((ROOT / ".github/auto-build.json").read_text(encoding="utf-8"))


class AutoConfigTests(unittest.TestCase):
    def write_config(self, directory, data):
        path = Path(directory) / "auto-build.json"
        path.write_text(json.dumps(data, ensure_ascii=False), encoding="utf-8")
        return path

    def test_default_config_covers_both_versions(self):
        envs = auto_config.load()
        self.assertEqual([env["TARGET_VERSION"] for env in envs], ["13", "12"])
        for env, hostname in zip(envs, ("debian13", "debian12")):
            self.assertEqual(env["TARGET_HOSTNAME"], hostname)
            self.assertEqual(env["TARGET_ENABLE_SSH"], "true")
            self.assertEqual(env["TARGET_INSTALL_VM_TOOLS"], "true")
            self.assertEqual(env["TARGET_APT_MIRROR"], "清华大学")
            self.assertEqual(env["TARGET_TIMEZONE"], "Asia/Shanghai")
            builds = [env[key] for key in
                      ("TARGET_BUILD", "TARGET_BUILD_2", "TARGET_BUILD_3", "TARGET_BUILD_4")]
            self.assertEqual(len(builds), 4)
            self.assertTrue(all(label.startswith("ESXi") for label in builds))
        self.assertEqual(auto_config.main(["--check"]), 0)

    def test_env_output_for_single_version(self):
        env = auto_config.environment_for("12")
        self.assertEqual(env["TARGET_VERSION"], "12")
        text = auto_config.render(env)
        self.assertEqual(len(text.splitlines()), 15)
        self.assertIn("TARGET_VERSION=12\n", text)
        self.assertIn("TARGET_HOSTNAME=debian12\n", text)
        with self.assertRaises(ValueError):
            auto_config.environment_for("11")

    def test_pending_skips_published_builds(self):
        builds = {"13": "20261111-2659", "12": "20261112-2660"}
        published = {"13-20261111-2659"}
        with patch("auto_config.resolve", side_effect=lambda version: {"build": builds[version]}), \
                patch("auto_config.release_exists", side_effect=lambda tag: tag in published):
            self.assertEqual(auto_config.pending(), ["12"])
            published.add("12-20261112-2660")
            self.assertEqual(auto_config.pending(), [])

    def test_invalid_configs_are_rejected(self):
        base = default_config()
        cases = (
            ({"builds": []}, "builds 不能为空"),
            ({"builds": [{"version": "11", "hostname": "debian11"}]}, "仅支持 Debian 12/13"),
            ({"builds": [{"version": "13", "hostname": "a"}, {"version": "13", "hostname": "b"}]},
             "版本不能重复"),
            ({"defaults": {**base["defaults"], "targets": []}}, "targets 必须是 1-4 个机型标签"),
            ({"defaults": {**base["defaults"], "targets": ["ESXi 6.7 + DGNU 9 (vmx-14)"] * 2}}, "不能重复"),
            ({"defaults": {**base["defaults"], "targets": ["不存在的机型"]}}, "构建目标 1 无效"),
            ({"defaults": {**base["defaults"], "targets": ["ESXi 6.7 + DGNU 9 (vmx-14)"] * 5}},
             "targets 必须是 1-4 个机型标签"),
            ({"defaults": {**base["defaults"], "apt_mirror": "不存在的源"}}, "不支持的软件源"),
            ({"defaults": {**base["defaults"], "timezone": "Mars/Base"}}, "不支持的时区"),
            ({"builds": [{"version": "13", "hostname": "bad host"}]}, "主机名不合法"),
            ({"defaults": {**base["defaults"], "password": "has space"}}, "密码仅允许"),
            ({"defaults": {**base["defaults"], "vcpu": 0}}, "vcpu 必须在 1-64 之间"),
        )
        with tempfile.TemporaryDirectory() as directory:
            for changes, message in cases:
                path = self.write_config(directory, {**base, **changes})
                with self.subTest(changes=changes), self.assertRaisesRegex(ValueError, message):
                    auto_config.load(path)

    def test_ssh_and_tools_can_be_disabled(self):
        with tempfile.TemporaryDirectory() as directory:
            data = default_config()
            data["defaults"].update(enable_ssh=False, install_vm_tools=False)
            envs = auto_config.load(self.write_config(directory, data))
        for env in envs:
            self.assertEqual(env["TARGET_ENABLE_SSH"], "false")
            self.assertEqual(env["TARGET_INSTALL_VM_TOOLS"], "false")

    def test_broken_json_is_reported(self):
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "auto-build.json"
            path.write_text("{not json", encoding="utf-8")
            with self.assertRaises(ValueError):
                auto_config.load(path)
