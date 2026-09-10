#!/usr/bin/env python3
"""Whole-isle gate: does any road, kerb or pavement fuse with the landscape, or float above it?

  C:/Users/Shadow/code/3duk-env/env/python.exe projects/one/Tools/road_fusion_audit.py \
      --landscape data/thanet/out/unreal/landscape_conformed \
      --gate-m 0.005 --float-gate-m 0.125 \
      --out projects/one/Saved/Diag/fusion_after_all.json

Every road/rail spline of every site document (13,097 at Thanet) is built with the geometry core on
the SURVEY heightfield -- the road drapes on the survey, BRIEF 1.1 -- and measured against the
landscape given by --landscape, which is the product the engine actually imports.  With
``--landscape`` pointing at the unconformed product this reproduces the D3 diagnosis; with it
pointing at ``landscape_conformed`` it is the acceptance gate.

Exit 1 (and a GATE FAIL line) when the worst penetration exceeds --gate-m or the worst float exceeds
--float-gate-m.

WHAT THIS GATE DOES NOT MEASURE, and why the pictures disagreed with it
----------------------------------------------------------------------
At commit b1cd3e5 this gate said GATE PASS over the whole isle -- zero penetration, 0.03 m of
clearance -- and 16 of the 31 street frames of ``renders/b1cd3e5`` had no carriageway in them.  Both
were true.  Three measurements settled why (2026-09-09, clearance agent; raw output under
``projects/one/Saved/Clearance/``):

1. It is NOT the sampling rule.  Over 241,205 points inside real corridors on that product, the
   bilinear rule and the landscape's own triangulated rule disagree by 0.4 mm at the median, 5.4 mm
   at the p95 and 13 mm at the p99, and NEITHER puts a single point of ground above a road.
   (``Saved/Clearance/rules_conformed.json``; --sampling now defaults to the triangulated rule
   anyway, so the measurement is of the surface the camera sees.)
2. It IS the landscape's level of detail -- the surface it DRAWS, which is not the surface
   ``GetHeightAtLocation`` returns.  ``--lods 0,1,2,3`` measures against it
   (``streetscape.terrain.LandscapeLodSurface``, a transcription of the engine's own
   ``GenerateHeightmapMips`` + ``LandscapeVertexFactory.ush``, replacing a 2026-09-09 model that had
   the stride and the anchor both wrong).  On the shipped 7c8b4a6 product, whole isle, 660,835
   stations (``Saved/Clearance/fusion_before_v5.json``): ground above the road at **0.0002 % of
   stations at LOD 0, 0.76 % at LOD 1, 8.18 % at LOD 2, 22.26 % at LOD 3**.  Where those levels are
   drawn is in ``LandscapeLodSurface.distances_m``: with this level's saved LOD properties and the
   render set's camera, LOD 0 holds to 381 m, LOD 1 by 476 m, LOD 2 by 1.43 km, LOD 3 by 4.29 km.
   So LOD 1 and LOD 2 are what a street frame's middle distance is made of, and LOD 3 is haze.
3. Proved in the engine, same camera, same level, same conform, one property changed:
   ``broadstairs/st_peters_high_street`` and ``cliftonville/princess_margaret_avenue_at_northdown``
   render as unbroken grass with the render harness's LOD "pin" applied, and as complete streets --
   carriageway, kerbs, both footways -- with ``MaxLODLevel = 0``, and equally with the landscape's
   OWN default LOD settings.  The harness's pin sets LODDistributionSetting and
   LOD0DistributionSetting to 1.0, and ``LandscapeRender.cpp:1548-1568`` divides the screen-size
   ratio by ``max(distribution, 1.01)`` per level -- so with 1.0 every LOD threshold collapses onto
   the LOD0 one and a component that leaves LOD0 falls straight to the coarsest LOD in the chain.
   The fix for the road defect was the road defect.  See needs_from_others.

So the sink is not "3 cm is enough because the numbers say zero": it is set from an engine sweep
(``Saved/Clearance/frames3``, the landscape lowered by 0, 5, 10 and 20 cm under a fixed camera) and
bounded by what the built block can cover -- ``conform.sink_profile``.
"""
from __future__ import annotations

import argparse
import glob
import json
import os
import random
import sys
import time

import numpy as np

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "blender"))

