import copy
from pathlib import Path
import sys
import unittest
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from diag.junction_arm_trim_candidates import RequestedPlan,verify_document,within_length_limits,search
from diag.junction_trim_candidates import Evaluator,metrics
from diag.corner_quality_audit import audit_document
from streetscape import io_json
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'blender/tests'))
import synthetic


class ArmCandidateTest(unittest.TestCase):
    def test_recorded_requests_reproduce_scaled_short_link_and_length_gate_rejects_overrun(self):
        raw=synthetic.junction_doc('short',[0,90,180,270],length=6.)
        raw['junctions'][0]['trim_radius_m']=8.
        site=io_json.site_from_dict(raw);original=RequestedPlan(site,{})
        for end in site.junctions[0].ends:
            self.assertEqual(original.requested['j0'][(end.spline_id,end.end)],8.)
            end.trim_radius_m=8.
        self.assertEqual(original.trims,RequestedPlan(site,{}).trims)
        # A previously untrimmed 10 m arm may not be consumed by an 8 m request.
        raw=synthetic.junction_doc('short',[0,90,180,270],length=10.)
        site=io_json.site_from_dict(raw);before=RequestedPlan(site,{})
        for end in site.junctions[0].ends:end.trim_radius_m=8.
        self.assertFalse(within_length_limits(before,RequestedPlan(site,{})))

    def test_serialized_search_matches_fresh_actual_mesh_audit_and_restores_schema(self):
        raw=synthetic.junction_crossroads();site=io_json.site_from_dict(raw)
        terrain=synthetic.junction_terrain_for(raw);ev=Evaluator(site,terrain);plan=ev.plan()
        before={'j0':ev.measure(plan,'j0')};self.assertEqual(before['j0']['status'],'fold_review')
        # This checks geometry/serialization, not host scheduling. The search has
        # bounded deterministic iterations; a busy VM must not exhaust its wall
        # budget and turn a valid geometry fixture into a timing-dependent test.
        with patch('diag.junction_arm_trim_candidates.time.perf_counter',return_value=0.):
            row,requests,after=search(ev,plan,before,'j0',seconds=10.)
        self.assertEqual(row['status'],'geometry_proposal');self.assertEqual(after['j0']['status'],'passed')
        self.assertTrue(all(end.trim_radius_m is None for end in site.junctions[0].ends))
        proposal=copy.deepcopy(raw)
        values={(r['spline_id'],r['end']):r['trim_radius_m'] for r in requests}
        for end in proposal['junctions'][0]['ends']:end['trim_radius_m']=values[(end['spline_id'],end['end'])]
        verify_document(raw,proposal)
        with patch('diag.corner_quality_audit.io_json.load_site',return_value=io_json.site_from_dict(proposal)):
            full=audit_document(Path('fixture.json'),terrain)
        self.assertEqual(after,{r['id']:metrics(r) for r in full['results']})
        for failure in ('centreline','binding','radius','boolean'):
            bad=copy.deepcopy(proposal)
            if failure=='centreline':bad['splines'][0]['points'][0]['x']+=.01
            elif failure=='binding':bad['junctions'][0]['ends'][0]['end']='invalid'
            else:bad['junctions'][0]['ends'][0]['trim_radius_m']=True if failure=='boolean' else 33.
            with self.assertRaises(ValueError):verify_document(raw,bad)

    def test_body_regression_prevents_retention_despite_junction_improvement(self):
        raw=synthetic.junction_crossroads();site=io_json.site_from_dict(raw)
        terrain=synthetic.junction_terrain_for(raw);ev=Evaluator(site,terrain);plan=ev.plan()
        before={'j0':ev.measure(plan,'j0')}
        with patch('diag.junction_arm_trim_candidates.body_regressions',return_value=['planted body fold']):
            row,requests,after=search(ev,plan,before,'j0',seconds=1.)
        self.assertIsNone(requests);self.assertIsNone(after)
        self.assertGreater(row['rejections']['body_regression_or_unmeasured'],0)
        self.assertTrue(all(end.trim_radius_m is None for end in site.junctions[0].ends))


if __name__=='__main__':unittest.main()
