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
from pathlib import Path

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "blender"))

from streetscape import conform as C                    # noqa: E402
from streetscape import io_json                         # noqa: E402
from streetscape import schema as S                     # noqa: E402
from streetscape.spline import JunctionPlan, Spline     # noqa: E402
from streetscape.terrain import Heightfield             # noqa: E402


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
    ap.add_argument("--survey-sampling", default="landscape_triangulated",
                    choices=["bilinear", "landscape_triangulated"],
                    help="sampling used to build road geometry; match the Unreal site terrain source")
    ap.add_argument("--streetscape", default="data/thanet/out/unreal/streetscape")
    ap.add_argument("--out", default="data/thanet/out/unreal/landscape_conformed")
    ap.add_argument("--extra-doc", action="append", default=[])
    ap.add_argument("--limit", type=int, default=0, help="stop after N site documents (smoke runs)")
    ap.add_argument("--sink-m", type=float, default=C.CorridorParams.sink_m,
                    help="the FLOOR of the per-station sink (conform.sink_profile)")
    ap.add_argument("--sink-max-m", type=float, default=C.CorridorParams.sink_max_m,
                    help="the CAP of the per-station sink")
    ap.add_argument("--sink-cover-frac", type=float, default=C.CorridorParams.sink_cover_frac,
                    help="fraction of the built block's own cover the sink may use")
    ap.add_argument("--sink-taper", type=float, default=C.CorridorParams.sink_taper,
                    help="cross-section slope the sink field may use between the two sides' depths "
                         "and out into the verge (conform.sink_field)")
    ap.add_argument("--sink-flat-m", type=float, default=C.CorridorParams.sink_flat_m,
                    help="how far either side of a covered face the sink is held flat before the "
                         "taper starts (conform.sink_field)")
    ap.add_argument("--sink-covered-max-m", type=float, default=C.CorridorParams.sink_covered_max_m,
                    help="the cap on the sink away from any covered face (conform.sink_field)")
    ap.add_argument("--verge-m", type=float, default=C.CorridorParams.verge_m)
    ap.add_argument("--only-doc", action="append", default=[],
                    help="restrict the burn to site documents whose basename contains this string "
                         "(repeatable).  For A/B parameter runs: the product is still complete, but "
                         "only these documents' corridors are burned into it.")
    ap.add_argument("--blend-min-m", type=float, default=C.CorridorParams.blend_min_m)
    ap.add_argument("--blend-max-m", type=float, default=C.CorridorParams.blend_max_m)
    ap.add_argument("--batter-deg", type=float, default=C.CorridorParams.batter_deg)
    ap.add_argument("--report-delta-m", type=float, default=C.CorridorParams.report_delta_m)
    ap.add_argument("--clamp-m", type=float, default=C.CorridorParams.clamp_m)
    ap.add_argument("--no-junctions", action="store_true",
                    help="do not burn the junction discs (the corridor bands only).  Leaves the "
                         "wedges between adjacent arms as blend, where the survey may rise back "
                         "through Renderer A's junction patch -- 814 of 87,969 patch vertices did, "
                         "worst 2.890 m.  For A/B measurement only.")
    ap.add_argument("--report", default=None, help="where to write the run report (default <out>/conform_report.json)")
    ap.add_argument("--checkpoint-dir", default=None, help="persist sparse stamping state, keyed by source bytes and parameters")
    ap.add_argument("--checkpoint-every", type=int, default=4)
    ap.add_argument("--max-docs", type=int, default=0, help="process at most this many new documents, then exit 2; requires checkpoint-dir")
    args = ap.parse_args()
    if args.max_docs < 0 or args.checkpoint_every <= 0:
        ap.error("max-docs must be nonnegative and checkpoint-every positive")
    if args.max_docs and not args.checkpoint_dir:
        ap.error("max-docs requires checkpoint-dir")
    if args.checkpoint_dir:
        from phase1_qc import run_lock
        Path(args.checkpoint_dir).mkdir(parents=True, exist_ok=True)
        with run_lock(Path(args.checkpoint_dir)/"run.lock"):
            return run(args, ap)
    return run(args, ap)


