"""Support contact is measured in world space, independently of sweep coordinates."""
import os
import sys
import unittest
import numpy as np
sys.path.insert(0,os.path.dirname(__file__))
import synthetic as syn
from streetscape import io_json
from streetscape.spline import Spline
from streetscape.edge import build_edge
from streetscape.terrain import Heightfield
from streetscape.support import batter_toes


class TestBankedSupport(unittest.TestCase):
    def spline(self,kind,terrain):
        doc = syn.load_fixture("straight_100")
        definition = doc["splines"][0]
        definition["elevation_profile"] = [dict(s_m=0,z_m=11.5,bank_deg=12),dict(s_m=100,z_m=11.5,bank_deg=12)]
        definition["segments"] = [dict(id="support",s0_m=0,s1_m=None,side="both",
            edge=dict(embankment=dict(kind=kind,side="both",material="grass",threshold_m=.01)))]
        site = io_json.site_from_dict(doc)
        return Spline(site.splines[0],site,terrain)

    def test_downhill_retaining_walls_remain_vertical_when_road_is_banked(self):
        field = Heightfield.from_function(lambda x,y:10+0*x,(512,512),xy0=(0,-256))
        sp = self.spline("retaining_wall",field)
        i = int(np.argmin(abs(sp.s-20)))
        for side in (-1,1):
            mesh,_ = build_edge(sp,side,field)
            vertices = mesh.vertices_of_groups(prefix="embankment:retaining_wall")
            self.assertGreater(len(vertices),0)
            self.assertEqual(mesh.validate(),[])
            self.assertTrue(mesh.is_closed_manifold(grp_filter={"embankment:retaining_wall:0"}))
            p = mesh.v[vertices[np.abs(mesh.vs[vertices]-sp.s[i])<1e-8]]
            self.assertAlmostEqual(p[:,2].min(),9.7,places=8)
            self.assertAlmostEqual(np.ptp(p[:,1]),.3,places=8)
            # Each wall face has the same XY at its top and bottom.
            self.assertEqual(len(np.unique(np.round(p[:,:2],8),axis=0)),2)

    def test_batter_toe_meets_sloping_ground_at_the_actual_world_position(self):
        field = Heightfield.from_function(lambda x,y:10-.2*y,(512,512),xy0=(0,-256))
        sp = self.spline("batter",field)
        mesh,_ = build_edge(sp,1,field)
        vertices = mesh.vertices_of_groups(prefix="embankment:batter")
        self.assertGreater(len(vertices),0)
        for station in np.unique(mesh.vs[vertices]):
            i = int(np.argmin(abs(sp.s-station)))
            p = mesh.v[vertices[np.abs(mesh.vs[vertices]-station)<1e-8]]
            start,toe = p[np.argmax(p[:,2])],p[np.argmin(p[:,2])]
            self.assertAlmostEqual(toe[2],field.sample(toe[0],toe[1])-.3,places=7)
            run = np.linalg.norm(toe[:2]-start[:2])
            self.assertAlmostEqual(run/(start[2]-toe[2]-.3),1.5,places=7)
            spec = sp.side_spec[1]
            expected = sp.frames.p[i]+(sp.edge_offset(1)[i]+spec.back_offset[i])*sp.frames.n[i]+(sp.edge_height(1)[i]+spec.hk_back[i])*sp.frames.b[i]
            self.assertTrue(np.allclose(start,expected,atol=1e-9))

    def test_missing_or_unreachable_toe_fails(self):
        class Missing:
            def sample(self,x,y): return np.full(np.shape(x),np.nan)
        class Falling:
            def sample(self,x,y): return -2*x
        args=(np.array([[0.,0.,1.]]),np.array([[1.,0.]]))
        for terrain in (Missing(),Falling()):
            with self.assertRaises(ValueError):
                batter_toes(*args,terrain,np.array([True]),1.5,.3)


if __name__=="__main__":
    unittest.main()
