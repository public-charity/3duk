"""Stream in ONE junction and prove it is complete without the rest of the isle.

  run_ue_python.ps1 -Script 09_junction_probe.py -Args "--nodes 5165.5,7121.6,3;7069.5,3073.7,4 [--radius-m 400]
                                                        [--map /Game/Thanet/Maps/Thanet] [--out <json>]"

A junction's arms are DIFFERENT actors and the patch is built into the owning arm's own road buffer, so the
obvious implementation - have the owner look its neighbours up in the world - draws a correct junction only when
every arm happens to be resident. That is not good enough for a digital twin, and this is the measurement that
says whether it was avoided: a fresh commandlet, a loader shape of `--radius-m` around one node and nothing else,
and then a census of what those resident actors actually built.

The pass condition is that the resident actors report junctions_owned == junctions_built with nothing skipped,
and at least one junction present. `actors_resident` says how few actors were loaded, which is the point: the
number is hundreds, not 15,423.

LOADER SHAPES ACCUMULATE. `LoadRegion` keeps every adapter it makes for the life of the process, so with more
than one --nodes the census is CUMULATIVE: row 2 counts row 1's actors as well. Each row therefore carries both
the running total and `delta_*`, what this node's own region added. Neither number is an estimate.
"""
import json
import os
import sys

import unreal

import ue_common as uc

NAME = "09_junction_probe"
DEFAULT_MAP = "/Game/Thanet/Maps/Thanet"


def main(argv):
    opts = uc.parse_args(
        argv,
        flags=(),
        options={"nodes": "", "radius_m": "400", "map": DEFAULT_MAP, "out": ""},
    )
    if not opts["nodes"]:
        uc.fail(NAME, "--nodes x,y[,arms];x,y[,arms] (document metres) is required")
    nodes = []
    for part in opts["nodes"].split(";"):
        part = part.strip()
        if not part:
            continue
        bits = part.split(",")
        nodes.append((float(bits[0]), float(bits[1]), int(bits[2]) if len(bits) > 2 else 0))

    les = unreal.get_editor_subsystem(unreal.LevelEditorSubsystem)
    if not les.load_level(opts["map"]):
        uc.fail(NAME, "load_level(%s) failed" % opts["map"])
    uc.log("map %s loaded after %.1fs" % (opts["map"], uc.elapsed_s()))

    radius_cm = float(opts["radius_m"]) * 100.0
    rows = []
    problems = []
    prev = None
    for x, y, arms in nodes:
        # ToUE: (x * 100, -y * 100, z * 100)
        unreal.StreetscapeEditorLibrary.load_region(unreal.Vector(x * 100.0, -y * 100.0, 0.0), radius_cm)
        c = json.loads(unreal.StreetscapeEditorLibrary.streetscape_census_json())
        row = {
            "node": [x, y],
            "arms_expected": arms,
            "radius_m": float(opts["radius_m"]),
            "actors_resident": int(c["actors"]),
            "junctions_owned": int(c["junctions_owned"]),
            "junctions_built": int(c["junctions_built"]),
            "junctions_skipped": int(c["junctions_skipped"]),
            "patch_verts": int(c["junction_patch_verts"]),
            "patch_tris": int(c["junction_patch_tris"]),
            "corners": int(c["junction_corners"]),
            "corner_tris": int(c["junction_corner_tris"]),
            "splines_trimmed": int(c["splines_trimmed"]),
            "trimmed_ends": int(c["trimmed_ends"]),
        }
        for k in ("actors_resident", "junctions_owned", "junctions_built", "patch_verts", "patch_tris",
                  "corners", "corner_tris", "splines_trimmed", "trimmed_ends"):
            row["delta_" + k] = row[k] - (prev[k] if prev else 0)
        prev = row
        rows.append(row)
        uc.log("node (%.1f, %.1f) r=%s m: %d actor(s) resident, %d/%d junctions built, %d skipped, "
               "patch %d/%d, corners %d/%d, %d spline(s) trimmed"
               % (x, y, opts["radius_m"], row["actors_resident"], row["junctions_built"], row["junctions_owned"],
                  row["junctions_skipped"], row["patch_verts"], row["patch_tris"], row["corners"],
                  row["corner_tris"], row["splines_trimmed"]))
        if row["delta_junctions_owned"] == 0:
            problems.append("(%.1f, %.1f): no junction is owned by any resident actor" % (x, y))
        if row["junctions_built"] != row["junctions_owned"] or row["junctions_skipped"]:
            problems.append("(%.1f, %.1f): owned %d, built %d, skipped %d"
                            % (x, y, row["junctions_owned"], row["junctions_built"], row["junctions_skipped"]))

    if problems:
        uc.fail(NAME, "a partially loaded world did not draw its junctions: %s" % " | ".join(problems))

    if opts["out"]:
        out = opts["out"].replace("\\", "/")
        d = os.path.dirname(out)
        if d and not os.path.isdir(d):
            os.makedirs(d)
        with open(out, "w", encoding="utf-8", newline="\n") as fh:
            json.dump({"map": opts["map"], "radius_m": float(opts["radius_m"]), "nodes": rows}, fh,
                      indent=1, sort_keys=True)
            fh.write("\n")
        uc.log("written: %s" % out)

    uc.report(NAME, {"nodes": len(rows),
                     "junctions_built": sum(r["junctions_built"] for r in rows),
                     "max_actors_resident": max(r["actors_resident"] for r in rows) if rows else 0})
    return 0


if __name__ == "__main__":
    main(sys.argv)
