import json
import os
import subprocess
import tempfile
import unittest
from pathlib import Path

import yaml

from support import ROOT
from config import MIRRORS, TIMEZONES, VERSIONS, catalog


class PanelTests(unittest.TestCase):
    def test_panel_catalog_and_workflow_guards(self):
        workflow = yaml.safe_load((ROOT / ".github/workflows/build-ova.yml").read_text())
        triggers = workflow.get("on", workflow.get(True))
        self.assertEqual(set(triggers), {"workflow_dispatch"})
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
        steps = workflow["jobs"]["build_ova"]["steps"]
        publish = next(step for step in steps if step.get("name") == "创建 GitHub Release")
        self.assertEqual(publish["if"], "success()")
        for step in steps:
            self.assertNotIn("${{", step.get("run", ""))


class PublishTests(unittest.TestCase):
    def test_existing_new_raced_and_failed_publications(self):
        for mode, expected in (("new", ["view", "create"]),
                               ("existing", ["view", "upload", "edit"]),
                               ("race", ["view", "create", "view", "upload", "edit"]),
                               ("network-error", ["view", "create", "view"]),
                               ("upload-error", ["view", "upload"])):
            with self.subTest(mode=mode), tempfile.TemporaryDirectory() as directory:
                work = Path(directory)
                executable = work / "gh"
                executable.write_text('''#!/usr/bin/python3
import json, os, sys
from pathlib import Path
command = sys.argv[2]
log = Path(os.environ['RUNNER_TEMP']) / 'gh-calls'
history = log.read_text().splitlines() if log.exists() else []
with log.open('a') as output: output.write(command + '\\n')
mode = os.environ['TEST_RELEASE_MODE']
if command == 'view': sys.exit(0 if mode in ('existing', 'upload-error') or (mode == 'race' and history) else 1)
if command == 'create':
    assert '--target' in sys.argv and os.environ['GITHUB_SHA'] in sys.argv
    sys.exit(1 if mode in ('race', 'network-error') else 0)
if command == 'upload': sys.exit(1 if mode == 'upload-error' else 0)
''')
                executable.chmod(0o755)
                asset = work / "test-console.ova"
                asset.touch()
                manifest = {"settings": {"version": "12", "vcpu": 2, "memory": 1024, "hostname": "test",
                                         "username": "debian", "mirror": "official", "install_vm_tools": True,
                                         "timezone": "UTC"},
                            "source": {"build": "20261106-1234"}, "build_time": "now",
                            "images": [{"target": "ESXi 7", "kind": "console", "filename": asset.name,
                                        "username": "debian", "size": "320M", "disk_gib": "4.00"}]}
                manifest_path = work / "manifest.json"
                manifest_path.write_text(json.dumps(manifest))
                env = dict(os.environ, PATH=str(work) + ":" + os.environ["PATH"], RUNNER_TEMP=str(work),
                           BUILD_MANIFEST=str(manifest_path), FINAL_TAG="20261106-1234", GITHUB_SHA="b" * 40,
                           TARGET_VERSION="12", TARGET_PASSWORD="123456", TEST_RELEASE_MODE=mode)
                result = subprocess.run(["bash", str(ROOT / "scripts/publish.sh")], env=env, cwd=work,
                                        text=True, capture_output=True)
                self.assertEqual(result.returncode == 0, mode not in ("network-error", "upload-error"), result.stderr)
                self.assertEqual((work / "gh-calls").read_text().splitlines(), expected)
                self.assertEqual((work / "release-notes.md").read_text().count("## Debian 云镜像 OVA"), 1)
