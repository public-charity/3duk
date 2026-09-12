import sys, unittest
from pathlib import Path
import numpy as np
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import offshore

class OffshoreTests(unittest.TestCase):
    def test_disabled_is_noop(self):
        self.assertIsNone(offshore.rules({}))
        self.assertEqual(offshore.apply({},None,None,None,None),{})

    def test_blue_plate_gaps_and_real_island(self):
        h=np.full((121,181),-2.,np.float32);h[:,:35]=20
        protected=np.zeros(h.shape,bool);protected[:,:35]=True
        protected[50:61,85:96]=True;h[protected & (np.indices(h.shape)[1]>35)]=4
        h[:,130:]=3.25
        missing=np.zeros(h.shape,bool);missing[:,130:]=True
        sea=np.zeros(h.shape,bool);sea[:,115:]=True
        old=h.copy();core,a,r=offshore.normalise(h,missing,sea,protected,-.6,blend_m=10,smooth_m=8)
        self.assertTrue((h[core]<-.9).all())
        np.testing.assert_array_equal(h[protected],old[protected])
        np.testing.assert_array_equal(h[a==0],old[a==0])
        self.assertTrue(r['inferred_not_surveyed_bathymetry'])
        self.assertTrue(np.isfinite(h).all())

    def test_no_donors_fails_without_mutation(self):
        h=np.ones((20,20),np.float32);old=h.copy();mask=np.ones(h.shape,bool)
        with self.assertRaises(ValueError):offshore.normalise(h,mask,mask,~mask,-.6)
        np.testing.assert_array_equal(h,old)

    def test_native_small_anomaly_is_removed(self):
        h=np.full((80,80),-2.,np.float32);h[41,41]=5
        m=np.zeros(h.shape,bool);sea=np.ones(h.shape,bool)
        core,a,_=offshore.normalise(h,m,sea,m,-.6,smooth_m=8)
        self.assertTrue(core[41,41]);self.assertLess(h[41,41],-.9)

    def test_review_boundary_and_submerged_connection(self):
        from unittest.mock import patch
        def rect(x1,y1,x2,y2):
            return dict(type='Polygon',coordinates=[[[x1,y1],[x2,y1],[x2,y2],[x1,y2],[x1,y1]]])
        spec=dict(review=dict(regions=[rect(60,0,120,80)],protected_land=[rect(0,0,30,80)]))
        h=np.full((81,121),-.5,np.float32);h[:,:30]=20
        cfg=dict(water_level=-.6)
        with patch.object(offshore,'rules',return_value=spec):
            sea,protected,_=offshore.masks(cfg,(-.5,1,0,80.5,0,-1),h)
        self.assertTrue(sea[40,-1]) # exact survey-boundary sample remains covered
        self.assertTrue(sea[40,70]) # flat submerged band is not connected land
        self.assertFalse(protected[40,70])

if __name__=='__main__':unittest.main()
