"""Known answers of noise.py (DESIGN.md 3.8, SCHEMA.md 9.3): bit-exact so the C++ port can be diffed."""
import os
import sys
import unittest

import numpy as np

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import synthetic as syn  # noqa: E402,F401  (adds Tools/blender to sys.path)
from streetscape import noise  # noqa: E402

EXP = syn.load_json(os.path.join(syn.FIXTURES_DIR, "expected.json"))["noise"]


class TestNoise(unittest.TestCase):
    def test_lowbias32_known_answers(self):
        for k, want in EXP["lowbias32"].items():
            x = int(k, 16) if k.startswith("0x") else int(k)
            got = int(noise.lowbias32(np.array([x], dtype=np.uint32))[0])
            self.assertEqual(got, int(want, 16), "lowbias32(%s) = %s, expected %s" % (k, hex(got), want))
        # scalar / python int / negative wrap
        self.assertEqual(int(noise.lowbias32(1)), 0x688990C0)
        self.assertEqual(int(noise.lowbias32(np.array([2], dtype=np.int64))[0]), 0xD1132181)

    def test_unit_noise_known_answers(self):
        got = noise.unit_noise(np.arange(5), 7)
        want = np.array(EXP["unit_noise_0_4_seed7"])
        np.testing.assert_allclose(got, want, atol=EXP["tol"], rtol=0)
        self.assertTrue(np.all(got >= -1) and np.all(got < 1))

    def test_unit_noise01_range_and_determinism(self):
        a = noise.unit_noise01(np.arange(10000), 3)
        b = noise.unit_noise01(np.arange(10000), 3)
        self.assertTrue(np.array_equal(a, b))
        self.assertTrue(a.min() >= 0.0 and a.max() < 1.0)
        self.assertAlmostEqual(float(a.mean()), 0.5, delta=0.02)

    def test_value_noise3_range_continuity_determinism(self):
        rs = np.random.RandomState(2)
        q = rs.rand(50000, 3) * 100
        v = noise.value_noise3(q, 1)
        self.assertTrue(v.min() >= -1.0 and v.max() <= 1.0)
        self.assertTrue(np.array_equal(v, noise.value_noise3(q, 1)))
        self.assertFalse(np.array_equal(v, noise.value_noise3(q, 2)))
        a = rs.rand(2000, 3) * 10
        b = a + np.array([0.001, 0.0, 0.0])
        d = np.abs(noise.value_noise3(a, 1) - noise.value_noise3(b, 1)).max()
        self.assertLess(d, EXP["value_noise3_continuity_1mm_max"])
        # lattice values are hit exactly at integer coordinates
        ip = np.array([[3, 4, 5], [0, 0, 0], [-2, 7, 1]], dtype=np.float64)
        np.testing.assert_allclose(noise.value_noise3(ip, 9), noise.lattice(ip[:, 0].astype(int), ip[:, 1].astype(int), ip[:, 2].astype(int), 9), atol=1e-12)

    def test_fbm3_normalised(self):
        q = np.random.RandomState(5).rand(50000, 3) * 200
        f = noise.fbm3(q, 1)
        lo, hi = EXP["fbm3_range"]
        self.assertTrue(f.min() >= lo and f.max() <= hi)
        self.assertLess(abs(float(f.mean())), 0.05)


if __name__ == "__main__":
    unittest.main()
