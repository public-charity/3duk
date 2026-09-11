"""Bounded exact LOD-0 terrain finish, allowing small fills as well as cuts.

All supplied surface triangles constrain terrain clearance. Supplied outer-base
points constrain contact. The integer solution minimizes changed height units;
inconsistent surfaces/edges fail instead of silently trading one defect for another.
This numerical helper never writes a product or edits survey inputs.
"""
import copy
import numpy as np
from scipy.optimize import milp, Bounds, LinearConstraint
from scipy.sparse import coo_matrix,hstack
from diag.terrain_contact import contacts, point_weights, clip_triangle, barycentric


def bounded_triangles(triangles, lo, hi):
    """Clip to a rectangle without changing any affine triangle height."""
    x,y=lo; X,Y=hi
    clips=(np.array([[x,y],[X,y],[X,Y]]),np.array([[x,y],[X,Y],[x,Y]]))
    result=[]
    for tri in triangles:
        if np.any(tri[:,:2].min(axis=0)>hi) or np.any(tri[:,:2].max(axis=0)<lo): continue
        for clip in clips:
            poly=clip_triangle(tri[:,:2],clip)
            if len(poly)<3: continue
            v=np.c_[poly,barycentric(tri[:,:2],poly)@tri[:,2]]
            result.extend(np.array([v[0],v[i],v[i+1]]) for i in range(1,len(v)-1))
    return np.array(result).reshape(-1,3,3)


def apply_adjustments(terrain, changes):
    """Copy touched tiles and update every shared post. Inputs remain unchanged."""
    result=copy.copy(terrain); result.tiles=dict(terrain.tiles)
    q=terrain.res-1; written=set(); originals={}
    for (i,j),tile in terrain.tiles.items():
        selected=[(x-i*q,(j+1)*q-y,z,(x,y)) for (x,y),z in changes.items()
                  if i*q<=x<=(i+1)*q and j*q<=y<=(j+1)*q]
        if not selected: continue
        updated=tile.copy()
        for col,row,z,key in selected:
            old=float(tile[row,col])
            if not np.isfinite([old,z]).all() or (key in originals and originals[key]!=old):
                raise ValueError('missing or inconsistent seam terrain')
            originals[key]=old; updated[row,col]=z; written.add(key)
        result.tiles[(i,j)]=updated
    if written!=set(changes): raise ValueError('adjusted post outside terrain coverage')
    return result


class TerrainFinishInfeasible(ValueError):
    def __init__(self,message,diagnostic=None):
        super().__init__(message)
        self.diagnostic=diagnostic or {}


