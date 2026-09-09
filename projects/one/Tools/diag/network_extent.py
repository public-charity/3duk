#!/usr/bin/env python3
"""Site-wide network length by class, and the corridor area each candidate fix would touch.

Cheap: reads the polyline points of every spline in the Streetscape documents (no Spline
build), sums chord lengths, and multiplies by a per-class corridor width.

Corridor half-width = carriageway/2 + kerb + pavement + verge, blend-out beyond that.
"""
import argparse, collections, glob, json, math, os

# carriageway width (m) from schema/profiles/*.json
WIDTH = {"trunk": 12.0, "primary": 10.0, "secondary": 8.5, "tertiary": 7.0, "residential": 6.0,
         "unclassified": 5.5, "living_street": 5.0, "service": 3.5, "pedestrian": 6.0,
         "footway": 2.0, "path": 2.0, "steps": 2.0, "cycleway": 2.5, "track": 3.0,
         "bridleway": 3.0, "rail": 3.4, "miniature": 3.4}
# kerb + pavement (m per side), from schema/profiles/edge_uk_kerb.json
KERB_PAVE = {"trunk": 1.925, "primary": 1.925, "secondary": 1.925, "tertiary": 1.925,
             "residential": 1.925, "unclassified": 1.925, "living_street": 1.925,
             "service": 1.925, "pedestrian": 0.0, "footway": 0.0, "path": 0.0, "steps": 0.0,
             "cycleway": 0.0, "track": 0.0, "bridleway": 0.0, "rail": 0.0, "miniature": 0.0}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dir", default="C:/Users/Shadow/code/3duk/data/thanet/out/unreal/streetscape")
    ap.add_argument("--verge-m", type=float, default=2.0)
    ap.add_argument("--blend-m", type=float, default=3.0)
    ap.add_argument("--site-area-km2", type=float, default=None,
                    help="kept (unclipped) landscape area; default from the landscape manifest")
    ap.add_argument("--landscape", default="C:/Users/Shadow/code/3duk/data/thanet/out/unreal/landscape")
    ap.add_argument("--out", required=True)
    args = ap.parse_args()

    L = collections.Counter()
    N = collections.Counter()
    for p in sorted(glob.glob(os.path.join(args.dir, "site_x*_y*.json"))):
        doc = json.load(open(p, encoding="utf-8"))
        for s in doc["splines"]:
            src = s.get("source") or {}
            if src.get("layer") not in ("roads", "rail"):
                continue
            cls = src.get("cls") or "?"
            pts = s["points"]
            d = 0.0
            for a, b in zip(pts, pts[1:]):
                d += math.hypot(b["x"] - a["x"], b["y"] - a["y"])
            L[cls] += d
            N[cls] += 1

    man = json.load(open(os.path.join(args.landscape, "landscape_manifest.json"), encoding="utf-8"))
    res = int(man["res"])
    n_tiles = len(man["tiles"])
    clipped_cells = int(man.get("clipped_cells_total", 0))
    kept_km2 = (n_tiles * (res - 1) ** 2 - clipped_cells) / 1e6
    if args.site_area_km2:
        kept_km2 = args.site_area_km2

    rows = {}
    tot_len = tot_core = tot_blend = 0.0
    for cls, ln in sorted(L.items(), key=lambda kv: -kv[1]):
        w = WIDTH.get(cls, 4.0)
        kp = KERB_PAVE.get(cls, 0.0)
        half_core = w / 2.0 + kp + args.verge_m
        half_all = half_core + args.blend_m
        core = ln * 2 * half_core
        allw = ln * 2 * half_all
        rows[cls] = {"splines": N[cls], "length_km": ln / 1000.0,
                     "carriageway_w_m": w, "kerb_pavement_m": kp,
                     "corridor_half_core_m": half_core, "corridor_half_total_m": half_all,
                     "core_area_km2": core / 1e6, "with_blend_area_km2": allw / 1e6}
        tot_len += ln
        tot_core += core
        tot_blend += allw

    out = {"verge_m": args.verge_m, "blend_m": args.blend_m,
           "kept_land_km2": kept_km2,
           "tiles": n_tiles, "clipped_cells_total": clipped_cells,
           "total_length_km": tot_len / 1000.0,
           "total_core_corridor_km2": tot_core / 1e6,
           "total_corridor_with_blend_km2": tot_blend / 1e6,
           "pct_of_kept_land_core": 100.0 * (tot_core / 1e6) / kept_km2,
           "pct_of_kept_land_with_blend": 100.0 * (tot_blend / 1e6) / kept_km2,
           "note": "areas double-count where corridors overlap (junctions, parallel ways); "
                   "they are an upper bound on the burned area.",
           "by_class": rows}
    json.dump(out, open(args.out, "w"), indent=1)
    print(json.dumps(out, indent=1))


if __name__ == "__main__":
    main()
