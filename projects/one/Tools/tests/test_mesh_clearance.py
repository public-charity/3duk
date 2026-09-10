"""Failure proofs for triangle-interior sampling, independent of road construction."""
from pathlib import Path
import sys
import unittest

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from diag.mesh_clearance import sample_triangles


class Terrain:
    def __init__(self, fn):
        self.fn = fn

    def sample(self, x, y):
        return self.fn(x, y)


class TriangleClearanceTests(unittest.TestCase):
    triangle = np.array([[[0, 0, 1], [2, 0, 1], [0, 2, 1]]], dtype=float)

    def test_finds_interior_peak_when_vertices_are_clear(self):
        ground = Terrain(lambda x, y: 2*np.exp(-((x-.6)**2+(y-.6)**2)/.08))
        self.assertTrue(np.all(ground.sample(self.triangle[0, :, 0], self.triangle[0, :, 1]) < 1))
        rec = sample_triangles(self.triangle, ground, spacing=.1)
        self.assertGreater(rec["penetrated_samples"], 0)
        self.assertGreater(rec["worst"]["ground_minus_surface_m"], .9)

    def test_respects_sloped_mesh_plane(self):
        triangle = self.triangle.copy()
        triangle[:, :, 2] = 1+triangle[:, :, 0]*.3+triangle[:, :, 1]*.2
        rec = sample_triangles(triangle, Terrain(lambda x, y: 1+x*.3+y*.2-.02))
        self.assertEqual(rec["penetrated_samples"], 0)
        self.assertAlmostEqual(rec["worst"]["ground_minus_surface_m"], -.02)

    def test_uncovered_surface_is_explicit(self):
        rec = sample_triangles(self.triangle, Terrain(lambda x, y: np.full_like(x, np.nan)))
        self.assertEqual(rec["finite_samples"], 0)
        self.assertEqual(rec["samples"], rec["uncovered_samples"])
        self.assertIsNone(rec["worst"])

    def test_empty_and_unbounded_inputs_fail(self):
        terrain = Terrain(lambda x, y: x*0)
        for triangles, spacing in (([], .25), (self.triangle, 0), (self.triangle*10000, .25)):
            with self.assertRaises(ValueError):
                sample_triangles(triangles, terrain, spacing)


if __name__ == "__main__":
    unittest.main()
