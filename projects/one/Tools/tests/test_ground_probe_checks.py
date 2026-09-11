import sys,unittest
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'ue'))
from ground_probe_checks import compare_ground_posts


class GroundProbeChecks(unittest.TestCase):
    def test_compressed_editor_probe_matches_exact_encoded_height(self):
        result=compare_ground_posts([[12148,5370,21.5,21.5]],[21.49969482421875],2)
        self.assertTrue(result['ok']);self.assertEqual(result['encoded_mismatches'],0)
        self.assertAlmostEqual(result['max_error_m'],.00030517578125)

    def test_one_height_unit_and_excess_compression_fail(self):
        point=[[12148,5370,21.5,21.5]]
        self.assertFalse(compare_ground_posts(point,[21.5+1/128],2)['ok'])
        result=compare_ground_posts(point,[21.501],2)
        self.assertEqual(result['encoded_mismatches'],0);self.assertFalse(result['ok'])

    def test_coverage_encoding_registration_and_missing_data_fail(self):
        for points,actual in (([[0,0,21.5,21.5]],[]),([[0.1,0,21.5,21.5]],[21.5]),([[0,0,21.501,21.5]],[21.5]),([[0,0,21.5,21.5]],[float('nan')])):
            with self.assertRaises(ValueError):compare_ground_posts(points,actual,2)


if __name__=='__main__':unittest.main()
