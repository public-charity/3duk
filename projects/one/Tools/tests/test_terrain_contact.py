import sys
from pathlib import Path
import unittest
import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
sys.path.insert(0, str(Path(__file__).resolve().parents[1]/"blender"))
from diag.terrain_contact import minimum_cut, apply_posts, exact_penetration, point_weights
from streetscape.terrain import Heightfield


class TerrainContactTest(unittest.TestCase):
    def field(self, fn):
        result = Heightfield.from_function(fn, extent_m=(16,8), tile_m=8)
        result.sampling = "landscape_triangulated"
        return result

    def test_exact_contact_on_small_triangle_and_quantized_result(self):
        field = self.field(lambda x,y: 1+0*x)
        triangles = np.array([[[2.15,3.12,.91],[2.37,3.12,.94],[2.24,3.41,.89]]])
        changes, stats = minimum_cut(triangles, field, max_cut_m=.2)
        candidate = apply_posts(field, changes)
        self.assertLessEqual(stats["max_cut_m"], .2)
        self.assertEqual(exact_penetration(triangles, candidate)["max_penetration_m"], 0)
        self.assertGreaterEqual(exact_penetration(triangles, candidate)["minimum_clearance_m"], .01-1e-7)
        self.assertTrue(np.all(field.tiles[(0,0)] == 1))
        self.assertIs(candidate.tiles[(1,0)], field.tiles[(1,0)])
        self.assertTrue(all(abs(v*128-round(v*128)) < 1e-8 for v in changes.values()))

    def test_interior_post_detected_when_mesh_vertices_are_clear(self):
        field = self.field(lambda x,y: 1+.25*((x==3)&(y==3)))
        triangles = np.array([[[1.2,1.2,1.1],[4.8,1.2,1.1],[3,4.8,1.1]]])
        self.assertTrue(np.all(field.sample(triangles[0,:,0],triangles[0,:,1]) < 1.1))
        self.assertAlmostEqual(exact_penetration(triangles,field)["max_penetration_m"], .15)
        changes, _ = minimum_cut(triangles, field)
        self.assertEqual(exact_penetration(triangles,apply_posts(field,changes))["max_penetration_m"], 0)

    def test_seam_post_updates_both_tiles(self):
        field = self.field(lambda x,y: 1+0*x)
        candidate = apply_posts(field, {(8,3):.75})
        self.assertEqual(candidate.tiles[(0,0)][5,8], .75)
        self.assertEqual(candidate.tiles[(1,0)][5,0], .75)
        self.assertEqual(field.tiles[(0,0)][5,8], 1)

    def test_large_cut_missing_terrain_and_empty_mesh_fail(self):
        field = self.field(lambda x,y: 2+0*x)
        tri = np.array([[[2,2,1],[3,2,1],[2,3,1]]])
        with self.assertRaisesRegex(ValueError, "budget"):
            minimum_cut(tri, field)
        field.tiles[(0,0)][:] = np.nan
        with self.assertRaisesRegex(ValueError, "missing"):
            minimum_cut(tri, field)
        with self.assertRaisesRegex(ValueError, "empty"):
            minimum_cut(np.empty((0,3,3)), field)

    def test_contact_that_would_open_an_adjacent_edge_is_rejected(self):
        field = self.field(lambda x,y: 1+0*x)
        tri = np.array([[[2,2,.9],[3,2,.9],[2,3,.9]]])
        minimum_cut(tri,field)  # Terrain alone can clear the lower surface.
        with self.assertRaisesRegex(ValueError, "budget"):
            minimum_cut(tri,field,protected_points=np.array([[2.25,2.25,1.]]))

    def test_point_constraints_use_the_same_diagonal_as_landscape(self):
        field = self.field(lambda x,y: np.round((.12*x*y+.03*x)*128)/128)
        for point in ((2.2,3.3),(2.8,3.7),(2.3,3.7),(8.,2.3)):
            keys,weights = point_weights(point,field.px_m)
            xy = np.asarray(keys,dtype=float)
            z = weights@field.sample(xy[:,0],xy[:,1])
            self.assertAlmostEqual(z,field.sample(*point),places=10)


if __name__ == "__main__":
    unittest.main()
