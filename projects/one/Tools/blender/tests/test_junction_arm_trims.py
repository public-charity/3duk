import copy,json,sys,unittest
from pathlib import Path
import numpy as np
HERE=Path(__file__).resolve().parent
sys.path.insert(0,str(HERE));sys.path.insert(0,str(HERE.parent))
import synthetic
from streetscape import io_json,schema
from streetscape.spline import JunctionPlan,Spline
from streetscape.build import build_all,junction_audit
import test_junction as junction_tests


class ArmTrimTest(unittest.TestCase):
    def test_missing_null_and_explicit_requests_round_trip_and_validate(self):
        base=dict(spline_id='arm',end='start')
        for value in ('missing',None,8.):
            raw=dict(base)
            if value!='missing':raw['trim_radius_m']=value
            self.assertEqual(schema.JunctionEnd.from_dict(raw).to_dict(),raw)
        for value in (-1.,0.,33.,float('nan'),True):
            with self.assertRaises(schema.SchemaError):schema.JunctionEnd.from_dict(dict(base,trim_radius_m=value))

    def test_default_geometry_is_exact_and_end_override_has_precedence(self):
        raw=synthetic.junction_crossroads();before=JunctionPlan(io_json.site_from_dict(raw))
        for end in raw['junctions'][0]['ends']:end['trim_radius_m']=None
        self.assertEqual(before.trims,JunctionPlan(io_json.site_from_dict(raw)).trims)
        raw['junctions'][0]['trim_radius_m']=10.
        raw['junctions'][0]['ends'][0]['trim_radius_m']=7.5
        plan=JunctionPlan(io_json.site_from_dict(raw))
        for index,end in enumerate(raw['junctions'][0]['ends']):
            self.assertAlmostEqual(plan.trim_for(end['spline_id'])[0],7.5 if index==0 else 10.,places=9)

    def test_actual_meshes_meet_on_the_same_unrebased_trim_stations(self):
        raw=json.loads((HERE/'fixtures/junction_arm_trims.json').read_text());site=io_json.site_from_dict(raw)
        plan=JunctionPlan(site);built=build_all(site,synthetic.junction_terrain_for(raw),plan=plan)
        report=junction_audit(plan,built)
        self.assertEqual(report['patches'],1);self.assertEqual(report['corners'],3)
        self.assertLessEqual(report['worst_patch_gap_m'],1e-9)
        self.assertLessEqual(report['worst_corner_gap_m'],1e-9)
        for end in site.junctions[0].ends:
            sp=built[end.spline_id].spline
            self.assertEqual(sp.s[0],0.)
            self.assertIn(sp.s_trim[0],sp.s)
            self.assertAlmostEqual(sp.s_trim[0],end.trim_radius_m or site.junctions[0].trim_radius_m,places=9)

    def test_two_requested_ends_still_keep_the_short_shared_spline(self):
        raw=junction_tests.TestDegenerate()._doc(6.)
        for junction in raw['junctions']:
            for end in junction['ends']:
                if end['spline_id']=='authored:arm0':end['trim_radius_m']=5.
        site=io_json.site_from_dict(raw);plan=JunctionPlan(site)
        sp=Spline(site.spline('authored:arm0'),site,synthetic.junction_terrain_for(raw),trim=plan.trim_for('authored:arm0'))
        self.assertAlmostEqual(sp.length,6.,places=9)
        self.assertAlmostEqual(sp.s_trim[1]-sp.s_trim[0],1.,places=9)
        self.assertEqual(sp.s[0],0.);self.assertEqual(sp.s[-1],sp.length)
        self.assertGreaterEqual(int(sp.active.sum()),2)


if __name__=='__main__':unittest.main()
