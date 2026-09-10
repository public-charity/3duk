#!/usr/bin/env python3
"""Bounded, reviewable terrain contact repair for ordinary junction corners.

Emits a sparse, source-hashed candidate only. Deep/occluded corners require a
geometry model and are refused. Production and source rasters are never written.
"""
import argparse
from contextlib import contextmanager
import json
from pathlib import Path
import sys
import time
import numpy as np
import scipy

TOOLS = Path(__file__).resolve().parents[1]
REPO = TOOLS.parents[2]
sys.path.insert(0, str(TOOLS))
sys.path.insert(0, str(TOOLS/"blender"))
from phase1_qc import atomic_json, content_identity, run_lock, sha256
from diag.junction_mesh_audit import surface_stats
from diag.terrain_contact import minimum_cut, apply_posts, exact_penetration
from streetscape import io_json
from streetscape.mesh import MeshBuffer
from streetscape.road import build_road, build_junction_patch
from streetscape.edge import build_junction_corners
from streetscape.spline import JunctionPlan, Spline
from streetscape.terrain import Heightfield


def bottom_points(mesh, spacing=.25):
    """Sample actual pavement outer-face bottom edges, including banked XY."""
    faces = mesh.f[mesh.group_mask_tris(prefix="corner_pavement:")]
    segments = set()
    for face in faces:
        for a,b in zip(face, np.roll(face,-1)):
            if mesh.vh[a] < -1e-6 and mesh.vh[b] < -1e-6:
                segments.add(tuple(sorted((int(a),int(b)))))
    points = []
    for a,b in segments:
        p,q = mesh.v[a],mesh.v[b]
        n = max(1,int(np.ceil(np.linalg.norm(q-p)/spacing)))
        points.append(p+np.linspace(0,1,n+1)[:,None]*(q-p))
    if not points:
        raise ValueError("no corner outer-face bottom edges")
    return np.concatenate(points)


def ribbon_bottom_points(sp, bounds, spacing=.25):
    """Actual banked XY/Z of emitted outer base edges, including bare skirts."""
    points = []
    for side in (-1,1):
        spec = sp.side_spec[side]
        present = spec.present&((spec.kerb_width+spec.pavement_width)>0)
        d = side*(sp.edge_offset(side)+np.where(present,spec.back_offset,sp.overlap_m))
        h = sp.edge_height(side)-np.where(present,spec.skirt,sp.skirt_drop_m)
        xyz = sp.frames.p+d[:,None]*sp.frames.n+h[:,None]*sp.frames.b
        mask = sp.active[:-1]&sp.active[1:]&(present[:-1]==present[1:])
        mask &= np.all(np.maximum(xyz[:-1,:2],xyz[1:,:2])>=bounds[0],axis=1)
        mask &= np.all(np.minimum(xyz[:-1,:2],xyz[1:,:2])<=bounds[1],axis=1)
        for i in np.flatnonzero(mask):
            p,q = xyz[i:i+2]
            n = max(1,int(np.ceil(np.linalg.norm(q-p)/spacing)))
            points.append(p+np.linspace(0,1,n+1)[:,None]*(q-p))
    return np.concatenate(points) if points else np.empty((0,3))


def check_daylight(points, baseline, candidate):
    old = np.maximum(0,points[:,2]-baseline.sample(points[:,0],points[:,1]))
    new = np.maximum(0,points[:,2]-candidate.sample(points[:,0],points[:,1]))
    if not np.isfinite(old).all() or not np.isfinite(new).all():
        raise ValueError("missing ground under protected outer face")
    return dict(samples=len(old),before_max_m=float(old.max()),after_max_m=float(new.max()),
                max_increase_m=float(np.max(new-old)))


