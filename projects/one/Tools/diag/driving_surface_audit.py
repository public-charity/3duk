"""Bounded screen for raised footway/kerb surfaces across vehicle-road centrelines.

Builds emitted road, junction and edge meshes with shared junction trims. This is
an obstruction screen, not complete lane/vehicle clearance certification. Missing
road coverage stays explicit; terrain clearance cannot waive a raised crossing.
"""
import argparse
import json
from pathlib import Path
import sys
import time

import numpy as np

TOOLS = Path(__file__).resolve().parents[1]
REPO = TOOLS.parents[2]
sys.path.insert(0, str(TOOLS))
sys.path.insert(0, str(TOOLS/"blender"))
from phase1_qc import atomic_json, content_identity
from streetscape import io_json
from streetscape.edge import build_edge, build_junction_corners
from streetscape.mesh import MeshBuffer
from streetscape.road import build_road, build_junction_patch
from streetscape.spline import JunctionPlan, Spline
from streetscape.terrain import Heightfield
from diag.bridge_crossing_audit import highest_triangle_z

PATHS = {"footway", "path", "cycleway", "steps", "pedestrian", "bridleway"}


def top_triangles(mesh, mask=None):
    triangles = mesh.v[mesh.f if mask is None else mesh.f[mask]]
    normal = np.cross(triangles[:,1]-triangles[:,0], triangles[:,2]-triangles[:,0])
    return triangles[normal[:,2] > .5*np.linalg.norm(normal, axis=1)]


def in_bounds(triangles, lo, hi):
    keep = np.all(triangles[:,:,:2].max(axis=1) >= lo, axis=1) & np.all(triangles[:,:,:2].min(axis=1) <= hi, axis=1)
    return triangles[keep]


