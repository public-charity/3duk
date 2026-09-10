from pathlib import Path
from types import SimpleNamespace
import sys
import unittest

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from diag.bridge_profile_candidate import approach_profile, hermite


class ApproachTests(unittest.TestCase):
    def spline(self, reverse=False):
        s = np.arange(0, 151, 2, dtype=float)
        z = 13+.01*s-3*np.exp(-s/8)
        bank = np.ones_like(s)
        return SimpleNamespace(id="test", length=150, s=s, z_ref=z[::-1] if reverse else z,
                               bank_deg=bank, sampling=SimpleNamespace(bank_rate_max_deg_per_m=.25))

    def test_hermite_preserves_heights_and_tangents(self):
        eps = 1e-5
        z = hermite(np.array([0, eps, 40-eps, 40]), 40, 13, 14, .01, .02)
        self.assertEqual(z[0], 13)
        self.assertEqual(z[-1], 14)
        self.assertAlmostEqual((z[1]-z[0])/eps, .01, places=6)
        self.assertAlmostEqual((z[-1]-z[-2])/eps, .02, places=6)

    def test_both_orientations_join_and_preserve_remote_geometry(self):
        for reverse in (False, True):
            sp = self.spline(reverse)
            q, z, bank, info = approach_profile(sp, "end" if reverse else "start", 13, .01)
            self.assertEqual(z[-1 if reverse else 0], 13)
            self.assertEqual(bank[-1 if reverse else 0], 0)
            self.assertEqual(z[0 if reverse else -1], sp.z_ref[0 if reverse else -1])
            d = 150-q if reverse else q
            mask = d > info["blend_length_m"]
            np.testing.assert_allclose(z[mask], np.interp(q[mask], sp.s, sp.z_ref))
            self.assertLess(info["blend_max_grade_pct"], 2)

    def test_missing_anchor_fails(self):
        with self.assertRaisesRegex(ValueError, "no supported approach anchor"):
            approach_profile(self.spline(), "start", 30, 0)


if __name__ == "__main__":
    unittest.main()