@contextmanager
def record_failure(path, report):
    try:
        yield
    except BaseException as error:
        report.update(status="failed",error=str(error),phase1_accepted=False)
        atomic_json(path,report)
        raise


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--document", required=True)
    ap.add_argument("--junction", action="append", required=True)
    ap.add_argument("--max-cut-m", type=float, default=.5)
    ap.add_argument("--landscape", type=Path, default=TOOLS.parent/"Saved/Phase1/ground_conformed_triangulated")
    ap.add_argument("--out", type=Path, default=TOOLS.parent/"Saved/Phase1/junction_contact_candidates")
    args = ap.parse_args()
    source = REPO/"data/thanet/out/unreal/streetscape"
    survey_dir = REPO/"data/thanet/out/unreal/landscape"
    path = (source/args.document).resolve()
    if path.parent != source.resolve():
        raise ValueError("document must be a source basename")
    inputs = list(source.glob("site_x*_y*.json"))
    inputs += [Path(__file__), TOOLS/"phase1_qc.py", TOOLS/"diag/terrain_contact.py",
               TOOLS/"diag/junction_mesh_audit.py", TOOLS/"diag/bridge_crossing_audit.py"]
    inputs += list((TOOLS/"blender/streetscape").glob("*.py"))
    for directory in (survey_dir,args.landscape):
        inputs += [directory/"landscape_manifest.json"]+list(directory.glob("hm_*.r16"))+list(directory.glob("clip_*.r8"))
    config = dict(document=args.document, junctions=args.junction, max_cut_m=args.max_cut_m,
                  clearance_m=.01, python=sys.version, numpy=np.__version__, scipy=scipy.__version__,
                  landscape=str(args.landscape.resolve()))
    identity, hashes = content_identity(inputs,config)
    root = args.out/identity[:20]
    root.mkdir(parents=True,exist_ok=True)
    report = dict(status="running", phase1_accepted=False, fingerprint=identity, config=config,
                  input_sha256=hashes, results=[])
    with run_lock(root/"run.lock"), record_failure(root/"report.json",report):
        atomic_json(root/"report.json",report)
        started = time.time()
        survey = Heightfield.from_landscape_dir(str(survey_dir))
        baseline = Heightfield.from_landscape_dir(str(args.landscape))
        survey.sampling = baseline.sampling = "landscape_triangulated"
        site = io_json.load_site(str(path))
        if (site.origin.E,site.origin.N) != (survey.origin_E,survey.origin_N):
            raise ValueError("source origin differs from terrain")
        plan = JunctionPlan(site)
        all_changes = {}
        meshes = []
        for jid in args.junction:
            if jid not in plan.arms:
                raise ValueError("junction is not planned: "+jid)
            arms = {}
            for arm in plan.arms[jid]:
                definition = site.spline(arm.spline_id)
                if definition.flags and (definition.flags.bridge or definition.flags.tunnel):
                    raise ValueError("structure corner requires a separate model: "+jid)
                arms[arm.spline_id] = Spline(definition,site,survey,trim=plan.trim_for(arm.spline_id))
            road, edge = MeshBuffer(), MeshBuffer()
            if not build_junction_patch(plan,jid,arms,road)["built"]:
                raise ValueError("junction patch did not build")
            build_junction_corners(plan,jid,arms,edge)
            triangles = edge.v[edge.f]
            normal = np.cross(triangles[:,1]-triangles[:,0],triangles[:,2]-triangles[:,0])
            keep = (np.min(edge.vh[edge.f],axis=1)>=-1e-8)&(normal[:,2]>.5*np.linalg.norm(normal,axis=1))
            top = triangles[keep]
            covers = [road.v[road.f]]
            for sp in arms.values():
                mesh,_ = build_road(sp)
                covers.append(mesh.v[mesh.f[mesh.group_mask_tris(exact="road")]])
            visibility = surface_stats(top,baseline,cover_triangles=np.concatenate(covers))
            if visibility.get("max_road_occlusion_depth_m",0)>.005:
                raise ValueError("occluded corner needs geometry review before terrain cutting: "+jid)
            before = exact_penetration(top,baseline)
            changes,stats = minimum_cut(top,baseline,max_cut_m=args.max_cut_m)
            for key,z in changes.items():
                all_changes[key] = min(all_changes.get(key,np.inf),z)
            meshes.append((jid,top,bottom_points(edge)))
            report["results"].append(dict(id=jid,before=before,cut=stats))
            atomic_json(root/"report.json",report)
            print(jid,stats,flush=True)
        candidate = apply_posts(baseline,all_changes)
        problems = []
        # Compare every neighbouring source spline, using the original survey for
        # geometry on both sides. A 512 m halo includes adjacent tile fragments.
        xy = np.array(list(all_changes),dtype=float)*baseline.px_m
        bounds = (xy.min(axis=0)-512,xy.max(axis=0)+512) if len(xy) else None
        checked = 0
        protected = []
        if bounds:
            for doc in sorted(source.glob("site_x*_y*.json")):
                raw = json.loads(doc.read_text())
                selected = []
                for definition in raw["splines"]:
                    pts = np.array([[p["x"],p["y"]] for p in definition["points"]])
                    if len(pts) and np.all(pts.max(axis=0)>=bounds[0]) and np.all(pts.min(axis=0)<=bounds[1]):
                        selected.append(definition["id"])
                if not selected:
                    continue
                nearby = io_json.site_from_dict(raw)
                nearplan = JunctionPlan(nearby)
                for sid in selected:
                    definition = nearby.spline(sid)
                    if definition.flags and (definition.flags.bridge or definition.flags.tunnel):
                        continue
                    sp = Spline(definition,nearby,survey,trim=nearplan.trim_for(sid))
                    checked += 1
                    points = ribbon_bottom_points(sp,(xy.min(axis=0)-2,xy.max(axis=0)+2))
                    if len(points):
                        protected.append((doc.name,sid,points))
        protect = np.concatenate([p for _,_,p in meshes]+[p for _,_,p in protected])
        initial = check_daylight(protect,baseline,candidate)
        report["initial_outer_edge_check"] = initial
        if initial["max_increase_m"]>.005:
            try:
                all_changes, stats = minimum_cut(np.concatenate([top for _,top,_ in meshes]),baseline,
                    max_cut_m=args.max_cut_m,protected_points=protect)
                candidate = apply_posts(baseline,all_changes)
                report["protected_cut"] = stats
            except ValueError as error:
                report["protected_cut_problem"] = str(error)
                problems.append("no terrain-only repair within the edge-contact/cut limits")
        for row,(_,top,points) in zip(report["results"],meshes):
            row["after"] = exact_penetration(top,candidate)
            row["corner_daylight"] = check_daylight(points,baseline,candidate)
            if row["after"]["max_penetration_m"]>.005 or row["corner_daylight"]["max_increase_m"]>.005:
                problems.append(row["id"]+": contact/daylight regression")
        regressions = []
        for doc,sid,points in protected:
            stats = check_daylight(points,baseline,candidate)
            if stats["max_increase_m"]>.005+1e-8:
                regressions.append(dict(document=doc,id=sid,**stats))
        report["neighbour_edges"] = dict(splines=checked,measured_edges=len(protected),
            measurement="emitted outer base edges at <=25 cm spacing; actual banked XY",regressions=regressions)
        if regressions:
            problems.append("new daylight on neighbouring ribbon edges")
        if content_identity(inputs,config)[0] != identity:
            raise ValueError("inputs changed during candidate generation")
        report.update(status="rejected" if problems else "candidate", problems=problems,
                      seconds=time.time()-started,changed_posts=len(all_changes))
        atomic_json(root/"posts.json",dict(fingerprint=identity,status=report["status"],
            grid_px_m=baseline.px_m,posts=[[x,y,z] for (x,y),z in sorted(all_changes.items())]))
        report["posts_sha256"] = sha256(root/"posts.json")
        atomic_json(root/"report.json",report)
        print(json.dumps(dict(report=str(root/"report.json"),status=report["status"],problems=problems)),flush=True)
        return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())
