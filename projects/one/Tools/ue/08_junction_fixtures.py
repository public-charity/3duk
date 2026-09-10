"""Drive the SIX frozen junction fixtures through the REAL import path and check the counts to the digit.

  run_ue_python.ps1 -Script 08_junction_fixtures.py -Args "--docs <dir> [--map /Game/Thanet/Maps/_JunctionFixtures]
                                                           [--expected <expected.json>] [--report <file>]"

WHY THIS EXISTS. `Streetscape.Junction.*` already proves the geometry, and it proved it for a whole round while
the level held no junction at all, because those tests call `FStreetRenderBuild::BuildJunctionPatch` directly and
nothing in `UStreetscapeEditorLibrary::ImportStreetscapeJson` ever did. So this asserts the same frozen numbers at
the other end of the pipe: it imports the fixture documents with the same call a site import makes, then reads the
counts back off the ACTORS - `junction_stats` on each AStreetscapeActor and `last_import_junctions_json()` for the
run as a whole - and compares them with `Tools/blender/tests/fixtures/expected.json`.

The documents come from the numpy toolchain (`junction_fixture_docs.py`), and the terrain is the plane those
numbers were frozen on (`UStreetHeightfieldTerrain.set_synthetic_plane`, read out of each document's `_terrain`
note), so nothing about the comparison is approximate. Zero junctions is a FAILURE, never a pass.
"""
import json
import os
import sys

import unreal

import ue_common as uc

NAME = "08_junction_fixtures"
DEFAULT_MAP = "/Game/Thanet/Maps/_JunctionFixtures"


def buffers_of(actor):
    """Every non-empty renderer buffer of one actor as {name: [verts, tris]} (the census's own keys)."""
    text = unreal.StreetscapeEditorLibrary.actor_stats_json(str(actor.get_editor_property("street_id")))
    st = json.loads(text) if text else {}
    return {k: [v["verts"], v["tris"]] for k, v in (st.get("buffers") or {}).items()}


