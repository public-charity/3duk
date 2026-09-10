#!/usr/bin/env python3
"""Sample emitted surface triangle interiors against imported terrain in a bounded document.

This complements the station audit. It does not certify unsampled triangle/terrain
intersections, imported engine mesh identity, skirts or floating outer faces.
"""
import argparse
import json
from pathlib import Path
import sys
import time

import numpy as np

TOOLS = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(TOOLS))
sys.path.insert(0, str(TOOLS / "blender"))
from phase1_qc import atomic_json, sha256
from streetscape import io_json
from streetscape.build import build_all
from streetscape.terrain import Heightfield

REPO = TOOLS.parents[2]


def sample_triangles(triangles, terrain, spacing=0.25, gate=0.005):
    """Barycentric grids whose adjacent samples are at most spacing metres apart.

    Includes vertices and edges, but still a sampled test, not an exact intersection.
    Samples on shared edges are counted more than once; fraction is not area fraction.
    """
    if not np.isfinite(spacing) or spacing <= 0:
        raise ValueError("spacing must be finite and positive")
    triangles = np.asarray(triangles, dtype=float).reshape(-1, 3, 3)
    if not len(triangles) or not np.isfinite(triangles).all():
        raise ValueError("empty or nonfinite triangle set")
    longest = np.linalg.norm(triangles - triangles[:, [1, 2, 0]], axis=2).max(axis=1)
    divisions = np.maximum(1, np.ceil(longest / spacing).astype(int))
    if divisions.max() > 256:
        raise ValueError("triangle too large for bounded sampling; subdivide the diagnostic region")
    count = finite = hit = 0
    worst = None
    for n in np.unique(divisions):
        ids = np.flatnonzero(divisions == n)
        weights = np.array([(i/n, j/n, 1-(i+j)/n)
                            for i in range(n+1) for j in range(n+1-i)])
        # Bound each temporary to roughly 200k sample points.
        batch = max(1, 200000 // len(weights))
        for start in range(0, len(ids), batch):
            chunk = ids[start:start+batch]
            points = np.einsum("wv,tvc->twc", weights, triangles[chunk])
            ground = terrain.sample(points[:, :, 0].ravel(), points[:, :, 1].ravel()).reshape(points.shape[:2])
            delta = ground - points[:, :, 2]
            ok = np.isfinite(delta)
            count += delta.size
            finite += int(ok.sum())
            hit += int((ok & (delta > gate)).sum())
            if ok.any():
                pos = np.unravel_index(np.argmax(np.where(ok, delta, -np.inf)), delta.shape)
                if worst is None or delta[pos] > worst["ground_minus_surface_m"]:
                    worst = {"ground_minus_surface_m": float(delta[pos]),
                             "triangle": int(chunk[pos[0]]), "xyz_m": points[pos].tolist(),
                             "ground_z_m": float(ground[pos])}
    return {"triangles": len(triangles), "samples": count, "finite_samples": finite,
            "uncovered_samples": count-finite, "penetrated_samples": hit,
            "spacing_m": spacing, "gate_m": gate, "worst": worst}


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--doc", type=Path, required=True)
    ap.add_argument("--id", action="append", default=[])
    ap.add_argument("--survey", type=Path, default=REPO / "data/thanet/out/unreal/landscape")
    ap.add_argument("--landscape", type=Path, default=REPO / "data/thanet/out/unreal/landscape_conformed")
    ap.add_argument("--spacing", type=float, default=0.25)
    ap.add_argument("--out", type=Path, required=True)
    args = ap.parse_args()
    started = time.time()
    site = io_json.load_site(str(args.doc))
    ids = args.id or [s.id for s in site.splines
                     if s.source.layer in ("roads", "rail")
                     and not (s.flags and (s.flags.bridge or s.flags.tunnel))]
    known = {s.id for s in site.splines}
    if not ids or set(ids) - known:
        ap.error("empty selection or unmatched spline IDs")
    survey = Heightfield.from_landscape_dir(str(args.survey))
    terrain = Heightfield.from_landscape_dir(str(args.landscape))
    survey.sampling = terrain.sampling = "landscape_triangulated"
    built = build_all(site, survey, only_ids=ids)
    terrain = terrain.rebased(site.origin.E, site.origin.N)
    rows = []
    for sid, result in built.items():
        for name, buf in result.buffers().items():
            if name not in ("road", "edge_left", "edge_right"):
                continue
            # Upward-facing carriageway, junction, kerb and pavement tops only.
            allowed = [i for i, g in enumerate(buf.group_names)
                       if g == "road" or g.startswith(("junction:", "kerb", "pavement", "corner_"))]
            mask = np.isin(buf.grp, allowed) & (buf.face_normals()[:, 2] > 1e-8)
            if not mask.any():
                continue
            rec = sample_triangles(buf.v[buf.f[mask]], terrain, args.spacing)
            if rec["worst"]:
                ix = int(np.flatnonzero(mask)[rec["worst"]["triangle"]])
                rec["worst"].update(buffer_triangle=ix, group=buf.group_names[buf.grp[ix]])
            rec.update(id=sid, buffer=name)
            rows.append(rec)
            print(sid, name, "hits", rec["penetrated_samples"], "/", rec["finite_samples"],
                  "max", rec["worst"]["ground_minus_surface_m"] if rec["worst"] else None, flush=True)
    if not rows or not any(r["finite_samples"] for r in rows):
        raise ValueError("no measured surfaces")
    atomic_json(args.out, {"scope": "diagnostic_subset", "phase1_accepted": False,
                          "doc": str(args.doc), "doc_sha256": sha256(args.doc),
                          "survey": str(args.survey), "landscape": str(args.landscape),
                          "sampling": "landscape_triangulated", "ids": ids,
                          "built_stats": {sid: result.stats for sid, result in built.items()},
                          "limitations": __doc__, "results": rows, "seconds": time.time()-started})
    print("report", args.out, "seconds", round(time.time()-started, 2), flush=True)


if __name__ == "__main__":
    main()
