"""Import a Streetscape JSON document into the level as AStreetscapeActors (UE_PLAN.md 5.3 row 3).

  run_ue_python.ps1 -Script 03_import_streetscape.py -Args "--json <file-or-dir> [--player-start] [--stats-out <file>]
                                                            [--map /Game/Thanet/Maps/Thanet] [--save]
                                                            [--expect-actors N] [--stats-limit N]"
  run_ue_python.ps1 -Script 03_import_streetscape.py -Args "--verify --stats-out <file>"   (re-open a saved map)

--verify FAILS when it finds no actor: in a World Partition commandlet "nothing streamed in" and "nothing there"
are indistinguishable to the caller, so success on zero is never a pass. --expect-actors N compares the count
against the number the caller knows to expect (streetscape_manifest.splines_by_layer summed, for a site import).
--stats-limit N caps the per-actor ActorStatsJson work at N actors (0 = all); at site scale it is the slow part.
--allow-no-terrain N accepts up to N splines whose stations all sampled NO ground (they are built flat at z = 0,
which is geometry that looks right and is wrong); the default 0 fails the import and names them.

One actor per spline, labelled with the spline id, with the components its profile_ids ask for (Road, EdgeLeft,
EdgeRight, HedgeLeft, HedgeRight, Overlay) and the mesh built from the SAME FStreetSamples the spline produced.
--stats-out writes the ActorStatsJson of the FIRST spline (the parity reference Tools/ue/compare_stats.py reads).
Prints THANET_OK 03_import_streetscape {...} with the per-actor buffer counts.
"""
import json
import os
import sys

import unreal

import ue_common as uc

NAME = "03_import_streetscape"
DEFAULT_MAP = "/Game/Thanet/Maps/Thanet"
# BRIEF 4.1: the thanet grid origin. Only used when the level has no site actor yet.
DEFAULT_ORIGIN_E = 627680.0
DEFAULT_ORIGIN_N = 163080.0


def component_names(actor):
    out = []
    for c in actor.get_components_by_class(unreal.SceneComponent):
        out.append(str(c.get_name()))
    return sorted(out)


def actor_summary(stats_text):
    """The few numbers the run should print (the whole stats.json goes to --stats-out)."""
    if not stats_text:
        return None
    st = json.loads(stats_text)
    return {
        "length_m": st.get("length_m"),
        "n_samples": st.get("n_samples"),
        "overlap": [st.get("overlap_min"), st.get("overlap_max")],
        "marking_strips": st.get("marking_strips"),
        "instances": st.get("instances"),
        "buffers": {k: [v["verts"], v["tris"]] for k, v in (st.get("buffers") or {}).items()},
        "stations_identical": st.get("stations_identical"),
        "validate": {k: v for k, v in (st.get("validate") or {}).items() if v},
    }


