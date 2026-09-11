"""Explicit two-arm surfaces retain legacy discs and close actual finished meshes."""
import copy
import os
import sys
import unittest
import numpy as np
sys.path[:0]=[os.path.dirname(__file__),os.path.dirname(os.path.dirname(os.path.dirname(__file__)))]
import synthetic as syn
from streetscape import io_json,schema as S
from streetscape.spline import JunctionPlan
from streetscape.build import build_all,junction_audit
from diag.corner_quality_audit import pavement_top_stats
from diag.road_surface_census import measure_surface


class TestConnectors(unittest.TestCase):
    def doc(self,name='junction_connector_bend'):
        return syn.load_json(os.path.join(syn.FIXTURES_DIR,name+'.json'))

    def test_finished_surfaces_and_reverse_binding(self):
        for name in ('junction_connector_bend','junction_connector_reverse'):
            raw=self.doc(name);site=io_json.site_from_dict(raw);plan=JunctionPlan(site);terrain=syn.junction_terrain_for(raw)
            results=build_all(site,terrain,plan=plan);audit=junction_audit(plan,results)
            self.assertEqual(audit['patches'],1);self.assertEqual(audit['corners'],2)
            self.assertLessEqual(audit['worst_patch_gap_m'],1e-9);self.assertLessEqual(audit['worst_corner_gap_m'],1e-9)
            self.assertLessEqual(audit['patch_overlap_area_m2'],1e-4)
            for d in site.splines:self.assertEqual(measure_surface(site,d.id,terrain,plan)['status'],'passed')
            for result in results.values():
                for mesh in result.edge.values():
                    if mesh is not None:
                        stats=pavement_top_stats(mesh)
                        self.assertEqual(stats['folded_top_triangles'],0);self.assertEqual(stats['inverted_top_triangles'],0)

    def test_legacy_two_arm_disc_stays_unbuilt(self):
        raw=self.doc();raw['junctions'][0]['kind']='disc'
        self.assertFalse(JunctionPlan(io_json.site_from_dict(raw)).arms)

    def test_optional_handle_round_trip_and_scope(self):
        for value in (None,.65,1.):
            raw=self.doc();raw['junctions'][0]['corner_handle_frac']=value
            site=io_json.site_from_dict(raw);self.assertEqual(site.junctions[0].to_dict()['corner_handle_frac'],value)
            plan=JunctionPlan(site);self.assertEqual(plan.config_for('j0')['corner_handle_frac'],.45 if value is None else value)
            self.assertEqual(plan.cfg['corner_handle_frac'],.45)
        raw=self.doc();del raw['junctions'][0]['corner_handle_frac']
        self.assertNotIn('corner_handle_frac',io_json.site_from_dict(raw).junctions[0].to_dict())
        for value in (0.,-1.,1.01,True,'0.5',float('nan')):
            bad=self.doc();bad['junctions'][0]['corner_handle_frac']=value
            with self.assertRaises(S.SchemaError):io_json.site_from_dict(bad)

    def test_invalid_topology_rejected(self):
        for case in ('one','three','duplicate','missing','unbound','off_node','no_road','rail'):
            raw=self.doc();j=raw['junctions'][0]
            if case=='one':j['ends']=j['ends'][:1]
            elif case=='three':j['ends'].append(copy.deepcopy(j['ends'][0]))
            elif case=='duplicate':j['ends'][1]=copy.deepcopy(j['ends'][0])
            elif case=='missing':j['ends'][1]['spline_id']='authored:missing'
            elif case=='unbound':raw['splines'][0]['junction_start']=None
            elif case=='off_node':j['x']+=1.
            elif case=='no_road':raw['splines'][0]['profile_ids']['road']=None
            else:raw['profiles']['road']['road_test_marked']['kind']='rail'
            with self.assertRaises(S.SchemaError,msg=case):io_json.site_from_dict(raw)


if __name__=='__main__':unittest.main()
