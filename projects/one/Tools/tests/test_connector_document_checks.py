import copy,json,sys,unittest
import numpy as np
from unittest.mock import patch
from pathlib import Path
TOOLS=Path(__file__).resolve().parents[1];sys.path[:0]=[str(TOOLS),str(TOOLS/'blender')]
from diag.connector_document_checks import check_complete_document,preserved_source,preserved_vertex_displacement
from diag.restore_geometry_selection import apply_retained_connectors


class ConnectorDocumentChecksTests(unittest.TestCase):
    def test_bend_full_document_preserves_every_source_definition(self):
        candidate=json.loads((TOOLS/'blender/tests/fixtures/junction_interior_bend_garrard.json').read_text(encoding='utf-8'))
        source=copy.deepcopy(candidate);source['junctions']=[]
        result=check_complete_document(source,candidate,None)
        self.assertEqual(result['before_body_totals'],{'fold_review':1})
        self.assertEqual(result['after_body_totals'],{'passed':1})
        self.assertEqual(len(result['new_bends']),1)
        self.assertEqual(result['new_connectors'],[])
        altered=copy.deepcopy(candidate);altered['splines'][0]['points'][0]['width_m']+=.01
        with self.assertRaisesRegex(ValueError,'source payload'):preserved_source(source,altered)

    def test_preserved_vertices_use_absolute_vector_limit_and_reject_invalid_coverage(self):
        source=np.array([[12100.,4685.,14.]])
        rounding=source.copy();rounding[0,2]+=5e-12
        self.assertGreater(preserved_vertex_displacement(source,rounding),0.)
        for candidate in (source+[[0.,0.,2e-9]],source+[[0.,8e-10,8e-10]],source[:0],np.full_like(source,np.nan)):
            with self.assertRaises(ValueError):preserved_vertex_displacement(source,candidate)
        # National-grid magnitude must never enlarge the tolerance.
        with self.assertRaises(ValueError):preserved_vertex_displacement(source+600000,source+600000+1e-6)

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

    def test_roundoff_is_reported_separately_and_topology_or_larger_changes_fail(self):
        from streetscape.build import build_all as real_build
        source,joined=self.fixture();third=copy.deepcopy(source['splines'][0])
        third.update(id='roads:untouched',continues_from=None,continues_to=None)
        for point in third['points']:point['x']+=100.
        source['splines'].append(copy.deepcopy(third));joined['splines'].append(copy.deepcopy(third))
        for mode in ('roundoff','movement','topology'):
            calls=[]
            def perturbed(*args,**kwargs):
                result=real_build(*args,**kwargs);calls.append(True)
                if len(calls)==2:
                    mesh=result[third['id']].road
                    if mode=='topology':mesh.f[0]=np.roll(mesh.f[0],1)  # Same triangle, changed indexing.
                    else:mesh.v[:,2]+=5e-12 if mode=='roundoff' else 2e-9
                return result
            with patch('diag.connector_document_checks.build_all',side_effect=perturbed):
                if mode=='roundoff':
                    report=check_complete_document(source,joined,None)
                    self.assertEqual(report['untouched_bodies_exact'],0)
                    self.assertEqual(report['untouched_bodies_with_roundoff'],1)
                    self.assertEqual(report['untouched_mesh_arrays_with_roundoff'],1)
                    self.assertLessEqual(report['maximum_preserved_vertex_displacement_m'],1e-9)
                else:
                    with self.assertRaises(ValueError):check_complete_document(source,joined,None)

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
