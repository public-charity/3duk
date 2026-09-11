"""Exact daylight along emitted straight edges over registered LOD-0 terrain.

Split at every x, y and x+y grid line. Terrain and edge height are affine between
these crossings. Include zero-gap roots when comparing positive daylight, since
clamping an affine gap at zero introduces another possible extremum.
"""
import numpy as np


def grid_crossings(segment, px_m, bounds=None):
    segment=np.asarray(segment,dtype=float)
    if segment.shape!=(2,3) or not np.isfinite(segment).all() or not np.isfinite(px_m) or px_m<=0:
        raise ValueError('finite 3D edge and positive grid spacing required')
    p,q=segment/px_m
    cuts=[0.,1.]
    for a,b in ((p[0],q[0]),(p[1],q[1]),(p[0]+p[1],q[0]+q[1])):
        if abs(b-a)<1e-14:continue
        lo,hi=sorted((a,b))
        if hi-lo>4096:raise ValueError('edge exceeds bounded grid budget')
        cuts.extend((k-a)/(b-a) for k in range(int(np.floor(lo))+1,int(np.ceil(hi))) if 0<(k-a)/(b-a)<1)
    if bounds is not None:
        bounds=np.asarray(bounds,dtype=float)
        if bounds.shape!=(4,) or not np.isfinite(bounds).all() or np.any(bounds[2:]<=bounds[:2]):
            raise ValueError('finite positive bounds required')
        for k in (0,1):
            delta=segment[1,k]-segment[0,k]
            if abs(delta)<1e-14:continue
            cuts.extend(t for limit in (bounds[k],bounds[k+2]) if 0<(t:=(limit-segment[0,k])/delta)<1)
    t=np.unique(cuts)
    return segment[0]+t[:,None]*(segment[1]-segment[0])


def constraint_points(segments,terrain,bounds=None,gap_roots=()):
    """Exact edge points for terrain constraints with piecewise gap limits."""
    if terrain.sampling!='landscape_triangulated' or terrain.shift_xy!=(0.,0.) or terrain.xy0!=(0.,0.):
        raise ValueError('unshifted triangulated terrain required')
    if not np.isfinite(gap_roots).all():raise ValueError('finite gap roots required')
    points=[]
    for segment in segments:
        part=grid_crossings(segment,terrain.px_m,bounds)
        gap=part[:,2]-terrain.sample(*part[:,:2].T)
        if not np.isfinite(gap).all():raise ValueError('missing terrain under constraint edge')
        points.extend(part)
        for value in gap_roots:
            signed=gap-value
            for i in np.flatnonzero(signed[:-1]*signed[1:]<0):
                t=signed[i]/(signed[i]-signed[i+1]);points.append(part[i]+t*(part[i+1]-part[i]))
    return np.asarray(points).reshape(-1,3)


def compare_segments(segments,before,after):
    segments=np.asarray(segments,dtype=float)
    if segments.ndim!=3 or segments.shape[1:]!=(2,3) or not len(segments):
        raise ValueError('nonempty emitted edge segments required')
    for terrain in (before,after):
        if terrain.sampling!='landscape_triangulated' or terrain.shift_xy!=(0.,0.) or terrain.xy0!=(0.,0.):
            raise ValueError('unshifted triangulated terrain required')
    if (before.px_m,before.origin_E,before.origin_N)!=(after.px_m,after.origin_E,after.origin_N):
        raise ValueError('terrain registration differs')
    oldmax=newmax=0.;increase=-np.inf;count=0;worst=None
    for segment in segments:
        points=grid_crossings(segment,before.px_m)
        old=points[:,2]-before.sample(*points[:,:2].T)
        new=points[:,2]-after.sample(*points[:,:2].T)
        if not np.isfinite(old).all() or not np.isfinite(new).all():raise ValueError('missing terrain under emitted edge')
        roots=[]
        for gap in (old,new):
            for i in np.flatnonzero(gap[:-1]*gap[1:]<0):
                t=gap[i]/(gap[i]-gap[i+1]);roots.append((old[i]+t*(old[i+1]-old[i]),new[i]+t*(new[i+1]-new[i]),points[i]+t*(points[i+1]-points[i])))
        if roots:
            old=np.r_[old,[r[0] for r in roots]];new=np.r_[new,[r[1] for r in roots]]
            points=np.vstack([points,[r[2] for r in roots]])
        old=np.maximum(old,0);new=np.maximum(new,0);delta=new-old;ix=int(np.argmax(delta))
        if delta[ix]>increase:increase=float(delta[ix]);worst=points[ix].tolist()
        oldmax=max(oldmax,float(old.max()));newmax=max(newmax,float(new.max()));count+=len(points)
    return dict(segments=len(segments),exact_breakpoints=count,before_max_gap_m=oldmax,after_max_gap_m=newmax,
                max_gap_increase_m=increase,worst_increase_edge_point_m=worst)
