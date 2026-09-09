#!/usr/bin/env python3
"""Write ``landscape_conformed`` -- the adapter's landscape with the road corridor burned into it.

  export PATH="/c/Users/Shadow/code/3duk-env/env/Library/bin:$PATH"     # not needed: no GDAL here
  C:/Users/Shadow/code/3duk-env/env/python.exe projects/one/Tools/conform_landscape.py \
      --landscape data/thanet/out/unreal/landscape \
      --streetscape data/thanet/out/unreal/streetscape \
      --out data/thanet/out/unreal/landscape_conformed

Reads the adapter's landscape product and every Streetscape site document, builds each road/rail
spline with the SAME geometry core the renderers use (so the burned surface is the road surface by
construction, not a second transcription of it), and writes a new product directory:

  hm_x*_y*.r16              the conformed heightmap             (the only bytes that differ)
  conform_delta_x*_y*.r16   int16 LE, h16_conformed - h16_survey (so the survey is recoverable cell
                            by cell and any diff is auditable)
  clip_/vis_/weight_*       copied byte for byte
  landscape_manifest.json   the source manifest + a `conform` block; `heightmap.semantics` says the
                            heights are no longer the raw survey
  conform_clamped.json      the runs where the earthwork exceeds report_delta_m, for the geometry
                            track's embankment / retaining-wall segments (BRIEF 1.1's own answer)

The road spline itself is always built on the UNCONFORMED landscape: the road drapes on the survey
(BRIEF 1.1), and the conformed product is derived from both.  Running this pass on its own output is
refused, so the burn cannot be applied twice.
"""
from __future__ import annotations

import argparse
import glob
import hashlib
import json
import os
import shutil
import subprocess
import sys
import time

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "blender"))

from streetscape import conform as C          # noqa: E402
from streetscape import io_json               # noqa: E402
from streetscape import schema as S           # noqa: E402
from streetscape.spline import Spline         # noqa: E402
from streetscape.terrain import Heightfield   # noqa: E402


def git_commit(repo):
    try:
        return subprocess.check_output(["git", "-C", repo, "rev-parse", "HEAD"],
                                       stderr=subprocess.DEVNULL).decode().strip()
    except Exception:                                                   # noqa: BLE001
        return None


def sha256(path, limit=None):
    h = hashlib.sha256()
    with open(path, "rb") as fh:
        while True:
            b = fh.read(1 << 20)
            if not b:
                break
            h.update(b)
    return h.hexdigest()


def slope_stats(z, clip, px_m):
    """Steepness exactly as step 05 measures it (central differences, degrees), over kept cells only:
    ``gy, gx = np.gradient(a); slope = degrees(atan(hypot(gx / pw, gy / ph)))``.  Recomputed for the
    conformed heights so any flattening of a cliff is visible in the manifest instead of being hidden
    behind the survey's own number."""
    a = np.array(z, dtype=np.float64)
    if clip is not None:
        a[clip != 255] = np.nan
    if not np.isfinite(a).any():
        return {"max_deg": 0.0, "p99_deg": 0.0, "cells_over_45deg": 0}
    gy, gx = np.gradient(a)
    with np.errstate(invalid="ignore"):
        sl = np.degrees(np.arctan(np.hypot(gx / px_m, gy / px_m)))
    v = sl[np.isfinite(sl)]
    if v.size == 0:
        return {"max_deg": 0.0, "p99_deg": 0.0, "cells_over_45deg": 0}
    return {"max_deg": round(float(v.max()), 3), "p99_deg": round(float(np.percentile(v, 99)), 3),
            "cells_over_45deg": int((v > 45.0).sum())}


def pct(v, q):
    v = np.asarray(v, dtype=np.float64)
    return float(np.percentile(v, q)) if v.size else 0.0


def dist(v):
    v = np.asarray(v, dtype=np.float64)
    v = v[np.isfinite(v)]
    if v.size == 0:
        return {"n": 0}
    return {"n": int(v.size), "min": float(v.min()), "max": float(v.max()),
            "p99": pct(v, 99), "p95": pct(v, 95), "p50": pct(v, 50), "mean": float(v.mean())}


