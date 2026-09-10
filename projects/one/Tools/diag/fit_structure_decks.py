#!/usr/bin/env python3
"""Screen bridge deck fits against first-return LIDAR. Produces candidates only.

No terrain, streetscape document or Unreal asset is modified. Tunnels deliberately
do not use first return, which measures whatever is above them.
"""
import argparse
from collections import Counter
import json
import math
from pathlib import Path
import sys

import numpy as np

TOOLS = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(TOOLS))
from phase1_qc import atomic_json, sha256


def robust_line(s, z):
    """Wide-baseline median slopes, then least squares on robust inliers."""
    s, z = np.asarray(s, dtype=float), np.asarray(z, dtype=float)
    ok = np.isfinite(s) & np.isfinite(z)
    coverage = float(ok.mean()) if ok.size else 0
    if ok.sum() < 5 or coverage < 0.8:
        return {"pass": False, "problems": ["insufficient finite first-return coverage"], "coverage": coverage}
    x, y = s[ok], z[ok]
    if np.ptp(x) < 1:
        return {"pass": False, "problems": ["less than one metre of sampled span"], "coverage": coverage}
    # Bound the quadratic estimator; final fit and residual checks use ALL points.
    indices = np.linspace(0, len(x) - 1, min(len(x), 128)).astype(int)
    xs, ys = x[indices], y[indices]
    dx, dy = xs[None, :] - xs[:, None], ys[None, :] - ys[:, None]
    wide = dx >= np.ptp(x) * 0.25
    slope = float(np.median(dy[wide] / dx[wide]))
    intercept = float(np.median(y - slope * x))
    residual = y - (intercept + slope * x)
    mad = float(np.median(np.abs(residual - np.median(residual))))
    inliers = np.abs(residual) <= max(0.15, 3 * 1.4826 * mad)
    if inliers.sum() >= 5:
        centred = x[inliers] - np.mean(x[inliers])
        denom = float(centred @ centred)
        if denom > 0:
            slope = float(centred @ (y[inliers] - np.mean(y[inliers])) / denom)
            intercept = float(np.mean(y[inliers]) - slope * np.mean(x[inliers]))
    residual = np.abs(y - (intercept + slope * x))
    supported = residual <= 0.25
    fraction = float(supported.sum() / len(s))
    problems = []
    if fraction < 0.8:
        problems.append("less than 80% of stations support deck within 0.25 m")
    # Both abutments need local support; a flat tree canopy on the central span
    # must not masquerade as a deck because most central samples fit well.
    for mask, label in ((x <= x.min() + np.ptp(x) * 0.15, "start"),
                        (x >= x.max() - np.ptp(x) * 0.15, "end")):
        if not mask.any() or float(np.median(residual[mask])) > 0.25:
            problems.append(label + " of span lacks local first-return support")
    return {"pass": not problems, "problems": problems, "coverage": coverage,
            "slope": slope, "intercept_m": intercept, "grade_pct": 100 * abs(slope),
            "support_fraction": fraction, "residual_p50_m": float(np.percentile(residual, 50)),
            "residual_p90_m": float(np.percentile(residual, 90)),
            "residual_max_m": float(residual.max()), "inliers_for_fit": int(inliers.sum())}


