import copy
from pathlib import Path
import sys
import unittest
from unittest.mock import patch
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from diag.junction_trim_candidates import Evaluator,metrics,regressions,try_radius,verify_document
from diag.corner_quality_audit import audit_document
from streetscape import io_json
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'blender/tests'))
import synthetic


class TrimCandidateTest(unittest.TestCase):
    def test_actual_cached_proposal_matches_independent_full_junction_audit(self):
        raw=synthetic.junction_crossroads();site=io_json.site_from_dict(raw)
        terrain=synthetic.junction_terrain_for(raw);evaluator=Evaluator(site,terrain);plan=evaluator.plan()
        before={'j0':evaluator.measure(plan,'j0')}
        self.assertEqual(before['j0']['status'],'fold_review')
        row,proposed,after=try_radius(evaluator,plan,before,'j0',8.)
        self.assertEqual(row['status'],'geometry_candidate')
        self.assertIsNone(site.junctions[0].trim_radius_m)
        self.assertIsNotNone(proposed)
        candidate=copy.deepcopy(raw);candidate['junctions'][0]['trim_radius_m']=8.
        with patch('diag.corner_quality_audit.io_json.load_site',return_value=io_json.site_from_dict(candidate)):
            full=audit_document(Path('fixture.json'),terrain)
        self.assertEqual(after,{r['id']:metrics(r) for r in full['results']})
        self.assertEqual(after['j0']['status'],'passed')

    def test_target_improvement_cannot_excuse_a_neighbour_regression_or_missing_coverage(self):
        passed=dict(status='passed',overlap=0.,inverted=0.,folded=0.)
        folded=dict(passed,status='fold_review',folded=2.)
        before={'target':folded,'neighbour':passed}
        after={'target':passed,'neighbour':dict(passed,status='fold_review',folded=.1)}
        self.assertEqual(regressions(before,after)[0]['id'],'neighbour')
        with self.assertRaisesRegex(ValueError,'coverage'):
            regressions(before,{'target':passed})

    def test_trim_override_cannot_consume_short_arms(self):
        raw=synthetic.junction_doc('short',[0,90,180,270],length=10.)
        site=io_json.site_from_dict(raw);terrain=synthetic.junction_terrain_for(raw)
        evaluator=Evaluator(site,terrain);plan=evaluator.plan();before={'j0':evaluator.measure(plan,'j0')}
        row,proposal,after=try_radius(evaluator,plan,before,'j0',8.)
        self.assertEqual(row['status'],'length_limit')
        self.assertIsNone(proposal);self.assertIsNone(after)
        self.assertIsNone(site.junctions[0].trim_radius_m)

    def test_complete_document_preservation_rejects_moved_centrelines_and_oversized_trims(self):
        source=synthetic.junction_crossroads();candidate=copy.deepcopy(source)
        candidate['junctions'][0]['trim_radius_m']=8.
        verify_document(source,candidate)
        for case in ('centreline','junction','oversized','missing'):
            with self.subTest(case=case):
                bad=copy.deepcopy(candidate)
                if case=='centreline':bad['splines'][0]['points'][0]['x']+=.01
                if case=='junction':bad['junctions'][0]['x']+=.01
                if case=='oversized':bad['junctions'][0]['trim_radius_m']=33.
                if case=='missing':bad['junctions']=[]
                with self.assertRaises(ValueError):verify_document(source,bad)


if __name__=='__main__':unittest.main()
