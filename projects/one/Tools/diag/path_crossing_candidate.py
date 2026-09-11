"""Infer a small downward footway profile beneath intersecting vehicle road surfaces.

The centreline, survey and vehicle roads stay fixed. Exact triangle intersections
constrain the footway profile, with bounded lowering and blend gradient. Endpoint
heights/banks are preserved; an infeasible isolated correction needs a connected
network model. Output is a complete source document candidate, never production.
"""
import argparse
import copy
import json
from pathlib import Path
import sys
import time

import numpy as np
from scipy.optimize import linprog, minimize, LinearConstraint, Bounds
from scipy.sparse import coo_matrix

TOOLS=Path(__file__).resolve().parents[1]
REPO=TOOLS.parents[2]
sys.path.insert(0,str(TOOLS))
sys.path.insert(0,str(TOOLS/"blender"))
from phase1_qc import atomic_json, content_identity, sha256
from streetscape import io_json
from streetscape.mesh import MeshBuffer
from streetscape.road import build_road, build_junction_patch
from streetscape.spline import JunctionPlan, Spline
from streetscape.terrain import Heightfield
from diag.driving_surface_audit import PATHS, top_triangles, in_bounds
from diag.terrain_contact import clip_triangle, barycentric, cross2
from diag.structure_inventory import read_osm_way_tags
from diag.corner_quality_audit import audit_document


def lane_width_candidate(raw, ids, tags, tuning):
    """Use existing project lane assumptions for explicitly tagged one-way arms.

    This is an inference, not surveyed width. Fixed raw lane evidence, unchanged
    centreline, and junctions or jointly modelled continuations at both endpoints
    are required. Preflight the complete selection before mutating the candidate.
    """
    if len(set(ids))!=len(ids):raise ValueError("duplicate width pilot ID")
    definitions={d["id"]:d for d in raw["splines"]}
    selected=set(ids);prepared={}
    for sid in ids:
        if sid not in definitions:raise ValueError("unknown width pilot ID: "+sid)
        definition=definitions[sid]
        evidence=tags[definition["source"]["osm_id"]]
        count=evidence.get("lanes","")
        if evidence.get("oneway")!="yes" or not count.isdigit() or not 1<=int(count)<=4 or "width" in evidence:
            raise ValueError("width pilot requires unambiguous one-way lane count and no explicit width: "+sid)
        n=int(count); lane=float(tuning["lane_width_m"]); margin=float(tuning["lane_margin_m"])
        quantum=float(tuning["width_quantum_m"])
        width=round((n*lane+margin)/quantum)*quantum
        prepared[sid]=(n,lane,margin,width,evidence)
    for sid in ids:
        definition=definitions[sid]
        for end,point,link,other_end,other_point,back in (
            ("start",0,"continues_from","end",-1,"continues_to"),
            ("end",-1,"continues_to","start",0,"continues_from")):
            if definition.get("junction_"+end):continue
            neighbour=definition.get(link)
            if neighbour not in selected:
                raise ValueError("width pilot requires junctions or jointly selected continuations at both ends: "+sid)
            other=definitions[neighbour]
            if other.get(back)!=sid or other.get("junction_"+other_end):
                raise ValueError("width continuation is not reciprocal: "+sid)
            a,b=definition["points"][point],other["points"][other_point]
            if np.hypot(a["x"]-b["x"],a["y"]-b["y"])>1e-3:
                raise ValueError("width continuation endpoints disagree: "+sid)
            if abs(prepared[sid][3]-prepared[neighbour][3])>1e-9:
                raise ValueError("width continuation needs a width transition: "+sid)
    rows=[]
    for sid in ids:
        definition=definitions[sid]
        n,lane,margin,width,evidence=prepared[sid]
        original=[float(p["width_m"]) for p in definition["points"]]
        profile=copy.deepcopy(raw["profiles"]["road"][definition["profile_ids"]["road"]])
        profile.update(lanes=n,lane_widths_m=[lane]*n,width_m=width)
        if n==1: profile["markings"]=[]
        profile_id="phase1_lane_"+sid.replace(":","_")
        raw["profiles"]["road"][profile_id]=profile
        definition["profile_ids"]["road"]=profile_id
        for p in definition["points"]: p["width_m"]=width
        model=dict(id=sid,kind="inferred_from_explicit_lanes",lanes=n,lane_width_m=lane,margin_m=margin,
                   width_m=width,old_width_range_m=[min(original),max(original)],raw_osm_tags=evidence)
        definition["_phase1_width_model"]=model
        rows.append(model)
    return rows


