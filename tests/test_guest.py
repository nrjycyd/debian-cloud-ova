import importlib.util
import copy
import json
import os
import subprocess
import tempfile
import unittest
import contextlib
import io
from pathlib import Path

from tests.support import ROOT, source_info
from config import MIRRORS, catalog, from_environment, validate
from render import cloud_config
from tests.support import environment

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
                            # Ubuntu 通用 schema 不含 Debian 的 generate_mirrorlists 扩展；
                            # 下方单独检查该值，其余生成字段严格按 schema 校验。
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
                            if ssh == "true":
                                self.assertTrue(config["ssh_pwauth"])
                                self.assertFalse(config["disable_root"])
                                self.assertIn("openssh-server", config["packages"])
                            else:
                                self.assertNotIn("ssh_pwauth", config)
                                self.assertNotIn("disable_root", config)
                                self.assertNotIn("openssh-server", config["packages"])
                                for command in config.get("bootcmd", []):
                                    self.assertNotIn("ova-disable-ssh", command)
                                    self.assertNotIn("systemctl", command)
                            if mirror != "official":
                                self.assertEqual(config["apt"], {"preserve_sources_list": True, "generate_mirrorlists": False})
                                self.assertIn(MIRRORS[mirror][1], config["bootcmd"][0])
                            info = json.loads(config["write_files"][2]["content"])
                            self.assertNotIn("password", info["settings"])
                            self.assertEqual(info["source"]["build"], "20261106-1234")

    def test_helper_failure_reaches_cloud_init_parent(self):
        # 使用 cloud-init 自身的 runcmd Shell 生成器验证错误传播。
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
                self.assertEqual((apt / "mirrors/debian.list.bak").read_bytes(), original)
                backups = {path.name: path.read_bytes() for path in (apt / "mirrors").glob("*.bak")}
                self.assertEqual(module.configure_mirrors(apt, mirror), 0)
                self.assertEqual(backups, {path.name: path.read_bytes() for path in (apt / "mirrors").glob("*.bak")})
                self.assertFalse((apt / "ova-source-backups").exists())
                # 恢复普通源以独立测试下一个镜像站，首份备份仍须保留。
                ordinary.write_bytes(original)

    def test_console_preserves_ssh_state_on_initialization_and_reboot(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            helper = root / "ssh-helper"
            helper.write_text("#!/bin/sh\nexit 77\n")
            helper.chmod(0o755)
            bootstrap = root / "bootstrap"
            bootstrap.write_text((ROOT / "guest/configure-ova.sh").read_text().replace(
                "/usr/local/sbin/configure-ova-ssh", str(helper)))
            bootstrap.chmod(0o755)
            systemctl = root / "systemctl"
            systemctl.write_text('#!/bin/sh\necho "$*" >> "$CALLS"\ncase "$*" in *ssh*) echo changed > "$STATE";; esac\n')
            systemctl.chmod(0o755)
            env = dict(os.environ, PATH=str(root) + ":" + os.environ["PATH"],
                       STATE=str(root / "state"), CALLS=str(root / "calls"))
            settings = from_environment(environment())
            settings["enable_ssh"] = False
            config = cloud_config(settings, {}, catalog()[3], {})
            self.assertNotIn("bootcmd", config)
            self.assertNotIn("ssh_pwauth", config)
            self.assertNotIn("disable_root", config)
            for initial in ("active/enabled", "inactive/disabled", "masked"):
                with self.subTest(initial=initial):
                    (root / "state").write_text(initial)
                    for _ in range(2):
                        script = util.shellify([[str(bootstrap), "false", "false"]])
                        subprocess.run(["sh"], input=script, text=True, env=env, check=True)
                        subprocess.run(["sh", str(ROOT / "guest/configure-ssh.sh"), "false"], env=env, check=True)
                        self.assertEqual((root / "state").read_text(), initial)
            self.assertEqual((root / "calls").read_text().splitlines(), ["daemon-reload"] * 6)

    def test_mirror_no_match_warns_but_idempotency_is_success(self):
        spec = importlib.util.spec_from_file_location("apt_mirrors", ROOT / "guest/apt-mirrors.py")
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        with tempfile.TemporaryDirectory() as directory:
            apt = Path(directory)
            (apt / "mirrors").mkdir()
            path = apt / "mirrors/debian.list"
            path.write_text("https://private.example/debian\n")
            mirror = MIRRORS["tuna"][1]
            errors = io.StringIO()
            with contextlib.redirect_stderr(errors):
                self.assertEqual(module.configure_mirrors(apt, mirror), 0)
            self.assertIn("[WARN]", errors.getvalue())
            self.assertEqual(path.read_text(), "https://private.example/debian\n")
            path.write_text(mirror + "\n")
            errors = io.StringIO()
            with contextlib.redirect_stderr(errors):
                self.assertEqual(module.configure_mirrors(apt, mirror), 0)
            self.assertEqual(errors.getvalue(), "")
