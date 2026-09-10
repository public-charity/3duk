from copy import deepcopy
from pathlib import Path
import sys
import unittest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "ue"))
from capture_readiness import require_heightmaps


class CaptureReadinessTests(unittest.TestCase):
    good = {"ready": True, "missing_heightmaps": 0, "components": 2,
            "textures": [{"ready": True, "fully_streamed": True, "mips": 9, "resident_after": 9}]}

    def test_ready_scene_and_scene_without_landscape(self):
        require_heightmaps(self.good)
        require_heightmaps({"ready": True, "missing_heightmaps": 0, "components": 0, "textures": []})

    def test_missing_or_unready_report_fails(self):
        for bad in ({}, {**self.good, "ready": False}, {**self.good, "textures": []},
                    {**self.good, "missing_heightmaps": 1}, {**self.good, "error": "no world"}):
            with self.assertRaises(RuntimeError):
                require_heightmaps(bad)

    def test_coarse_mips_fail_even_if_summary_claims_ready(self):
        bad = deepcopy(self.good)
        bad["textures"][0]["resident_after"] = 7
        with self.assertRaises(RuntimeError):
            require_heightmaps(bad)


if __name__ == "__main__":
    unittest.main()
