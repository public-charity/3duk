#!/usr/bin/env python3
"""Sample modelled rail bridge base envelopes above nearby emitted ground-road triangles.

The current ballast mesh is open underneath. This measures a nominal horizontal
base at ballast depth; it does not certify a designed structural soffit or legal clearance.
"""
import argparse
import json
from pathlib import Path
import sys

import numpy as np

TOOLS = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(TOOLS))
sys.path.insert(0, str(TOOLS / "blender"))
from phase1_qc import atomic_json, sha256
from streetscape import io_json
from streetscape.road import build_road
from streetscape.spline import Spline
from streetscape.terrain import Heightfield

REPO = TOOLS.parents[2]


def highest_triangle_z(triangles, xy):
    result = np.full(len(xy), -np.inf)
    for a, b, c in triangles:
        det = (b[1]-c[1])*(a[0]-c[0])+(c[0]-b[0])*(a[1]-c[1])
        if abs(det) < 1e-10:
            continue
        u = ((b[1]-c[1])*(xy[:, 0]-c[0])+(c[0]-b[0])*(xy[:, 1]-c[1]))/det
        v = ((c[1]-a[1])*(xy[:, 0]-c[0])+(a[0]-c[0])*(xy[:, 1]-c[1]))/det
        w = 1-u-v
        inside = (u >= -1e-9) & (v >= -1e-9) & (w >= -1e-9)
        result[inside] = np.maximum(result[inside], (u*a[2]+v*b[2]+w*c[2])[inside])
    result[~np.isfinite(result)] = np.nan
    return result


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--candidate", type=Path, required=True)
    ap.add_argument("--streetscape", type=Path, default=REPO/"data/thanet/out/unreal/streetscape")
    ap.add_argument("--survey", type=Path, default=REPO/"data/thanet/out/unreal/landscape")
    ap.add_argument("--ground-candidate", type=Path, help="complete source documents with candidate road elevations")
    ap.add_argument("--out", type=Path, required=True)
    args = ap.parse_args()
    ground_documents, ground_manifest_hash = {}, None
    if args.ground_candidate:
        manifest_path = args.ground_candidate/"candidate_manifest.json"
        manifest = json.loads(manifest_path.read_text())
        if manifest.get("scope") != "document_elevations":
            raise ValueError("ground candidate must preserve complete source documents")
        ground_manifest_hash = sha256(manifest_path)
        for name, digest in manifest["candidate_documents"].items():
            candidate_path = (args.ground_candidate/name).resolve()
            if candidate_path.parent != args.ground_candidate.resolve() or sha256(candidate_path) != digest:
                raise ValueError("invalid ground candidate document: "+name)
            if sha256(args.streetscape/name) != manifest["source_documents"][name]:
                raise ValueError("ground candidate source changed: "+name)
            ground_documents[name] = json.loads(candidate_path.read_text())
    hf = Heightfield.from_landscape_dir(str(args.survey))
    hf.sampling = "landscape_triangulated"
    decks = []
    for p in args.candidate.glob("site_x*_y*.json"):
        site = io_json.load_site(str(p))
        for sdef in site.splines:
            if not (sdef.flags and sdef.flags.bridge and sdef.elevation_profile):
                continue
            sp = Spline(sdef, site, hf)
            q = np.linspace(0, sp.length, int(np.ceil(sp.length/.25))+1)
            frames = sp.frames.at(q)
            width = np.interp(q, sp.s, sp.width)
            depth = sp.road_profile.rail.ballast.depth_m
            lat = width[:, None]*np.linspace(-.5, .5, int(np.ceil(width.max()/.25))+1)[None, :]
            pts = frames.p[:, None, :]+lat[:, :, None]*frames.n[:, None, :]-depth*frames.b[:, None, :]
            pts = pts.reshape(-1, 3)
            decks.append((sp.id, pts))
    if not decks:
        raise ValueError("no explicit bridge decks")
    roads = []
    for p in args.streetscape.glob("site_x*_y*.json"):
        raw = ground_documents.get(p.name) or json.loads(p.read_text())
        selected = []
        for row in raw["splines"]:
            if row["source"]["layer"] != "roads" or any((row.get("flags") or {}).get(k) for k in ("bridge", "tunnel")):
                continue
            xy = np.array([[pt["x"], pt["y"]] for pt in row["points"]])
            lo, hi = xy.min(axis=0)-20, xy.max(axis=0)+20
            if any(np.all(pts[:, :2].max(axis=0) >= lo) and np.all(pts[:, :2].min(axis=0) <= hi) for _, pts in decks):
                selected.append(row["id"])
        if selected:
            site = io_json.site_from_dict(raw)
            for sid in selected:
                sp = Spline(site.spline(sid), site, hf)
                buf, _ = build_road(sp)
                mask = buf.group_mask_tris(exact="road")
                if mask.any():
                    roads.append((sid, buf.v[buf.f[mask]]))
    rows = []
    for sid, pts in decks:
        crossing = []
        for road_id, triangles in roads:
            z = highest_triangle_z(triangles, pts[:, :2])
            ok = np.isfinite(z)
            if not ok.any():
                continue
            clearance = pts[ok, 2]-z[ok]
            crossing.append({"road": road_id, "samples": int(ok.sum()),
                             "minimum_nominal_base_clearance_m": float(clearance.min()),
                             "maximum_nominal_base_clearance_m": float(clearance.max())})
        rows.append({"bridge": sid, "crossings": crossing})
    atomic_json(args.out, {"scope": "candidate", "production_accepted": False, "model": __doc__,
                          "candidate_manifest_sha256": sha256(args.candidate/"candidate_manifest.json"),
                          "ground_candidate_manifest_sha256": ground_manifest_hash,
                          "bridge_spacing_m": .25, "results": rows})
    print(json.dumps(rows, indent=2))
    if any(not r["crossings"] for r in rows):
        raise ValueError("some candidate decks have no measured ground-road crossing")
    if any(c["minimum_nominal_base_clearance_m"] <= 0 for r in rows for c in r["crossings"]):
        raise ValueError("candidate bridge base intersects a ground road")


if __name__ == "__main__":
    main()
