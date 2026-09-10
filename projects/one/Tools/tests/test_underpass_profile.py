import sys
from pathlib import Path
from types import SimpleNamespace
import unittest

import numpy as np

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from diag.underpass_profile_candidate import infer_profile


class UnderpassInferenceTest(unittest.TestCase):
    def alignment(self):
        s=np.arange(141,dtype=float)
        z=12+.01*s
        z[(s>=62)&(s<=78)]+=3  # contaminated ground follows the deck through the opening
        bank=np.ones_like(s)
        bank[(s>=62)&(s<=78)]=5
        return SimpleNamespace(s=s,z_ref=z,bank_deg=bank,length=140,
            sampling=SimpleNamespace(bank_rate_max_deg_per_m=.25))

    def test_known_floor_recovered_and_remote_profiles_unchanged(self):
        sp=self.alignment()
        q,z,b,stats=infer_profile(sp,[0,60,80],20,40,5)
        np.testing.assert_allclose(z,12+.01*q,atol=1e-12)
        np.testing.assert_allclose(b,1,atol=1e-12)
        self.assertAlmostEqual(stats["max_model_grade_pct"],1)
        for anchor in (55,85):
            i=np.searchsorted(q,anchor)
            self.assertAlmostEqual((z[i+1]-z[i])/(q[i+1]-q[i]),.01)
            self.assertAlmostEqual((z[i]-z[i-1])/(q[i]-q[i-1]),.01)
        outside=(q<55)|(q>85)
        np.testing.assert_array_equal(z[outside],np.interp(q[outside],sp.s,sp.z_ref))

    def test_short_approach_and_steep_inference_rejected(self):
        sp=self.alignment()
        with self.assertRaisesRegex(ValueError,"too short"):
            infer_profile(sp,[0,10,30],20,40,5)
        sp.z_ref=.2*sp.s
        with self.assertRaisesRegex(ValueError,"grade/bank"):
            infer_profile(sp,[0,60,80],20,40,5)

    def test_missing_observations_rejected(self):
        sp=self.alignment()
        sp.z_ref[55]=np.nan
        with self.assertRaisesRegex(ValueError,"nonfinite"):
            infer_profile(sp,[0,60,80],20,40,5)


if __name__=="__main__":
    unittest.main()
