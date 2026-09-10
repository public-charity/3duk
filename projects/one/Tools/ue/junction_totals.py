"""Add up the per-slice junction totals of a site import and compare them with the numpy audit.

    C:/Users/Shadow/code/3duk-env/env/python.exe projects/one/Tools/ue/junction_totals.py \
        --census  projects/one/Saved/Tests/build_level_assert_loaded.json \
        --audit   projects/one/Saved/Diag/junction_isle.json \
        [--out    projects/one/Saved/Junctions/isle.json]
    ... or --slices <dir> to sum the per-slice --junctions-out files of an import instead.

TWO SOURCES, AND THE LEVEL IS THE BETTER ONE.

``--census`` reads the ``streetscape_census`` block of ``07_assert_level.py --census-only``: the whole world
streamed into one commandlet, every AStreetscapeActor's own ``JunctionStats`` added up. That is what the SAVED
LEVEL holds, measured after the import is over and reloaded from disk - not what the importer said it did.

``--slices`` sums the per-slice ``--junctions-out`` files. A site import runs as twelve commandlets and no single
one of them sees the isle, so the sum is where the import-side claim gets made. It also carries the plan-side
counts the level cannot know (arms, arms_unseparable, splines_degenerate), because those belong to the solve
rather than to any actor.

Either way the comparison is against ``Tools/blender/streetscape/build.py --junction-audit`` over the same
documents. Exits non-zero on any disagreement. Junctions do not cross documents (measured: 0 of 5,185 ends name a
spline outside their own file), so slicing by document cannot split one.
"""
import glob
import json
import os
import sys

# import key -> numpy audit key. Only counts: areas and trims are compared separately, to a tolerance.
COUNTS = {
    "junctions_in_documents": "junctions",
    "junctions_built": "patches",
    "arms": "arms",
    "arms_dropped": "arms_dropped",
    "arms_unseparable": "arms_unseparable",
    "trimmed_ends": "trimmed_ends",
    "splines_trimmed": "splines_trimmed",
    "splines_degenerate": "splines_degenerate",
    "splines_untrimmable": "splines_untrimmable",
    "junctions_skipped_kind": "junctions_skipped_kind",
    "junctions_skipped_arms": "junctions_skipped_arms",
    "non_monotone": "non_monotone",
    "patch_verts": "patch_verts",
    "patch_tris": "patch_tris",
    "corners": "corners",
    "corners_skipped_no_kerb": "corners_skipped_no_kerb",
    "corners_skipped_incompatible": "corners_skipped_incompatible",
    "corner_tris": "corner_tris",
}
FLOATS = {"trim_total_m": "trim_total_m", "patch_area_m2": "patch_area_m2",
          "patch_overlap_area_m2": "patch_overlap_area_m2"}


# census key -> numpy audit key, for the level-side source
CENSUS = {
    "junctions_built": "patches",
    "junction_non_monotone": "non_monotone",
    "junction_patch_verts": "patch_verts",
    "junction_patch_tris": "patch_tris",
    "junction_corners": "corners",
    "junction_corners_skipped_no_kerb": "corners_skipped_no_kerb",
    "junction_corners_skipped_incompatible": "corners_skipped_incompatible",
    "junction_corner_tris": "corner_tris",
    "splines_trimmed": "splines_trimmed",
    "trimmed_ends": "trimmed_ends",
}
# ... and the two 3-D areas, which are NOT expected to the digit: the level drapes its stations from the
# landscape's own triangulated rule and the numpy audit from the bilinear one (docs/TERRAIN_ROADS.md 3), so a
# patch's area moves by the sub-millimetre the heights move by. Counts are unaffected and are compared exactly.
CENSUS_FLOATS = {"junction_patch_area_m2": ("patch_area_m2", 1e-6),
                 "junction_patch_overlap_area_m2": ("patch_overlap_area_m2", 1e-4),
                 "trim_total_m": ("trim_total_m", 1e-9)}


def from_census(path, audit_path, out_path):
    """The level's own account: every actor's JunctionStats, added up by StreetscapeCensusJson."""
    d = json.load(open(path, "r", encoding="utf-8"))
    c = d.get("streetscape_census")
    if not c:
        print("%s has no streetscape_census block (run 07_assert_level.py without --no-load-all)" % path,
              file=sys.stderr)
        return 1
    audit = json.load(open(audit_path, "r", encoding="utf-8"))["totals"] if audit_path else None
    bad = []
    rows = {}
    print("%-40s %12s %12s" % ("level census", "level", "numpy"))
    for k, ak in CENSUS.items():
        got = int(c.get(k) or 0)
        want = audit.get(ak) if audit else None
        ok = "" if want is None else ("OK" if got == want else "MISMATCH")
        if ok == "MISMATCH":
            bad.append("%s: level %d, numpy %d" % (k, got, want))
        rows[k] = {"level": got, "numpy": want, "verdict": ok}
        print("%-40s %12d %12s %s" % (k, got, "-" if want is None else want, ok))
    for k, (ak, tol) in CENSUS_FLOATS.items():
        got = float(c.get(k) or 0.0)
        want = audit.get(ak) if audit else None
        ok = ""
        if want is not None:
            rel = abs(got - want) / max(1.0, abs(want))
            ok = "OK" if rel <= tol else "MISMATCH"
            if ok == "MISMATCH":
                bad.append("%s: level %.6f, numpy %.6f (rel %.3g > %g)" % (k, got, want, rel, tol))
        rows[k] = {"level": got, "numpy": want, "verdict": ok}
        print("%-40s %12.4f %12s %s" % (k, got, "-" if want is None else "%.4f" % want, ok))

    owned = int(c.get("junctions_owned") or 0)
    built = int(c.get("junctions_built") or 0)
    skipped = int(c.get("junctions_skipped") or 0)
    print("%-40s %12d" % ("junctions_owned (level)", owned))
    print("%-40s %12d" % ("junctions_skipped (level)", skipped))
    if built == 0:
        print("FAIL: the level holds no junction at all", file=sys.stderr)
        return 1
    if owned != built or skipped:
        bad.append("owned %d, built %d, skipped %d" % (owned, built, skipped))
    if out_path:
        dd = os.path.dirname(out_path)
        if dd and not os.path.isdir(dd):
            os.makedirs(dd)
        with open(out_path, "w", encoding="utf-8", newline="\n") as fh:
            json.dump({"source": path, "audit": audit_path, "rows": rows, "actors": c.get("actors"),
                       "junctions_owned": owned, "junctions_built": built, "junctions_skipped": skipped,
                       "mismatches": bad}, fh, indent=1, sort_keys=True)
            fh.write("\n")
        print("written: %s" % out_path)
    if bad:
        print("FAIL: %d disagreement(s): %s" % (len(bad), " | ".join(bad)), file=sys.stderr)
        return 1
    print("THANET_OK junction_totals %s" % json.dumps(
        {"source": "level census", "junctions_built": built, "trimmed_ends": int(c.get("trimmed_ends") or 0),
         "matches_numpy": audit is not None}))
    return 0