def minimum_adjustment(triangles, terrain, bounds, edge_points, max_cut_m=.5,
                       max_raise_m=.5, clearance_m=.01, edge_gap_m=.005,
                       relaxable_edges=None,diagnose_failure=False):
    bounds=np.asarray(bounds,dtype=float)
    limits=np.array([max_cut_m,max_raise_m,clearance_m,edge_gap_m])
    if bounds.shape!=(4,) or not np.isfinite(bounds).all() or np.any(bounds[2:]-bounds[:2]<=0) or np.any(bounds[2:]-bounds[:2]>64):
        raise ValueError('terrain finish rectangle must be finite, positive and <=64 m')
    if not np.isfinite(limits).all() or np.any(limits<0) or not 0<=clearance_m<max_cut_m:
        raise ValueError('invalid terrain finish limits')
    px=terrain.px_m
    lo=np.ceil(bounds[:2]/px).astype(int); hi=np.floor(bounds[2:]/px).astype(int)
    keys=[(x,y) for x in range(lo[0],hi[0]+1) for y in range(lo[1],hi[1]+1)]
    if not keys: raise ValueError('terrain finish rectangle contains no posts')
    index={key:i for i,key in enumerate(keys)}; n=len(keys)
    xy=np.asarray(keys)*px; old=terrain.sample(*xy.T)
    if not np.isfinite(old).all(): raise ValueError('missing terrain in finish rectangle')
    enc=terrain.manifest.get('heightmap',{}).get('z_encoding',{})
    unit=float(enc.get('per_unit',128.)); offset=float(enc.get('offset',32768.))
    if not np.isfinite([unit,offset]).all() or unit<=0: raise ValueError('invalid height encoding')
    encoded=old*unit+offset
    if np.max(abs(encoded-np.round(encoded)))>1e-5: raise ValueError('terrain is not quantized to its encoding')
    rows=[]; lower=[]; upper=[]
    def add(row,l,u):
        rows.append(row); lower.append(l); upper.append(u)
    count=0
    near=bounded_triangles(triangles,(lo-1)*px,(hi+1)*px)
    for ks,weights,z in contacts(near,terrain):
        p=np.asarray(ks)*px; ground=terrain.sample(*p.T)
        if not np.isfinite(ground).all(): raise ValueError('missing contact terrain')
        for w,top in zip(weights,z):
            row={index[k]:float(v/unit) for k,v in zip(ks,w) if k in index and v>1e-12}
            if not row: continue
            add(row,-np.inf,float(top-clearance_m-w@ground)); count+=1
    if not count: raise ValueError('no surface coverage for terrain finish')
    edge_count=0;relax_rows=[]
    edge_points=np.asarray(edge_points).reshape(-1,3)
    relaxable=np.ones(len(edge_points),dtype=bool) if relaxable_edges is None else np.asarray(relaxable_edges,dtype=bool)
    if relaxable.shape!=(len(edge_points),):raise ValueError('invalid relaxable edge mask')
    for point,relax in zip(edge_points,relaxable):
        ks,w=point_weights(point[:2],px)
        row={index[k]:float(v/unit) for k,v in zip(ks,w) if k in index and v>1e-12}
        if not row: continue
        ground=float(terrain.sample(*point[:2]))
        if not np.isfinite(ground): raise ValueError('missing terrain under finish edge')
        if relax:relax_rows.append((len(rows),point.tolist()))
        add(row,float(point[2]-edge_gap_m-ground),np.inf); edge_count+=1
    if not edge_count: raise ValueError('no protected edge contact')
    # Absolute encoded change auxiliaries keep the objective linear and exact.
    for i in range(n):
        add({i:1.,n+i:-1.},-np.inf,0.)
        add({i:-1.,n+i:-1.},-np.inf,0.)
    ri=[];ci=[];v=[]
    for r,row in enumerate(rows):
        for c,value in row.items():ri.append(r);ci.append(c);v.append(value)
    matrix=coo_matrix((v,(ri,ci)),shape=(len(rows),2*n)).tocsr()
    low=np.r_[np.maximum(-np.floor(max_cut_m*unit),-np.round(encoded)),np.zeros(n)]
    high=np.r_[np.minimum(np.floor(max_raise_m*unit),65535-np.round(encoded)),np.full(n,np.inf)]
    result=milp(np.r_[np.zeros(n),np.ones(n)],integrality=np.r_[np.ones(n),np.zeros(n)],
        bounds=Bounds(low,high),constraints=LinearConstraint(matrix,lower,upper),options={'time_limit':20.})
    if not result.success:
        diagnostic={}
        if diagnose_failure and relax_rows:
            # Quantify the irreducible gap, keeping all surface ceilings and
            # neighbouring-edge protection hard. This is evidence, not a candidate.
            extra=coo_matrix((np.ones(len(relax_rows)),([r for r,_ in relax_rows],np.zeros(len(relax_rows),dtype=int))),
                            shape=(len(rows),1)).tocsr()
            relaxed=milp(np.r_[np.zeros(n),np.full(n,1e-6),1.],integrality=np.r_[np.ones(n),np.zeros(n+1)],
                bounds=Bounds(np.r_[low,0.],np.r_[high,1.]),
                constraints=LinearConstraint(hstack([matrix,extra],format='csr'),lower,upper),options={'time_limit':20.})
            diagnostic.update(status='complete' if relaxed.success else 'failed',message=relaxed.message)
            if relaxed.success:
                value=matrix@relaxed.x[:-1]
                bottlenecks=sorted([(float(lower[r]-value[r]),p) for r,p in relax_rows],reverse=True)
                diagnostic.update(minimum_extra_gap_m=float(relaxed.x[-1]),
                    achievable_max_contact_gap_m=float(edge_gap_m+relaxed.x[-1]),
                    active_gap_points=[dict(extra_gap_m=d,point_m=p) for d,p in bottlenecks[:5]])
        raise TerrainFinishInfeasible('terrain finish cannot satisfy all surface and edge constraints: '+result.message,diagnostic)
    steps=np.round(result.x[:n]); solved=np.r_[steps,abs(steps)]
    value=matrix@solved
    if np.any(value<np.array(lower)-1e-7) or np.any(value>np.array(upper)+1e-7):
        raise ValueError('integer terrain finish failed exact constraint readback')
    changes={k:float((round(encoded[i])+steps[i]-offset)/unit) for k,i in index.items() if steps[i]!=0}
    return changes,dict(surface_contact_vertices=count,edge_points=edge_count,variables=n,changed_posts=len(changes),
        raised_posts=int(np.sum(steps>0)),lowered_posts=int(np.sum(steps<0)),
        max_raise_m=float(max(0,steps.max())/unit),max_cut_m=float(max(0,-steps.min())/unit),
        sum_absolute_adjustment_m=float(abs(steps).sum()/unit))
