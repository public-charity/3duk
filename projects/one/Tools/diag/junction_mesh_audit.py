#!/usr/bin/env python3
"""Resumable checks of emitted junction patch and upper kerb/pavement corner triangles.

The road-fusion gate measures untrimmed ribbon envelopes. This complementary gate
builds the actual junction mesh from trimmed arms and samples triangle interiors,
so a clear row of spline stations cannot conceal ground through a junction centre.
"""
import argparse
from collections import Counter
import json
from pathlib import Path
import sys
import time

import numpy as np

TOOLS=Path(__file__).resolve().parents[1]
REPO=TOOLS.parents[2]
sys.path.insert(0,str(TOOLS))
sys.path.insert(0,str(TOOLS/"blender"))
from phase1_qc import atomic_json, content_identity, run_lock, sample_documents, sha256
from streetscape import io_json
from streetscape.mesh import MeshBuffer
from streetscape.road import build_junction_patch, build_road
from streetscape.edge import build_junction_corners
from streetscape.spline import JunctionPlan, Spline
from streetscape.terrain import Heightfield
from diag.bridge_crossing_audit import highest_triangle_z
from diag.corner_quality_audit import pavement_top_stats


def surface_stats(triangles, terrain, spacing=.25, cover_triangles=None):
    """Barycentric lattice including vertices/edges; longest triangle edge spacing <= spacing."""
    if len(triangles)==0:
        return {"triangles":0,"samples":0,"finite_samples":0,"missing_ground":0,"max_penetration_m":None}
    points=[]
    for tri in triangles:
        if not np.isfinite(tri).all():
            raise ValueError("nonfinite mesh triangle")
        n=max(1,int(np.ceil(np.max(np.linalg.norm(tri-np.roll(tri,1,axis=0),axis=1))/spacing)))
        if n>256:
            raise ValueError("oversized triangle exceeds bounded sampling budget")
        a,b=np.triu_indices(n+1)
        u=a/n
        v=(b-a)/n
        points.append(tri[0]+u[:,None]*(tri[1]-tri[0])+v[:,None]*(tri[2]-tri[0]))
    points=np.concatenate(points)
    ground=terrain.sample(points[:,0],points[:,1])
    visible_z=points[:,2].copy()
    occlusion=np.zeros(len(points))
    if cover_triangles is not None and len(cover_triangles):
        lo,hi=points[:,:2].min(axis=0),points[:,:2].max(axis=0)
        near=np.all(cover_triangles[:,:,:2].max(axis=1)>=lo,axis=1)&np.all(cover_triangles[:,:,:2].min(axis=1)<=hi,axis=1)
        cover=highest_triangle_z(cover_triangles[near],points[:,:2])
        covered=np.isfinite(cover)&(cover>visible_z)
        occlusion[covered]=cover[covered]-visible_z[covered]
        visible_z[covered]=cover[covered]
    finite=np.isfinite(ground)
    if not finite.any():
        return {"triangles":len(triangles),"samples":len(points),"finite_samples":0,
                "missing_ground":len(points),"max_penetration_m":None}
    raw_gap=ground-points[:,2]
    gap=ground-visible_z
    j=int(np.argmax(np.where(finite,gap,-np.inf)))
    return {"triangles":len(triangles),"samples":len(points),"finite_samples":int(finite.sum()),
        "missing_ground":int((~finite).sum()),"max_penetration_m":float(max(0,gap[j])),
        "raw_max_penetration_m":float(max(0,np.max(raw_gap[finite]))),
        "samples_covered_by_road":int(np.sum(occlusion>1e-6)),"max_road_occlusion_depth_m":float(occlusion.max()),
        "minimum_clearance_m":float(-gap[j]),"worst_mesh_xyz_m":points[j].tolist(),"worst_ground_z_m":float(ground[j])}


