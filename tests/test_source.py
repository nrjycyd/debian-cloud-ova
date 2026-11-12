import contextlib
import io
import json
import tempfile
import unittest
import urllib.error
from pathlib import Path
from unittest.mock import patch

from tests.support import source_info
import config
import source


def metadata(version, variant, build, **overrides):
    info = {"release": source.VERSIONS[version], "arch": "amd64", "vendor": variant, "version": build}
    info.update(overrides)
    return json.dumps({"items": [{"kind": "Build", "data": {"info": info}}]}).encode()


def missing():
    return urllib.error.HTTPError("https://example.invalid/image.json", 404, "Not Found", None, None)


class SourceTests(unittest.TestCase):
    def test_prefers_first_variant_in_configured_order(self):
        # 期望值从 config.VARIANTS 推导：调整优先级或固定单一变体后无需改测试。
        for version in ("12", "13"):
            expected = source_info(version)
            sums = f"{expected['sha512']}  {expected['url'].rsplit('/', 1)[1]}\n".encode()
            with self.subTest(version=version), patch(
                    "source.fetch",
                    side_effect=[metadata(version, config.VARIANTS[0], expected["build"]), sums]) as fetch:
                self.assertEqual(source.resolve(version), expected)
                self.assertTrue(fetch.call_args_list[0].args[0].endswith(
                    f"/debian-{version}-{config.VARIANTS[0]}-amd64.json"))
                self.assertNotIn("/latest/", fetch.call_args_list[1].args[0])

    @unittest.skipUnless(len(config.VARIANTS) > 1, "当前配置只有一个候选变体，没有回退")
    def test_falls_back_to_next_configured_variant(self):
        expected = source_info("13", variant=config.VARIANTS[1])
        sums = f"{expected['sha512']}  {expected['url'].rsplit('/', 1)[1]}\n".encode()
        warnings = io.StringIO()
        with patch("source.fetch",
                   side_effect=[missing(), metadata("13", config.VARIANTS[1], expected["build"]), sums]), \
                contextlib.redirect_stderr(warnings):
            resolved = source.resolve("13")
        self.assertEqual(resolved, expected)
        self.assertEqual(resolved["variant"], config.VARIANTS[1])
        self.assertIn(f"debian-13-{config.VARIANTS[0]}-amd64", warnings.getvalue())

    def test_all_configured_variants_missing_reports_every_url(self):
        with patch("source.fetch", side_effect=[missing() for _ in config.VARIANTS]), \
                self.assertRaises(ValueError) as caught:
            source.resolve("13")
        for variant in config.VARIANTS:
            self.assertIn(f"debian-13-{variant}-amd64.json", str(caught.exception))

    def test_vendor_mismatch_is_rejected(self):
        variant = config.VARIANTS[0]
        with patch("source.fetch", side_effect=[metadata("13", variant, "20261106-1234", vendor="azure")]):
            with self.assertRaisesRegex(ValueError, "不匹配"):
                source.resolve("13")

    def test_custom_variant_order_is_respected(self):
        # 维护时可临时传入其他顺序（例如本次构建固定 generic），不必改配置。
        expected = source_info("13", variant="generic")
        sums = f"{expected['sha512']}  {expected['url'].rsplit('/', 1)[1]}\n".encode()
        with patch("source.fetch",
                   side_effect=[metadata("13", "generic", expected["build"]), sums]) as fetch:
            self.assertEqual(source.resolve("13", variants=("generic",)), expected)
        self.assertIn("debian-13-generic-amd64.json", fetch.call_args_list[0].args[0])

    def test_http_server_error_is_retried(self):
        url = "https://cloud.debian.org/images/cloud/trixie/latest/debian-13-genericcloud-amd64.json"
        unavailable = urllib.error.HTTPError(url, 503, "Service Unavailable", None, None)
        with patch("source.urllib.request.urlopen",
                   side_effect=[unavailable, io.BytesIO(b"metadata")]), patch("source.time.sleep"):
            self.assertEqual(source.fetch(url), b"metadata")

    def test_download_verifies_and_reuses_only_matching_files(self):
        payload = b"official qcow2 bytes"
        info = source_info(payload=payload)
        with tempfile.TemporaryDirectory() as td:
            path = Path(td) / "source.qcow2"
            with patch("source.urllib.request.urlopen", return_value=io.BytesIO(payload)):
                source.download(info, path)
            self.assertEqual(path.read_bytes(), payload)
            with patch("source.urllib.request.urlopen", side_effect=AssertionError("cache should be reused")):
                source.download(info, path)
            path.write_bytes(b"old or incomplete download")
            with patch("source.urllib.request.urlopen", return_value=io.BytesIO(b"bad digest")):
                with self.assertRaises(ValueError):
                    source.download(info, path)
            self.assertEqual(path.read_bytes(), b"old or incomplete download")
            self.assertFalse(path.with_suffix(".qcow2.part").exists())
            with patch("source.urllib.request.urlopen", return_value=io.BytesIO(payload)):
                source.download(info, path)
            self.assertEqual(path.read_bytes(), payload)

    def test_source_identity_cannot_cross_versions_or_hosts(self):
        info = source_info()
        self.assertEqual(source.validate(info, "12"), info)
        for variant in config.KNOWN_VARIANTS:
            swapped = info["url"].replace(info["variant"], variant)
            self.assertEqual(source.validate({**info, "variant": variant, "url": swapped}, "12")["url"], swapped)
        other = next(variant for variant in config.KNOWN_VARIANTS if variant != info["variant"])
        for invalid in ({**info, "url": "https://example.org/image.qcow2"},
                        {**info, "variant": other},
                        {**info, "url": info["url"].replace(info["variant"], "nocloud")},
                        {**info, "variant": "nocloud"},
                        {**info, "debian_version": "13"}, {**info, "build": "../../latest"}):
            with self.assertRaises(ValueError):
                source.validate(invalid, "12")
