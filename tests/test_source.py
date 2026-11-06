import io
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from support import source_info
import source


class SourceTests(unittest.TestCase):
    def test_latest_metadata_pins_immutable_version(self):
        for version in ("12", "13"):
            expected = source_info(version)
            metadata = {"items": [{"kind": "Build", "data": {"info": {
                "release": source.VERSIONS[version], "arch": "amd64", "vendor": "genericcloud",
                "version": expected["build"],
            }}}]}
            sums = f"{expected['sha512']}  {expected['url'].rsplit('/', 1)[1]}\n".encode()
            with patch("source.fetch", side_effect=[json.dumps(metadata).encode(), sums]) as fetch:
                self.assertEqual(source.resolve(version), expected)
                self.assertNotIn("/latest/", fetch.call_args_list[1].args[0])
            with patch("source.fetch", side_effect=[json.dumps(metadata).encode(), b"no matching checksum"]):
                with self.assertRaises(ValueError):
                    source.resolve(version)

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
        for invalid in ({**info, "url": "https://example.org/image.qcow2"},
                        {**info, "debian_version": "13"}, {**info, "build": "../../latest"}):
            with self.assertRaises(ValueError):
                source.validate(invalid, "12")
