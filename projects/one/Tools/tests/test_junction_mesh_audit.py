import sys
from pathlib import Path
import unittest
import numpy as np

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from diag.junction_mesh_audit import surface_stats


class JunctionInteriorTest(unittest.TestCase):
    def test_interior_penetration_detected_when_vertices_are_clear(self):
        triangle=np.array([[[0,0,1],[2,0,1],[0,2,1]]],dtype=float)
        class Hill:
            def sample(self,x,y):
                return .8+.5*np.exp(-((x-.75)**2+(y-.75)**2)/.08)
        field=Hill()
        self.assertTrue(np.all(field.sample(triangle[0,:,0],triangle[0,:,1])<1))
        measured=surface_stats(triangle,field,.25)
        self.assertGreater(measured["max_penetration_m"],.1)
        self.assertGreater(measured["samples"],3)

    def test_empty_and_missing_ground_cannot_be_measurements(self):
        class Missing:
            def sample(self,x,y):
                return np.full(len(x),np.nan)
        self.assertEqual(surface_stats(np.empty((0,3,3)),Missing())["finite_samples"],0)
        result=surface_stats(np.array([[[0,0,1],[1,0,1],[0,1,1]]]),Missing())
        self.assertEqual(result["finite_samples"],0)
        self.assertEqual(result["missing_ground"],result["samples"])

    def test_covered_corner_is_separate_from_visible_penetration(self):
        triangle=np.array([[[0,0,1],[2,0,1],[0,2,1]]],dtype=float)
        covering=triangle.copy()
        covering[:,:,2]=2
        class Flat:
            def sample(self,x,y):
                return np.full(len(x),1.5)
        result=surface_stats(triangle,Flat(),cover_triangles=covering)
        self.assertEqual(result["max_penetration_m"],0)
        self.assertAlmostEqual(result["raw_max_penetration_m"],.5)
        self.assertAlmostEqual(result["max_road_occlusion_depth_m"],1)


if __name__=="__main__":
    unittest.main()
