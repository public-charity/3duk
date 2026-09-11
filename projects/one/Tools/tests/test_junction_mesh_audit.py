import sys
from pathlib import Path
import unittest
from unittest.mock import patch
import numpy as np

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from diag.junction_mesh_audit import surface_stats,audit_document
from streetscape import io_json
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'blender/tests'))
import synthetic


class JunctionInteriorTest(unittest.TestCase):
    def test_upward_facing_folded_pavement_stays_out_of_terrain_checks(self):
        doc=synthetic.junction_crossroads();doc['junctions'][0]['trim_radius_m']=4.
        site=io_json.site_from_dict(doc);terrain=synthetic.junction_terrain_for(doc)
        with patch('diag.junction_mesh_audit.io_json.load_site',return_value=site), \
             patch('diag.junction_mesh_audit.surface_stats',side_effect=AssertionError('folded pavement must be gated')):
            report=audit_document(Path('folded_pavement.json'),terrain,terrain,.25)
        row=report['results'][0]
        self.assertEqual(report['totals'],{'needs_geometry':1})
        self.assertLessEqual(row['overlap_area_m2'],1e-4)
        self.assertEqual(row['geometry']['inverted_top_triangles'],0)
        self.assertGreater(row['geometry']['folded_top_triangles'],0)
        self.assertNotIn('patch',row)

    def test_overlapping_junction_stays_in_coverage_without_expensive_terrain_checks(self):
        doc=synthetic.junction_doc('overlapping',[0,30,180],widths=[10,10,10],radius_m=1.)
        doc['junctions'][0]['trim_radius_m']=1.
        site=io_json.site_from_dict(doc);terrain=synthetic.junction_terrain_for(doc)
        with patch('diag.junction_mesh_audit.io_json.load_site',return_value=site), \
             patch('diag.junction_mesh_audit.surface_stats',side_effect=AssertionError('contact check should be gated')):
            report=audit_document(Path('overlapping.json'),terrain,terrain,.25)
        self.assertEqual(report['junctions'],1)
        self.assertEqual(report['totals'],{'needs_geometry':1})
        self.assertGreater(report['results'][0]['overlap_area_m2'],1e-4)
        self.assertNotIn('patch',report['results'][0])

    def test_failed_curve_is_an_explicit_junction_result(self):
        doc=synthetic.junction_crossroads();site=io_json.site_from_dict(doc);terrain=synthetic.junction_terrain_for(doc)
        with patch('diag.junction_mesh_audit.io_json.load_site',return_value=site), \
             patch('diag.junction_mesh_audit.build_junction_patch',side_effect=ValueError('unresolved cusp')):
            report=audit_document(Path('cusp.json'),terrain,terrain,.25)
        self.assertEqual(report['totals'],{'needs_geometry':1})
        self.assertEqual(report['results'][0]['reason'],'unresolved cusp')

    def test_interior_penetration_detected_when_vertices_are_clear(self):
        triangle=np.array([[[0,0,1],[2,0,1],[0,2,1]]],dtype=float)
        class Hill:
            def sample(self,x,y):
                return .8+.5*np.exp(-((x-.75)**2+(y-.75)**2)/.08)
        field=Hill()
        self.assertTrue(np.all(field.sample(triangle[0,:,0],triangle[0,:,1])<1))
        measured=surface_stats(triangle,field,.25)
        self.assertGreater(measured["max_penetration_m"],.1)
        self.assertGreater(measured["samples"],3)

    def test_empty_and_missing_ground_cannot_be_measurements(self):
        class Missing:
            def sample(self,x,y):
                return np.full(len(x),np.nan)
        self.assertEqual(surface_stats(np.empty((0,3,3)),Missing())["finite_samples"],0)
        result=surface_stats(np.array([[[0,0,1],[1,0,1],[0,1,1]]]),Missing())
        self.assertEqual(result["finite_samples"],0)
        self.assertEqual(result["missing_ground"],result["samples"])

    def test_covered_corner_is_separate_from_visible_penetration(self):
        triangle=np.array([[[0,0,1],[2,0,1],[0,2,1]]],dtype=float)
        covering=triangle.copy()
        covering[:,:,2]=2
        class Flat:
            def sample(self,x,y):
                return np.full(len(x),1.5)
        result=surface_stats(triangle,Flat(),cover_triangles=covering)
        self.assertEqual(result["max_penetration_m"],0)
        self.assertAlmostEqual(result["raw_max_penetration_m"],.5)
        self.assertAlmostEqual(result["max_road_occlusion_depth_m"],1)


if __name__=="__main__":
    unittest.main()
