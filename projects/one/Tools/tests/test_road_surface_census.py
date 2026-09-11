import copy,json,sys,tempfile,unittest
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from diag.road_surface_census import measure_surface,audit_document,pending_documents
from phase1_qc import sha256
from streetscape import io_json
from streetscape.spline import JunctionPlan
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'blender/tests'))
import synthetic


class RoadSurfaceCensusTest(unittest.TestCase):
    def test_actual_rail_and_ballast_are_measured_and_a_too_wide_road_fails(self):
        for fixture in ('rail_R300_600','curve_R20_200'):
            raw=synthetic.load_fixture(fixture);site=io_json.site_from_dict(raw);terrain=synthetic.terrain_for(raw)
            result=measure_surface(site,site.splines[0].id,terrain,JunctionPlan(site))
            self.assertEqual(result['status'],'passed')
            if fixture.startswith('rail'):
                for group in ('ballast','rail:left','rail:right'):
                    self.assertGreater(result['parts'][group]['surface_triangles'],0)
            else:
                bad=copy.deepcopy(raw)
                for definition in bad['splines']:
                    for point in definition['points']:point['width_m']=60.
                site=io_json.site_from_dict(bad)
                result=measure_surface(site,site.splines[0].id,terrain,JunctionPlan(site))
                self.assertEqual(result['status'],'fold_review')
                self.assertGreater(result['parts']['road']['folded_area_m2'],0)

    def test_complete_document_keeps_nonroad_definitions_in_coverage(self):
        raw=synthetic.junction_crossroads();extra=copy.deepcopy(raw['splines'][0]);extra['id']='authored:nonroad'
        extra['profile_ids']['road']=None;extra.pop('junction_start',None);extra.pop('junction_end',None);raw['splines'].append(extra)
        with tempfile.TemporaryDirectory() as temp:
            path=Path(temp)/'site_x0_y0.json';path.write_text(json.dumps(raw))
            report=audit_document(path,synthetic.junction_terrain_for(raw))
            self.assertEqual(report['definitions'],5);self.assertEqual(sum(report['totals'].values()),5)
            self.assertEqual(report['totals']['without_road_profile'],1)

    def test_missing_or_corrupt_report_reduces_completion(self):
        with tempfile.TemporaryDirectory() as temp:
            root=Path(temp);source=root/'site_x0_y0.json';report=root/'site_x0_y0.report.json';report.write_text('{}')
            records={source.name:dict(report_sha256=sha256(report))}
            self.assertEqual(pending_documents([source],root,records),[])
            report.write_text('{')
            self.assertEqual(pending_documents([source],root,records),[source]);self.assertEqual(records,{})
            with self.assertRaisesRegex(ValueError,'coverage'):pending_documents([source],root,{'unexpected':{}})


if __name__=='__main__':unittest.main()