def runs_of(mask, s, values, side, kind):
    """Contiguous station runs where mask is true, as [{s0, s1, side, max_m}]."""
    out = []
    if not mask.any():
        return out
    idx = np.flatnonzero(mask)
    breaks = np.flatnonzero(np.diff(idx) > 1)
    starts = np.concatenate([[0], breaks + 1])
    ends = np.concatenate([breaks, [len(idx) - 1]])
    for a, b in zip(starts, ends):
        i0, i1 = idx[a], idx[b]
        seg = values[i0:i1 + 1]
        j = int(np.nanargmax(np.abs(seg)))
        out.append({"s0_m": round(float(s[i0]), 3), "s1_m": round(float(s[i1]), 3),
                    "side": "left" if side == S.LEFT else "right", "kind": kind,
                    "worst_m": round(float(seg[j]), 4)})
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--landscape", default="data/thanet/out/unreal/landscape")
    ap.add_argument("--streetscape", default="data/thanet/out/unreal/streetscape")
    ap.add_argument("--out", default="data/thanet/out/unreal/landscape_conformed")
    ap.add_argument("--extra-doc", action="append", default=[])
    ap.add_argument("--limit", type=int, default=0, help="stop after N site documents (smoke runs)")
    ap.add_argument("--sink-m", type=float, default=C.CorridorParams.sink_m)
    ap.add_argument("--verge-m", type=float, default=C.CorridorParams.verge_m)
    ap.add_argument("--blend-min-m", type=float, default=C.CorridorParams.blend_min_m)
    ap.add_argument("--blend-max-m", type=float, default=C.CorridorParams.blend_max_m)
    ap.add_argument("--batter-deg", type=float, default=C.CorridorParams.batter_deg)
    ap.add_argument("--report-delta-m", type=float, default=C.CorridorParams.report_delta_m)
    ap.add_argument("--clamp-m", type=float, default=C.CorridorParams.clamp_m)
    ap.add_argument("--report", default=None, help="where to write the run report (default <out>/conform_report.json)")
    args = ap.parse_args()

    t0 = time.time()
    params = C.CorridorParams(sink_m=args.sink_m, verge_m=args.verge_m, blend_min_m=args.blend_min_m,
                              blend_max_m=args.blend_max_m, batter_deg=args.batter_deg,
                              report_delta_m=args.report_delta_m, clamp_m=args.clamp_m)
    src = os.path.abspath(args.landscape).replace("\\", "/")
    dst = os.path.abspath(args.out).replace("\\", "/")
    if src == dst:
        sys.exit("refusing to write over the source landscape product")
    man = json.load(open(os.path.join(src, "landscape_manifest.json"), encoding="utf-8"))
    if "conform" in man:
        sys.exit("%s is already a conformed product (its manifest has a `conform` block): the burn "
                 "must start from the adapter's landscape, or it would be applied twice" % src)
    grid = C.MosaicGrid.from_manifest(man)
    print("grid %d x %d (%d tiles listed)" % (grid.W, grid.H, len(man.get("tiles", []))), flush=True)

    hf = Heightfield.from_landscape_dir(src)
    print("heightfield: %d tiles loaded, %.1f s" % (len(hf.tiles), time.time() - t0), flush=True)

    def z_raw_at(x, y):
        return hf.sample(np.asarray(x, dtype=np.float64), np.asarray(y, dtype=np.float64))

    acc = C.ConformAccumulator(grid)
    files = sorted(glob.glob(os.path.join(args.streetscape, "site_x*_y*.json")))
    if args.limit:
        files = files[:args.limit]
    files += list(args.extra_doc)
    clamped = []
    per_class = {}
    n_docs = 0
    skipped = []
    earth_all = []
    for path in files:
        site = io_json.load_site(path)
        for sdef in site.splines:
            layer = (sdef.source.layer if sdef.source is not None else None)
            if layer not in params.layers or sdef.profile_ids.road is None:
                continue
            cls = (sdef.source.cls if sdef.source is not None else None) or "?"
            try:
                sp = Spline(sdef, site, hf)
            except Exception as e:                                      # noqa: BLE001
                skipped.append([os.path.basename(path), sdef.id, repr(e)[:160]])
                acc.stats["splines_skipped"] += 1
                continue
            if any("no terrain under any station" in w for w in sp.warnings):
                # z_ref would be 0 m: burning that would dig a crater in ground the survey never saw
                skipped.append([os.path.basename(path), sdef.id, "no terrain under any station"])
                acc.stats["splines_skipped"] += 1
                continue
            for cx, cy, z, rank, u in C.spline_targets(sp, params, z_raw_at, acc.stats):
                col = cx.astype(np.int64)
                row = (grid.H - 1) - cy.astype(np.int64)
                ok = (col >= 0) & (col < grid.W) & (row >= 0) & (row < grid.H)
                acc.add(col[ok], row[ok], z[ok], rank[ok], u[ok])
            acc.stats["splines"] += 1
            shelf = C.shelf_levels(sp, params, z_raw_at)
            e_sp = []
            for side in (S.LEFT, S.RIGHT):
                e = shelf[side]["earthwork_m"]
                e_sp.append(e[np.isfinite(e)])
                big = np.isfinite(e) & (np.abs(e) > params.report_delta_m)
                for r in runs_of(big, sp.s, e, side, "fill_or_cut"):
                    r["spline_id"] = sp.id
                    r["cls"] = cls
                    r["doc"] = os.path.basename(path)
                    clamped.append(r)
            if e_sp:
                e_cat = np.concatenate(e_sp)
                d = per_class.setdefault(cls, {"splines": 0, "stations": 0, "max_fill_m": 0.0,
                                               "max_cut_m": 0.0, "abs_sum": 0.0})
                d["splines"] += 1
                d["stations"] += int(e_cat.size)
                if e_cat.size:
                    d["max_fill_m"] = max(d["max_fill_m"], float(e_cat.max()))
                    d["max_cut_m"] = min(d["max_cut_m"], float(e_cat.min()))
                    d["abs_sum"] += float(np.abs(e_cat).sum())
                    earth_all.append(e_cat.astype(np.float32))
        n_docs += 1
        if n_docs % 10 == 0:
            print("  %d/%d docs, %d splines, %.0f s" % (n_docs, len(files), acc.stats["splines"],
                                                        time.time() - t0), flush=True)
    stats = acc.finish()
    print("stamped: %s, %.0f s" % (json.dumps(stats), time.time() - t0), flush=True)

    # ---- write the product ---------------------------------------------------------------
    os.makedirs(dst, exist_ok=True)
    enc = man["heightmap"]["z_encoding"]
    per_unit = float(enc["per_unit"])
    offset = float(enc["offset"])
    res = grid.res
    key2 = acc.key
    z2 = acc.z
    tiles_out = []
    slope_rows = []
    total_changed = 0
    max_fill = 0.0
    max_cut = 0.0
    all_delta = []
    copied = 0
    for t in man.get("tiles", []):
        i, j = int(t["x"]), int(t["y"])
        files_t = t.get("files", {})
        hm_name = files_t.get("heightmap") or "hm_x%d_y%d.r16" % (i, j)
        hm_path = os.path.join(src, hm_name)
        if not os.path.isfile(hm_path):
            tiles_out.append({"x": i, "y": j, "cells_changed": 0, "note": "no heightmap in source"})
            continue
        h16 = np.fromfile(hm_path, dtype="<u2").reshape(res, res).astype(np.int64)
        r0, c0 = grid.tile_origin(i, j)
        k = key2[r0:r0 + res, c0:c0 + res]
        zt = z2[r0:r0 + res, c0:c0 + res]
        mask = (k != C.KEY_NONE) & np.isfinite(zt)
        clip = None
        clip_name = files_t.get("clip")
        if clip_name and os.path.isfile(os.path.join(src, clip_name)):
            clip = np.fromfile(os.path.join(src, clip_name), dtype=np.uint8).reshape(res, res)
            mask &= clip == 255              # never write a cell the clip declares absent
        new = h16.copy()
        if mask.any():
            q = np.rint(np.asarray(zt, dtype=np.float64)[mask] * per_unit) + offset
            new[mask] = np.clip(q, 0, 65535).astype(np.int64)
        delta = (new - h16).astype(np.int32)
        changed = int((delta != 0).sum())
        total_changed += changed
        new.astype("<u2").tofile(os.path.join(dst, hm_name))
        d_m = delta.astype(np.float64) / per_unit
        if changed:
            np.clip(delta, -32768, 32767).astype("<i2").tofile(
                os.path.join(dst, "conform_delta_x%d_y%d.r16" % (i, j)))
            nz = d_m[delta != 0]
            max_fill = max(max_fill, float(nz.max()))
            max_cut = min(max_cut, float(nz.min()))
            all_delta.append(nz.astype(np.float32))
        row = {"x": i, "y": j, "cells_changed": changed,
               "max_fill_m": round(float(d_m.max()), 4) if changed else 0.0,
               "max_cut_m": round(float(d_m.min()), 4) if changed else 0.0,
               "delta_file": ("conform_delta_x%d_y%d.r16" % (i, j)) if changed else None}
        if changed:
            px = float(man.get("px_m", 1.0))
            zb = (h16.astype(np.float64) - offset) / per_unit
            za = (new.astype(np.float64) - offset) / per_unit
            cm = clip
            sb = slope_stats(zb, cm, px)
            sa = slope_stats(za, cm, px)
            row["slope_max_deg_survey"] = sb["max_deg"]
            row["slope_max_deg_conformed"] = sa["max_deg"]
            row["cells_over_45deg_survey"] = sb["cells_over_45deg"]
            row["cells_over_45deg_conformed"] = sa["cells_over_45deg"]
            slope_rows.append((i, j, sb, sa))
        tiles_out.append(row)
    # everything that is not a heightmap is copied byte for byte
    for name in sorted(os.listdir(src)):
        if name.startswith("hm_") or name == "landscape_manifest.json":
            continue
        s_path = os.path.join(src, name)
        if os.path.isfile(s_path):
            shutil.copyfile(s_path, os.path.join(dst, name))
            copied += 1

    deltas = np.concatenate(all_delta) if all_delta else np.zeros(0, dtype=np.float32)
    earth = np.concatenate(earth_all) if earth_all else np.zeros(0, dtype=np.float32)
    conform_block = {
        "source": os.path.relpath(src, dst).replace("\\", "/"),
        "source_abs": src,
        "generator": "projects/one/Tools/conform_landscape.py",
        "geometry_core": "projects/one/Tools/blender/streetscape/conform.py",
        "commit": git_commit(os.path.join(HERE, "..", "..")),
        "generated_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "corridor": params.to_json(),
        "streetscape": os.path.abspath(args.streetscape).replace("\\", "/"),
        "splines_burned": stats["splines"],
        "splines_skipped": stats["splines_skipped"],
        "cells_changed": total_changed,
        "cells_touched": stats["cells_touched"],
        "contributions": stats["contributions"],
        "arbitrations": stats["arbitrations"],
        "cells_clamped": int(stats.get("cells_clamped", 0)),
        "clamp_note": ("outside the built surface and its apron the ground moves by at most clamp_m; the "
                       "built surface itself is exact, which is what the acceptance gate measures"),
        "arbitration_max_drop_m": round(stats["arbitration_max_drop_m"], 4),
        "max_fill_m": round(max_fill, 4),
        "max_cut_m": round(max_cut, 4),
        "delta_m": dist(deltas),
        "abs_delta_m": dist(np.abs(deltas)),
        "earthwork_at_verge_edge_m": dist(earth),
        "clamped_runs": len(clamped),
        "slope_qa": {
            "tiles_measured": len(slope_rows),
            "max_deg_survey": round(max([r[2]["max_deg"] for r in slope_rows] or [0.0]), 3),
            "max_deg_conformed": round(max([r[3]["max_deg"] for r in slope_rows] or [0.0]), 3),
            "cells_over_45deg_survey": int(sum(r[2]["cells_over_45deg"] for r in slope_rows)),
            "cells_over_45deg_conformed": int(sum(r[3]["cells_over_45deg"] for r in slope_rows)),
            "worst_flattening_deg": round(max([r[2]["max_deg"] - r[3]["max_deg"] for r in slope_rows] or [0.0]), 3),
            "worst_flattening_tile": (lambda rs: [rs[0][0], rs[0][1]] if rs else None)(
                sorted(slope_rows, key=lambda r: -(r[2]["max_deg"] - r[3]["max_deg"]))),
            "note": "over the tiles the burn changed only; site-wide slope_qa above is the survey's and is "
                    "left untouched, so a consumer can see both. A cliff the burn flattened would show here.",
        },
        "delta_raster": {"file": "conform_delta_x{i}_y{j}.r16", "dtype": "int16 little-endian, row-major",
                         "shape": [res, res],
                         "decode": "z_survey_m = (h16_conformed - delta) / %g - %g / %g"
                                   % (per_unit, offset, per_unit),
                         "note": "h16_conformed - h16_survey, present only for tiles with a change; "
                                 "absent file = this tile is byte-identical to the source product"},
        "note": ("The landscape under the road corridor is the ROAD, not the survey: the built "
                 "surface (carriageway + kerb + pavement), a verge and a blend are written from the "
                 "spline heights of the geometry core.  Everything outside the corridor is the "
                 "source product byte for byte.  The survey is at data/<site>/out/terrain and the "
                 "unconformed landscape at the `source` path above; both are untouched by this pass."),
    }
    man2 = dict(man)
    hm = dict(man2["heightmap"])
    hm["semantics"] = ("h16 of step 05's filled DTM, CONFORMED TO THE ROAD CORRIDOR -- not the raw "
                       "survey.  See the `conform` block and conform_delta_x{i}_y{j}.r16.")
    man2["heightmap"] = hm
    man2["conform"] = conform_block
    man2["conform_tiles"] = tiles_out
    with open(os.path.join(dst, "landscape_manifest.json"), "w", encoding="utf-8", newline="\n") as fh:
        json.dump(man2, fh, indent=1)
        fh.write("\n")
    with open(os.path.join(dst, "conform_clamped.json"), "w", encoding="utf-8", newline="\n") as fh:
        json.dump({"threshold_m": params.report_delta_m,
                   "note": ("runs where the earthwork at the far edge of the verge exceeds the "
                            "threshold: the burn does NOT flatten these away silently, it writes them "
                            "here so Renderer B can carry an embankment or retaining wall (BRIEF 1.1)"),
                   "runs": sorted(clamped, key=lambda r: -abs(r["worst_m"]))}, fh, indent=1)
        fh.write("\n")
    report = {"ok": True, "elapsed_s": round(time.time() - t0, 1), "docs": n_docs,
              "out": dst, "conform": conform_block, "by_class": per_class,
              "skipped": skipped[:200], "skipped_total": len(skipped),
              "files_copied": copied, "tiles": len(tiles_out)}
    rpath = args.report or os.path.join(dst, "conform_report.json")
    os.makedirs(os.path.dirname(os.path.abspath(rpath)), exist_ok=True)
    with open(rpath, "w", encoding="utf-8", newline="\n") as fh:
        json.dump(report, fh, indent=1)
        fh.write("\n")
    print(json.dumps({k: v for k, v in report.items() if k not in ("skipped", "by_class")}, indent=1))
    print("CONFORM_OK %s" % rpath)


if __name__ == "__main__":
    main()
