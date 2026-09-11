import copy,json,sys,unittest
from pathlib import Path
TOOLS=Path(__file__).resolve().parents[1];sys.path[:0]=[str(TOOLS),str(TOOLS/'blender')]
from diag.connector_document_checks import check_complete_document,preserved_source
from diag.restore_geometry_selection import apply_retained_connectors


class ConnectorDocumentChecksTests(unittest.TestCase):
    def fixture(self):
        joined=json.loads((TOOLS/'blender/tests/fixtures/junction_connector_bend.json').read_text(encoding='utf-8'))
        source=copy.deepcopy(joined);source['junctions']=[]
        for d in source['splines']:d['junction_start']=None;d['junction_end']=None
        return source,joined

    def test_complete_fixture_checks_finished_meshes_and_source_preservation(self):
        source,joined=self.fixture();original=copy.deepcopy(source);candidate=copy.deepcopy(joined)
        report=check_complete_document(source,joined,None)
        self.assertEqual(report['status'],'complete_document_geometry_verified');self.assertEqual(report['additions'],1)
        self.assertEqual(source,original);self.assertEqual(joined,candidate)
        self.assertEqual(report['body_regressions'],0)
        self.assertLessEqual(report['new_connectors'][0]['finished_mesh_seams']['worst_patch_gap_m'],1e-9)

    def test_endpoint_or_metadata_changes_are_rejected_before_build(self):
        for mode in ('point','metadata','count'):
            source,joined=self.fixture()
            if mode=='point':joined['splines'][0]['points'][0]['x']+=.001
            elif mode=='metadata':joined['generator']='changed'
            else:joined['splines'].pop()
            with self.assertRaises(ValueError):preserved_source(source,joined)

    def test_two_joins_sharing_a_road_are_checked_together(self):
        source,joined=self.fixture();first,second=source['splines'];third=copy.deepcopy(first)
        third['id']='roads:third';third['continues_from']=second['id'];third['continues_to']=None
        x,y=second['points'][-1]['x'],second['points'][-1]['y']
        third['points']=[dict(first['points'][0],x=x,y=y),dict(first['points'][-1],x=x+30.,y=y)]
        second['continues_to']=third['id'];source['splines'].append(third)
        a=copy.deepcopy(joined['junctions'][0]);b=copy.deepcopy(a);b.update(id='connector:second',x=x,y=y)
        b['ends']=[dict(spline_id=second['id'],end='end'),dict(spline_id=third['id'],end='start')]
        docs={'fixture':source};apply_retained_connectors(docs,{'fixture':[a,b]})
        result=check_complete_document(source,docs['fixture'],None)
        self.assertEqual(result['additions'],2);self.assertEqual(result['changed_bodies'],3)
        broken=copy.deepcopy(docs['fixture']);broken['junctions'][-1]['corner_handle_frac']=.01
        with self.assertRaises(ValueError):check_complete_document(source,broken,None)


if __name__=='__main__':unittest.main()
