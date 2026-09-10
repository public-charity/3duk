#!/usr/bin/env python3
"""Measure every bridge/tunnel and its connected approaches before modelling decks.

Read-only. Groups touching structure segments across document/tile boundaries;
records unsupported/branching groups instead of inventing endpoint elevations.
All coordinates remain document-local metres; heights are ODN metres.
"""
from collections import Counter, defaultdict
import argparse
import json
import math
from pathlib import Path
import sys
import time

import numpy as np

TOOLS = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(TOOLS))
sys.path.insert(0, str(TOOLS / "blender"))
from phase1_qc import atomic_json, sha256
from streetscape import io_json
from streetscape.spline import Spline
from streetscape.terrain import Heightfield

REPO = TOOLS.parents[2]


def structure_kind(row):
    flags = row.get("flags") or {}
    return "bridge" if flags.get("bridge") else "tunnel" if flags.get("tunnel") else "ground"


def sample_dsm(dataset, x, y):
    """Bilinear first-return heights from one small VRT window, with pixel-centre registration."""
    gt = dataset.GetGeoTransform()
    if gt[2] != 0 or gt[4] != 0:
        raise ValueError("rotated DSM is unsupported")
    cx, cy = (x - gt[0]) / gt[1] - 0.5, (y - gt[3]) / gt[5] - 0.5
    bx, by = np.floor(cx).astype(int), np.floor(cy).astype(int)
    x0, x1 = max(0, int(bx.min())), min(dataset.RasterXSize, int(bx.max()) + 2)
    y0, y1 = max(0, int(by.min())), min(dataset.RasterYSize, int(by.max()) + 2)
    out = np.full(x.shape, np.nan)
    if x1 <= x0 or y1 <= y0:
        return out
    band = dataset.GetRasterBand(1)
    data = band.ReadAsArray(x0, y0, x1 - x0, y1 - y0).astype(float)
    nd = band.GetNoDataValue()
    data[data < -1e20] = np.nan
    if nd is not None:
        data[data == nd] = np.nan
    ok = (bx >= x0) & (bx + 1 < x1) & (by >= y0) & (by + 1 < y1)
    ix, iy = bx[ok] - x0, by[ok] - y0
    tx, ty = cx[ok] - bx[ok], cy[ok] - by[ok]
    a, b, c, d = data[iy, ix], data[iy, ix + 1], data[iy + 1, ix], data[iy + 1, ix + 1]
    out[ok] = (1 - ty) * ((1 - tx) * a + tx * b) + ty * ((1 - tx) * c + tx * d)
    return out


