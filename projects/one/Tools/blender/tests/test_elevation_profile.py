"""Explicit structural alignments preserve survey samples and shared renderer stations."""
from pathlib import Path
import sys
import unittest

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))
import synthetic as syn
from streetscape import io_json, schema as S
from streetscape.build import build_all
from streetscape.spline import Spline
from streetscape.terrain import Heightfield


class ElevationProfileTests(unittest.TestCase):
    def doc(self):
        doc = syn.load_fixture("straight_100")
        doc["splines"][0]["elevation_profile"] = [
            {"s_m": 0, "z_m": 20, "bank_deg": 0},
            {"s_m": 12.3, "z_m": 20.123, "bank_deg": 1},
            {"s_m": 67.8, "z_m": 20.678, "bank_deg": -1},
            {"s_m": 100, "z_m": 21, "bank_deg": 0}]
        return doc

    def test_deck_stays_over_valley_and_survey_remains_raw(self):
        site = io_json.site_from_dict(self.doc())
        terrain = Heightfield.from_function(lambda x, y: 20-10*np.exp(-((x-50)/10)**2),
                                           extent_m=(128, 128), tile_m=128, px_m=1, xy0=(0, -64))
        built = build_all(site, terrain)
        result = next(iter(built.values()))
        sp = result.spline
        self.assertLess(sp.z_raw.min(), 11)
        np.testing.assert_allclose(sp.z_ref, 20+.01*sp.s, atol=1e-12)
        np.testing.assert_allclose(sp.bank_deg, np.interp(sp.s, [0, 12.3, 67.8, 100], [0, 1, -1, 0]))
        self.assertIn(12.3, sp.s)
        self.assertIn(67.8, sp.s)
        self.assertTrue(all(result.stats["stations_identical"].values()))

    def test_profile_roundtrip_and_absent_profile_compatibility(self):
        doc = self.doc()
        roundtrip = io_json.site_from_dict(doc).to_dict()
        self.assertEqual(roundtrip["splines"][0]["elevation_profile"], doc["splines"][0]["elevation_profile"])
        old = io_json.site_from_dict(syn.load_fixture("straight_100")).to_dict()
        self.assertNotIn("elevation_profile", old["splines"][0])

    def test_malformed_knots_fail(self):
        for profile in ([], [{"s_m": 0, "z_m": 20, "bank_deg": 0}],
                        [{"s_m": 1, "z_m": 20, "bank_deg": 0}, {"s_m": 100, "z_m": 21, "bank_deg": 0}],
                        [{"s_m": 0, "z_m": 20, "bank_deg": 0}, {"s_m": 0, "z_m": 21, "bank_deg": 0}]):
            doc = self.doc()
            doc["splines"][0]["elevation_profile"] = profile
            self.assertTrue(io_json.validate_structure(doc))

    def test_changed_horizontal_length_invalidates_profile(self):
        doc = self.doc()
        doc["splines"][0]["elevation_profile"][-1]["s_m"] = 99
        site = io_json.site_from_dict(doc)
        with self.assertRaises(S.SchemaError):
            Spline(site.splines[0], site, syn.terrain_for(doc))


if __name__ == "__main__":
    unittest.main()
