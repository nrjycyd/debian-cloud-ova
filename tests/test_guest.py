import importlib.util
import copy
import json
import os
import subprocess
import tempfile
import unittest
from pathlib import Path

from support import ROOT, source_info
from config import MIRRORS, catalog, from_environment, validate
from render import cloud_config
from test_config import environment

from cloudinit import util
from cloudinit.config.schema import validate_cloudconfig_schema


class GuestTests(unittest.TestCase):
    def test_generated_cloud_configs(self):
        for version in ("12", "13"):
            for ssh in ("false", "true"):
                for mirror in MIRRORS:
                    for tools in ("false", "true"):
                        with self.subTest(version=version, ssh=ssh, mirror=mirror, tools=tools):
                            settings = from_environment(environment())
                            settings.update(version=version, mirror=mirror, enable_ssh=ssh, install_vm_tools=tools,
                                            password="12@#%+=.,_-3456")
                            settings = validate(settings, image=True)
                            config = cloud_config(settings, source_info(version), catalog()[3], {})
                            # Debian's generate_mirrorlists extension is absent from
                            # Ubuntu's generic schema. Check its exact value below,
                            # and strictly validate every other generated field.
                            schema_config = copy.deepcopy(config)
                            if "apt" in schema_config:
                                schema_config["apt"].pop("generate_mirrorlists")
                            self.assertTrue(validate_cloudconfig_schema(schema_config, strict=True))
                            self.assertEqual(config["chpasswd"]["users"][0]["password"], settings["password"])
                            self.assertEqual(config["users"][0]["name"], "root" if ssh == "true" else "debian")
                            self.assertTrue(config["growpart"]["ignore_growroot_disabled"])
                            self.assertTrue(config["resize_rootfs"])
                            self.assertEqual(len(config["runcmd"]), 1)
                            self.assertEqual("open-vm-tools" in config["packages"], tools == "true")
                            if mirror != "official":
                                self.assertEqual(config["apt"], {"preserve_sources_list": True, "generate_mirrorlists": False})
                                self.assertIn(MIRRORS[mirror][1], config["bootcmd"][0])
                            info = json.loads(config["write_files"][2]["content"])
                            self.assertNotIn("password", info["settings"])
                            self.assertEqual(info["source"]["build"], "20261106-1234")

    def test_helper_failure_reaches_cloud_init_parent(self):
        # Use cloud-init's actual runcmd shell renderer, not a hand-written approximation.
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            ssh = root / "ssh-helper"
            ssh.write_text("#!/bin/sh\necho SSH_HELPER_FAILED >&2\nexit 29\n")
            ssh.chmod(0o755)
            systemctl = root / "systemctl"
            systemctl.write_text("#!/bin/sh\necho SHOULD_NOT_RUN\nexit 0\n")
            systemctl.chmod(0o755)
            bootstrap = root / "bootstrap"
            bootstrap.write_text((ROOT / "guest/configure-ova.sh").read_text().replace(
                "/usr/local/sbin/configure-ova-ssh", str(ssh)))
            bootstrap.chmod(0o755)
            for tools in ("true", "false"):
                script = util.shellify([[str(bootstrap), "true", tools]])
                result = subprocess.run(["/bin/sh"], input=script, text=True, capture_output=True,
                                        env=dict(os.environ, PATH=str(root) + ":" + os.environ["PATH"]))
                self.assertEqual(result.returncode, 29)
                self.assertIn("SSH_HELPER_FAILED", result.stderr)
                self.assertNotIn("SHOULD_NOT_RUN", result.stdout)

    def test_mirror_scope_backup_and_symlinks(self):
        spec = importlib.util.spec_from_file_location("apt_mirrors", ROOT / "guest/apt-mirrors.py")
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        with tempfile.TemporaryDirectory() as directory:
            apt = Path(directory)
            (apt / "mirrors").mkdir()
            ordinary = apt / "mirrors/debian.list"
            ordinary.write_text("https://deb.debian.org/debian\nhttps://private.example/debian\n")
            security = apt / "mirrors/security.list"
            security.write_text("http://deb.debian.org/debian-security\n")
            (apt / "sources.list.d").mkdir()
            definition = apt / "sources.list.d/debian.sources"
            definition.write_text("URIs: mirror+file:///etc/apt/mirrors/debian.list\n")
            before = definition.read_bytes()
            linked = apt / "linked.list"
            linked.write_text("https://deb.debian.org/debian\n")
            (apt / "mirrors/link.list").symlink_to(linked)
            original = ordinary.read_bytes()
            for _, mirror in list(MIRRORS.values())[1:]:
                module.configure_mirrors(apt, mirror)
                self.assertIn("https://private.example/debian", ordinary.read_text())
                self.assertEqual(definition.read_bytes(), before)
                self.assertEqual(linked.read_text(), "https://deb.debian.org/debian\n")
                self.assertEqual(security.read_text(), "https://security.debian.org/debian-security\n")
                self.assertEqual((apt / "ova-source-backups/mirrors/debian.list").read_bytes(), original)
                # Restore to test the next mirror independently, preserving the first backup.
                ordinary.write_bytes(original)
