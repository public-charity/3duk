#!/usr/bin/env python3
"""Infer an occluded road floor between surveyed approaches, as a separate elevation candidate.

The centreline beneath a rail deck is unobserved. Its height is an explicit Hermite
interpolation, not a claimed survey measurement. Outside deck footprints (plus a 2 m
raster margin), changed heights must agree with DTM. Source pixels and production
documents are never edited. Width and structural soffit still require visual review.
"""
import argparse
import copy
import json
from pathlib import Path
import sys
import time

import numpy as np

TOOLS = Path(__file__).resolve().parents[1]
REPO = TOOLS.parents[2]
sys.path.insert(0, str(TOOLS))
sys.path.insert(0, str(TOOLS / "blender"))
from diag.bridge_alignment import chain_samples, merge_profile, split_profile
from diag.bridge_profile_candidate import hermite, knots
from diag.bridge_crossing_audit import highest_triangle_z
from diag.structure_inventory import verify_inventory_sources
from phase1_qc import atomic_json, sha256
from streetscape import io_json
from streetscape.spline import Spline
from streetscape.terrain import Heightfield
from ue.candidate_preview import read_candidate


def infer_profile(combined, offsets, before_m, after_m, floor_anchor_m):
    """Interpolate only the occluded floor neighbourhood; blend bank over longer approaches."""
    if min(before_m, after_m) < 10 or not 2 <= floor_anchor_m <= min(before_m, after_m):
        raise ValueError("invalid approach/height-anchor distances")
    low, high = offsets[1]-before_m, offsets[2]+after_m
    if low < 5 or high > combined.length-5:
        raise ValueError("approaches too short for stable anchors")
    floor_low, floor_high = offsets[1]-floor_anchor_m, offsets[2]+floor_anchor_m
    q = np.unique(np.r_[combined.s, np.arange(low, high, .5), low, high, floor_low, floor_high])
    z = np.interp(q, combined.s, combined.z_ref)
    bank = np.interp(q, combined.s, combined.bank_deg)
    base_z = z.copy()
    g0 = (np.interp(floor_low+2, combined.s, combined.z_ref)-np.interp(floor_low-2, combined.s, combined.z_ref))/4
    g1 = (np.interp(floor_high+2, combined.s, combined.z_ref)-np.interp(floor_high-2, combined.s, combined.z_ref))/4
    mask = (q >= low)&(q <= high)
    floor_mask = (q >= floor_low)&(q <= floor_high)
    z[floor_mask] = hermite(q[floor_mask]-floor_low, floor_high-floor_low,
        np.interp(floor_low, q, base_z), np.interp(floor_high, q, base_z), g0, g1)
    t = (q[mask]-low)/(high-low)
    bank[mask] = np.interp(low, combined.s, combined.bank_deg)+(3*t*t-2*t*t*t)*(
        np.interp(high, combined.s, combined.bank_deg)-np.interp(low, combined.s, combined.bank_deg))
    interval = (q[:-1] >= low-1e-8)&(q[1:] <= high+1e-8)
    max_grade = float(np.max(np.abs(np.diff(z)[interval]/np.diff(q)[interval])))
    max_bank_rate = float(np.max(np.abs(np.diff(bank)[interval]/np.diff(q)[interval])))
    if not np.isfinite(z).all() or not np.isfinite(bank).all():
        raise ValueError("nonfinite inferred profile")
    if max_grade > .15 or max_bank_rate > combined.sampling.bank_rate_max_deg_per_m+1e-6:
        raise ValueError("inferred profile exceeds grade/bank modelling tripwire")
    return q, z, bank, {"max_model_grade_pct":100*max_grade,"max_bank_rate_deg_per_m":max_bank_rate,
        "floor_anchor_z_m":[float(np.interp(floor_low,q,z)),float(np.interp(floor_high,q,z))]}


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--road", required=True)
    ap.add_argument("--bridge-candidate", type=Path, required=True)
    ap.add_argument("--before-m", type=float, default=20)
    ap.add_argument("--after-m", type=float, default=40)
    ap.add_argument("--floor-anchor-m", type=float, default=5,
                    help="height anchors this far beyond each underpass end; longer approaches blend bank only")
    ap.add_argument("--inventory", type=Path, default=TOOLS.parent/"Saved/Phase1/structures_baseline.json")
    ap.add_argument("--out", type=Path, required=True)
    args = ap.parse_args()
    start = time.time()
    if min(args.before_m, args.after_m) < 10 or not 2 <= args.floor_anchor_m <= min(args.before_m, args.after_m):
        raise ValueError("at least ten metres of each approach required")
    source = REPO/"data/thanet/out/unreal/streetscape"
    if args.out.resolve().is_relative_to(source.resolve()) or (args.out/"candidate_manifest.json").exists():
        raise ValueError("choose a new candidate directory outside source streetscape")
    inventory = json.loads(args.inventory.read_text())
    verify_inventory_sources(inventory)
    bridge_record, bridge_files = read_candidate(args.bridge_candidate)
    definitions, documents = {}, {}
    for path in source.glob("site_x*_y*.json"):
        raw = json.loads(path.read_text())
        documents[path.name] = raw
        for row in raw["splines"]:
            definitions[row["id"]] = (path.name, row)
    target = definitions[args.road][1]
    previous, following = target.get("continues_from"), target.get("continues_to")
    if not previous or not following:
        raise ValueError("road needs explicit source continuations at both ends")
    chain = []
    for sid, target_end in ((previous, target["points"][0]), (args.road, None), (following, target["points"][-1])):
        row = definitions[sid][1]
        if row["source"]["layer"] != "roads" or row.get("elevation_profile"):
            raise ValueError("requires original road splines: "+sid)
        if any((row.get("flags") or {}).get(k) for k in ("bridge", "tunnel", "steps")):
            raise ValueError("unsupported ground approach: "+sid)
        reverse = False
        if target_end is not None:
            distances = [np.hypot(p["x"]-target_end["x"], p["y"]-target_end["y"])
                         for p in (row["points"][0], row["points"][-1])]
            if min(distances) > 1e-5 or abs(distances[0]-distances[1]) < .35:
                raise ValueError("continuation is not an exact unambiguous join")
            reverse = (np.argmin(distances) == 0) if sid == previous else (np.argmin(distances) == 1)
        chain.append((sid, reverse))
    hf = Heightfield.from_landscape_dir(str(REPO/"data/thanet/out/unreal/landscape"))
    hf.sampling = "landscape_triangulated"
    sites, cache = {}, {}

    def built(sid):
        if sid not in cache:
            name, _ = definitions[sid]
            if name not in sites:
                sites[name] = io_json.site_from_dict(documents[name])
            cache[sid] = Spline(sites[name].spline(sid), sites[name], hf)
        return cache[sid]

    combined, offsets = chain_samples(chain, built)
    q, z, bank, profile_stats = infer_profile(combined, offsets, args.before_m, args.after_m, args.floor_anchor_m)
    # Rail ballast footprints enlarged by two metres bound missing/contaminated ground pixels.
    deck_triangles, deck_ids = [], []
    for path, _ in bridge_files:
        site = io_json.load_site(path)
        for row in site.splines:
            if not (row.flags and row.flags.bridge):
                continue
            sp = Spline(row, site, hf)
            sq = np.linspace(0, sp.length, int(np.ceil(sp.length/.5))+1)
            f = sp.frames.at(sq)
            half = np.interp(sq, sp.s, sp.width)/2+2
            normal = f.n_flat
            left, right = f.p+half[:, None]*normal, f.p-half[:, None]*normal
            triangles = np.concatenate([np.stack([left[:-1],right[:-1],left[1:]],axis=1),
                                        np.stack([right[:-1],right[1:],left[1:]],axis=1)])
            deck_triangles.append(triangles)
            deck_ids.append(sp.id)
    if not deck_triangles:
        raise ValueError("no modelled rail decks")
    updates = split_profile(chain, built, offsets, q, z, bank, combined.length)
    output, evidence, overlaps = {}, [], set()
    for sid, _ in chain:
        sp = built(sid)
        qs, zz, bb = merge_profile(sp, [updates[sid]])
        name, raw = definitions[sid]
        changed = copy.deepcopy(raw)
        changed["elevation_profile"] = knots(qs, zz, bb)
        changed["_elevation_model"] = {"role":"inferred_underpass_floor", "road":args.road,
            "method":"Hermite between surveyed approaches; bank interpolated between external anchors",
            "occlusion_raster_margin_m":2.0, "production_accepted":False}
        if name not in output:
            output[name] = copy.deepcopy(documents[name])
        output[name]["splines"] = [changed if s["id"] == sid else s for s in output[name]["splines"]]
        xyz = sp.frames.at(qs).p
        observed = hf.sample(xyz[:,0], xyz[:,1])
        occluded = np.zeros(len(qs),dtype=bool)
        for bridge_id, triangles in zip(deck_ids,deck_triangles):
            covered = np.isfinite(highest_triangle_z(triangles,xyz[:,:2]))
            if covered.any():
                overlaps.add(bridge_id)
                occluded |= covered
        baseline = np.interp(qs,sp.s,sp.z_ref)
        tested = (np.abs(zz-baseline)>.001)&~occluded
        good = tested&np.isfinite(observed)
        residual = np.abs(zz-observed)
        support = float(np.sum(good&(residual<=.25))/tested.sum()) if tested.any() else 1.0
        if support < .8:
            bad = good&(residual>.25)
            raise ValueError(sid+": inferred profile lacks 80% agreement with observable approach DTM: "+str({
                "support":support,"tested":int(tested.sum()),"bad_s":qs[bad].tolist(),
                "model_z":zz[bad].tolist(),"dtm_z":observed[bad].tolist()}))
        # A large height reduction is allowed only beneath the independently modelled rail footprint.
        if np.any((baseline-zz>.5)&~occluded):
            raise ValueError(sid+": large height reduction outside rail occlusion")
        evidence.append({"id":sid,"tested_approach_stations":int(tested.sum()),"dtm_support_fraction":support,
            "approach_dtm_residual_p95_m":float(np.percentile(residual[good],95)) if good.any() else None,
            "occluded_stations":int(occluded.sum()),"maximum_lowering_m":float(np.max(baseline-zz)),
            "endpoint_z_m":[float(zz[0]),float(zz[-1])],"endpoint_bank_deg":[float(bb[0]),float(bb[-1])]})
    if not overlaps:
        raise ValueError("road does not overlap modelled rail decks")
    for raw in output.values():
        site=io_json.site_from_dict(raw)
        for definition in site.splines:
            Spline(definition,site,hf)
    verify_inventory_sources(inventory)
    if read_candidate(args.bridge_candidate)[0] != bridge_record:
        raise ValueError("bridge candidate changed during inference")
    for name, raw in output.items():
        atomic_json(args.out/name,raw)
    atomic_json(args.out/"candidate_manifest.json",{"scope":"document_elevations","production_accepted":False,
        "tool_sha256":sha256(__file__),"inventory_sha256":sha256(args.inventory),
        "bridge_candidate_manifest_sha256":bridge_record["manifest_sha256"],
        "source_documents":{n:sha256(source/n) for n in output},
        "candidate_documents":{n:sha256(args.out/n) for n in output},"modified_ids":[sid for sid,_ in chain],"road":args.road,
        "occluding_bridges":sorted(overlaps),"before_m":args.before_m,"after_m":args.after_m,
        "floor_anchor_m":args.floor_anchor_m,**profile_stats,"measured":evidence,
        "seconds":time.time()-start,"remaining":["road width and side-wall clearance", "structural soffit",
        "candidate terrain conform", "engine visual review"],"model":__doc__})
    print(json.dumps({"out":str(args.out),"splines":len(chain),"measured":evidence,"seconds":time.time()-start},indent=2))


if __name__ == "__main__":
    main()