def main(argv):
    opts = uc.parse_args(
        argv,
        flags=(),
        options={"docs": "", "map": DEFAULT_MAP, "expected": "", "report": ""},
    )
    docs = opts["docs"].replace("\\", "/")
    if not docs or not os.path.isdir(docs):
        uc.fail(NAME, "--docs <dir> written by junction_fixture_docs.py is required")
    expected_path = (opts["expected"] or
                     os.path.join(uc.project_dir(), "Tools/blender/tests/fixtures/expected.json")).replace("\\", "/")
    if not os.path.isfile(expected_path):
        uc.fail(NAME, "no expected.json at %s" % expected_path)
    expected = json.load(open(expected_path, "r", encoding="utf-8"))["junction"]["fixtures"]

    files = sorted(docs + "/" + f for f in os.listdir(docs) if f.lower().endswith(".json"))
    if not files:
        uc.fail(NAME, "no documents under %s" % docs)

    les = unreal.get_editor_subsystem(unreal.LevelEditorSubsystem)
    # a fresh, EMPTY level: the fixtures are authored at origin (0, 0) and the Thanet site actor is at
    # (627680, 163080), so importing them into the site map would be rejected on the origin - and should be.
    # new_level refuses to overwrite, so a re-run loads the scratch map it made last time and empties it.
    if unreal.EditorAssetLibrary.does_asset_exist(opts["map"]):
        if not les.load_level(opts["map"]):
            uc.fail(NAME, "load_level(%s) failed" % opts["map"])
        gone = unreal.StreetscapeEditorLibrary.purge_streetscape_actors()
        uc.log("scratch level %s reloaded, %d stale actor(s) purged after %.1fs" % (opts["map"], gone, uc.elapsed_s()))
    else:
        if not les.new_level(opts["map"]):
            uc.fail(NAME, "new_level(%s) failed" % opts["map"])
        uc.log("empty level %s created after %.1fs" % (opts["map"], uc.elapsed_s()))

    # The totals ACCUMULATE across import calls (a site import is one call per document), so they are zeroed once
    # here and each fixture's own numbers are read as the delta. Six fixtures through one accumulator is also the
    # check that the accumulation itself is right - the last row's running total must be the sum of all six.
    unreal.StreetscapeEditorLibrary.reset_import_junction_totals()
    running = {}
    results = {}
    problems = []
    for path in files:
        name = os.path.splitext(os.path.basename(path))[0]
        want = expected.get(name)
        if want is None:
            uc.log("skipping %s: not one of the frozen fixtures" % name)
            continue
        doc = json.load(open(path, "r", encoding="utf-8"))

        site = unreal.StreetscapeEditorLibrary.ensure_site_actor(
            str(doc["site"]), float(doc["origin"]["E"]), float(doc["origin"]["N"]))
        if site is None:
            uc.fail(NAME, "ensure_site_actor failed for %s" % name)
        terrain = site.get_editor_property("terrain_source")
        if terrain is None:
            uc.fail(NAME, "the site actor has no terrain source")
        # synthetic.junction_terrain_for: a grade note, or flat 10 m
        t = doc.get("_terrain") or {}
        z0 = float(t.get("z_m", 10.0))
        gx = float(t.get("gx", 0.0)) if t.get("kind") == "grade" else 0.0
        gy = float(t.get("gy", 0.0)) if t.get("kind") == "grade" else 0.0
        terrain.set_synthetic_plane(z0, gx, gy)
        uc.log("%s: terrain %s" % (name, terrain.describe_source()))

        # THE REAL IMPORT. bPreloadWorld=False is correct and documented: this level holds no streetscape actor.
        got = unreal.StreetscapeEditorLibrary.import_streetscape_json(path, False, False, 0)
        if got < 0:
            uc.fail(NAME, "import_streetscape_json(%s) failed - see the errors above" % name)

        cumulative = json.loads(unreal.StreetscapeEditorLibrary.last_import_junctions_json())
        summary = {k: (v - running.get(k, 0)) if isinstance(v, (int, float)) else v
                   for k, v in cumulative.items()}
        running = {k: v for k, v in cumulative.items() if isinstance(v, (int, float))}
        eas = unreal.get_editor_subsystem(unreal.EditorActorSubsystem)
        actors = [a for a in eas.get_all_level_actors() if isinstance(a, unreal.StreetscapeActor)]
        verts = tris = 0
        owners = []
        trimmed_ends = 0
        for a in actors:
            for _, vt in buffers_of(a).items():
                verts += vt[0]
                tris += vt[1]
            js = a.get_editor_property("junction_stats")
            trim = a.get_editor_property("junction_trim_m")
            if trim.x > 0.0:
                trimmed_ends += 1
            if trim.y > 0.0:
                trimmed_ends += 1
            if int(js.get_editor_property("owned")) > 0:
                owners.append(str(a.get_editor_property("street_id")))

        got_row = {
            "splines": got,
            "actors": len(actors),
            "arms": int(summary["arms"]),
            "junctions_built": int(summary["junctions_built"]),
            "patch_verts": int(summary["patch_verts"]),
            "patch_tris": int(summary["patch_tris"]),
            "corners": int(summary["corners"]),
            "corner_tris": int(summary["corner_tris"]),
            "trimmed_ends": trimmed_ends,
            "total_verts": verts,
            "total_tris": tris,
            "owner": owners[0] if owners else None,
            "skipped": list(summary.get("skipped") or []),
        }
        want_row = {
            "arms": int(want["arms"]),
            "junctions_built": 1,
            "patch_verts": int(want["patch_verts"]),
            "patch_tris": int(want["patch_tris"]),
            "corners": int(want["corners"]),
            "corner_tris": int(want["corner_tris"]),
            "trimmed_ends": int(want["arms"]),
            "total_verts": int(want["total_verts"]),
            "total_tris": int(want["total_tris"]),
        }
        bad = {k: [got_row[k], v] for k, v in want_row.items() if got_row[k] != v}
        if bad:
            problems.append("%s: %s" % (name, json.dumps(bad, sort_keys=True)))
        if got_row["skipped"]:
            problems.append("%s: skipped %s" % (name, got_row["skipped"]))
        results[name] = {"got": got_row, "want": want_row, "match": not bad}
        uc.log("%-22s built=%d patch=%d/%d corners=%d/%d total=%d/%d %s"
               % (name, got_row["junctions_built"], got_row["patch_verts"], got_row["patch_tris"],
                  got_row["corners"], got_row["corner_tris"], got_row["total_verts"], got_row["total_tris"],
                  "OK" if not bad else "MISMATCH " + json.dumps(bad, sort_keys=True)))

        # the level is reused for the next fixture, so clear it: ids do not collide but the totals would
        unreal.StreetscapeEditorLibrary.purge_streetscape_actors()

    if not results:
        uc.fail(NAME, "no fixture was imported - nothing was measured, which is not a pass")
    total_built = sum(r["got"]["junctions_built"] for r in results.values())
    if total_built == 0:
        uc.fail(NAME, "%d fixture(s) imported and NOT ONE junction was built" % len(results))
    if problems:
        uc.fail(NAME, "junction parity failed: %s" % " | ".join(problems))

    if opts["report"]:
        out = opts["report"].replace("\\", "/")
        d = os.path.dirname(out)
        if d and not os.path.isdir(d):
            os.makedirs(d)
        with open(out, "w", encoding="utf-8", newline="\n") as fh:
            json.dump({"expected": expected_path, "fixtures": results}, fh, indent=1, sort_keys=True)
            fh.write("\n")
        uc.log("report written: %s" % out)

    # the accumulator itself: six calls, one running total
    if int(running.get("junctions_built") or 0) != total_built:
        uc.fail(NAME, "the running total says %d junction(s) built, the six fixtures say %d"
                % (running.get("junctions_built"), total_built))
    uc.report(NAME, {"fixtures": len(results), "junctions_built": total_built,
                     "running_total_junctions_built": int(running.get("junctions_built") or 0),
                     "all_match": all(r["match"] for r in results.values())})
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