def overlap_constraints(path_mesh, road_triangles):
    """Yield (path vertex indices, barycentric weights, required lowering).

    On each clipped intersection polygon both surfaces are affine. Its vertices
    suffice to bound the entire overlap, including narrow sub-station crossings.
    """
    for face in path_mesh.f[path_mesh.group_mask_tris(exact="road")]:
        triangle=path_mesh.v[face]
        normal=np.cross(triangle[1]-triangle[0],triangle[2]-triangle[0])
        if normal[2] <= .5*np.linalg.norm(normal):
            continue
        near=in_bounds(road_triangles,triangle[:,:2].min(axis=0),triangle[:,:2].max(axis=0))
        for road in near:
            polygon=clip_triangle(triangle[:,:2],road[:,:2])
            if len(polygon)<3:
                continue
            area=abs(np.sum(cross2(polygon-polygon[0],np.roll(polygon,-1,axis=0)-polygon[0])))*.5
            if area<1e-9:
                continue
            weights=barycentric(triangle[:,:2],polygon)
            road_z=barycentric(road[:,:2],polygon)@road[:,2]
            yield face,weights,weights@triangle[:,2]-road_z


def fit_lowering(stations, mesh, road, max_lower=.5, max_blend_grade=.10, clearance=.01, reference_z=None,
                 fairing_length_m=2.):
    indices=np.searchsorted(stations,mesh.vs)
    if np.any(indices>=len(stations)) or not np.allclose(stations[indices],mesh.vs,rtol=0,atol=1e-8):
        raise ValueError("path vertex is not on a shared spline station")
    rows,cols,values,rhs=[],[],[],[]
    def constraint(idx,coef,bound):
        row=len(rhs)
        rows.extend([row]*len(idx)); cols.extend(idx); values.extend(coef); rhs.append(bound)
    contacts=0
    worst=-np.inf
    for face,weights,rise in overlap_constraints(mesh,road):
        for w,r in zip(weights,rise):
            constraint(indices[face],-w,-float(r)-clearance)
        contacts+=len(rise)
        worst=max(worst,float(rise.max()))
    if contacts==0:
        raise ValueError("path has no actual vehicle-road triangle overlap")
    for i,ds in enumerate(np.diff(stations)):
        constraint([i,i+1],[1.,-1.],max_blend_grade*ds)
        constraint([i,i+1],[-1.,1.],max_blend_grade*ds)
    weights=np.empty(len(stations))
    weights[1:-1]=(stations[2:]-stations[:-2])*.5
    weights[0]=(stations[1]-stations[0])*.5
    weights[-1]=(stations[-1]-stations[-2])*.5
    bounds=[(0,max_lower)]*len(stations)
    bounds[0]=bounds[-1]=(0,0)
    matrix=coo_matrix((values,(rows,cols)),shape=(len(rhs),len(stations))).tocsr()
    result=linprog(weights,A_ub=matrix,b_ub=rhs,bounds=bounds,method="highs")
    if not result.success:
        relaxed=linprog(weights,A_ub=matrix,b_ub=rhs,bounds=(0,max_lower),method="highs")
        diagnostic=("; diagnostic only: freeing endpoints requires lowering start %.6f m / end %.6f m" %
                    (relaxed.x[0],relaxed.x[-1])) if relaxed.success else "; still infeasible with free endpoints"
        raise ValueError("isolated path correction infeasible with fixed endpoints and bounded blend: "+result.message+diagnostic)
    delta=result.x
    fair_stats={}
    if reference_z is not None:
        # Minimum lowering alone introduces peaks in every unconstrained gap.
        # Fair the actual height curve under the SAME affine overlap constraints.
        # Integrated squared curvature and displacement balance at a physical
        # length scale, instead of smoothing an entire crossing into a deep valley.
        z=np.asarray(reference_z,dtype=float)
        if z.shape!=stations.shape or not np.isfinite(z).all():
            raise ValueError("invalid reference height for crossing fairing")
        ds=np.diff(stations)
        curvature=np.zeros((len(stations)-2,len(stations)))
        for k,(a,b) in enumerate(zip(ds[:-1],ds[1:])):
            curvature[k,k:k+3]=2/(a+b)*np.array([1/a,-1/a-1/b,1/b])
        cw=(ds[:-1]+ds[1:])*.5
        bend=curvature.T@(cw[:,None]*curvature)
        if not np.isfinite(fairing_length_m) or fairing_length_m<=0:
            raise ValueError("invalid crossing fairing length")
        hessian=bend+fairing_length_m**-4*np.diag(weights)
        linear=bend@z
        objective=lambda d: .5*d@hessian@d-linear@d
        gradient=lambda d: hessian@d-linear
        fair=minimize(objective,delta,jac=gradient,method="SLSQP",
            bounds=Bounds(*np.array(bounds).T),
            constraints=[LinearConstraint(matrix.toarray(),-np.inf,np.array(rhs))],
            options=dict(ftol=1e-12,maxiter=300))
        if not fair.success or np.max(matrix@fair.x-np.array(rhs))>1e-7:
            raise ValueError("constrained crossing fairing failed: "+fair.message)
        delta=fair.x
        fair_stats=dict(model="integrated squared profile curvature plus displacement / fairing_length^4",
            fairing_length_m=fairing_length_m,
            iterations=int(fair.nit),before_bending_energy=float((curvature@(z-result.x))@(cw*(curvature@(z-result.x)))),
            after_bending_energy=float((curvature@(z-delta))@(cw*(curvature@(z-delta)))),
            max_profile_grade=float(np.max(np.abs(np.diff(z-delta)/ds))))
    return delta,dict(contact_vertices=contacts,before_max_rise_m=worst,max_lowering_m=float(delta.max()),
                         max_blend_grade=float(np.max(np.abs(np.diff(delta)/np.diff(stations)))),fairing=fair_stats)