def audit_document(path, survey, terrain, spacing):
    site=io_json.load_site(str(path))
    plan=JunctionPlan(site)
    arms={};arm_errors={}
    for sid in sorted({a.spline_id for values in plan.arms.values() for a in values}):
        definition=site.spline(sid)
        try:arms[sid]=Spline(definition,site,survey,trim=plan.trim_for(sid))
        except ValueError as exc:arm_errors[sid]=str(exc)
    rows=[]
    arm_meshes={}
    for junction in site.junctions:
        jid=junction.id
        row={"id":jid,"xy_m":[junction.x,junction.y]}
        if jid not in plan.arms:
            row.update(status="not_planned",reason="kind or fewer than three usable arms")
        elif any(site.spline(a.spline_id).flags and
                 (site.spline(a.spline_id).flags.bridge or site.spline(a.spline_id).flags.tunnel)
                 for a in plan.arms[jid]):
            row.update(status="needs_structure_model",arms=[a.spline_id for a in plan.arms[jid]])
        elif any(a.spline_id in arm_errors for a in plan.arms[jid]):
            row.update(status="needs_geometry",reason="arm build failed",
                errors={a.spline_id:arm_errors[a.spline_id] for a in plan.arms[jid] if a.spline_id in arm_errors})
        else:
            road,edge=MeshBuffer(),MeshBuffer()
            try:
                patch=build_junction_patch(plan,jid,arms,road)
                corner=build_junction_corners(plan,jid,arms,edge)
            except ValueError as exc:
                row.update(status="needs_geometry",reason=str(exc));rows.append(row);continue
            if not patch["built"]:
                row.update(status="needs_geometry",reason="planned patch did not build");rows.append(row);continue
            geometry=pavement_top_stats(edge)
            row.update(patch_area_m2=patch["area_m2"],overlap_area_m2=patch["overlap_area_m2"],
                       corner_build=corner,geometry=geometry)
            # No expensive terrain pass can make an overlapping or folded surface
            # acceptable. Retain the junction in coverage and fix its geometry first.
            if (patch["overlap_area_m2"]>1e-4 or geometry["inverted_top_triangles"]
                    or geometry["folded_top_triangles"] or corner["skipped_incompatible"]):
                row.update(status="needs_geometry",reason="patch overlap, folded/inverted pavement or incompatible corner section")
                rows.append(row);continue
            top=np.empty((0,3,3))
            if len(edge.f):
                triangles=edge.v[edge.f]
                normal=np.cross(triangles[:,1]-triangles[:,0],triangles[:,2]-triangles[:,0])
                # Exclude the intentional road tuck and block skirts. The lip/top sits at h >= 0.
                keep=(np.min(edge.vh[edge.f],axis=1)>=-1e-8)&(normal[:,2]>.5*np.linalg.norm(normal,axis=1))
                top=triangles[keep]
            covers=[road.v[road.f]]
            for arm in plan.arms[jid]:
                if arm.spline_id not in arm_meshes:
                    mesh,_=build_road(arms[arm.spline_id])
                    arm_meshes[arm.spline_id]=mesh.v[mesh.f[mesh.group_mask_tris(exact="road")]]
                covers.append(arm_meshes[arm.spline_id])
            cover_triangles=np.concatenate(covers)
            row.update(patch=surface_stats(road.v[road.f],terrain,spacing,cover_triangles),
                       corner_top=surface_stats(top,terrain,spacing,cover_triangles),corner_build=corner,
                       patch_area_m2=patch["area_m2"],overlap_area_m2=patch["overlap_area_m2"])
            measured=[row["patch"]]+([row["corner_top"]] if len(top) else [])
            bad=any(r["finite_samples"]==0 or r["missing_ground"] or r["max_penetration_m"]>.005 for r in measured)
            # Deeply covered pavement is a modelling/overlap review, not visible terrain penetration.
            hidden=len(top) and row["corner_top"].get("max_road_occlusion_depth_m",0)>.125
            row["status"]="failed" if bad else "overlap_review" if hidden else "passed"
        rows.append(row)
    return {"document":path.name,"junctions":len(site.junctions),"plan":plan.stats,"results":rows,
            "totals":dict(Counter(r["status"] for r in rows))}


