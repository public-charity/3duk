import sys
from pathlib import Path
import unittest
import numpy as np
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from streetscape.spline import corner_curve,corner_frames


def reference(a,b,d0,d1,node,cap):
    """Dense de Casteljau reference, independent of the sampler's error bounds."""
    d0=np.r_[np.asarray(d0)/np.linalg.norm(d0),0.]
    d1=np.r_[np.asarray(d1)/np.linalg.norm(d1),0.]
    angle=np.arctan2(d0[0]*d1[1]-d0[1]*d1[0],d0@d1)
    chord=np.linalg.norm((b-a)[:2])
    h=chord/3 if abs(angle)<1e-6 else (4/3)*np.tan(abs(angle)/4)*chord/(2*np.sin(abs(angle)/2))
    h=min(h,cap*min(np.linalg.norm(a[:2]-node),np.linalg.norm(b[:2]-node)))
    t=np.linspace(0,1,8193)[:,None]
    v=np.broadcast_to(np.array([a,a+h*d0,b-h*d1,b])[None,:,:],(len(t),4,3)).copy()
    for n in (3,2,1):v=(1-t[:,:,None])*v[:,:n]+t[:,:,None]*v[:,1:n+1]
    return v[:,0]


class CornerCurveQualityTest(unittest.TestCase):
    def check_curve(self,a,b,d0,d1,node):
        a=np.array(a,dtype=float);b=np.array(b,dtype=float);node=np.array(node,dtype=float)
        p,t=corner_curve(a,b,d0,d1,node,10.,.75)
        np.testing.assert_array_equal(p[0],a);np.testing.assert_array_equal(p[-1],b)
        np.testing.assert_allclose(t[0,:2],np.asarray(d0)/np.linalg.norm(d0),atol=1e-12)
        np.testing.assert_allclose(t[-1,:2],np.asarray(d1)/np.linalg.norm(d1),atol=1e-12)
        self.assertLessEqual(np.linalg.norm(np.diff(p,axis=0),axis=1).max(),1.+1e-9)
        self.assertLessEqual(np.degrees(np.arccos(np.clip(np.sum(t[:-1]*t[1:],axis=1),-1,1))).max(),10.+1e-8)
        dense=reference(a,b,d0,d1,node,.75)
        # Test every reference point against its corresponding parameter interval.
        s=np.linspace(0,len(p)-1,len(dense));i=np.minimum(s.astype(int),len(p)-2)
        v=p[i+1]-p[i];u=np.clip(np.sum((dense-p[i])*v,axis=1)/np.sum(v*v,axis=1),0,1)
        self.assertLessEqual(np.linalg.norm(dense-p[i]-u[:,None]*v,axis=1).max(),.01+1e-9)
        return p

    def test_long_shallow_corner_resolves_internal_turn_and_chord_error(self):
        p=self.check_curve([0,0,51.7],[.13,25.22,51.3],[-.063,.998],[-.311,.950],[-3.9,16.5])
        self.assertGreater(len(p),25)

    def test_parallel_end_tangents_preserve_an_s_bend(self):
        p=self.check_curve([0,0,10],[30,10,11],[1,0],[1,0],[15,5])
        self.assertGreater(np.max(abs(p[:,1]-p[:,0]/3)),.1)

    def test_cusp_or_invalid_profile_fails_with_a_bounded_error(self):
        with self.assertRaisesRegex(ValueError,'cannot meet quality limits'):
            corner_curve([0,0,0],[10,0,0],[-1,0],[-1,0],[5,1],10,.75)
        with self.assertRaisesRegex(ValueError,'invalid corner'):
            corner_curve([0,0,0],[10,0,0],[1,0],[1,0],[5,1],0,.75)

    def test_transported_bank_cannot_flip_the_up_direction_inside_a_bend(self):
        # Same endpoint tangent, with an internal near reversal; world-normal
        # interpolation used to point the frame down around the middle.
        angle=np.radians([0,60,120,170,120,60,0])
        t=np.c_[np.cos(angle),np.sin(angle),np.zeros(len(angle))]
        p=np.c_[np.arange(len(angle)),np.zeros(len(angle)),np.zeros(len(angle))]
        n0=np.array([0,np.cos(.05),np.sin(.05)])
        n1=np.array([0,np.cos(-.08),np.sin(-.08)])
        fr=corner_frames(p,t,n0,n1)
        np.testing.assert_allclose(fr.n[0],n0,atol=1e-12)
        np.testing.assert_allclose(fr.n[-1],n1,atol=1e-12)
        self.assertGreaterEqual(fr.b[:,2].min(),np.cos(.08)-1e-12)
        np.testing.assert_allclose(np.sum(fr.n*t,axis=1),0,atol=1e-12)
        np.testing.assert_allclose(np.linalg.norm(fr.n,axis=1),1,atol=1e-12)


if __name__=='__main__':unittest.main()