def main(argv):
    opts = {"slices": "", "audit": "", "out": "", "census": ""}
    i = 0
    while i < len(argv):
        k = argv[i][2:].replace("-", "_")
        if not argv[i].startswith("--") or k not in opts:
            print("unknown argument %r" % argv[i], file=sys.stderr)
            return 2
        opts[k] = argv[i + 1]
        i += 2
    if opts["census"]:
        return from_census(opts["census"], opts["audit"], opts["out"])
    if not opts["slices"]:
        print("--census <07_assert_level json> or --slices <dir> is required", file=sys.stderr)
        return 2

    files = sorted(glob.glob(os.path.join(opts["slices"], "slice_*.json")),
                   key=lambda p: int(os.path.basename(p).split("_")[1].split(".")[0]))
    if not files:
        print("no slice_*.json under %s - nothing was measured, which is not a pass" % opts["slices"], file=sys.stderr)
        return 1

    total = {k: 0 for k in list(COUNTS) + ["documents", "documents_with_junctions", "owners",
                                           "junctions_planned", "junctions_owned", "junctions_skipped_build",
                                           "corner_verts"]}
    for k in FLOATS:
        total[k] = 0.0
    skipped = []
    for f in files:
        d = json.load(open(f, "r", encoding="utf-8"))
        for k in total:
            total[k] += d.get(k, 0)
        skipped += list(d.get("skipped") or [])
    total["slices"] = len(files)
    total["skipped"] = skipped

    print("%-32s %12s %12s %s" % ("count", "import", "numpy", ""))
    rows = []
    bad = []
    audit = None
    if opts["audit"]:
        audit = json.load(open(opts["audit"], "r", encoding="utf-8"))["totals"]
    for k, ak in COUNTS.items():
        want = audit.get(ak) if audit else None
        ok = "" if want is None else ("OK" if total[k] == want else "MISMATCH")
        if ok == "MISMATCH":
            bad.append("%s: import %d, numpy %d" % (k, total[k], want))
        rows.append((k, total[k], want, ok))
        print("%-32s %12d %12s %s" % (k, total[k], "-" if want is None else want, ok))
    for k, ak in FLOATS.items():
        want = audit.get(ak) if audit else None
        ok = ""
        if want is not None:
            ok = "OK" if abs(total[k] - want) <= 1e-6 * max(1.0, abs(want)) else "MISMATCH"
            if ok == "MISMATCH":
                bad.append("%s: import %.6f, numpy %.6f" % (k, total[k], want))
        rows.append((k, total[k], want, ok))
        print("%-32s %12.4f %12s %s" % (k, total[k], "-" if want is None else "%.4f" % want, ok))

    if total["junctions_planned"] > 0 and total["junctions_built"] == 0:
        print("FAIL: the plan solved %d junction(s) and NOT ONE was built" % total["junctions_planned"], file=sys.stderr)
        return 1
    accounted = total["junctions_planned"] + total["junctions_skipped_kind"] + total["junctions_skipped_arms"]
    if total["junctions_in_documents"] != accounted:
        print("FAIL: %d record(s), %d accounted for" % (total["junctions_in_documents"], accounted), file=sys.stderr)
        return 1
    if total["junctions_planned"] != total["junctions_built"]:
        print("FAIL: planned %d, built %d" % (total["junctions_planned"], total["junctions_built"]), file=sys.stderr)
        return 1
    if skipped:
        print("skipped (%d): %s" % (len(skipped), json.dumps(skipped[:20])))

    if opts["out"]:
        d = os.path.dirname(opts["out"])
        if d and not os.path.isdir(d):
            os.makedirs(d)
        with open(opts["out"], "w", encoding="utf-8", newline="\n") as fh:
            json.dump({"slices": files, "totals": total,
                       "numpy": (audit if audit else None),
                       "mismatches": bad}, fh, indent=1, sort_keys=True)
            fh.write("\n")
        print("written: %s" % opts["out"])
    if bad:
        print("FAIL: %d count(s) differ from the numpy audit: %s" % (len(bad), " | ".join(bad)), file=sys.stderr)
        return 1
    print("THANET_OK junction_totals %s" % json.dumps(
        {"slices": total["slices"], "junctions_built": total["junctions_built"],
         "trimmed_ends": total["trimmed_ends"], "matches_numpy": audit is not None and not bad}))
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
