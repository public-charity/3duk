import sys,unittest
from pathlib import Path
import numpy as np
TOOLS=Path(__file__).resolve().parents[1];sys.path[:0]=[str(TOOLS),str(TOOLS/'blender')]
from diag.terrain_surface_coverage import projected_surface_mask
from diag.terrain_contact import exact_penetration
from streetscape.terrain import Heightfield


class TerrainSurfaceCoverageTests(unittest.TestCase):
    def test_steep_surface_penetration_is_not_hidden_by_a_slope_filter(self):
        triangles=np.array([[[2.,2.,.5],[2.25,2.,2.5],[2.,2.25,.5]]])
        normal=np.cross(triangles[:,1]-triangles[:,0],triangles[:,2]-triangles[:,0])
        self.assertFalse(np.any(normal[:,2]>.5*np.linalg.norm(normal,axis=1)))
        keep,coverage=projected_surface_mask(triangles)
        self.assertEqual(coverage['steep_height_graph_triangles'],1)
        field=Heightfield.from_function(lambda x,y:1.+0*x,extent_m=(8,8),tile_m=8)
        field.sampling='landscape_triangulated'
        self.assertAlmostEqual(exact_penetration(triangles[keep],field)['max_penetration_m'],.5)

    def test_winding_cannot_remove_coverage_and_vertical_faces_remain_explicit(self):
        a=np.array([[2.,2.,1.],[3.,2.,1.],[2.,3.,1.]])
        vertical=np.array([[2.,2.,1.],[2.,2.,2.],[2.,3.,1.]])
        keep,coverage=projected_surface_mask(np.array([a,a[::-1],vertical]))
        self.assertEqual(keep.tolist(),[True,True,False])
        self.assertEqual(coverage['downward_height_graph_triangles'],1)
        self.assertEqual(coverage['vertical_or_degenerate_xy_triangles'],1)
        for invalid in (np.full((1,3,3),np.nan),np.zeros((3,3))):
            with self.assertRaises(ValueError):projected_surface_mask(invalid)


if __name__=='__main__':unittest.main()