def main():
    ap=argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--document",required=True)
    ap.add_argument("--path-id",required=True)
    ap.add_argument("--lane-width-road",action="append",default=[],help="explicit one-way approach ID to remodel with existing project lane-width tuning")
    ap.add_argument("--junction-trim",action="append",default=[],help="bounded reviewed trim override, JUNCTION_ID=METRES; topology and coordinates stay fixed")
    ap.add_argument("--out",type=Path,default=TOOLS.parent/"Saved/Phase1/path_crossing_candidates")
    args=ap.parse_args()
    source=REPO/"data/thanet/out/unreal/streetscape"
    path=(source/args.document).resolve()
    if path.parent!=source.resolve():
        raise ValueError("document must be a source basename")
    raw=json.loads(path.read_text())
    original_osm=REPO/"data/thanet/raw/thanet.osm"
    osm_ids={d["source"]["osm_id"] for d in raw["splines"] if d["id"] in set(args.lane_width_road)|{args.path_id}}
    tags=read_osm_way_tags(original_osm,osm_ids)
    path_osm=next(d["source"]["osm_id"] for d in raw["splines"] if d["id"]==args.path_id)
    if tags[path_osm].get("footway")!="crossing":
        raise ValueError("original OSM source must explicitly identify a crossing footway")
    tuning_path=REPO/"sources/config/tuning.json"
    tuning=json.loads(tuning_path.read_text())["roads"]
    width_models=lane_width_candidate(raw,args.lane_width_road,tags,tuning)
    trim_models=[];trim_seen=set()
    for value in args.junction_trim:
        jid,metres=value.rsplit("=",1);radius=float(metres)
        if jid in trim_seen or not np.isfinite(radius) or not 0<radius<=32:
            raise ValueError("junction trim must be unique and within (0,32] metres")
        junction=next((j for j in raw.get("junctions",[]) if j["id"]==jid),None)
        if junction is None:raise ValueError("unknown trim junction: "+jid)
        trim_seen.add(jid)
        trim_models.append(dict(id=jid,old_trim_radius_m=junction.get("trim_radius_m"),trim_radius_m=radius,
            kind="reviewed geometry trim; fixed junction topology and survey registration"))
        junction["trim_radius_m"]=radius
    definition=next(s for s in raw["splines"] if s["id"]==args.path_id)
    if definition.get("elevation_profile"):
        raise ValueError("path already has an explicit elevation model")
    if definition["source"]["cls"] not in PATHS-{"steps"} or any((definition.get("flags") or {}).get(k) for k in ("bridge","tunnel")):
        raise ValueError("only nonstructure, non-stair paths may use this inference")
    xy=np.array([[p["x"],p["y"]] for p in definition["points"]])
    lo,hi=xy.min(axis=0)-32,xy.max(axis=0)+32
    if np.any(hi-lo>256):
        raise ValueError("path is too long for the bounded crossing pilot")
    # A boundary crossing needs adjacent-document modelling; do not silently omit it.
    tile=raw["_tile"]["bounds_local"]
    if np.any(lo<tile[:2]) or np.any(hi>tile[2:]):
        raise ValueError("path neighbourhood reaches a document boundary")
    survey_dir=REPO/"data/thanet/out/unreal/landscape"
    inputs=[path,original_osm,tuning_path,Path(__file__),TOOLS/"phase1_qc.py",TOOLS/"diag/driving_surface_audit.py",TOOLS/"diag/terrain_contact.py",TOOLS/"diag/structure_inventory.py",TOOLS/"diag/corner_quality_audit.py",TOOLS/"diag/bridge_crossing_audit.py"]
    inputs+=list((TOOLS/"blender/streetscape").glob("*.py"))
    inputs+=[survey_dir/"landscape_manifest.json"]+list(survey_dir.glob("hm_*.r16"))+list(survey_dir.glob("clip_*.r8"))
    config=dict(document=args.document,path=args.path_id,lane_width_models=width_models,junction_trim_models=trim_models,max_lower_m=.5,max_blend_grade=.10,clearance_m=.01,fairing_length_m=2.,
                model="inferred smooth crossing height below existing vehicle mesh; unchanged endpoint heights and bank")
    identity,hashes=content_identity(inputs,config)
    root=args.out/identity[:20]
    root.mkdir(parents=True,exist_ok=True)
    report=dict(status="running",phase1_accepted=False,config=config,fingerprint=identity,input_sha256=hashes)
    atomic_json(root/"report.json",report)
    started=time.time()
    try:
        survey=Heightfield.from_landscape_dir(str(survey_dir)); survey.sampling="landscape_triangulated"
        site=io_json.site_from_dict(raw); plan=JunctionPlan(site)
        if (site.origin.E,site.origin.N)!=(survey.origin_E,survey.origin_N):
            raise ValueError("document/terrain origin mismatch")
        junctions=[j for j in site.junctions if np.all(np.array([j.x,j.y])+32>=lo) and np.all(np.array([j.x,j.y])-32<=hi)]
        ids={a.spline_id for j in junctions for a in plan.arms.get(j.id,[])} | {args.path_id}
        for d in site.splines:
            if d.source.layer!="roads" or d.source.cls in PATHS: continue
            p=np.array([[p.x,p.y] for p in d.points])
            if np.all(p.max(axis=0)+32>=lo) and np.all(p.min(axis=0)-32<=hi): ids.add(d.id)
        splines={sid:Spline(site.spline(sid),site,survey,trim=plan.trim_for(sid)) for sid in ids}
        sp=splines[args.path_id]
        mesh,_=build_road(sp)
        roads=[]
        for sid,built in splines.items():
            d=site.spline(sid)
            if d.source.cls in PATHS or (d.flags and (d.flags.bridge or d.flags.tunnel)): continue
            road,_=build_road(built)
            top=in_bounds(top_triangles(road,road.group_mask_tris(exact="road")),lo,hi)
            if len(top): roads.append(top)
        for j in junctions:
            if j.id not in plan.arms: continue
            if not any(site.spline(a.spline_id).source.cls not in PATHS for a in plan.arms[j.id]): continue
            if any(site.spline(a.spline_id).flags and (site.spline(a.spline_id).flags.bridge or site.spline(a.spline_id).flags.tunnel) for a in plan.arms[j.id]): continue
            road=MeshBuffer()
            if not build_junction_patch(plan,j.id,splines,road)["built"]: raise ValueError("junction build failed")
            top=in_bounds(top_triangles(road),lo,hi)
            if len(top): roads.append(top)
        road=np.concatenate(roads)
        delta,stats=fit_lowering(sp.s,mesh,road,reference_z=sp.z_ref)
        candidate=copy.deepcopy(raw)
        target=next(d for d in candidate["splines"] if d["id"]==args.path_id)
        target["elevation_profile"]=[dict(s_m=float(s),z_m=float(z-d),bank_deg=float(b)) for s,z,d,b in zip(sp.s,sp.z_ref,delta,sp.bank_deg)]
        target["_phase1_crossing_model"]={**config,"source_sha256":sha256(path),"source_profile_sha256":identity}
        candidate_site=io_json.site_from_dict(candidate)
        built=Spline(candidate_site.spline(args.path_id),candidate_site,survey,trim=plan.trim_for(args.path_id))
        after,_=build_road(built)
        worst=max(float(rise.max()) for _,_,rise in overlap_constraints(after,road))
        if worst>-.0099:
            raise ValueError("actual rebuilt path does not remain below vehicle road: "+str(worst))
        if not np.allclose(built.z_ref[[0,-1]],sp.z_ref[[0,-1]],rtol=0,atol=1e-8):
            raise ValueError("path endpoints moved")
        atomic_json(root/path.name,candidate)
        before_corners=audit_document(path,survey)
        after_corners=audit_document(root/path.name,survey)
        atomic_json(root/'junctions_before.json',before_corners)
        atomic_json(root/'junctions_after.json',after_corners)
        before_by_id={r['id']:r for r in before_corners['results']}
        if set(before_by_id)!={r['id'] for r in after_corners['results']}:
            raise ValueError('candidate lost junction coverage')
        for row in after_corners['results']:
            old=before_by_id[row['id']]
            if (old['status']=='passed' and row['status']!='passed') or row['status']=='needs_geometry':
                raise ValueError('candidate junction quality regressed: '+row['id'])
            if row.get('patch_overlap_area_m2',0)>old.get('patch_overlap_area_m2',0)+1e-4:
                raise ValueError('candidate junction overlap increased: '+row['id'])
            if row.get('pavement',{}).get('inverted_area_m2',0)>old.get('pavement',{}).get('inverted_area_m2',0)+1e-6:
                raise ValueError('candidate pavement fold increased: '+row['id'])
        if content_identity(inputs,config)[0]!=identity:raise ValueError('crossing candidate inputs changed during run')
        report.update(status="complete",stats=stats,after_max_rise_m=worst,candidate_document=str(root/path.name),
                      junction_quality=dict(before=before_corners['totals'],after=after_corners['totals'],regressions=0),
                      candidate_sha256=sha256(root/path.name),seconds=round(time.time()-started,3),
                      next_gate="reconform candidate ground, contact/support checks, native preview; not accepted")
    except BaseException as exc:
        report.update(status="failed",error=str(exc)); raise
    finally:
        atomic_json(root/"report.json",report)
    print(json.dumps(report,indent=2))


if __name__=="__main__": main()
