"""Compare an Unreal ActorStatsJson against the Blender/numpy stats.json of the same spline.

  python compare_stats.py --ue <ue_stats.json> --numpy <Tools/blender/renders/trinity_square.stats.json>
                          [--json-out <report.json>]

Pure stdlib (runs under the pipeline python or UE's). Compared, per DESIGN.md 14 and the phase-3 gate:

  length_m          +- 0.05 m
  n_samples         exact
  overlap min/max   exact per side and overall (1e-9)
  buffers           verts and tris per buffer AND per material, exact
  per_group         verts and tris per group, exact
  marking_strips    exact
  instances         exact per kind

Prints one line per row and finally PARITY OK (exit 0) or PARITY FAIL (exit 1). Tolerances are NOT knobs: a count
that differs means one of the two implementations is wrong.
"""
import argparse
import json
import sys

L_TOL = 0.05
OVERLAP_TOL = 1e-9

Rows = []


def row(name, ue, np_, ok, note=""):
    Rows.append({"field": name, "unreal": ue, "numpy": np_, "ok": bool(ok), "note": note})
    return bool(ok)


def near(a, b, tol):
    if a is None or b is None:
        return a is None and b is None
    return abs(float(a) - float(b)) <= tol


def cmp_exact(name, ue, np_):
    return row(name, ue, np_, ue == np_)


def cmp_counts(name, ue_map, np_map):
    """{key: {'verts': v, 'tris': t}} compared key by key, both directions."""
    ok = True
    keys = sorted(set(list((ue_map or {}).keys()) + list((np_map or {}).keys())))
    for k in keys:
        u = (ue_map or {}).get(k)
        n = (np_map or {}).get(k)
        if u is None or n is None:
            ok = row("%s[%s]" % (name, k), u, n, False, "missing on one side") and ok
            continue
        ok = row("%s[%s].verts" % (name, k), u.get("verts"), n.get("verts"), u.get("verts") == n.get("verts")) and ok
        ok = row("%s[%s].tris" % (name, k), u.get("tris"), n.get("tris"), u.get("tris") == n.get("tris")) and ok
    return ok


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--ue", required=True, help="ActorStatsJson written by 03_import_streetscape.py --stats-out")
    ap.add_argument("--numpy", required=True, help="stats.json written by streetscape.build / the Blender run")
    ap.add_argument("--json-out", default=None)
    args = ap.parse_args(argv)

    with open(args.ue, "r", encoding="utf-8") as fh:
        U = json.load(fh)
    with open(args.numpy, "r", encoding="utf-8") as fh:
        N = json.load(fh)

    ok = True
    ok = row("spline_id", U.get("spline_id"), N.get("spline_id"), U.get("spline_id") == N.get("spline_id")) and ok
    ok = row("length_m", U.get("length_m"), N.get("length_m"), near(U.get("length_m"), N.get("length_m"), L_TOL),
             "+- %g" % L_TOL) and ok
    ok = cmp_exact("n_samples", U.get("n_samples"), N.get("n_samples")) and ok
    ok = cmp_exact("points_merged", U.get("points_merged"), N.get("points_merged")) and ok
    ok = cmp_exact("kind", U.get("kind"), N.get("kind")) and ok

    # -- overlap
    for side in ("left", "right"):
        u = (U.get("overlap") or {}).get(side)
        n = (N.get("overlap") or {}).get(side)
        if u is None and n is None:
            continue
        if u is None or n is None:
            ok = row("overlap.%s" % side, u, n, False, "missing on one side") and ok
            continue
        for k in ("min", "max"):
            ok = row("overlap.%s.%s" % (side, k), u.get(k), n.get(k), near(u.get(k), n.get(k), OVERLAP_TOL)) and ok
    for k in ("overlap_min", "overlap_max"):
        ok = row(k, U.get(k), N.get(k), near(U.get(k), N.get(k), OVERLAP_TOL)) and ok

    # -- buffers: totals, per material, per group
    ub = U.get("buffers") or {}
    nb = N.get("buffers") or {}
    names = sorted(set(list(ub.keys()) + list(nb.keys())))
    for name in names:
        u = ub.get(name)
        n = nb.get(name)
        if u is None or n is None:
            ok = row("buffers[%s]" % name, "present" if u else None, "present" if n else None, False, "missing on one side") and ok
            continue
        ok = row("buffers[%s].verts" % name, u.get("verts"), n.get("verts"), u.get("verts") == n.get("verts")) and ok
        ok = row("buffers[%s].tris" % name, u.get("tris"), n.get("tris"), u.get("tris") == n.get("tris")) and ok
        ok = cmp_counts("buffers[%s].per_material" % name, u.get("per_material"), n.get("per_material")) and ok
        ok = cmp_counts("buffers[%s].per_group" % name, u.get("per_group"), n.get("per_group")) and ok

    ok = cmp_exact("marking_strips", U.get("marking_strips"), N.get("marking_strips")) and ok

    ui = U.get("instances") or {}
    ni = N.get("instances") or {}
    for k in sorted(set(list(ui.keys()) + list(ni.keys()))):
        ok = row("instances[%s]" % k, ui.get(k), ni.get(k), ui.get(k) == ni.get(k)) and ok

    # -- stations_identical must hold on both sides (DESIGN.md 5 rule 2)
    us = U.get("stations_identical") or {}
    ns = N.get("stations_identical") or {}
    for k in sorted(set(list(us.keys()) + list(ns.keys()))):
        ok = row("stations_identical[%s]" % k, us.get(k), ns.get(k), bool(us.get(k)) and bool(ns.get(k))) and ok

    # -- informational (not a gate): validate lists must be empty on both sides
    for src, tag in ((U, "unreal"), (N, "numpy")):
        for k, v in (src.get("validate") or {}).items():
            if v:
                ok = row("validate[%s] (%s)" % (k, tag), v, [], False) and ok

    width = max(len(r["field"]) for r in Rows)
    for r in Rows:
        print("%-*s  ue=%-28s numpy=%-28s %s%s" % (
            width, r["field"], json.dumps(r["unreal"]), json.dumps(r["numpy"]),
            "OK" if r["ok"] else "MISMATCH", ("  (%s)" % r["note"]) if r["note"] else ""))
    n_bad = sum(1 for r in Rows if not r["ok"])
    print("%d rows compared, %d mismatch(es)" % (len(Rows), n_bad))
    print("PARITY OK" if ok else "PARITY FAIL")
    if args.json_out:
        with open(args.json_out, "w", encoding="utf-8", newline="\n") as fh:
            json.dump({"ok": bool(ok), "rows": Rows}, fh, indent=1)
            fh.write("\n")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
