#!/usr/bin/env python3
"""Create a separate bridge/approach alignment candidate for explicitly selected DSM fits.

No survey or production document is changed. Unsupported connectivity, short/ambiguous
approaches and conflicting profiles fail instead of silently extending a guessed deck.
"""
import argparse
import copy
import json
from pathlib import Path
import sys
import time

import numpy as np

TOOLS = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(TOOLS))
sys.path.insert(0, str(TOOLS / "blender"))
from phase1_qc import atomic_json, sha256
from diag.structure_inventory import sample_dsm, verify_inventory_sources
from streetscape import io_json
from streetscape.spline import Spline
from streetscape.terrain import Heightfield

REPO = TOOLS.parents[2]


def hermite(distance, length, z0, z1, g0, g1):
    t = np.asarray(distance) / length
    return (2*t**3-3*t**2+1)*z0 + (t**3-2*t**2+t)*length*g0 + (-2*t**3+3*t**2)*z1 + (t**3-t**2)*length*g1


def approach_profile(sp, end, deck_z, outward_grade, min_run=40, max_run=120):
    """Join deck height/tangent to the existing approach, preserving its remote endpoint."""
    reverse = end == "end"
    d = sp.length-sp.s[::-1] if reverse else sp.s.copy()
    z = sp.z_ref[::-1] if reverse else sp.z_ref.copy()
    bank = sp.bank_deg[::-1] if reverse else sp.bank_deg.copy()
    anchor = None
    # Ten metres of agreement beyond the blend avoids attaching to a transient DTM spike.
    for length in np.arange(min_run, min(max_run, sp.length-10)+1e-8, 5.0):
        look = np.arange(length, length+10.01, 1.0)
        if np.max(np.abs(np.interp(look, d, z)-(deck_z+outward_grade*look))) <= .25:
            anchor = float(length)
            break
    if anchor is None:
        raise ValueError(sp.id + ": no supported approach anchor before max_run")
    q = np.unique(np.r_[d, np.arange(0, anchor, 1.0), anchor])
    zz, bb = np.interp(q, d, z), np.interp(q, d, bank)
    iz = min(len(d)-2, max(0, int(np.searchsorted(d, anchor, side="right"))-1))
    anchor_grade = (z[iz+1]-z[iz])/(d[iz+1]-d[iz])
    mask = q <= anchor
    zz[mask] = hermite(q[mask], anchor, deck_z, np.interp(anchor, d, z), outward_grade, anchor_grade)
    t = q[mask]/anchor
    bb[mask] = (3*t*t-2*t*t*t)*np.interp(anchor, d, bank)
    grade = np.diff(zz)/np.diff(q)
    bank_rate = np.diff(bb)/np.diff(q)
    selected = q[:-1] < anchor
    if np.max(np.abs(grade[selected])) > .05:
        raise ValueError(sp.id + ": approach exceeds 5% modelling grade tripwire")
    if np.max(np.abs(bank_rate[selected])) > sp.sampling.bank_rate_max_deg_per_m+1e-6:
        raise ValueError(sp.id + ": approach exceeds bank-rate limit")
    info = {"spline_id": sp.id, "end": end, "blend_length_m": anchor,
            "endpoint_change_m": float(deck_z-z[0]), "deck_outward_grade": outward_grade,
            "anchor_grade": float(anchor_grade), "blend_max_grade_pct": float(np.max(np.abs(grade[selected]))*100),
            "blend_max_bank_rate_deg_m": float(np.max(np.abs(bank_rate[selected])))}
    if reverse:
        q, zz, bb = sp.length-q[::-1], zz[::-1], bb[::-1]
    return q, zz, bb, info


