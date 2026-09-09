#!/usr/bin/env python3
"""D1 -- the same shared-edge audit on the ADAPTER product the landscape is built from.

data/<site>/out/unreal/landscape/hm_x{i}_y{j}.r16 is what the importer assembles into the
ALandscape. Unlike the GeoTIFF it has no NoData: clipped cells are filled nearest-valid and
the clip_*.r8 / vis_*.r8 masks carry the truth. So a shared edge here can disagree for two
different reasons and they must be separated:

  visible   -- both sides are kept ground (clip mask 255 on both, and not hidden by vis)
               => a false cliff the player sees
  hidden    -- at least one side is clipped or hidden by the visibility layer
               => invented values behind the Wantsum cut; never rendered

Usage:
  export PATH="/c/Users/Shadow/code/3duk-env/env/Library/bin:$PATH"
  C:/Users/Shadow/code/3duk-env/env/python.exe Tools/diag/seam_audit_r16.py --out <dir>/seam_r16.json
"""
import argparse, json, os
import numpy as np


def load(path, res):
    a = np.fromfile(path, dtype="<u2")
    if a.size != res * res:
        raise ValueError("%s: %d values" % (path, a.size))
    return a.reshape(res, res)


def load8(path, res):
    if not os.path.isfile(path):
        return None
    return np.fromfile(path, dtype=np.uint8).reshape(res, res)


def edge(a, which):
    if which == "east":
        return a[:, -1]
    if which == "west":
        return a[:, 0]
    if which == "north":
        return a[0, :]
    if which == "south":
        return a[-1, :]
    raise ValueError(which)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--landscape", default="C:/Users/Shadow/code/3duk/data/thanet/out/unreal/landscape")
    ap.add_argument("--out", required=True)
    args = ap.parse_args()
    man = json.load(open(os.path.join(args.landscape, "landscape_manifest.json"), encoding="utf-8"))
    res = int(man["res"])
    enc = man["heightmap"]["z_encoding"]
    per_unit, offset = float(enc["per_unit"]), float(enc["offset"])
    tiles = {(t["x"], t["y"]): t for t in man["tiles"]}

    cache = {}

    def get(key):
        if key not in cache:
            t = tiles[key]
            f = t["files"]
            cache[key] = (load(os.path.join(args.landscape, f["heightmap"]), res),
                          load8(os.path.join(args.landscape, f["clip"]), res),
                          load8(os.path.join(args.landscape, f["vis"]), res) if f.get("vis") else None)
        return cache[key]

    pairs = []
    for key in sorted(tiles):
        i, j = key
        for (nk, ea, eb, kind) in (((i + 1, j), "east", "west", "h"),
                                   ((i, j + 1), "north", "south", "v")):
            if nk not in tiles:
                continue
            ha, ca, va = get(key)
            hb, cb, vb = get(nk)
            A = edge(ha, ea).astype(np.int64)
            B = edge(hb, eb).astype(np.int64)
            d16 = np.abs(A - B)
            # visible = kept by the clip on BOTH sides and not hidden by the visibility layer
            # (vis weight >= 2/3*255 = 170 is a hole, DESIGN.md 9)
            ka = np.ones(res, bool) if ca is None else (edge(ca, ea) == 255)
            kb = np.ones(res, bool) if cb is None else (edge(cb, eb) == 255)
            ha_hole = np.zeros(res, bool) if va is None else (edge(va, ea) >= 170)
            hb_hole = np.zeros(res, bool) if vb is None else (edge(vb, eb) >= 170)
            vis = ka & kb & ~ha_hole & ~hb_hole
            rec = {"kind": kind, "a": list(key), "b": list(nk),
                   "n_disagree": int((d16 > 0).sum()),
                   "max_h16": int(d16.max()), "max_m": float(d16.max()) / per_unit,
                   "visible_samples": int(vis.sum()),
                   "visible_disagree": int((vis & (d16 > 0)).sum()),
                   "visible_max_h16": int(d16[vis].max()) if vis.any() else 0,
                   "visible_max_m": float(d16[vis].max()) / per_unit if vis.any() else 0.0,
                   "clip_state_a": tiles[key].get("clip_state"),
                   "clip_state_b": tiles[nk].get("clip_state"),
                   "source_fill_a": tiles[key].get("source_fill"),
                   "source_fill_b": tiles[nk].get("source_fill")}
            pairs.append(rec)
        cache.pop(key, None) if False else None

    tot = sum(p["n_disagree"] for p in pairs)
    vtot = sum(p["visible_disagree"] for p in pairs)
    vmax = max(p["visible_max_h16"] for p in pairs)
    amax = max(p["max_h16"] for p in pairs)
    bad_v = [p for p in pairs if p["visible_disagree"] > 0]
    tiles_bad = set()
    for p in bad_v:
        tiles_bad.add(tuple(p["a"])); tiles_bad.add(tuple(p["b"]))
    vd = np.concatenate([np.array([]) if not p["visible_disagree"] else
                         np.full(p["visible_disagree"], p["visible_max_m"]) for p in pairs]) \
        if pairs else np.array([])
    summary = {
        "pairs": len(pairs),
        "pairs_disagreeing_any": sum(1 for p in pairs if p["n_disagree"]),
        "pairs_disagreeing_visible": len(bad_v),
        "tiles_touching_a_visible_seam": len(tiles_bad),
        "samples_total": len(pairs) * res,
        "samples_disagree_any": tot,
        "samples_visible": sum(p["visible_samples"] for p in pairs),
        "samples_disagree_visible": vtot,
        "max_h16_any": amax, "max_m_any": amax / per_unit,
        "max_h16_visible": vmax, "max_m_visible": vmax / per_unit,
        "per_edge_visible_max_m": {
            "max": float(max(p["visible_max_m"] for p in pairs)),
            "p99": float(np.percentile([p["visible_max_m"] for p in pairs], 99)),
            "p50": float(np.percentile([p["visible_max_m"] for p in pairs], 50))},
        "worst_visible": sorted(bad_v, key=lambda p: -p["visible_max_m"])[:15],
    }
    json.dump({"summary": summary, "pairs": pairs}, open(args.out, "w"), indent=1)
    print(json.dumps(summary, indent=1)[:5000])


if __name__ == "__main__":
    main()