def main():
    ap=argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--scope",choices=("sample","full"),default="sample")
    ap.add_argument("--max-docs",type=int,default=4)
    ap.add_argument("--spacing-m",type=float,default=.25)
    ap.add_argument("--landscape",type=Path,default=TOOLS.parent/"Saved/Phase1/ground_conformed_triangulated")
    ap.add_argument("--out",type=Path,default=TOOLS.parent/"Saved/Phase1/junction_mesh_qc")
    args=ap.parse_args()
    if args.max_docs<0 or args.spacing_m<=0:
        ap.error("invalid budget/spacing")
    source=REPO/"data/thanet/out/unreal/streetscape"
    survey_dir=REPO/"data/thanet/out/unreal/landscape"
    paths=sorted(source.glob("site_x*_y*.json"))
    spec=TOOLS/"ue/render_set.json"
    selected=paths if args.scope=="full" else sample_documents(paths,spec)
    selected=[p for p in selected if json.loads(p.read_text()).get("junctions")]
    if not selected:
        raise ValueError("no junction documents")
    inputs=paths+[spec,Path(__file__),TOOLS/"phase1_qc.py",TOOLS/"diag/bridge_crossing_audit.py",TOOLS/"diag/corner_quality_audit.py"]
    inputs+=list((TOOLS/"blender/streetscape").glob("*.py"))
    for directory in (survey_dir,args.landscape):
        inputs += [directory/"landscape_manifest.json"]+list(directory.glob("hm_*.r16"))+list(directory.glob("clip_*.r8"))
    config={"documents":[p.name for p in selected],"scope":args.scope,"spacing_m":args.spacing_m,
            "landscape":str(args.landscape.resolve()),"python":sys.version,"numpy":np.__version__}
    fingerprint,hashes=content_identity(inputs,config)
    root=args.out/fingerprint[:20]
    root.mkdir(parents=True,exist_ok=True)
    with run_lock(root/"run.lock"):
        atomic_json(root/"inputs.json",{"fingerprint":fingerprint,"config":config,"sha256":hashes})
        state_path=root/"state.json"
        state=json.loads(state_path.read_text()) if state_path.exists() else {"documents":{},"fingerprint":fingerprint}
        survey=Heightfield.from_landscape_dir(str(survey_dir))
        terrain=Heightfield.from_landscape_dir(str(args.landscape))
        survey.sampling=terrain.sampling="landscape_triangulated"
        ran=0
        for path in selected:
            report_path=root/path.name
            old=state["documents"].get(path.name,{})
            if old.get("status")=="complete" and report_path.exists() and sha256(report_path)==old.get("report_sha256"):
                continue
            if args.max_docs and ran>=args.max_docs:
                state["documents"][path.name]={"status":"pending"}
                continue
            state["documents"][path.name]={"status":"running"}
            atomic_json(state_path,state)
            started=time.time()
            report=audit_document(path,survey,terrain,args.spacing_m)
            atomic_json(report_path,report)
            state["documents"][path.name]={"status":"complete","report_sha256":sha256(report_path),
                "totals":report["totals"],"seconds":time.time()-started}
            atomic_json(state_path,state)
            print(path.name,report["totals"],"seconds",round(time.time()-started,2),flush=True)
            ran+=1
        if content_identity(inputs,config)[0]!=fingerprint:
            raise ValueError("inputs changed during junction audit")
        totals=Counter()
        for row in state["documents"].values():
            totals.update(row.get("totals",{}))
        state.update(totals=dict(totals),phase1_accepted=False,
            complete=all(row["status"]=="complete" for row in state["documents"].values()))
        atomic_json(state_path,state)
        print(json.dumps({"state":str(state_path),"totals":dict(totals),"complete":state["complete"]}),flush=True)
        return 1 if totals["failed"] or totals["overlap_review"] else 0 if state["complete"] else 2


if __name__=="__main__":
    sys.exit(main())