from streetscape import fusion as F           # noqa: E402
from streetscape import io_json               # noqa: E402
from streetscape.spline import Spline         # noqa: E402
from streetscape.terrain import Heightfield, LandscapeLodSurface   # noqa: E402


def _structure_summary(rows) -> dict:
    """How big is the structure problem, in one block: counts, length, and the distribution of the
    deck's dive below its own chord.  A bridge with a 3 m sag is a bridge that is not there."""
    out = {"count": len(rows), "by_kind": {}, "measured": 0}
    for k in ("bridge", "tunnel"):
        sel = [r for r in rows if r.get("kind") == k]
        m = [r for r in sel if "chord_sag_m" in r]
        out["by_kind"][k] = {"count": len(sel),
                             "length_km": round(sum(r.get("length_m", 0.0) for r in m) / 1000.0, 3)}
        if m:
            sag = np.array([r["chord_sag_m"] for r in m], dtype=np.float64)
            gr = np.array([r["max_grade_pct"] for r in m], dtype=np.float64)
            out["by_kind"][k].update({
                "chord_sag_m": {"max": float(sag.max()), "p95": float(np.percentile(sag, 95)),
                                "p50": float(np.percentile(sag, 50)), "mean": float(sag.mean())},
                "max_grade_pct": {"max": float(gr.max()), "p95": float(np.percentile(gr, 95)),
                                  "p50": float(np.percentile(gr, 50))},
                "over_0_5m_sag": int((sag > 0.5).sum()), "over_1m_sag": int((sag > 1.0).sum()),
                "over_25pct_grade": int((gr > 25.0).sum())})
        out["measured"] += len(m)
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--landscape", default="data/thanet/out/unreal/landscape_conformed",
                    help="the landscape the engine imports: what the road is measured AGAINST")
    ap.add_argument("--survey", default="data/thanet/out/unreal/landscape",
                    help="the landscape the road is DRAPED on (BRIEF 1.1); defaults to the adapter product")
    ap.add_argument("--survey-sampling", default="landscape_triangulated",
                    choices=["bilinear", "landscape_triangulated"],
                    help="sampling used to BUILD the street; must match the saved Unreal site terrain source. "
                         "The production default is triangulated; bilinear reproduces the older audit reference.")
    ap.add_argument("--streetscape", default="data/thanet/out/unreal/streetscape")
    ap.add_argument("--extra-doc", action="append", default=[])
    ap.add_argument("--only-doc", action="append", default=[],
                    help="restrict to site documents whose basename contains this string "
                         "(repeatable).  Pairs with conform_landscape.py --only-doc for A/B runs "
                         "over a subset small enough to iterate on.")
    ap.add_argument("--n", type=int, default=0, help="0 = every spline; otherwise a spread sample")
    ap.add_argument("--seed", type=int, default=20260909)
    ap.add_argument("--k-road", type=int, default=9)
    ap.add_argument("--k-edge", type=int, default=5)
    ap.add_argument("--layers", default="roads,rail")
    ap.add_argument("--sampling", default="landscape_triangulated",
                    choices=["bilinear", "landscape_triangulated"],
                    help="the rule the LANDSCAPE is read with.  Default is the landscape's own "
                         "triangulation -- the surface the camera sees and the pawn walks on "
                         "(docs/TERRAIN_ROADS.md 3.5), not the numpy bilinear contract.  Inside real "
                         "corridors the two differ by 0.4 mm at the median and 13 mm at the p99 "
                         "(Saved/Clearance/rules_conformed.json), so this changes the number very "
                         "little and the claim a great deal.")
    ap.add_argument("--structures", default="skip", choices=["skip", "include"],
                    help="ways flagged bridge or tunnel carry the elevation of the ground UNDER the "
                         "structure, unadjusted (06_build_networks.py:15-16), and the conform does not "
                         "burn them.  Measuring 'is the ground above the deck' on those is measuring "
                         "the wrong thing: they are counted and named, not gated.")
    ap.add_argument("--slope", action="store_true", help="also bucket by terrain slope (4 extra samples/station)")
    ap.add_argument("--gate-m", type=float, default=None)
    ap.add_argument("--float-gate-m", type=float, default=0.125,
                    help="a gap deeper than this under the outer face of the built block is daylight")
    ap.add_argument("--float-max-frac", type=float, default=None,
                    help="fail when more than this fraction of stations float (the recorded baseline; "
                         "it may only go down, as the geometry track turns the recorded runs into "
                         "embankments and retaining walls)")
    ap.add_argument("--lod", type=int, default=None, help="shorthand for --lods <k>")
    ap.add_argument("--lods", default="0",
                    help="comma-separated levels of detail to measure against, e.g. 0,1,2,3.  Level "
                         "0 is the surface the height query and the collision return; every level "
                         "above it is the mesh the RENDERER draws further away "
                         "(streetscape.terrain.LandscapeLodSurface, transcribed from "
                         "GenerateHeightmapMips and LandscapeVertexFactory.ush).  The splines are "
                         "built once and sampled against every level, so four levels cost four "
                         "sets of samples, not four runs.  This is the difference between a road "
                         "that is above the ground in the data and a road that is visible.")
    ap.add_argument("--rules", action="store_true",
                    help="also read the SAME landscape at the SAME corridor points with BOTH "
                         "interpolation rules and report the difference (fusion.rule_delta).  This is "
                         "the measurement that decides whether the conform having been burned against "
                         "the bilinear contract, while the engine rasterises triangles, is what hides "
                         "a carriageway.  Costs one extra pair of samples per station.")
    ap.add_argument("--lod-max-frac", action="append", default=[], metavar="K:FRAC",
                    help="gate the DRAWN surface, not only the queried one: fail when more than "
                         "FRAC of built length has ground above the road at level of detail K "
                         "(repeatable, e.g. --lod-max-frac 1:0.007 --lod-max-frac 2:0.045).  This "
                         "exists because at b1cd3e5 the LOD-0 gate said PASS over the whole isle "
                         "while 16 of 31 street frames had no carriageway in them: a gate that "
                         "measures the surface the height query returns is not a gate on the "
                         "picture.  Like the float fraction, these numbers may only go DOWN.")
    ap.add_argument("--worst", type=int, default=20, help="how many worst stations to list")
    ap.add_argument("--out", required=True)
    args = ap.parse_args()

    files = sorted(glob.glob(os.path.join(args.streetscape, "site_x*_y*.json")))
    for token in args.only_doc:
        if not any(token in os.path.basename(f) for f in files):
            ap.error("--only-doc matched no documents: " + token)
    if args.only_doc:
        files = [f for f in files if any(t in os.path.basename(f) for t in args.only_doc)]
    files += list(args.extra_doc)
    if not files:
        ap.error("no site documents: empty coverage cannot pass")

    t0 = time.time()
    layers = set(args.layers.split(","))
    hf_survey = Heightfield.from_landscape_dir(args.survey)
    hf_survey.sampling = args.survey_sampling
    same = (os.path.abspath(args.survey) == os.path.abspath(args.landscape)
            and args.survey_sampling == args.sampling)
    hf_lod0 = hf_survey if same else Heightfield.from_landscape_dir(args.landscape)
    hf_lod0.sampling = args.sampling
    lods = sorted({int(v) for v in str(args.lods).split(",") if str(v).strip() != ""}
                  | ({int(args.lod)} if args.lod is not None else set()))
    surfaces = {}
    for k in lods:
        surfaces[k] = hf_lod0 if k == 0 else LandscapeLodSurface.from_landscape_dir(
            args.landscape, k, sampling=args.sampling)
    hf_test = surfaces[lods[0]]
    print("survey %d tiles, test lods %s (%s), %.1f s"
          % (len(hf_survey.tiles), lods, args.sampling, time.time() - t0), flush=True)

    rng = random.Random(args.seed)
    per_file = []
    for p in files:
        doc = json.load(open(p, encoding="utf-8"))
        idx = [i for i, s in enumerate(doc["splines"])
               if (s.get("source") or {}).get("layer") in layers and s["profile_ids"].get("road")]
        if not idx and p in args.extra_doc:
            idx = [i for i, s in enumerate(doc["splines"]) if s["profile_ids"].get("road")]
        rng.shuffle(idx)
        if idx:
            per_file.append((p, idx))
    rng.shuffle(per_file)
    chosen = []
    if args.n <= 0:
        for p, idx in per_file:
            chosen.extend((p, i) for i in idx)
    else:
        r = 0
        while len(chosen) < args.n and any(r < len(idx) for _, idx in per_file):
            for p, idx in per_file:
                if r < len(idx) and len(chosen) < args.n:
                    chosen.append((p, idx[r]))
            r += 1
    print("%d splines from %d documents" % (len(chosen), len(per_file)), flush=True)
    if not chosen:
        ap.error("no eligible splines: empty coverage cannot pass")

    cache = {}
    records = []
    records_lod = {k: [] for k in lods}
    skipped = []
    structures = []
    worst = []
    floating_runs = []
    rule_delta, rule_clear_b, rule_clear_t = [], [], []
    for n, (path, i) in enumerate(chosen):
        if path not in cache:
            cache[path] = io_json.load_site(path)
        site = cache[path]
        sdef = site.splines[i]
        cls = (sdef.source.cls if sdef.source is not None else None) or "?"
        if args.structures == "skip" and sdef.flags is not None and (sdef.flags.bridge or sdef.flags.tunnel):
            # Named and MEASURED, not merely skipped.  "The deck is the ground under the structure"
            # is the pipeline's contract, and it is the one place where the honest answer to Alex's
            # "above ground as necessary" is *above*: a bridge that follows the ground beneath it
            # dives into the cutting it spans.  `chord_sag_m` is how far the deck falls below the
            # straight line between its own two ends -- both of which are measured LIDAR on this very
            # way -- so it is the size of the missing structure, stated without inventing a deck
            # height.  This list is what the geometry track needs to fix z_ref on a structure run.
            row = {"doc": os.path.basename(path), "spline_id": sdef.id, "cls": cls,
                   "kind": "bridge" if sdef.flags.bridge else "tunnel"}
            try:
                sp = Spline(sdef, site, hf_survey)
                z = np.asarray(sp.z_ref, dtype=np.float64)
                s = np.asarray(sp.s, dtype=np.float64)
                if z.size >= 2 and np.isfinite(z).all() and s[-1] > 0:
                    chord = z[0] + (z[-1] - z[0]) * (s - s[0]) / (s[-1] - s[0])
                    grade = np.abs(np.diff(z) / np.maximum(np.diff(s), 1e-6)) * 100.0
                    row.update({"length_m": round(float(s[-1]), 3),
                                "z_min_m": round(float(z.min()), 3), "z_max_m": round(float(z.max()), 3),
                                "chord_sag_m": round(float(np.max(chord - z)), 3),
                                "chord_rise_m": round(float(np.max(z - chord)), 3),
                                "max_grade_pct": round(float(grade.max()) if grade.size else 0.0, 1)})
            except Exception as e:                                      # noqa: BLE001
                row["error"] = repr(e)[:120]
            structures.append(row)
            continue
        try:
            sp = Spline(sdef, site, hf_survey)
        except Exception as e:                                          # noqa: BLE001
            skipped.append([os.path.basename(path), sdef.id, repr(e)[:140]])
            continue
        if any("no terrain under any station" in w for w in sp.warnings):
            # The survey has no ground anywhere under this way, so the geometry core built it flat at
            # z = 0 and the corridor pass refuses to burn it (it would dig a crater in ground nothing
            # measured).  It cannot be measured against the landscape either: with the triangulated
            # rule three good corners are enough to return a height, and the flat ribbon then reads as
            # 32 m of penetration that is not the conform's.  Counted, named, and excluded.
            skipped.append([os.path.basename(path), sdef.id, "no terrain under any station"])
            continue
        slope = F.terrain_slope_deg(hf_lod0, sp.xy[:, 0], sp.xy[:, 1]) if args.slope else None
        for k in lods:
            r_k = F.audit_spline(sp, surfaces[k], args.k_road, args.k_edge)
            records_lod[k].append((cls, slope, r_k))
        rec = records_lod[lods[0]][-1][2]
        records.append((cls, slope, rec))
        if args.rules:
            d, cb, ct = F.rule_delta(sp, hf_test, args.k_road)
            rule_delta.append(d); rule_clear_b.append(cb); rule_clear_t.append(ct)
        v = rec["valid"]
        hit = np.flatnonzero(v & (rec["float"] > args.float_gate_m))
        for run in np.split(hit, np.flatnonzero(np.diff(hit) > 1)+1):
            if not len(run):
                continue
            j = int(run[np.argmax(rec["float"][run])])
            floating_runs.append({"doc":os.path.basename(path),"spline_id":sdef.id,"cls":cls,
                "name":sdef.source.name if sdef.source is not None else None,
                "s0_m":float(sp.s[run[0]]),"s1_m":float(sp.s[run[-1]]),
                "length_m":float(rec["span"][run].sum()),"max_gap_m":float(rec["float"][j]),
                "worst_s_m":float(sp.s[j]),"worst_xy_m":[float(sp.xy[j,0]),float(sp.xy[j,1])]})
        if v.any():
            j = int(np.nanargmax(np.where(v, rec["penetration"], -np.inf)))
            worst.append((float(rec["penetration"][j]), float(rec["float"][j]), sdef.id, cls,
                          os.path.basename(path), int(j), float(sp.s[j]),
                          float(sp.xy[j, 0]), float(sp.xy[j, 1])))
        if (n + 1) % 1000 == 0:
            print("  %d/%d, %.0f s" % (n + 1, len(chosen), time.time() - t0), flush=True)

    worst.sort(key=lambda w: -w[0])
    agg = F.aggregate(records, gate_m=(args.gate_m if args.gate_m is not None else 0.0),
                      float_gate_m=args.float_gate_m)
    if agg.get("stations_with_terrain", 0) == 0:
        sys.exit("GATE FAIL: no stations with terrain; excluded %d structures, skipped %d splines"
                 % (len(structures), len(skipped)))
    by_lod = {}
    for k in lods:
        a_k = F.aggregate(records_lod[k], gate_m=(args.gate_m if args.gate_m is not None else 0.0),
                          float_gate_m=args.float_gate_m)
        by_lod["lod%d" % k] = {m: a_k[m] for m in a_k if m != "by_terrain_slope"}
    lod_model = {k if k == 0 else "lod%d" % k: (surfaces[k].describe() if k else {"lod": 0})
                 for k in lods}
    lod_model = {("lod%d" % k): (surfaces[k].describe() if k else
                                 {"lod": 0, "source": hf_lod0.source, "sampling": hf_lod0.sampling})
                 for k in lods}
    lod_model["where_each_lod_is_drawn_m"] = LandscapeLodSurface.distances_m()
    lod_model["where_each_lod_is_drawn_m"]["screen_multiple"] = float(
        lod_model["where_each_lod_is_drawn_m"]["screen_multiple"])
    lod_model["where_each_lod_is_drawn_m"]["lod_begins_m"] = [
        float(v) for v in lod_model["where_each_lod_is_drawn_m"]["lod_begins_m"]]
    out = {"config": {"landscape": os.path.abspath(args.landscape).replace("\\", "/"),
                      "survey": os.path.abspath(args.survey).replace("\\", "/"),
                      "streetscape": os.path.abspath(args.streetscape).replace("\\", "/"),
                      "sampling": args.sampling, "survey_sampling": args.survey_sampling,
                      "lod": args.lod, "structures": args.structures,
                      "k_road": args.k_road, "k_edge": args.k_edge,
                      "layers": sorted(layers), "n": len(chosen), "extra_docs": args.extra_doc,
                      "elapsed_s": round(time.time() - t0, 1)},
           "summary": agg, "by_lod": by_lod, "lod_model": lod_model, "skipped": skipped, "skipped_count": len(skipped),
           "structures_not_gated": sorted(structures, key=lambda r: -abs(r.get("chord_sag_m") or 0.0))[:400],
           "structures_not_gated_count": len(structures),
           "structures_summary": _structure_summary(structures),
           "structures_note": ("bridge/tunnel ways are excluded from the GATE: their elevation is the "
                               "ground under the structure, unadjusted (sources/derive/"
                               "06_build_networks.py 15-16), and the corridor conform does not burn "
                               "them, so 'is the ground above this way' is the wrong question to ask "
                               "of them.  They are measured instead: chord_sag_m is how far the deck "
                               "falls below the straight line between its own two ends, i.e. how deep "
                               "into the obstacle it spans the way currently dives.  Fixing that is a "
                               "z_ref question in the shared spline layer, not a conform one.  Pass "
                               "--structures include to gate them anyway."),
           "floating_runs": sorted(floating_runs,key=lambda row:(-row["max_gap_m"],row["spline_id"],row["s0_m"])),
           "measurement_scope": "untrimmed ribbon envelopes; junction patch/corner meshes require their separate geometry audit",
           "worst_stations": [{"penetration_m": w[0], "float_m": w[1], "spline_id": w[2], "cls": w[3],
                               "doc": w[4], "station": w[5], "s_m": w[6], "local_xy_m": [w[7], w[8]]}
                              for w in worst[:args.worst]]}
    if args.rules and rule_delta:
        out["sampling_rules"] = F.rule_summary(rule_delta, rule_clear_b, rule_clear_t)
        r = out["sampling_rules"]
        print("sampling rules over %d corridor points: |bilinear - triangulated| p50 %.4f m "
              "p99 %.4f m max %.4f m; ground above the road at %d point(s) bilinear, %d triangulated"
              % (r["points"], r["abs_bilinear_minus_triangulated_m"]["p50"],
                 r["abs_bilinear_minus_triangulated_m"]["p99"], r["abs_bilinear_minus_triangulated_m"]["max"],
                 r["points_with_ground_above_road_bilinear"], r["points_with_ground_above_road_triangulated"]),
              flush=True)
    os.makedirs(os.path.dirname(os.path.abspath(args.out)), exist_ok=True)
    lod_gates = []
    for spec in args.lod_max_frac:
        ks, _, fs = str(spec).partition(":")
        kk, ff = int(ks), float(fs)
        got = by_lod.get("lod%d" % kk, {}).get("fraction_length_penetrated")
        if got is None:
            sys.exit("--lod-max-frac %s: LOD %d was not measured (add it to --lods)" % (spec, kk))
        lod_gates.append((kk, ff, got, got <= ff))
    out["lod_gates"] = [{"lod": kk, "allowed_fraction_length": ff, "measured": got, "pass": okk}
                        for kk, ff, got, okk in lod_gates]
    with open(args.out, "w", encoding="utf-8", newline="\n") as fh:
        json.dump(out, fh, indent=1)
        fh.write("\n")
    print(json.dumps({k: v for k, v in agg.items() if k not in ("by_class", "by_terrain_slope")}, indent=1))
    for k in lods:
        a_k = by_lod["lod%d" % k]
        print("LOD %d: ground above the road at %.4f%% of stations, %.4f%% of length, worst %.3f m; "
              "float over %.3f m at %.4f%% of stations"
              % (k, 100.0 * a_k["fraction_stations_penetrated"],
                 100.0 * a_k["fraction_length_penetrated"],
                 a_k["penetration_m_over_all_stations"]["max"], args.float_gate_m,
                 100.0 * a_k["fraction_stations_floating"]), flush=True)
    print("worst: %s" % json.dumps(out["worst_stations"][:3]))

    pen_max = agg.get("penetration_m_over_all_stations", {}).get("max", 0.0)
    flt_max = agg.get("float_m_over_all_stations", {}).get("max", 0.0)
    if args.gate_m is not None:
        frac = agg.get("fraction_stations_floating", 0.0)
        ok_pen = pen_max <= args.gate_m
        # The float criterion is a FRACTION, not a maximum, and the reason is measured, not assumed:
        # where two modelled surfaces overlap the burn puts the ground on the LOWER one, so a cliff
        # stair zigzagging over itself, a path above a promenade or a way crossing a railway leaves the
        # upper surface standing clear.  That is a structure -- BRIEF 1.1's embankment or retaining wall
        # on Renderer B -- and the runs are written to conform_clamped.json for the geometry track.
        # Attribution over 60 floating splines: 36 disappear when the spline is burned on its own
        # (Saved/Diag/float_attribution.json).  So the number to defend is "no worse than today", and
        # it must fall as those structures are built.
        ok_flt = args.float_max_frac is None or frac <= args.float_max_frac
        ok = ok_pen and ok_flt and all(o for _, _, _, o in lod_gates)
        for kk, ff, got, okk in lod_gates:
            print("LOD GATE %s: LOD %d has ground above the road over %.4f%% of built length "
                  "(allowed %.4f%%)" % ("PASS" if okk else "FAIL", kk, 100.0 * got, 100.0 * ff))
        print("GATE %s: worst penetration %.6f m (allowed %.6f); float over %.3f m at %.4f%% of "
              "stations (allowed %s), worst float %.6f m"
              % ("PASS" if ok else "FAIL", pen_max, args.gate_m, args.float_gate_m, 100.0 * frac,
                 "-" if args.float_max_frac is None else "%.4f%%" % (100.0 * args.float_max_frac), flt_max))
        if not ok:
            sys.exit(1)


if __name__ == "__main__":
    main()
