"""A real section transition may open from zero without leaving a back-facing top."""
import sys,unittest
from pathlib import Path
import numpy as np
HERE=Path(__file__).resolve().parent
sys.path[:0]=[str(HERE),str(HERE.parent)]
import synthetic
from streetscape import io_json
from streetscape.spline import JunctionPlan
from streetscape.build import build_all,junction_audit


class CollapsedPavementTest(unittest.TestCase):
    def test_opening_corner_surface_faces_up_and_keeps_all_road_and_kerb_seams(self):
        raw=synthetic.load_fixture('junction_collapsed_pavement');site=io_json.site_from_dict(raw)
        plan=JunctionPlan(site);built=build_all(site,synthetic.junction_terrain_for(raw),plan=plan)
        tested=0
        for part in built.values():
            for mesh in part.edge.values():
                mask=mesh.group_mask_tris(prefix='corner_pavement:')
                mask &= np.min(mesh.vh[mesh.f],axis=1)>=-1e-8
                tri=mesh.v[mesh.f[mask]];normal=np.cross(tri[:,1]-tri[:,0],tri[:,2]-tri[:,0])
                tested+=len(tri)
                self.assertTrue(np.all(normal[:,2]>=-1e-8))
        self.assertGreater(tested,0)
        report=junction_audit(plan,built)
        self.assertEqual(report['patches'],1);self.assertEqual(report['corners'],3)
        self.assertLessEqual(report['worst_patch_gap_m'],1e-9)
        self.assertLessEqual(report['worst_corner_gap_m'],1e-9)


if __name__=='__main__':unittest.main()
