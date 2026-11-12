import contextlib
import io
import json
import tempfile
import unittest
import urllib.error
from pathlib import Path
from unittest.mock import patch

from tests.support import source_info
import source


def metadata(version, variant, build, **overrides):
    info = {"release": source.VERSIONS[version], "arch": "amd64", "vendor": variant, "version": build}
    info.update(overrides)
    return json.dumps({"items": [{"kind": "Build", "data": {"info": info}}]}).encode()


def missing():
    return urllib.error.HTTPError("https://example.invalid/image.json", 404, "Not Found", None, None)


class SourceTests(unittest.TestCase):
    def test_prefers_genericcloud_for_every_supported_version(self):
        for version in ("12", "13"):
            expected = source_info(version)
            sums = f"{expected['sha512']}  {expected['url'].rsplit('/', 1)[1]}\n".encode()
            with self.subTest(version=version), patch(
                    "source.fetch",
                    side_effect=[metadata(version, "genericcloud", expected["build"]), sums]) as fetch:
                self.assertEqual(source.resolve(version), expected)
                self.assertTrue(fetch.call_args_list[0].args[0].endswith(
                    f"/debian-{version}-genericcloud-amd64.json"))
                self.assertNotIn("/latest/", fetch.call_args_list[1].args[0])

    def test_falls_back_to_generic_when_genericcloud_is_missing(self):
        # 20261111-2659 的发布目录缺少 genericcloud，但 daily 目录仍有，故按序回退而不是写死版本变体。
        expected = dict(source_info("13"))
        expected["variant"] = "generic"
        expected["url"] = expected["url"].replace("genericcloud", "generic")
        sums = f"{expected['sha512']}  {expected['url'].rsplit('/', 1)[1]}\n".encode()
        warnings = io.StringIO()
        with patch("source.fetch",
                   side_effect=[missing(), metadata("13", "generic", expected["build"]), sums]), \
                contextlib.redirect_stderr(warnings):
            resolved = source.resolve("13")
        self.assertEqual(resolved, expected)
        self.assertEqual(resolved["variant"], "generic")
        self.assertIn("debian-13-genericcloud-amd64", warnings.getvalue())

    def test_all_variants_missing_reports_every_url(self):
        with patch("source.fetch", side_effect=[missing(), missing()]), \
                self.assertRaises(ValueError) as caught:
            source.resolve("13")
        self.assertIn("debian-13-genericcloud-amd64.json", str(caught.exception))
        self.assertIn("debian-13-generic-amd64.json", str(caught.exception))

    def test_vendor_mismatch_is_rejected(self):
        with patch("source.fetch", side_effect=[metadata("13", "genericcloud", "20261106-1234", vendor="azure")]):
            with self.assertRaisesRegex(ValueError, "不匹配"):
                source.resolve("13")

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
        for variant in source.VARIANTS:
            swapped = info["url"].replace("genericcloud", variant)
            self.assertEqual(source.validate({**info, "variant": variant, "url": swapped}, "12")["url"], swapped)
        for invalid in ({**info, "url": "https://example.org/image.qcow2"},
                        {**info, "url": info["url"].replace("genericcloud", "nocloud")},
                        {**info, "variant": "nocloud"},
                        {**info, "variant": "generic"},
                        {**info, "debian_version": "13"}, {**info, "build": "../../latest"}):
            with self.assertRaises(ValueError):
                source.validate(invalid, "12")