def ordered_chain(group, snap_m):
    if group["status"] != "measured_chain" or len(group["ends"]) != 2:
        raise ValueError("group is not a simple chain")
    remaining = {r["spline_id"]: r for r in group["segments"]}
    first = group["ends"][0]
    sid, end = first["spline_id"], first["end"]
    result, offset = [], 0.0
    while remaining:
        segment = remaining.pop(sid)
        reverse = end == "end"
        result.append((segment, reverse, offset))
        offset += segment["length_m"]
        if not remaining:
            break
        xy = segment["xy_ends_m"][0 if reverse else 1]
        candidates = sorted((math.dist(xy, r["xy_ends_m"][i]), key, label)
                            for key, r in remaining.items() for i, label in enumerate(("start", "end")))
        distance, sid, end = candidates[0]
        if distance > snap_m:
            raise ValueError("disconnected chain during ordering")
    return result


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--inventory", type=Path, default=TOOLS.parent / "Saved/Phase1/structures_baseline.json")
    ap.add_argument("--out", type=Path, default=TOOLS.parent / "Saved/Phase1/deck_candidates.json")
    args = ap.parse_args()
    inventory = json.loads(args.inventory.read_text(encoding="utf-8"))
    rows = []
    for group in inventory["groups"]:
        row = {"id": group["id"], "kind": group["kind"], "length_m": group["length_m"],
               "splines": group["splines"], "production_accepted": False}
        if group["kind"] == "tunnel":
            row.update(status="needs_subsurface_model", problems=["first return cannot measure a tunnel floor"])
            rows.append(row)
            continue
        try:
            chain = ordered_chain(group, inventory["snap_m"])
        except ValueError as exc:
            row.update(status="needs_connectivity_review", problems=[str(exc)])
            rows.append(row)
            continue
        all_s, all_z, all_spread = [], [], []
        for segment, reverse, offset in chain:
            sample = segment["samples"]
            s = np.array(sample["s_m"], dtype=float)
            z = np.array(sample["dsm_p20_m"], dtype=float)
            spread = np.array(sample["dsm_p80_m"], dtype=float) - z
            if reverse:
                s, z, spread = segment["length_m"] - s[::-1], z[::-1], spread[::-1]
            all_s.extend(offset + s)
            all_z.extend(z)
            all_spread.extend(spread)
        unique_s, indices = np.unique(all_s, return_index=True)
        z = np.array(all_z)[indices]
        fit = robust_line(unique_s, z)
        problems = list(fit["problems"])
        spread = np.asarray(all_spread)[np.isfinite(all_spread)]
        row["lateral_spread_p50_m"] = float(np.median(spread)) if spread.size else None
        if not spread.size or float(np.median(spread)) > 0.5:
            problems.append("large lateral first-return spread; vegetation/parapet risk")
        if "slope" in fit:
            # QC tripwires, not claims about engineering standards or surveying.
            grade_limit = 5.0 if row["id"].startswith("rail:") else 15.0
            if fit["grade_pct"] > grade_limit:
                problems.append("fitted grade exceeds configured modelling tripwire")
            z0, z1 = fit["intercept_m"], fit["intercept_m"] + fit["slope"] * group["length_m"]
            row["candidate_end_heights_m"] = [z0, z1]
            row["change_from_current_ends_m"] = [z0 - group["ends"][0]["built_z_m"],
                                                 z1 - group["ends"][1]["built_z_m"]]
            row["profile_by_spline"] = []
            for segment, reverse, offset in chain:
                a = fit["intercept_m"] + fit["slope"] * offset
                b = a + fit["slope"] * segment["length_m"]
                row["profile_by_spline"].append({"spline_id": segment["spline_id"],
                                                  "s_m": [0.0, segment["length_m"]],
                                                  "z_m": [b, a] if reverse else [a, b]})
        row.update(fit=fit, problems=problems,
                   status="deck_candidate_requires_approaches" if not problems else "needs_deck_review")
        rows.append(row)
    result = {"source_inventory": str(args.inventory.resolve()), "source_sha256": sha256(args.inventory),
              "tool_sha256": sha256(__file__), "groups": rows,
              "summary": dict(Counter(r["status"] for r in rows)),
              "modelling_note": "Robust line fitted to DSM cross-section 20th percentile. Fitted deck geometry is modelled from first return, not raw survey. All candidates still require approach continuity, bank, crossing clearance and in-engine validation."}
    atomic_json(args.out, result)
    print(json.dumps(result["summary"], indent=2))
    for row in rows:
        if row["id"] in ("rail:310977210:0", "rail:4596560:0"):
            print(json.dumps(row, indent=2))


if __name__ == "__main__":
    main()
