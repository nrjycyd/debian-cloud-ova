import json
import os
import shutil
import subprocess
import tarfile
import unittest
import xml.etree.ElementTree as ET
from pathlib import Path
from unittest.mock import patch

import yaml

from tests.support import ROOT, build_fixture, fake_download, source_info
import build
from config import catalog
from report import release_notes, summary
from tests.support import environment


class BuildTests(unittest.TestCase):
    def batch(self, env):
        info = source_info(env["TARGET_VERSION"], b"3221225472\n")
        with patch("build.resolve", return_value=info), patch("build.download", side_effect=fake_download):
            build.run_batch(env)
        return json.loads((Path(env["RUNNER_TEMP"]) / "build-manifest.json").read_text())

    def check_images(self, manifest, expected_bytes):
        for image in manifest["images"]:
            with tarfile.open(image["filename"]) as archive:
                members = archive.getnames()
                self.assertEqual(len(members), 4)
                ovf = ET.fromstring(archive.extractfile(next(x for x in members if x.endswith(".ovf"))).read())
                namespace = "{http://schemas.dmtf.org/ovf/envelope/1}"
                self.assertEqual(int(ovf.find(f"{namespace}DiskSection/{namespace}Disk").get(namespace + "capacity")), expected_bytes)
                config = yaml.safe_load(archive.extractfile("cidata.iso").read())
                if image["kind"] == "ssh":
                    self.assertTrue(config["ssh_pwauth"])
                    self.assertFalse(config["disable_root"])
                else:
                    self.assertNotIn("ssh_pwauth", config)
                    self.assertNotIn("disable_root", config)
                    self.assertNotIn("openssh-server", config["packages"])
                self.assertEqual(config["users"][0]["name"], image["username"])
                self.assertEqual(config["runcmd"][0][1], str(image["kind"] == "ssh").lower())
                digest_manifest = archive.extractfile(next(x for x in members if x.endswith(".mf"))).read().decode()
                import hashlib
                for name in (x for x in members if not x.endswith(".mf")):
                    checksum = hashlib.sha256(archive.extractfile(name).read()).hexdigest()
                    self.assertIn(f"SHA256({name})= {checksum}", digest_manifest)
            self.assertEqual(image["disk_bytes"], expected_bytes)

    def test_default_batches_and_capacity(self):
        for version in ("12", "13"):
            for ssh in ("false", "true"):
                with self.subTest(version=version, ssh=ssh), build_fixture() as (work, env):
                    env.update(environment(), TARGET_VERSION=version, TARGET_ENABLE_SSH=ssh, TARGET_DISK="2")
                    manifest = self.batch(env)
                    self.assertEqual(len(manifest["images"]), 8 if ssh == "true" else 4)
                    self.check_images(manifest, 3 * 1073741824)
                    self.assertEqual((work / "guestfish-calls").read_text().splitlines(), ["prepare"])
                    self.assertEqual((work / "convert-calls").read_text().splitlines(), ["convert"])
                    self.assertEqual((work / "verify-calls").read_text().splitlines(), ["verify"])
                    if os.geteuid() != 0:
                        self.assertEqual((work / "sudo-calls").read_text().splitlines(), ["sudo", "sudo"])
                    self.assertEqual((work / "debian-source.qcow2").read_bytes(), b"3221225472\n")
                    self.assertFalse(list(work.glob("tmp*/user-data")))
                    notes = release_notes(manifest, env["TARGET_PASSWORD"])
                    self.assertEqual(notes.count("## Debian 云镜像 OVA"), 1)
                    self.assertIn("磁盘大小：**3.00 GB**", notes)
                    self.assertIn("实际磁盘容量：3.00 GiB", summary(manifest, dict(env, BUILD_STATUS="success")))
                    self.assertNotIn("123456", json.dumps(manifest))

    def test_all_presets_exact_ovf_mapping(self):
        with build_fixture() as (work, env):
            env.update(environment(), TARGET_ENABLE_SSH="false", TARGET_BUILD_2="不构建", TARGET_BUILD_3="", TARGET_BUILD_4="")
            for preset in catalog():
                env["TARGET_BUILD"] = preset["label"]
                manifest = self.batch(env)
                with tarfile.open(manifest["images"][0]["filename"]) as archive:
                    ovf = archive.extractfile(next(x for x in archive.getnames() if x.endswith(".ovf"))).read().decode()
                self.assertIn(f"<vssd:VirtualSystemType>{preset['vmx']}</vssd:VirtualSystemType>", ovf)
                self.assertIn(f'ovf:id="{preset["os_id"]}" vmw:osType="{preset["os_type"]}"', ovf)

    def test_larger_disk_and_preparation_failures(self):
        for mode in ("larger", "fail", "missing", "wrong-vmdk", "invalid-json"):
            with self.subTest(mode=mode), build_fixture() as (work, env):
                env.update(environment(), TARGET_BUILD_2="不构建", TARGET_BUILD_3="", TARGET_BUILD_4="",
                           TARGET_ENABLE_SSH="false", TARGET_DISK="08")
                if mode in ("fail", "missing"):
                    env["MOCK_GUESTFISH"] = mode
                elif mode != "larger":
                    env["MOCK_QEMU"] = mode
                if mode == "larger":
                    self.check_images(self.batch(env), 8 * 1073741824)
                else:
                    with self.assertRaises(subprocess.CalledProcessError):
                        self.batch(env)
                    self.assertFalse(list(work.glob("*.ova")))
                    self.assertFalse((work / "outputs").exists())

    def test_later_failure_does_not_expose_publish_outputs(self):
        with build_fixture() as (work, env):
            env.update(environment(), MOCK_FAIL_VMX="vmx-19")
            with self.assertRaises(subprocess.CalledProcessError):
                self.batch(env)
            self.assertEqual(len(list(work.glob("*.ova"))), 2)
            self.assertFalse((work / "outputs").exists())
            self.assertFalse((work / "build-manifest.json").exists())
            self.assertIn("本次未发布镜像", summary(None, dict(env, BUILD_STATUS="failure")))

    def test_invalid_input_stops_before_download(self):
        with build_fixture() as (_, env):
            env.update(environment(), TARGET_DISK="18446744073709551620")
            with patch("build.resolve") as resolve, self.assertRaises(ValueError):
                build.run_batch(env)
            resolve.assert_not_called()

    def test_mutated_working_disk_invalidates_prepared_vmdk(self):
        with build_fixture() as (work, env):
            env.update(environment(), TARGET_ENABLE_SSH="false", TARGET_BUILD_2="不构建", TARGET_BUILD_3="", TARGET_BUILD_4="")
            self.batch(env)
            disk = work / "debian-13-genericcloud-amd64.qcow2"
            with disk.open("ab") as output:
                output.write(b"externally modified\n")
            self.batch(env)
            self.assertEqual(len((work / "guestfish-calls").read_text().splitlines()), 2)
            self.assertEqual(len((work / "convert-calls").read_text().splitlines()), 2)

    @unittest.skipUnless(os.geteuid() == 0 and shutil.which("runuser"), "root-only non-root runner simulation")
    def test_nonroot_creator_uses_noninteractive_sudo(self):
        with build_fixture() as (work, env):
            work.chmod(0o777)
            image = work / "pristine.qcow2"
            fake_download(None, image)
            metadata = work / "source.json"
            metadata.write_text(json.dumps(source_info("12", image.read_bytes())))
            preset = next(item for item in catalog() if item["label"] == "ESXi 7.0 U3 + DGNU 11 (vmx-19)")
            env.update(OVA_SOURCE_IMAGE=str(image), OVA_SOURCE_MANIFEST=str(metadata),
                       VIRTUAL_SYSTEM_TYPE=preset["vmx"], OVF_OS_ID=str(preset["os_id"]), OVF_OS_TYPE=preset["os_type"])
            result = subprocess.run(["runuser", "-u", "nobody", "--preserve-environment", "--", "bash",
                                     str(ROOT / "debian-ova-creator.sh"), "-d", "12", "-c", "2", "-m", "1024",
                                     "-s", "4", "-H", "debian-cloud", "-u", "debian", "-p", "123456",
                                     "-S", "false", "-M", "official", "-V", "true", "-T", "UTC"],
                                    env=env, text=True, capture_output=True)
            self.assertEqual(result.returncode, 0, result.stderr)
            self.assertEqual((work / "sudo-calls").read_text().splitlines(), ["sudo", "sudo"])

    def test_missing_creator_argument_stops_before_disk_work(self):
        arguments = {"d": "12", "c": "2", "m": "1024", "s": "4", "H": "debian-cloud",
                     "u": "debian", "p": "123456", "S": "false", "M": "official", "V": "true", "T": "UTC"}
        for missing in arguments:
            with self.subTest(missing=missing), build_fixture() as (work, env):
                command = ["bash", str(ROOT / "debian-ova-creator.sh")]
                for flag, value in arguments.items():
                    if flag != missing:
                        command.extend(["-" + flag, value])
                result = subprocess.run(command, env=env, text=True, capture_output=True)
                self.assertNotEqual(result.returncode, 0)
                self.assertIn("缺少 -" + missing, result.stderr)
                self.assertEqual(sorted(path.name for path in work.iterdir()), ["bin"])

    def test_readonly_verification_failure_stops_packaging(self):
        for failure in ("fail", "missing", "nonempty"):
            with self.subTest(failure=failure), build_fixture() as (work, env):
                env.update(environment(), MOCK_VERIFY=failure)
                with self.assertRaises(subprocess.CalledProcessError):
                    self.batch(env)
                self.assertFalse(list(work.glob("*.ova")))
                self.assertFalse((work / "outputs").exists())

    def test_changed_vmdk_invalidates_readonly_verification_cache(self):
        with build_fixture() as (work, env):
            env.update(environment(), TARGET_ENABLE_SSH="false", TARGET_BUILD_2="不构建", TARGET_BUILD_3="", TARGET_BUILD_4="")
            self.batch(env)
            with next(work.glob("*.vmdk")).open("ab") as output:
                output.write(b"changed disk bytes\n")
            self.batch(env)
            self.assertEqual(len((work / "verify-calls").read_text().splitlines()), 2)
            self.assertEqual(len((work / "convert-calls").read_text().splitlines()), 1)

    def test_cleanup_preserves_success_and_failure_status(self):
        for failed in (False, True):
            with self.subTest(failed=failed), build_fixture() as (work, env):
                env.update(environment(), TARGET_BUILD_2="不构建", TARGET_BUILD_3="", TARGET_BUILD_4="",
                           TARGET_ENABLE_SSH="false", MOCK_TEMP_RESIDUE="true")
                if failed:
                    env["MOCK_GUESTFISH"] = "fail"
                    with self.assertRaises(subprocess.CalledProcessError) as error:
                        self.batch(env)
                    self.assertEqual(error.exception.returncode, 1)
                else:
                    self.assertEqual(len(self.batch(env)["images"]), 1)
                self.assertTrue(list(work.glob("tmp*/residue")))
                self.assertFalse(list(work.glob("tmp*/user-data")))
                self.assertFalse(list(work.glob("tmp*/meta-data")))

    def test_removed_test_channel_cannot_build_publishable_assets(self):
        with build_fixture() as (work, env):
            env.update(environment(), GITHUB_REF="refs/heads/test", TARGET_ENABLE_SSH="false",
                       TARGET_BUILD_2="不构建", TARGET_BUILD_3="", TARGET_BUILD_4="")
            with self.assertRaisesRegex(ValueError, "仅支持 main"):
                self.batch(env)
            self.assertFalse(list(work.glob("*.ova")))
            self.assertFalse((work / "outputs").exists())
