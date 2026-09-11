import sys
from pathlib import Path
import unittest
import numpy as np

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from diag.driving_surface_audit import obstructions
from diag.path_crossing_candidate import fit_lowering, overlap_constraints, lane_width_candidate
from streetscape.mesh import MeshBuffer


def rectangle(x1,x2,z):
    return np.array([[[x1,-2,z],[x2,-2,z],[x2,2,z]],[[x1,-2,z],[x2,2,z],[x1,2,z]]],dtype=float)


def path_mesh():
    s=np.arange(11,dtype=float)
    mesh=MeshBuffer()
    mesh.v=np.array([[x,y,.15] for x in s for y in (-1,1)])
    mesh.vs=np.repeat(s,2)
    mesh.f=np.array([[2*i,2*i+2,2*i+3] for i in range(10)]+[[2*i,2*i+3,2*i+1] for i in range(10)])
    mesh.grp=np.zeros(len(mesh.f),dtype=int)
    mesh.group_names=["road"]
    return s,mesh


class DrivingSurfaceTest(unittest.TestCase):
    def test_raised_crossing_fails_but_flush_and_underlying_paths_do_not(self):
        xy=np.array([[5,0],[2,0],[20,0]],dtype=float)
        for height,expected in ((.076,[0]),(.003,[]),(-.01,[])):
            hits,_,road_z,_=obstructions(xy,rectangle(0,10,0),rectangle(4,6,height))
            self.assertEqual(hits.tolist(),expected)
            self.assertTrue(np.isnan(road_z[-1]))  # Missing coverage is never a height-zero pass.

    def test_overlap_solver_catches_narrow_crossing_between_path_stations(self):
        s,mesh=path_mesh()
        road=rectangle(4.35,4.45,0)
        lowering,stats=fit_lowering(s,mesh,road)
        mesh.v[:,2]-=np.repeat(lowering,2)
        rises=[r for _,_,r in overlap_constraints(mesh,road)]
        self.assertLessEqual(max(float(r.max()) for r in rises),-.01+1e-8)
        self.assertEqual(lowering[0],0)
        self.assertEqual(lowering[-1],0)
        self.assertLessEqual(np.max(np.abs(np.diff(lowering))),.1+1e-8)
        self.assertGreater(stats["contact_vertices"],0)

    def test_crossing_at_fixed_endpoint_requires_connected_model(self):
        s,mesh=path_mesh()
        with self.assertRaisesRegex(ValueError,"infeasible with fixed endpoints"):
            fit_lowering(s,mesh,rectangle(0,2,0))

    def test_fair_profile_removes_inter_crossing_hump_without_losing_clearance(self):
        s,mesh=path_mesh()
        road=np.concatenate([rectangle(2.8,3.2,.08),rectangle(6.8,7.2,.08)])
        plain,_=fit_lowering(s,mesh,road)
        fair,stats=fit_lowering(s,mesh,road,reference_z=np.full(len(s),.15))
        self.assertLess(stats['fairing']['after_bending_energy'],stats['fairing']['before_bending_energy']*.5)
        self.assertGreater(fair[5],plain[5])  # No unnecessary high island between two crossing dips.
        self.assertEqual(fair[0],0)
        self.assertEqual(fair[-1],0)
        mesh.v[:,2]-=np.repeat(fair,2)
        self.assertLessEqual(max(float(r.max()) for _,_,r in overlap_constraints(mesh,road)),-.01+1e-8)

    def test_explicit_single_lane_model_can_reduce_class_default_without_moving_points(self):
        raw={"profiles":{"road":{"primary":{"lanes":2,"lane_widths_m":[3.,3.],"width_m":10.,"markings":[{"id":"centre"}]}}},
             "splines":[{"id":"roads:1:0","source":{"osm_id":"1"},"profile_ids":{"road":"primary"},
                         "points":[{"x":0,"y":0,"width_m":10.},{"x":20,"y":0,"width_m":10.}],
                         "junction_start":"a","junction_end":"b"}]}
        tuning=dict(lane_width_m=3.,lane_margin_m=1.,width_quantum_m=.5)
        model=lane_width_candidate(raw,["roads:1:0"],{"1":{"lanes":"1","oneway":"yes"}},tuning)
        d=raw["splines"][0]
        self.assertEqual([p["width_m"] for p in d["points"]],[4.,4.])
        self.assertEqual([(p["x"],p["y"]) for p in d["points"]],[(0,0),(20,0)])
        self.assertEqual(raw["profiles"]["road"][d["profile_ids"]["road"]]["markings"],[])
        self.assertEqual(model[0]["kind"],"inferred_from_explicit_lanes")
        with self.assertRaisesRegex(ValueError,"no explicit width"):
            lane_width_candidate(raw,["roads:1:0"],{"1":{"lanes":"1","oneway":"yes","width":"4.7"}},tuning)


if __name__=="__main__": unittest.main()