def obstructions(xy, road, obstacle, gate=.04):
    road_z = highest_triangle_z(road, xy)
    top_z = highest_triangle_z(obstacle, xy)
    valid = np.isfinite(road_z) & np.isfinite(top_z)
    rise = np.where(valid, top_z-road_z, -np.inf)
    ids = np.flatnonzero(rise > gate)
    return ids, rise, road_z, top_z


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--bounds", required=True, help="local x1,y1,x2,y2; at most 256 m on each side")
    ap.add_argument("--streetscape", type=Path, default=REPO/"data/thanet/out/unreal/streetscape")
    ap.add_argument("--out", type=Path, default=TOOLS.parent/"Saved/Phase1/driving_surface_qc")
    args = ap.parse_args()
    bounds = np.array(list(map(float, args.bounds.split(","))))
    if bounds.shape != (4,) or not np.isfinite(bounds).all() or np.any(bounds[2:]-bounds[:2] <= 0) or np.any(bounds[2:]-bounds[:2] > 256):
        raise ValueError("bounds must be a finite, positive rectangle <=256 m")
    lo, hi = bounds[:2], bounds[2:]
    documents = []
    raw_by_path = {}
    for path in sorted(args.streetscape.glob("site_x*_y*.json")):
        raw = json.loads(path.read_text())
        selected = []
        for d in raw["splines"]:
            if d["source"]["layer"] != "roads":
                continue
            p = np.array([[p["x"], p["y"]] for p in d["points"]])
            if np.all(p.max(axis=0)+32 >= lo) and np.all(p.min(axis=0)-32 <= hi):
                selected.append(d["id"])
        if selected:
            documents.append((path, selected))
            raw_by_path[path] = raw
    if not documents:
        raise ValueError("no source roads intersect the requested rectangle")
    survey_dir = REPO/"data/thanet/out/unreal/landscape"
    inputs = [p for p,_ in documents]+[Path(__file__), TOOLS/"phase1_qc.py", TOOLS/"diag/bridge_crossing_audit.py"]
    inputs += list((TOOLS/"blender/streetscape").glob("*.py"))
    inputs += [survey_dir/"landscape_manifest.json"]+list(survey_dir.glob("hm_*.r16"))+list(survey_dir.glob("clip_*.r8"))
    config = dict(bounds_m=bounds.tolist(), spacing_m=.25, raised_gate_m=.04, scope="vehicle centreline surface obstruction screen")
    identity, hashes = content_identity(inputs, config)
    root = args.out/identity[:20]
    root.mkdir(parents=True, exist_ok=True)
    report = dict(status="running", phase1_accepted=False, fingerprint=identity, config=config, input_sha256=hashes,
                  documents=[str(p) for p,_ in documents], obstructions=[], coverage=[])
    atomic_json(root/"report.json", report)
    started = time.time()
    try:
        survey = Heightfield.from_landscape_dir(str(survey_dir))
        survey.sampling = "landscape_triangulated"
        roads, obstacles, drivers = [], [], []
        for path, selected in documents:
            site = io_json.site_from_dict(raw_by_path[path])
            if (site.origin.E, site.origin.N) != (survey.origin_E, survey.origin_N):
                raise ValueError("document/terrain registration mismatch")
            plan = JunctionPlan(site)
            junctions = [j for j in site.junctions if np.all(np.array([j.x,j.y])+32 >= lo) and np.all(np.array([j.x,j.y])-32 <= hi)]
            ids = set(selected) | {a.spline_id for j in junctions for a in plan.arms.get(j.id, [])}
            splines = {}
            for sid in sorted(ids):
                definition = site.spline(sid)
                if definition.flags and (definition.flags.bridge or definition.flags.tunnel):
                    report.setdefault("excluded_structures", []).append(sid)
                    continue
                sp = Spline(definition, site, survey, trim=plan.trim_for(sid))
                splines[sid] = sp
                mesh,_ = build_road(sp)
                top = in_bounds(top_triangles(mesh, mesh.group_mask_tris(exact="road")), lo, hi)
                if not len(top):
                    continue
                path_kind = definition.source.cls in PATHS
                if path_kind:
                    obstacles.append((sid, "path", top))
                else:
                    roads.append(top)
                    q = np.linspace(0, sp.length, int(np.ceil(sp.length/.25))+1)
                    xy = sp.frames.at(q).p[:,:2]
                    keep = np.all(xy >= lo, axis=1) & np.all(xy <= hi, axis=1)
                    if keep.any():
                        drivers.append((sid, q[keep], xy[keep]))
                for side in (1,-1):
                    edge,_ = build_edge(sp, side, survey)
                    for group in edge.group_names:
                        if group not in ("kerb", "pavement"):
                            continue
                        top = in_bounds(top_triangles(edge, edge.group_mask_tris(exact=group)), lo, hi)
                        if len(top):
                            obstacles.append((sid+":"+str(side)+":"+group, "edge", top))
            for j in junctions:
                if j.id not in plan.arms or any(a.spline_id not in splines for a in plan.arms[j.id]):
                    continue
                road, edge = MeshBuffer(), MeshBuffer()
                if not build_junction_patch(plan, j.id, splines, road)["built"]:
                    raise ValueError("planned junction did not build: "+j.id)
                build_junction_corners(plan, j.id, splines, edge)
                top = in_bounds(top_triangles(road), lo, hi)
                # Vehicle junctions only. A footway-only junction is an obstacle.
                vehicle = any(site.spline(a.spline_id).source.cls not in PATHS for a in plan.arms[j.id])
                if len(top):
                    if vehicle:
                        roads.append(top)
                    else:
                        obstacles.append((j.id, "path_junction", top))
                for group in edge.group_names:
                    top = in_bounds(top_triangles(edge, edge.group_mask_tris(exact=group)), lo, hi)
                    if len(top):
                        obstacles.append((group, "corner", top))
        if not roads or not drivers:
            raise ValueError("no measured vehicle-road coverage")
        road = np.concatenate(roads)
        for sid, stations, xy in drivers:
            z = highest_triangle_z(road, xy)
            report["coverage"].append(dict(id=sid, samples=len(xy), missing_road_samples=int((~np.isfinite(z)).sum())))
            for oid, kind, top in obstacles:
                near = in_bounds(top, xy.min(axis=0), xy.max(axis=0))
                if not len(near):
                    continue
                hits, rise, rz, tz = obstructions(xy, road, near)
                if not len(hits):
                    continue
                worst = hits[np.argmax(rise[hits])]
                report["obstructions"].append(dict(road=sid, obstacle=oid, kind=kind, samples=len(hits),
                    s_range_m=[float(stations[hits[0]]), float(stations[hits[-1]])],
                    max_rise_m=float(rise[worst]), worst_xy_m=xy[worst].tolist(),
                    road_z_m=float(rz[worst]), obstacle_z_m=float(tz[worst])))
            atomic_json(root/"report.json", report)
        report["obstructions"].sort(key=lambda r:r["max_rise_m"], reverse=True)
        report.update(status="complete", screen_pass=not report["obstructions"] and not any(r["missing_road_samples"] for r in report["coverage"]),
                      seconds=round(time.time()-started,3))
    except BaseException as exc:
        report.update(status="failed", error=str(exc))
        raise
    finally:
        atomic_json(root/"report.json", report)
    print(json.dumps({"report":str(root/"report.json"), "screen_pass":report["screen_pass"],
                      "drivers":len(drivers), "obstructions":report["obstructions"], "seconds":report["seconds"]}, indent=2))


if __name__ == "__main__":
    main()
