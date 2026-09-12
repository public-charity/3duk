import copy,json,sys,unittest
from pathlib import Path
TOOLS=Path(__file__).resolve().parents[1];sys.path[:0]=[str(TOOLS),str(TOOLS/'blender')]
from diag.internal_bend_candidates import screen_road,fold_clusters,unsupported_continuity
from diag.connector_document_checks import check_complete_document
from streetscape import io_json
from streetscape.spline import Spline,JunctionPlan


class InteriorBendCandidateTests(unittest.TestCase):
    def fixture(self,name='junction_interior_bend_garrard'):
        raw=json.loads((TOOLS/'blender/tests/fixtures'/f'{name}.json').read_text(encoding='utf-8'))
        raw['junctions']=[]
        return raw

    def test_real_corner_proposal_removes_fold_and_passes_complete_document(self):
        raw=self.fixture();original=copy.deepcopy(raw);sid=raw['splines'][0]['id'];checkpoints=[]
        candidate,report=screen_road(raw,sid,None,20.,lambda r:checkpoints.append(copy.deepcopy(r)))
        self.assertEqual(report['status'],'local_geometry_proposal')
        self.assertEqual(report['after_body']['status'],'passed')
        self.assertEqual(len(report['additions']),1)
        self.assertTrue(checkpoints)
        self.assertEqual(raw,original)
        self.assertEqual(candidate['splines'],original['splines'])
        full=check_complete_document(raw,candidate,None)
        self.assertEqual(full['body_regressions'],0)
        self.assertEqual(full['after_body_totals'],{'passed':1})

    def test_expired_search_budget_does_not_publish_a_geometry_candidate(self):
        raw=self.fixture();candidate,report=screen_road(raw,raw['splines'][0]['id'],None,1e-9)
        self.assertIsNone(candidate)
        self.assertEqual(report['stop_reason'],'search_budget_exhausted')
        self.assertEqual(report['additions'],[])

    def test_actual_barrier_timeline_is_recognized_as_unproved_continuity(self):
        raw=self.fixture('junction_interior_bend');site=io_json.site_from_dict(raw);plan=JunctionPlan(site)
        sp=Spline(site.splines[0],site,None,trim=plan.trim_for(site.splines[0].id))
        self.assertTrue(unsupported_continuity(sp))
        raw=self.fixture();site=io_json.site_from_dict(raw);plan=JunctionPlan(site)
        sp=Spline(site.splines[0],site,None,trim=plan.trim_for(site.splines[0].id))
        self.assertFalse(unsupported_continuity(sp))
        self.assertEqual(len(fold_clusters(sp)),1)


if __name__=='__main__':unittest.main()