def run(args, ap):
    files = sorted(glob.glob(os.path.join(args.streetscape, "site_x*_y*.json")))
    for token in args.only_doc:
        if not any(token in os.path.basename(f) for f in files):
            ap.error("--only-doc matched no documents: " + token)
    if args.only_doc:
        files = [f for f in files if any(t in os.path.basename(f) for t in args.only_doc)]
    if args.limit:
        files = files[:args.limit]
    files += list(args.extra_doc)
    if not files:
        ap.error("no site documents: an empty conform is not a successful product")
    if (args.only_doc or args.limit) and os.path.abspath(args.out) == os.path.abspath("data/thanet/out/unreal/landscape_conformed"):
        ap.error("subset conform requires a separate --out; refusing to replace the full-site product")

    t0 = time.time()
    params = C.CorridorParams(sink_m=args.sink_m, sink_max_m=args.sink_max_m,
                              sink_cover_frac=args.sink_cover_frac, sink_taper=args.sink_taper, sink_flat_m=args.sink_flat_m,
                              sink_covered_max_m=args.sink_covered_max_m,
                              verge_m=args.verge_m, blend_min_m=args.blend_min_m,
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
    hf.sampling = args.survey_sampling
    print("heightfield: %d tiles loaded, %.1f s" % (len(hf.tiles), time.time() - t0), flush=True)

    def z_raw_at(x, y):
        return hf.sample(np.asarray(x, dtype=np.float64), np.asarray(y, dtype=np.float64))

    acc = C.ConformAccumulator(grid)
    clamped = []
    per_class = {}
    n_docs = 0
    skipped = []
    structures = []
    earth_all = []
    jstats = {"junctions_seen": 0, "junctions_burned": 0, "junctions_no_patch": 0,
              "junctions_missing_arm": 0, "cells_stamped": 0}
    checkpoint = None
    resumed_docs = 0
    if args.checkpoint_dir:
        from conform_checkpoint import ConformCheckpoint, checkpoint_inputs
        inputs, config = checkpoint_inputs(args, files, HERE)
        checkpoint = ConformCheckpoint(args.checkpoint_dir, inputs, config)
        prior = checkpoint.load(acc)
        if prior:
            n_docs = resumed_docs = prior["n_docs"]
            if prior["completed_documents"] != files[:n_docs]:
                raise ValueError("checkpoint document coverage does not match input order")
            clamped, per_class, skipped, structures = (prior[k] for k in ("clamped", "per_class", "skipped", "structures"))
            earth_all, jstats = prior["earth_all"], prior["jstats"]
        print("checkpoint: %s, resumed %d/%d documents" % (checkpoint.path, resumed_docs, len(files)), flush=True)
    for path in files[resumed_docs:]:
        site = io_json.load_site(path)
        ok_for_junction = {}                 # spline id -> the def, for the arms worth building
        for sdef in site.splines:
            layer = (sdef.source.layer if sdef.source is not None else None)
            if layer not in params.layers or sdef.profile_ids.road is None:
                continue
            cls = (sdef.source.cls if sdef.source is not None else None) or "?"
            if sdef.flags is not None and (sdef.flags.bridge or sdef.flags.tunnel):
                # A STRUCTURE, not a road on the ground.  The pipeline's own contract is that a
                # bridge or tunnel way carries the elevation of the ground UNDER it, unadjusted
                # (sources/derive/06_build_networks.py:15-16, 11_linear_features.py:22) -- the
                # invented +3 m / -4 m offsets were removed on purpose.  So burning this way's
                # corridor would conform the ground to a surface that is not the ground: at the
                # Chatham Main Line bridge over Minnis Road the rail way dives from 11.2 m to 8.5 m
                # in 18 m because that is the ROAD underneath, and the burn cut that dive into the
                # ground the road itself is built on.  The ground under a structure belongs to
                # whatever passes below it, and that way burns it.
                kind = "bridge" if sdef.flags.bridge else "tunnel"
                skipped.append([os.path.basename(path), sdef.id, "structure: %s (not burned)" % kind])
                structures.append({"spline_id": sdef.id, "cls": cls, "kind": kind,
                                   "layer": layer, "doc": os.path.basename(path)})
                acc.stats["splines_structure"] = acc.stats.get("splines_structure", 0) + 1
                continue
            try:
                sp = Spline(sdef, site, hf)
            except Exception as e:                                      # noqa: BLE001
                raise RuntimeError("%s: %s failed to build; refusing conformed product" % (path, sdef.id)) from e
            if getattr(sp, "trimmed", False):
                # The burn must claim the ground under the junction disc, and only the UNTRIMMED
                # extent does (conform.py's JUNCTIONS note).  Spline() trims only when a trim is
                # handed in and this call hands none in, so a trimmed spline here means the default
                # changed underneath the burn -- fail loudly rather than leave a hole per junction.
                sys.exit("%s: %s came back TRIMMED (%.3f/%.3f m).  The corridor burn must see the "
                         "untrimmed extent or the ground under every junction disc is left as survey."
                         % (os.path.basename(path), sdef.id, sp.trim_m[0], sp.trim_m[1]))
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
            # this spline's corridor was burned, so it is fit to be an arm: it has a road profile, it
            # is not a structure, it built, and it has survey ground under it.  A junction whose arm
            # is missing any of that is left to its arms' corridors rather than burned from a patch
            # whose height came from a spline this pass refused.
            ok_for_junction[sdef.id] = sdef
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
        # -- the junction discs -------------------------------------------------------------
        # A corridor is a band along ONE spline; between two arms, close to the node, there are
        # wedges no band covers as built surface.  Renderer A lays tarmac across them, and before
        # this pass existed 814 of 87,969 patch vertices over the isle sat BELOW the conformed
        # ground, worst 2.890 m (Saved/Diag/junction_isle.json) -- ground standing up through the
        # middle of a crossroads.  The patch polygon is rasterised here with the geometry core's own
        # `junction_target_z` as its target, so what is burned is the surface Renderer A builds.
        if not args.no_junctions and site.junctions:
            plan = JunctionPlan(site)
            arm_ids = sorted({a.spline_id for arms in plan.arms.values() for a in arms})
            tsp = {}
            for sid in arm_ids:
                sdef = ok_for_junction.get(sid)
                if sdef is None:
                    continue
                try:
                    # TRIMMED: the patch is bounded by the arms' trimmed end rows, so the frames it
                    # is built from must be the trimmed ones.  The corridor above deliberately used
                    # the untrimmed extent; both are the same surface, they differ only in which
                    # stations are active.
                    tsp[sid] = Spline(sdef, site, hf, trim=plan.trim_for(sid))
                except Exception as e:                                  # noqa: BLE001
                    raise RuntimeError("%s: junction arm %s failed to build" % (path, sid)) from e
            for jid in sorted(plan.arms):
                jstats["junctions_seen"] += 1
                if any(a.spline_id not in tsp for a in plan.arms[jid]):
                    jstats["junctions_missing_arm"] += 1
                    continue
                out = C.junction_targets(plan, jid, tsp, params)
                if out is None:
                    jstats["junctions_no_patch"] += 1
                    continue
                jx, jy, jz, jrank, ju = out
                col = jx.astype(np.int64)
                row = (grid.H - 1) - jy.astype(np.int64)
                ok = (col >= 0) & (col < grid.W) & (row >= 0) & (row < grid.H)
                acc.add(col[ok], row[ok], jz[ok], jrank[ok], ju[ok])
                jstats["junctions_burned"] += 1
                jstats["cells_stamped"] += int(ok.sum())
        n_docs += 1
        budget_done = bool(args.max_docs and n_docs-resumed_docs >= args.max_docs)
        if checkpoint and (n_docs % args.checkpoint_every == 0 or budget_done or n_docs == len(files)):
            state_path = checkpoint.save(acc, {"n_docs": n_docs, "completed_documents": files[:n_docs],
                                              "clamped": clamped, "per_class": per_class, "skipped": skipped,
                                              "structures": structures, "jstats": jstats}, earth_all)
            print("CHECKPOINT %d/%d docs: %s" % (n_docs, len(files), state_path), flush=True)
        if budget_done and n_docs < len(files):
            print("CONFORM_PENDING: no product written; repeat command to resume", flush=True)
            return 2
        if n_docs % 10 == 0:
            print("  %d/%d docs, %d splines, %.0f s" % (n_docs, len(files), acc.stats["splines"],
                                                        time.time() - t0), flush=True)
    stats = acc.finish()
    if checkpoint:
        checkpoint.verify_inputs()
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
        "survey_sampling": args.survey_sampling,
        "scope": "subset" if args.only_doc or args.limit else "full",
        "input_documents": {os.path.basename(path): sha256(path) for path in files},
        "commit": git_commit(os.path.join(HERE, "..", "..")),
        "generated_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "corridor": params.to_json(),
        "streetscape": os.path.abspath(args.streetscape).replace("\\", "/"),
        "splines_burned": stats["splines"],
        "splines_skipped": stats["splines_skipped"],
        "splines_structure": int(stats.get("splines_structure", 0)),
        "structure_note": ("ways flagged bridge or tunnel are NOT burned.  Their elevation is the "
                           "ground under the structure, unadjusted (sources/derive/06_build_networks.py "
                           "15-16), so conforming the ground to them would cut the deck's dive into "
                           "the ground the way underneath is built on.  The ground under a structure "
                           "belongs to whatever passes below, and that way burns it.  The list is "
                           "conform_structures.json.  The DECK height itself is a z_ref question in "
                           "the shared spline layer and is NOT decided here, and it is the open half "
                           "of Alex's 'above ground as necessary': measured over the isle by "
                           "projects/one/Tools/road_fusion_audit.py (structures_summary of "
                           "Saved/Clearance/fusion_after_v4.json), a bridge deck falls below the "
                           "straight line between its own two ends by a median of 1.909 m, a p95 of "
                           "5.408 m and a maximum of 12.595 m (rail:27641607:0, a 99 m rail bridge, "
                           "at a 161 % grade); 58 of 92 bridges sag more than 1 m and 71 of 92 carry "
                           "a grade over 25 %.  That is the railway 'leaving the ground at bridges' "
                           "of renders/b1cd3e5/INDEX.md defect 8, seen from underneath."),
        "junctions": dict(jstats, burned=(not args.no_junctions), note=(
            "Renderer A's junction patch is burned as BUILT SURFACE with the geometry core's own "
            "road.junction_target_z as its target, plus an apron of apron_m.  A corridor is a band "
            "along one spline and leaves wedges between adjacent arms that only the patch covers; "
            "without this the survey rises back through the middle of a crossroads (measured before "
            "it existed: 814 of 87,969 patch vertices below the conformed ground, worst 2.890 m).  "
            "The disc's sink is the shallowest of its arms', so the disc and its arms cannot step.  "
            "junctions_missing_arm are junctions with an arm this pass did not burn (a bridge, a "
            "tunnel, or a spline with no survey ground under it): they keep their arms' corridors.  "
            "MEASURED over the isle, patch vertices below the conformed ground: 814 of 87,969 "
            "without the disc burn, 94 with it (build.py --junction-audit --clearance-landscape, "
            "Saved/Clearance/junction_isle_v4.json vs Saved/Diag/junction_isle.json).  All 91 that "
            "an independent attribution can place belong to 7 junctions with a BRIDGE arm "
            "(Saved/Clearance/why_patch_low.py): the deck there carries the elevation of the ground "
            "under the structure, so its patch is not a surface any ground should be conformed to.  "
            "That residual is a z_ref question in the shared spline layer, not a conform one.")),
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
    # The source manifest's roundtrip block measures the SURVEY against its own GeoTIFF and tells a
    # consumer it may assert the two agree to the quantum.  Inside the corridor that is false by up to
    # `max_fill_m`, so carrying it forward unchanged is a lie by omission (open defect 4 of
    # BRIEF.md 9.2).  It is kept -- it is still true OUTSIDE the corridor and the delta rasters make
    # the difference recoverable -- but it is re-scoped in words, here, on this product.
    if isinstance(hm.get("roundtrip_measured"), dict):
        rt = dict(hm["roundtrip_measured"])
        rt["scope"] = ("MEASURED ON THE SOURCE (unconformed) PRODUCT, and true here only for cells "
                       "this pass did not change.  Inside the corridor the heights are the road, not "
                       "the survey: see conform.abs_delta_m and conform_delta_x{i}_y{j}.r16, which "
                       "recover the survey cell by cell.")
        rt["cells_changed_by_conform"] = total_changed
        rt["max_abs_change_by_conform_m"] = round(max(abs(max_fill), abs(max_cut)), 4)
        hm["roundtrip_measured"] = rt
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
    with open(os.path.join(dst, "conform_structures.json"), "w", encoding="utf-8", newline="\n") as fh:
        json.dump({"note": conform_block["structure_note"],
                   "count": len(structures),
                   "by_kind": {k: sum(1 for s in structures if s["kind"] == k) for k in ("bridge", "tunnel")},
                   "splines": sorted(structures, key=lambda r: (r["kind"], r["spline_id"]))}, fh, indent=1)
        fh.write("\n")
    # Announce the product in the adapter's own site index.  Until this ran, `unreal_manifest.json`
    # listed `landscape` and not `landscape_conformed` -- so the landscape the engine imports was
    # announced by nothing but its own manifest (open defect 3 of BRIEF.md 9.2).  The adapter now
    # carries a `derived_products` block (sources/adapters/unreal.py:derived_products); this refreshes
    # the entry so the index is current without re-running the adapter.  Only that one key is
    # rewritten, and only if the index exists.
    root_index = os.path.join(os.path.dirname(dst), "unreal_manifest.json")
    index_updated = False
    if os.path.isfile(root_index):
        try:
            idx = json.load(open(root_index, encoding="utf-8"))
            entry = (idx.get("derived_products") or {}).get(os.path.basename(dst), {})
            entry.update({
                "derived_from": conform_block["source"].strip("./") or "landscape",
                "generator": conform_block["generator"],
                "manifest": "%s/landscape_manifest.json" % os.path.basename(dst),
                "written_by_this_adapter": False,
                "present": True,
                "generated_utc": conform_block["generated_utc"],
                "commit": conform_block["commit"],
                "cells_changed": conform_block["cells_changed"],
                "max_fill_m": conform_block["max_fill_m"],
                "max_cut_m": conform_block["max_cut_m"],
                "heightmap_semantics": hm["semantics"],
                # the two modelling choices, surfaced in the index rather than left three files down;
                # sources/adapters/unreal.py:derived_products writes the same keys on a full adapter run
                "sink_note": conform_block["corridor"].get("sink_note"),
                "structures_not_burned": conform_block["splines_structure"],
                "structure_note": conform_block["structure_note"],
                "junctions": {k: v for k, v in conform_block["junctions"].items() if k != "note"},
                "junction_note": conform_block["junctions"]["note"],
            })
            entry.setdefault("why", ("the road corridor burned into a copy of the landscape so the "
                                     "built street sits on the ground instead of in it"))
            idx.setdefault("derived_products", {})[os.path.basename(dst)] = entry
            with open(root_index, "w", encoding="utf-8", newline="\n") as fh:
                json.dump(idx, fh, indent=1)
                fh.write("\n")
            index_updated = True
        except Exception as e:                                          # noqa: BLE001
            print("WARNING: could not update %s: %r" % (root_index, e), flush=True)
    report = {"ok": True, "elapsed_s": round(time.time() - t0, 1), "docs": n_docs,
              "resumed_docs": resumed_docs, "processed_docs_this_run": n_docs-resumed_docs,
              "root_index_updated": index_updated, "root_index": root_index,
              "structures_not_burned": len(structures),
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
    return 0


if __name__ == "__main__":
    sys.exit(main())
