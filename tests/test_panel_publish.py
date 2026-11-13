import json
import os
import subprocess
import tempfile
import unittest
from pathlib import Path

import yaml

from tests.support import ROOT
from config import MIRRORS, TIMEZONES, VARIANTS, VERSIONS, catalog, variant_policy
from panel import validate as validate_panel
from release import policy

POLICY = variant_policy(VARIANTS)


class PanelTests(unittest.TestCase):
    def test_panel_catalog_and_workflow_guards(self):
        workflow = yaml.safe_load((ROOT / ".github/workflows/build-ova.yml").read_text())
        triggers = workflow.get("on", workflow.get(True))
        self.assertEqual(set(triggers), {"workflow_dispatch", "schedule"})
        self.assertEqual(triggers["schedule"], [{"cron": "0 6 * * *"}])
        inputs = triggers["workflow_dispatch"]["inputs"]
        labels = [item["label"] for item in catalog()]
        for slot in ("build_target", "build_target_2", "build_target_3", "build_target_4"):
            self.assertEqual(inputs[slot]["options"], labels if slot == "build_target" else ["不构建"] + labels)
        self.assertEqual([inputs[key]["default"] for key in ("build_target", "build_target_2", "build_target_3", "build_target_4")],
                         ["ESXi 6.7 U3 + DGNU 10 (vmx-15)", "ESXi 7.0 U3 + DGNU 11 (vmx-19)",
                          "ESXi 8.0 U3 + DGNU 13 (vmx-21)", "ESXi 9.0+ + DGNU 13 (vmx-22)"])
        self.assertEqual(inputs["debian_version"]["options"], list(VERSIONS))
        self.assertEqual(inputs["apt_mirror"]["options"], [label for label, _ in MIRRORS.values()])
        self.assertEqual(inputs["timezone"]["options"], list(TIMEZONES))
        self.assertFalse(workflow["concurrency"]["cancel-in-progress"])
        self.assertEqual(workflow["concurrency"]["queue"], "max")
        self.assertNotIn("github.ref", workflow["concurrency"]["group"])
        validate_panel((ROOT / ".github/workflows/build-ova.yml").read_text())
        steps = workflow["jobs"]["build_ova"]["steps"]
        publish = next(step for step in steps if step.get("name") == "创建 GitHub Release")
        self.assertEqual(publish["if"], "success() && steps.check.outputs.skip != 'true'")
        check = next(step for step in steps if step.get("name") == "检查是否有新版本")
        self.assertEqual(check["if"], "github.event_name == 'schedule'")
        self.assertIn("gh release view", check["run"])
        prune = next(step for step in steps if step.get("name") == "保留最近版本")
        self.assertIn("scripts/prune.py", prune["run"])
        self.assertIn("--keep 2", prune["run"])
        for step in steps:
            self.assertNotIn("${{", step.get("run", ""))

    def test_all_choice_defaults_and_shared_options_reject_drift(self):
        workflow = yaml.safe_load((ROOT / ".github/workflows/build-ova.yml").read_text())
        inputs = workflow.get("on", workflow.get(True))["workflow_dispatch"]["inputs"]
        for name, definition in inputs.items():
            if definition.get("type") != "choice":
                continue
            previous = definition["default"]
            definition["default"] = "invalid default"
            with self.subTest(name=name), self.assertRaises(ValueError):
                validate_panel(yaml.safe_dump(workflow))
            definition["default"] = previous
        for name in ("debian_version", "apt_mirror", "timezone"):
            inputs[name]["options"].append("extra option")
            with self.subTest(name=name), self.assertRaises(ValueError):
                validate_panel(yaml.safe_dump(workflow))
            inputs[name]["options"].pop()

    def test_only_main_can_publish(self):
        self.assertEqual(policy("refs/heads/main", "12", "20261106-1234"),
                         {"tag": "12-20261106-1234"})
        for ref in ("", "refs/heads/test", "refs/heads/feature", "refs/tags/test", "refs/pull/1/merge"):
            with self.assertRaises(ValueError):
                policy(ref, "12", "20261106-1234")


