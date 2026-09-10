from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1]/"ue"))
from content_guard import snapshot, differences, require_unchanged


class ContentGuardTests(unittest.TestCase):
    def test_no_write_capture_preserves_every_byte(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root/"actor.uasset").write_bytes(b"baseline")
            before = snapshot(root)
            self.assertTrue(require_unchanged(before, snapshot(root))["unchanged"])

    def test_actor_deletion_fails_even_without_level_save(self):
        before = {"actor.uasset": "old", "level.umap": "unchanged"}
        with self.assertRaisesRegex(ValueError, "deleted"):
            require_unchanged(before, {"level.umap": "unchanged"})

    def test_actor_replacement_and_added_files_are_visible(self):
        delta = differences({"actor.uasset": "old"}, {"actor.uasset": "new", "other.uasset": "new"})
        self.assertEqual(delta["modified"], ["actor.uasset"])
        self.assertEqual(delta["added"], ["other.uasset"])


if __name__ == "__main__":
    unittest.main()
