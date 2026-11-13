import json
import unittest
from unittest.mock import patch

import prune


def release(tag, created):
    return {"tagName": tag, "createdAt": created}


class PruneTests(unittest.TestCase):
    def run_prune(self, items, keep=2, expect_assets=8, actual_assets=None, dry_run=False):
        assets = expect_assets if actual_assets is None else actual_assets
        calls = []

        def fake_gh(*args):
            calls.append(args)
            if args[:2] == ("release", "list"):
                return json.dumps(items)
            if args[:2] == ("release", "view"):
                return json.dumps({"assets": [{} for _ in range(assets)]})
            if args[:2] == ("release", "delete"):
                return ""
            raise AssertionError(args)

        with patch("prune.gh", side_effect=fake_gh):
            deleted = prune.prune("13", keep, expect_assets, dry_run)
        return deleted, calls

    def deletes(self, calls):
        return [call[2] for call in calls if call[:2] == ("release", "delete")]

    def test_keeps_newest_two_and_deletes_older(self):
        items = [release("13-20261111-2659", "2026-11-11T10:00:00Z"),
                 release("13-20261110-2658", "2026-11-10T10:00:00Z"),
                 release("13-20261103-2651", "2026-11-03T10:00:00Z")]
        deleted, calls = self.run_prune(items)
        self.assertEqual(deleted, ["13-20261103-2651"])
        self.assertEqual(self.deletes(calls), ["13-20261103-2651"])

    def test_fewer_releases_than_keep_is_noop(self):
        items = [release("13-20261111-2659", "2026-11-11T10:00:00Z"),
                 release("13-20261110-2658", "2026-11-10T10:00:00Z")]
        deleted, calls = self.run_prune(items)
        self.assertEqual(deleted, [])
        self.assertEqual(self.deletes(calls), [])

    def test_incomplete_newest_release_blocks_cleanup(self):
        items = [release("13-20261111-2659", "2026-11-11T10:00:00Z"),
                 release("13-20261110-2658", "2026-11-10T10:00:00Z"),
                 release("13-20261103-2651", "2026-11-03T10:00:00Z")]
        with self.assertRaisesRegex(ValueError, "暂不清理旧版本"):
            self.run_prune(items, actual_assets=4)

    def test_dry_run_reports_without_deleting(self):
        items = [release("13-20261111-2659", "2026-11-11T10:00:00Z"),
                 release("13-20261110-2658", "2026-11-10T10:00:00Z"),
                 release("13-20261103-2651", "2026-11-03T10:00:00Z")]
        deleted, calls = self.run_prune(items, dry_run=True)
        self.assertEqual(deleted, ["13-20261103-2651"])
        self.assertEqual(self.deletes(calls), [])

    def test_only_matching_version_and_tag_shape(self):
        items = [release("12-20261106-1234", "2026-11-12T10:00:00Z"),
                 release("13-latest", "2026-11-12T09:00:00Z"),
                 release("13-2026111-123", "2026-11-12T08:00:00Z"),
                 release("13-20261111-2659", "2026-11-11T10:00:00Z"),
                 release("13-20261110-2658", "2026-11-10T10:00:00Z"),
                 release("13-20261103-2651", "2026-11-03T10:00:00Z")]
        deleted, calls = self.run_prune(items)
        self.assertEqual(deleted, ["13-20261103-2651"])
        self.assertEqual(self.deletes(calls), ["13-20261103-2651"])

    def test_invalid_arguments(self):
        for keep, assets in ((0, 8), (2, 0)):
            with self.subTest(keep=keep, assets=assets), self.assertRaises(ValueError):
                prune.prune("13", keep, assets)