class PublishTests(unittest.TestCase):
    def test_existing_new_raced_and_failed_publications(self):
        self.publish_modes("refs/heads/main")

    def publish_modes(self, ref):
        for mode, expected in (("new", ["view", "create"]),
                               ("existing", ["view", "upload", "edit"]),
                               ("race", ["view", "create", "view", "upload", "edit"]),
                               ("network-error", ["view", "create", "view"]),
                               ("upload-error", ["view", "upload"])):
            with self.subTest(mode=mode, ref=ref), tempfile.TemporaryDirectory() as directory:
                work = Path(directory)
                executable = work / "gh"
                title = f"Debian 12 · {POLICY[0]}"
                executable.write_text('''#!/usr/bin/python3
import json, os, sys
from pathlib import Path
command = sys.argv[2]
log = Path(os.environ['RUNNER_TEMP']) / 'gh-calls'
history = log.read_text().splitlines() if log.exists() else []
with log.open('a') as output: output.write(command + '\\n')
mode = os.environ['TEST_RELEASE_MODE']
tag = sys.argv[3]
assert tag == '12-20261106-1234'
assert os.environ['GITHUB_REF'] == 'refs/heads/main'
if command in ('create', 'edit'):
    assert '--prerelease=false' in sys.argv
    assert sys.argv[sys.argv.index('--title') + 1] == '__TITLE__'
if command == 'view': sys.exit(0 if mode in ('existing', 'upload-error') or (mode == 'race' and history) else 1)
if command == 'create':
    assert '--target' in sys.argv and os.environ['GITHUB_SHA'] in sys.argv
    if mode in ('race', 'network-error'): print('CREATE_ORIGINAL_403', file=sys.stderr); sys.exit(47)
    sys.exit(0)
if command == 'upload': sys.exit(1 if mode == 'upload-error' else 0)
'''.replace("__TITLE__", title))
                executable.chmod(0o755)
                asset = work / "test-console.ova"
                asset.touch()
                manifest = {"settings": {"version": "12", "vcpu": 2, "memory": 1024, "disk": 4, "hostname": "test",
                                         "username": "debian", "mirror": "official", "install_vm_tools": True,
                                         "timezone": "UTC"},
                            "source": {"build": "20261106-1234", "variant": POLICY[0]},
                            "build_time": "now", "target_count": 1,
                            "release": policy(ref, "12", "20261106-1234"),
                            "images": [{"target": "ESXi 7", "kind": "console", "filename": asset.name,
                                        "username": "debian", "size": "320M", "disk_gib": "4.00", "disk_bytes": 4294967296}]}
                manifest_path = work / "manifest.json"
                manifest_path.write_text(json.dumps(manifest))
                env = dict(os.environ, PATH=str(work) + ":" + os.environ["PATH"], RUNNER_TEMP=str(work),
                           BUILD_MANIFEST=str(manifest_path), FINAL_TAG=manifest["release"]["tag"], GITHUB_SHA="b" * 40,
                           GITHUB_REF=ref,
                           TARGET_VERSION="12", TARGET_PASSWORD="123456", TEST_RELEASE_MODE=mode)
                result = subprocess.run(["bash", str(ROOT / "scripts/publish.sh")], env=env, cwd=work,
                                        text=True, capture_output=True)
                self.assertEqual(result.returncode == 0, mode not in ("network-error", "upload-error"), result.stderr)
                if mode == "network-error":
                    self.assertEqual(result.returncode, 47)
                    self.assertIn("CREATE_ORIGINAL_403", result.stderr)
                self.assertEqual((work / "gh-calls").read_text().splitlines(), expected)
                self.assertEqual((work / "release-notes.md").read_text().count("## Debian 云镜像 OVA"), 1)
                # 即使标签有效，其他 ref 也不得发布。
                before = (work / "gh-calls").read_text()
                for invalid_ref in ("refs/heads/test", "refs/heads/feature", "refs/tags/v1"):
                    env["GITHUB_REF"] = invalid_ref
                    rejected = subprocess.run(["bash", str(ROOT / "scripts/publish.sh")], env=env, cwd=work,
                                              text=True, capture_output=True)
                    self.assertNotEqual(rejected.returncode, 0)
                    self.assertEqual((work / "gh-calls").read_text(), before)
                env["GITHUB_REF"] = ref
                env["FINAL_TAG"] = "wrong-tag"
                rejected = subprocess.run(["bash", str(ROOT / "scripts/publish.sh")], env=env, cwd=work,
                                          text=True, capture_output=True)
                self.assertNotEqual(rejected.returncode, 0)
                self.assertEqual((work / "gh-calls").read_text(), before)
                env["FINAL_TAG"] = manifest["release"]["tag"]
                del manifest["release"]
                manifest_path.write_text(json.dumps(manifest))
                rejected = subprocess.run(["bash", str(ROOT / "scripts/publish.sh")], env=env, cwd=work,
                                          text=True, capture_output=True)
                self.assertNotEqual(rejected.returncode, 0)
                self.assertIn("缺少 release 字段", rejected.stderr)
                self.assertEqual((work / "gh-calls").read_text(), before)