def finite_list(values):
    return [float(v) if np.isfinite(v) else None for v in values]


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--streetscape", type=Path, default=REPO / "data/thanet/out/unreal/streetscape")
    ap.add_argument("--survey", type=Path, default=REPO / "data/thanet/out/unreal/landscape")
    ap.add_argument("--snap-m", type=float, default=0.35)
    ap.add_argument("--dsm", type=Path, default=REPO / "data/thanet/interim/dsm.vrt")
    ap.add_argument("--out", type=Path, default=TOOLS.parent / "Saved/Phase1/structures_baseline.json")
    args = ap.parse_args()
    if args.snap_m <= 0:
        ap.error("snap-m must be positive")
    start = time.time()
    defs, endpoint_bins, endpoints, files = {}, defaultdict(list), {}, {}
    for path in sorted(args.streetscape.glob("site_x*_y*.json")):
        raw = json.loads(path.read_text(encoding="utf-8"))
        files[path.name] = sha256(path)
        for row in raw["splines"]:
            source = row.get("source") or {}
            if source.get("layer") not in ("roads", "rail") or not row["profile_ids"].get("road"):
                continue
            sid = row["id"]
            if sid in defs:
                raise ValueError("duplicate spline " + sid)
            defs[sid] = (path, row)
            for end, point in (("start", row["points"][0]), ("end", row["points"][-1])):
                key = (sid, end)
                xy = (point["x"], point["y"])
                endpoints[key] = xy
                cell = (source["layer"], math.floor(xy[0] / args.snap_m), math.floor(xy[1] / args.snap_m))
                endpoint_bins[cell].append(key)
    structures = {sid for sid, (_, row) in defs.items() if structure_kind(row) != "ground"}
    if not structures:
        ap.error("no structures: empty inventory cannot pass")

    def neighbours(key):
        sid, _ = key
        xy = endpoints[key]
        layer = defs[sid][1]["source"]["layer"]
        bx, by = math.floor(xy[0] / args.snap_m), math.floor(xy[1] / args.snap_m)
        result = []
        for dx in (-1, 0, 1):
            for dy in (-1, 0, 1):
                for other in endpoint_bins.get((layer, bx + dx, by + dy), []):
                    if other[0] != sid and math.dist(xy, endpoints[other]) <= args.snap_m:
                        result.append(other)
        return sorted(result)

    links = {}
    for sid in sorted(structures):
        for end in ("start", "end"):
            candidates = [key for key in neighbours((sid, end)) if key[0] in structures
                          and structure_kind(defs[key[0]][1]) == structure_kind(defs[sid][1])]
            nearest = min((math.dist(endpoints[(sid, end)], endpoints[k]) for k in candidates), default=math.inf)
            links[(sid, end)] = [k for k in candidates
                                if math.dist(endpoints[(sid, end)], endpoints[k]) <= nearest + 1e-5]
    # Mutual nearest endpoints prevent a 7 cm tile-boundary stub from connecting
    # both its ends to the same previous endpoint merely because snap is 35 cm.
    links = {key: [other for other in values if key in links[other]] for key, values in links.items()}
    groups, unseen = [], set(structures)
    while unseen:
        seed = min(unseen)
        component, pending = set(), [seed]
        while pending:
            sid = pending.pop()
            if sid in component:
                continue
            component.add(sid)
            pending.extend(key[0] for end in ("start", "end") for key in links[(sid, end)])
        unseen -= component
        groups.append(sorted(component))

    hf = Heightfield.from_landscape_dir(args.survey)
    hf.sampling = "landscape_triangulated"
    from osgeo import gdal
    gdal.UseExceptions()
    dsm = gdal.Open(str(args.dsm))
    sites, built = {}, {}

    def spline(sid):
        if sid not in built:
            path, _ = defs[sid]
            if path not in sites:
                site = io_json.load_site(str(path))
                sites[path] = (site, {s.id: s for s in site.splines})
            site, by_id = sites[path]
            built[sid] = Spline(by_id[sid], site, hf)
        return built[sid]

    def endpoint_record(key):
        sid, end = key
        sp = spline(sid)
        index = 0 if end == "start" else -1
        approaches = []
        for other in neighbours(key):
            if other[0] in structures:
                continue
            asp = spline(other[0])
            ai = 0 if other[1] == "start" else -1
            approaches.append({"spline_id": other[0], "end": other[1],
                               "distance_m": math.dist(endpoints[key], endpoints[other]),
                               "z_m": float(asp.z_ref[ai]), "bank_deg": float(asp.bank_deg[ai]),
                               "has_survey": bool(np.isfinite(asp.z_raw[ai]))})
        return {"spline_id": sid, "end": end, "xy_m": endpoints[key],
                "raw_z_m": float(sp.z_raw[index]) if np.isfinite(sp.z_raw[index]) else None,
                "built_z_m": float(sp.z_ref[index]), "bank_deg": float(sp.bank_deg[index]),
                "ground_approaches": approaches}

    result = []
    for component in groups:
        ends = [(sid, end) for sid in component for end in ("start", "end") if not links[(sid, end)]]
        branched = any(len(links[(sid, end)]) > 1 for sid in component for end in ("start", "end"))
        row = {"id": component[0], "kind": structure_kind(defs[component[0]][1]),
               "splines": component, "documents": sorted({defs[sid][0].name for sid in component}),
               "status": "complex_connectivity" if branched or len(ends) != 2 else "measured_chain",
               "ends": [endpoint_record(key) for key in ends], "segments": []}
        for sid in component:
            sp = spline(sid)
            chord = np.interp(sp.s, [0, sp.length], [sp.z_ref[0], sp.z_ref[-1]])
            grade = np.abs(np.diff(sp.z_ref) / np.diff(sp.s)) * 100
            segment = {"spline_id": sid, "length_m": sp.length,
                                    "xy_ends_m": [endpoints[(sid, "start")], endpoints[(sid, "end")]],
                                    "class": defs[sid][1]["source"].get("cls"),
                                    "max_grade_pct": float(grade.max()) if grade.size else 0,
                                    "chord_sag_m": float(np.max(chord - sp.z_ref)),
                                    "chord_rise_m": float(np.max(sp.z_ref - chord)),
                                    "max_abs_bank_deg": float(np.abs(sp.bank_deg).max()),
                                    "missing_terrain_stations": sp.z_raw_nan_count}
            # First return may contain deck, vegetation, vehicles or parapets.
            # Record lateral samples and their spread; do not call them ground.
            offsets = sp.width[:, None] * np.array([-0.3, -0.15, 0, 0.15, 0.3])[None, :]
            normal = np.column_stack([-sp.t_h_xy[:, 1], sp.t_h_xy[:, 0]])
            x = sp.xy[:, 0, None] + offsets * normal[:, 0, None] + hf.origin_E
            y = sp.xy[:, 1, None] + offsets * normal[:, 1, None] + hf.origin_N
            heights = sample_dsm(dsm, x, y)
            segment["samples"] = {"s_m": finite_list(sp.s), "terrain_z_m": finite_list(sp.z_raw),
                                  "built_z_m": finite_list(sp.z_ref),
                                  "dsm_centre_m": finite_list(heights[:, 2]),
                                  "dsm_p20_m": finite_list(np.nanpercentile(heights, 20, axis=1)),
                                  "dsm_p80_m": finite_list(np.nanpercentile(heights, 80, axis=1))}
            row["segments"].append(segment)
        row["length_m"] = sum(s["length_m"] for s in row["segments"])
        if row["status"] == "measured_chain":
            row["endpoint_chord_grade_pct"] = (100 * abs(row["ends"][1]["built_z_m"] -
                                                        row["ends"][0]["built_z_m"]) / row["length_m"])
            row["both_ends_surveyed"] = all(e["raw_z_m"] is not None for e in row["ends"])
            row["both_ends_have_ground_approaches"] = all(e["ground_approaches"] for e in row["ends"])
        result.append(row)
    result.sort(key=lambda r: -max(s["chord_sag_m"] + s["chord_rise_m"] for s in r["segments"]))
    report = {"source": {"survey": str(args.survey.resolve()), "survey_sampling": hf.sampling,
                         "streetscape": str(args.streetscape.resolve()),
                         "document_sha256": files, "survey_manifest_sha256": sha256(args.survey / "landscape_manifest.json"),
                         "dsm_vrt": str(args.dsm.resolve()), "dsm_vrt_sha256": sha256(args.dsm),
                         "tool_sha256": sha256(__file__)},
              "snap_m": args.snap_m, "groups": result,
              "summary": {"structure_splines": len(structures), "groups": len(groups),
                          "by_kind": dict(Counter(r["kind"] for r in result)),
                          "status": dict(Counter(r["status"] for r in result)),
                          "groups_crossing_documents": sum(len(r["documents"]) > 1 for r in result),
                          "chains_with_ground_approaches_both_ends": sum(r.get("both_ends_have_ground_approaches", False) for r in result),
                          "elapsed_s": round(time.time() - start, 2)},
              "note": "Read-only baseline. Endpoint chords are candidate models, not surveyed deck heights or accepted fixes."}
    atomic_json(args.out, report)
    print(json.dumps(report["summary"], indent=2))
    for row in result[:8]:
        print(row["id"], row["kind"], row["status"], "segments", len(row["splines"]),
              "max current grade", round(max(s["max_grade_pct"] for s in row["segments"]), 2),
              "candidate chord grade", round(row.get("endpoint_chord_grade_pct", -1), 2))
    print("wrote", args.out)


if __name__ == "__main__":
    main()
