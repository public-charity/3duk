import hashlib
import json
from pathlib import Path
import sys
import tempfile
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "ue"))
from candidate_preview import read_candidate
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from diag.bridge_crossing_audit import highest_triangle_z
import numpy as np


class CandidatePreviewTests(unittest.TestCase):
    def test_exact_delta_and_tampering(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            path = root/"site.json"
            path.write_text(json.dumps({"splines": [{"id": "test"}], "junctions": []}))
            manifest = {"scope": "delta", "candidate_documents": {"site.json": hashlib.sha256(path.read_bytes()).hexdigest()}}
            (root/"candidate_manifest.json").write_text(json.dumps(manifest))
            record, files = read_candidate(root)
            self.assertEqual(record["ids"], ["test"])
            self.assertFalse(record["saved"])
            path.write_text("{}")
            with self.assertRaisesRegex(ValueError, "changed"):
                read_candidate(root)

    def test_empty_delta_fails(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root/"candidate_manifest.json").write_text('{"scope":"delta","candidate_documents":{}}')
            with self.assertRaises(ValueError):
                read_candidate(root)

    def test_crossing_uses_highest_overlapping_triangle(self):
        tri = np.array([[[0, 0, 1], [2, 0, 3], [0, 2, 1]]], dtype=float)
        layers = np.concatenate([tri, tri+[0, 0, 2]])
        z = highest_triangle_z(layers, np.array([[.5, .5], [3, 3]]))
        self.assertAlmostEqual(z[0], 3.5)
        self.assertTrue(np.isnan(z[1]))


if __name__ == "__main__":
    unittest.main()
