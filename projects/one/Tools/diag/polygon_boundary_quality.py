"""Simple-boundary gate for junction footprint rings, independent of fan winding.

A self-crossing ring can have zero fan signed-area excess while winding twice
around overlapping regions. Check nonadjacent crossings/touches and collinear
backtracking before treating fan area as a coverage certificate.
"""
import numpy as np


def cross(a,b):return a[...,0]*b[...,1]-a[...,1]*b[...,0]


def boundary_quality(points,tolerance_m=1e-7):
    points=np.asarray(points,dtype=float)
    if points.ndim!=2 or points.shape[1]!=2 or not np.isfinite(points).all() or not 0<tolerance_m<=1e-4:
        raise ValueError('finite XY boundary and small positive tolerance required')
    if not 3<=len(points)<=4096:raise ValueError('boundary vertex count must be 3..4096')
    # Consecutive coincident XY vertices can represent vertical section edges.
    # Remove them for the footprint test, retaining nonconsecutive repeats.
    kept=[0]
    for i in range(1,len(points)):
        if np.linalg.norm(points[i]-points[kept[-1]])>tolerance_m:kept.append(i)
    if len(kept)>1 and np.linalg.norm(points[kept[-1]]-points[kept[0]])<=tolerance_m:kept.pop()
    p=points[kept]-points[kept[0]];n=len(p)
    if n<3:return dict(simple=False,reason='degenerate footprint',vertices=n)
    q=np.roll(p,-1,axis=0);d=q-p;length=np.linalg.norm(d,axis=1)
    counts=dict(proper_crossings=0,nonadjacent_touches=0,collinear_overlaps=0);examples=[]
    for i in range(n):
        js=np.arange(i+1,n)
        mask=np.all(np.minimum(p[js],q[js])<=np.maximum(p[i],q[i])+tolerance_m,axis=1)&np.all(np.maximum(p[js],q[js])>=np.minimum(p[i],q[i])-tolerance_m,axis=1)
        for j in js[mask]:
            adjacent=j==i+1 or (i==0 and j==n-1)
            a,b=p[i],q[i];c,e=p[j],q[j]
            ca=float(cross(d[i],c-a)/length[i]);ea=float(cross(d[i],e-a)/length[i])
            ac=float(cross(d[j],a-c)/length[j]);bc=float(cross(d[j],b-c)/length[j])
            kind=None
            if max(abs(ca),abs(ea),abs(ac),abs(bc))<=tolerance_m:
                u=d[i]/length[i];lo,hi=sorted((float((c-a)@u),float((e-a)@u)))
                overlap=min(length[i],hi)-max(0.,lo)
                if overlap>tolerance_m:kind='collinear_overlaps'
                elif not adjacent and overlap>=-tolerance_m:kind='nonadjacent_touches'
            elif not adjacent:
                if ca*ea<0 and ac*bc<0 and min(abs(ca),abs(ea),abs(ac),abs(bc))>tolerance_m:
                    kind='proper_crossings'
                else:
                    for point,start,end,distance in ((c,a,b,ca),(e,a,b,ea),(a,c,e,ac),(b,c,e,bc)):
                        if abs(distance)<=tolerance_m and np.all(point>=np.minimum(start,end)-tolerance_m) and np.all(point<=np.maximum(start,end)+tolerance_m):
                            kind='nonadjacent_touches';break
            if kind:
                counts[kind]+=1
                if len(examples)<12:examples.append(dict(kind=kind,segments=[kept[i],kept[j]]))
    area=float(abs(cross(p,q).sum())*.5)
    return dict(simple=not any(counts.values()) and area>tolerance_m*tolerance_m,vertices=n,
        collapsed_consecutive_xy_vertices=len(points)-n,area_m2=area,**counts,examples=examples)