def knots(s, z, bank):
    return [dict(s_m=float(a), z_m=float(b), bank_deg=float(c)) for a, b, c in zip(s, z, bank)]


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--group", action="append", required=True)
    ap.add_argument("--connected", action="store_true", help="join short bridge connectors and follow ground approaches across tile stubs")
    ap.add_argument("--inventory", type=Path, default=TOOLS.parent / "Saved/Phase1/structures_baseline.json")
    ap.add_argument("--fits", type=Path, default=TOOLS.parent / "Saved/Phase1/deck_candidates.json")
    ap.add_argument("--out", type=Path, required=True)
    args = ap.parse_args()
    start = time.time()
    if (args.out/"candidate_manifest.json").exists():
        raise ValueError("candidate already exists; choose a fresh output directory")
    inv = json.loads(args.inventory.read_text())
    fits = json.loads(args.fits.read_text())
    if fits["source_sha256"] != sha256(args.inventory):
        raise ValueError("deck fits do not match inventory")
    verify_inventory_sources(inv)
    source = Path(inv["source"]["streetscape"])
    if args.out.resolve() == source.resolve() or source.resolve() in args.out.resolve().parents:
        raise ValueError("candidate must be outside the production streetscape directory")
    survey = Heightfield.from_landscape_dir(inv["source"]["survey"])
    survey.sampling = "landscape_triangulated"
    raw_docs, definitions = {}, {}
    for p in sorted(source.glob("site_x*_y*.json")):
        raw_docs[p.name] = json.loads(p.read_text())
        for row in raw_docs[p.name]["splines"]:
            definitions[row["id"]] = (p.name, row)
    sites, splines, changes, rows = {}, {}, {}, []

    def built(sid):
        name, raw = definitions[sid]
        if name not in sites:
            if sha256(source/name) != inv["source"]["document_sha256"][name]:
                raise ValueError("source document changed since inventory: " + name)
            sites[name] = io_json.site_from_dict(raw_docs[name])
        if sid not in splines:
            splines[sid] = Spline(sites[name].spline(sid), sites[name], survey)
        return splines[sid]

    def add(sid, profile, group, role):
        if sid in changes:
            raise ValueError("conflicting candidate profiles for " + sid)
        built(sid)
        raw = copy.deepcopy(definitions[sid][1])
        if raw.get("elevation_profile"):
            raise ValueError("source already has a modelled profile: " + sid)
        raw["elevation_profile"] = profile
        raw["_elevation_model"] = {"group": group, "role": role, "status": "candidate",
                                    "method": "DSM robust deck line with Hermite approach blend",
                                    "fits_sha256": sha256(args.fits)}
        changes[sid] = raw

    groups = {g["id"]: g for g in inv["groups"]}
    fitted = {g["id"]: g for g in fits["groups"]}
    if args.connected:
        from diag.bridge_alignment import network_profiles
        decks, approaches, records, selected = network_profiles(args.group, groups, fitted, definitions, built,
                                                                approach_profile, hermite, inv["snap_m"])
        for sid, (q, z, bank, gid) in decks.items():
            add(sid, knots(q, z, bank), gid, "deck")
        for sid, (q, z, bank, owners) in approaches.items():
            add(sid, knots(q, z, bank), owners, "approach")
        rows = [{"group": gid, "approaches": [r for r in records if gid in r["groups"]]} for gid in selected]
        for row in rows:
            print(json.dumps(row), flush=True)
    for gid in ([] if args.connected else args.group):
        if gid not in groups or gid not in fitted:
            raise ValueError("unmatched group " + gid)
        group, fit = groups[gid], fitted[gid]
        if fit["status"] != "deck_candidate_requires_approaches" or not gid.startswith("rail:"):
            raise ValueError("pilot only supports passing rail-deck fits: " + gid)
        by_id = {p["spline_id"]: p for p in fit["profile_by_spline"]}
        for sid, p in by_id.items():
            add(sid, knots(p["s_m"], p["z_m"], [0, 0]), gid, "deck")
        rec = {"group": gid, "approaches": []}
        for end in group["ends"]:
            approaches = end["ground_approaches"]
            if len(approaches) != 1:
                raise ValueError(gid + ": ambiguous/missing ground approach")
            approach = approaches[0]
            sp = built(approach["spline_id"])
            p = by_id[end["spline_id"]]
            is_start = end["end"] == "start"
            z0 = p["z_m"][0 if is_start else 1]
            gradient = (p["z_m"][1]-p["z_m"][0])/p["s_m"][1]
            q, z, bank, info = approach_profile(sp, approach["end"], z0, gradient*(-1 if is_start else 1))
            add(sp.id, knots(q, z, bank), gid, "approach")
            rec["approaches"].append(info)
        rows.append(rec)
        print(gid, json.dumps(rec["approaches"]), flush=True)

    # Emit delta documents for transient import; never a whole-site replacement.
    docs = {}
    for sid, row in changes.items():
        name = definitions[sid][0]
        if name not in docs:
            docs[name] = copy.deepcopy(raw_docs[name])
            docs[name]["splines"], docs[name]["junctions"] = [], []
            docs[name]["_candidate_scope"] = "bridge/approach delta; not a whole-site replacement"
        docs[name]["splines"].append(row)
    from osgeo import gdal
    gdal.UseExceptions()
    dsm = gdal.Open(inv["source"]["dsm_vrt"])
    measured = []
    for name, doc in docs.items():
        candidate = io_json.site_from_dict(doc)
        for sdef in candidate.splines:
            sp = Spline(sdef, candidate, survey)
            before = built(sp.id)
            if changes[sp.id]["_elevation_model"]["role"] == "deck":
                tested = np.ones(sp.n, dtype=bool)
            else:
                old = np.interp(sp.s, before.s, before.z_ref)
                tested = np.abs(sp.z_ref-old) > .001
            normal = np.column_stack([-sp.t_h_xy[:, 1], sp.t_h_xy[:, 0]])
            offset = sp.width[:, None]*np.array([-.3, -.15, 0, .15, .3])[None, :]
            heights = sample_dsm(dsm, sp.xy[:, 0, None]+offset*normal[:, 0, None]+candidate.origin.E,
                                 sp.xy[:, 1, None]+offset*normal[:, 1, None]+candidate.origin.N)
            residual = np.nanpercentile(heights, 20, axis=1)-sp.z_ref
            valid = tested & np.isfinite(residual)
            if tested.any() and (valid.sum()/tested.sum() < .8 or
                                np.sum(valid & (np.abs(residual) <= .25))/tested.sum() < .8):
                raise ValueError(sp.id + ": changed profile lacks 80% DSM support within 0.25 m")
            measured.append({"id": sp.id, "length_m": sp.length, "profile_knots": len(sdef.elevation_profile),
                             "tested_stations": int(tested.sum()),
                             "dsm_tested_stations": int(valid.sum()),
                             "dsm_support_fraction": float(np.sum(valid & (np.abs(residual) <= .25))/tested.sum()) if tested.any() else 1.0,
                             "dsm_abs_residual_p95_m": float(np.percentile(np.abs(residual[valid]), 95)) if valid.any() else None,
                             "end_z_m": [float(sp.z_ref[0]), float(sp.z_ref[-1])],
                             "end_bank_deg": [float(sp.bank_deg[0]), float(sp.bank_deg[-1])]})
    # Validate every document before emitting any of them.
    for name, doc in docs.items():
        atomic_json(args.out/name, doc)
    atomic_json(args.out/"candidate_manifest.json", {"scope": "delta", "production_accepted": False,
                "alignment_mode": "connected" if args.connected else "single_spline",
                "alignment_tool_sha256": sha256(TOOLS/"diag/bridge_alignment.py") if args.connected else None,
                "tool_sha256": sha256(__file__), "inventory_sha256": sha256(args.inventory), "fits_sha256": sha256(args.fits),
                "source_documents": {n: sha256(source/n) for n in docs},
                "candidate_documents": {n: sha256(args.out/n) for n in docs},
                "groups": rows, "measured": measured, "seconds": time.time()-start,
                "remaining": ["crossing clearance", "support geometry", "engine visual review"]})
    print("wrote", args.out, "splines", len(changes), "seconds", round(time.time()-start, 2))


if __name__ == "__main__":
    main()