def main(argv):
    opts = uc.parse_args(
        argv,
        flags=("player_start", "save", "verify", "no_preload", "purge", "census"),
        options={"json": "", "map": DEFAULT_MAP, "stats_out": "", "site": "", "origin_e": "", "origin_n": "",
                 "region_radius_m": "20000", "set_game_mode": "", "expect_actors": "", "stats_limit": "0", "slice": "", "allow_no_terrain": "0", "files": "",
                 "first": "", "sample_mode": ""},
    )
    src = ""
    if not opts["verify"] and not opts["files"]:
        if not opts["json"]:
            uc.fail(NAME, "--json <file-or-dir> (or --files a,b,c) is required, or --verify to re-open a saved map")
        src = opts["json"].replace("\\", "/")
        if not (os.path.isfile(src) or os.path.isdir(src)):
            uc.fail(NAME, "no such file or directory: %s" % src)

    timing = {}
    imp = unreal.StreetscapeLandscapeImporter

    def rss():
        return round(imp.rss_mb(), 1)

    les = unreal.get_editor_subsystem(unreal.LevelEditorSubsystem)
    if not les.load_level(opts["map"]):
        uc.fail(NAME, "load_level(%s) failed" % opts["map"])
    uc.log("map %s loaded after %.1fs (rss %.1f MB)" % (opts["map"], uc.elapsed_s(), rss()))
    timing["map_loaded_s"] = uc.elapsed_s()
    timing["rss_mb_after_load"] = rss()

    site_name = opts["site"] or uc.site_name()
    origin_e = float(opts["origin_e"]) if opts["origin_e"] else DEFAULT_ORIGIN_E
    origin_n = float(opts["origin_n"]) if opts["origin_n"] else DEFAULT_ORIGIN_N
    site = unreal.StreetscapeEditorLibrary.ensure_site_actor(site_name, origin_e, origin_n)
    if site is None:
        uc.fail(NAME, "ensure_site_actor failed")
    terrain = site.get_editor_property("terrain_source")
    # WHICH SURFACE THE STREET IS DRAPED FROM. UStreetHeightfieldTerrain defaults to the landscape's own
    # triangulated rule, because that is the ground the pawn collides with and the camera sees (docs/TERRAIN_ROADS.md
    # 3; landscape_manifest.json:sampling_note). The numpy Heightfield still defaults to bilinear, so a run whose
    # numbers are going to be compared against a numpy stats.json must pin the SAME rule on both sides:
    #     --sample-mode bilinear   for the FD parity comparison (Tools/ue/compare_stats.py)
    #     --sample-mode triangulated (or the default) for a level a player will walk on
    # Either way the rule is printed below and carried in the report's "terrain" string, so no run is ambiguous.
    if opts["sample_mode"] and terrain is not None:
        modes = {"bilinear": unreal.StreetHeightSampling.BILINEAR,
                 "triangulated": unreal.StreetHeightSampling.LANDSCAPE_TRIANGULATED}
        if opts["sample_mode"] not in modes:
            uc.fail(NAME, "--sample-mode must be bilinear or triangulated, not %r" % opts["sample_mode"])
        terrain.set_sampling(modes[opts["sample_mode"]])
    uc.log("site actor %s origin (%g, %g), terrain %s" % (
        site.get_actor_label(), origin_e, origin_n, terrain.describe_source() if terrain else "NONE"))

    if opts["verify"]:
        # re-opened map: World Partition commandlets skip LoadLastLoadedRegions, so pull the actors in by hand and
        # let OnRegister -> PostRegisterAllComponents rebuild every mesh from the saved definition (DESIGN.md 10)
        # the default radius used to be 1 km around UE (0, 0), which is the SOUTH-WEST CORNER of the site - the
        # test stretch is 11.5 km from it, so --verify streamed nothing in and then reported success on an empty
        # world. 20 km covers the whole 13.3 x 9.7 km isle.
        r = float(opts["region_radius_m"]) * 100.0
        unreal.StreetscapeEditorLibrary.load_region(unreal.Vector(0.0, 0.0, 0.0), r)
        n = len(unreal.StreetscapeEditorLibrary.streetscape_actor_ids())
        uc.log("verify: load_region(radius %g m) -> %d streetscape actor(s) after %.1fs" % (r / 100.0, n, uc.elapsed_s()))
        if n == 0:
            uc.fail(NAME, "verify found 0 AStreetscapeActor in %s after streaming a %g m radius - "
                          "'nothing streamed in' and 'nothing there' look identical, so this is a failure, not a pass"
                    % (opts["map"], r / 100.0))
    else:
        if opts["purge"]:
            # a full-site import must start from nothing: whatever a previous partial run or an audit left in the
            # level keeps its id, and an id this import does not carry is never replaced - it just stays.
            gone = unreal.StreetscapeEditorLibrary.purge_streetscape_actors()
            uc.log("--purge: destroyed %d existing AStreetscapeActor after %.1fs" % (gone, uc.elapsed_s()))
            timing["purge_s"] = uc.elapsed_s()
            timing["purged_actors"] = gone
        files = [src]
        if opts["files"]:
            # exact document list: --slice boundaries move when the directory listing changes, and re-running a
            # slice with --no-preload after that would spawn a second actor for every id it re-imports
            files = [f.replace("\\", "/") for f in opts["files"].split(",") if f.strip()]
            for f in files:
                if not os.path.isfile(f):
                    uc.fail(NAME, "--files names a file that does not exist: %s" % f)
            uc.log("--files: %d document(s)" % len(files))
        elif os.path.isdir(src):
            files = sorted(src + "/" + f for f in os.listdir(src)
                           if f.lower().endswith(".json") and not f.lower().endswith("_manifest.json"))
            if opts["slice"]:
                i, k = (int(v) for v in opts["slice"].split("/"))
                if not (1 <= i <= k):
                    uc.fail(NAME, "--slice must be i/n with 1 <= i <= n")
                files = files[(i - 1) * len(files) // k: i * len(files) // k]
                uc.log("slice %s: %d of the site's documents (%s .. %s)"
                       % (opts["slice"], len(files), os.path.basename(files[0]) if files else "-",
                          os.path.basename(files[-1]) if files else "-"))
            if not files:
                uc.fail(NAME, "no .json documents under %s for this slice" % src)
            if opts["first"]:
                # --player-start lands on the FIRST spline of the FIRST document, and the alphabetical first
                # document of the site is an arbitrary one-barrier tile. Name the document the spawn should be on.
                want = opts["first"].replace("\\", "/")
                match = [f for f in files if f == want or os.path.basename(f) == os.path.basename(want)]
                if not match:
                    uc.fail(NAME, "--first %s is not one of the %d documents being imported" % (want, len(files)))
                files = match + [f for f in files if f not in match]
                uc.log("--first: %s moved to the front of %d document(s)" % (os.path.basename(match[0]), len(files)))
        # Site scale is 15,422 actors. Preloading the whole world before EVERY document would hold the entire isle
        # in memory for the run; a slice of a fresh build knows the level holds none of its ids, so it preloads
        # once at most. --no-preload turns it off entirely (only correct on a level with no streetscape actors).
        n = 0
        preload = not opts["no_preload"]
        for k, f in enumerate(files):
            got = unreal.StreetscapeEditorLibrary.import_streetscape_json(
                f, bool(opts["player_start"]) and k == 0, preload, int(opts["allow_no_terrain"]))
            if got < 0:
                uc.fail(NAME, "import_streetscape_json(%s) failed - see the errors above" % f)
            n += got
            preload = False
            if len(files) > 1:
                uc.log("[%d/%d] %s -> %d actor(s) (total %d) after %.1fs (rss %.0f MB)"
                       % (k + 1, len(files), os.path.basename(f), got, n, uc.elapsed_s(), rss()))
        uc.log("import_streetscape_json -> %d actor(s) from %d document(s) after %.1fs (rss %.1f MB)"
               % (n, len(files), uc.elapsed_s(), rss()))
        timing["import_done_s"] = uc.elapsed_s()
        timing["rss_mb_after_import"] = rss()
        timing["documents"] = len(files)

    ids = [str(i) for i in unreal.StreetscapeEditorLibrary.streetscape_actor_ids()]
    eas = unreal.get_editor_subsystem(unreal.EditorActorSubsystem)
    actors = {}
    for a in eas.get_all_level_actors():
        if isinstance(a, unreal.StreetscapeActor):
            actors[str(a.get_editor_property("street_id"))] = a

    if opts["expect_actors"]:
        want = int(opts["expect_actors"])
        if len(ids) != want:
            uc.fail(NAME, "expected %d streetscape actor(s), the level has %d" % (want, len(ids)))
        uc.log("actor count %d == --expect-actors" % want)

    per_actor = {}
    stats_written = None
    limit = int(opts["stats_limit"])
    stats_ids = ids if limit <= 0 else ids[:limit]
    for k, sid in enumerate(stats_ids):
        text = unreal.StreetscapeEditorLibrary.actor_stats_json(sid)
        if not text:
            uc.fail(NAME, "actor_stats_json(%s) returned nothing" % sid)
        per_actor[sid] = {
            "components": component_names(actors[sid]) if sid in actors else [],
            "stats": actor_summary(text),
        }
        if k == 0 and opts["stats_out"]:
            out = opts["stats_out"].replace("\\", "/")
            d = os.path.dirname(out)
            if d and not os.path.isdir(d):
                os.makedirs(d)
            written = unreal.StreetscapeEditorLibrary.write_actor_stats_json(sid, out)
            if not written:
                uc.fail(NAME, "write_actor_stats_json(%s, %s) failed" % (sid, out))
            stats_written = str(written)
            uc.log("stats written: %s" % stats_written)

    player_starts = [str(a.get_actor_label()) for a in eas.get_all_level_actors() if isinstance(a, unreal.PlayerStart)]

    # UE_PLAN.md 7: the map itself names the game mode, so opening /Game/Thanet/Maps/Thanet and pressing Play
    # spawns the explorer regardless of the project's GlobalDefaultGameMode.
    game_mode_set = None
    if opts["set_game_mode"]:
        gm = unreal.load_class(None, opts["set_game_mode"])
        if gm is None:
            uc.fail(NAME, "--set-game-mode %r did not resolve to a class" % opts["set_game_mode"])
        world = unreal.get_editor_subsystem(unreal.UnrealEditorSubsystem).get_editor_world()
        ws = world.get_world_settings()
        ws.set_editor_property("default_game_mode", gm)
        ws.modify()
        game_mode_set = str(gm.get_path_name())
        uc.log("world settings default_game_mode = %s" % game_mode_set)

    census = None
    if opts["census"]:
        census = json.loads(unreal.StreetscapeEditorLibrary.streetscape_census_json())
        uc.log("census: %s" % json.dumps({k: v for k, v in census.items() if not isinstance(v, dict)}, sort_keys=True))
        if int(census.get("actors_without_samples") or 0) > 0:
            uc.fail(NAME, "%d of %d streetscape actor(s) have no built samples" %
                    (census["actors_without_samples"], census["actors"]))
        timing["census_done_s"] = uc.elapsed_s()

    saved = False
    after_save = {}
    if opts["save"]:
        timing["save_start_s"] = uc.elapsed_s()
        if not les.save_current_level():
            uc.fail(NAME, "save_current_level failed")
        saved = uc.save_all()
        # PreSave stashes and empties every renderer's UDynamicMesh; PostSaveRoot puts it back, so the meshes must
        # still be there in this session (DESIGN.md 10 - the design's "save then blank" bug)
        for sid in stats_ids:
            st = json.loads(unreal.StreetscapeEditorLibrary.actor_stats_json(sid))
            after_save[sid] = {k: [v["verts"], v["tris"]] for k, v in (st.get("buffers") or {}).items()}
        for sid in stats_ids:
            before = per_actor[sid]["stats"]["buffers"]
            if after_save[sid] != before:
                uc.fail(NAME, "%s: buffers changed across the save: %s -> %s" % (sid, before, after_save[sid]))
        uc.log("buffers unchanged across the save: %s" % json.dumps(after_save, sort_keys=True))
        timing["save_done_s"] = uc.elapsed_s()
        timing["save_s"] = round(timing["save_done_s"] - timing["save_start_s"], 1)
        timing["rss_mb_after_save"] = rss()

    uc.report(NAME, {
        "timing": timing,
        "census": census,
        "rss_mb_end": rss(),
        "mode": "verify" if opts["verify"] else "import",
        "json": src,
        "map": opts["map"],
        "site": site_name,
        "origin": [origin_e, origin_n],
        "terrain": terrain.describe_source() if terrain else None,
        "actors": n,
        "ids": ids if len(ids) <= 40 else (ids[:40] + ["... %d more" % (len(ids) - 40)]),
        "ids_count": len(ids),
        "stats_for": len(stats_ids),
        "per_actor": per_actor,
        "player_starts": player_starts,
        "game_mode_set": game_mode_set,
        "stats_out": stats_written,
        "saved": saved,
        "buffers_after_save": after_save,
    })


if __name__ == "__main__":
    main(sys.argv)
