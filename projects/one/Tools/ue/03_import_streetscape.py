"""Import a Streetscape JSON document into the level as AStreetscapeActors (UE_PLAN.md 5.3 row 3).

  run_ue_python.ps1 -Script 03_import_streetscape.py -Args "--json <file-or-dir> [--player-start] [--stats-out <file>]
                                                            [--map /Game/Thanet/Maps/Thanet] [--save]"
  run_ue_python.ps1 -Script 03_import_streetscape.py -Args "--verify --stats-out <file>"   (re-open a saved map)

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
        flags=("player_start", "save", "verify"),
        options={"json": "", "map": DEFAULT_MAP, "stats_out": "", "site": "", "origin_e": "", "origin_n": "",
                 "region_radius_m": "1000", "set_game_mode": ""},
    )
    src = ""
    if not opts["verify"]:
        if not opts["json"]:
            uc.fail(NAME, "--json <file-or-dir> is required (or --verify to re-open a saved map)")
        src = opts["json"].replace("\\", "/")
        if not (os.path.isfile(src) or os.path.isdir(src)):
            uc.fail(NAME, "no such file or directory: %s" % src)

    les = unreal.get_editor_subsystem(unreal.LevelEditorSubsystem)
    if not les.load_level(opts["map"]):
        uc.fail(NAME, "load_level(%s) failed" % opts["map"])
    uc.log("map %s loaded after %.1fs" % (opts["map"], uc.elapsed_s()))

    site_name = opts["site"] or uc.site_name()
    origin_e = float(opts["origin_e"]) if opts["origin_e"] else DEFAULT_ORIGIN_E
    origin_n = float(opts["origin_n"]) if opts["origin_n"] else DEFAULT_ORIGIN_N
    site = unreal.StreetscapeEditorLibrary.ensure_site_actor(site_name, origin_e, origin_n)
    if site is None:
        uc.fail(NAME, "ensure_site_actor failed")
    terrain = site.get_editor_property("terrain_source")
    uc.log("site actor %s origin (%g, %g), terrain %s" % (
        site.get_actor_label(), origin_e, origin_n, terrain.describe_source() if terrain else "NONE"))

    if opts["verify"]:
        # re-opened map: World Partition commandlets skip LoadLastLoadedRegions, so pull the actors in by hand and
        # let OnRegister -> PostRegisterAllComponents rebuild every mesh from the saved definition (DESIGN.md 10)
        r = float(opts["region_radius_m"]) * 100.0
        unreal.StreetscapeEditorLibrary.load_region(unreal.Vector(0.0, 0.0, 0.0), r)
        n = len(unreal.StreetscapeEditorLibrary.streetscape_actor_ids())
        uc.log("verify: load_region(radius %g m) -> %d streetscape actor(s) after %.1fs" % (r / 100.0, n, uc.elapsed_s()))
    else:
        n = unreal.StreetscapeEditorLibrary.import_streetscape_json(src, bool(opts["player_start"]))
        if n < 0:
            uc.fail(NAME, "import_streetscape_json(%s) failed - see the errors above" % src)
        uc.log("import_streetscape_json -> %d actor(s) after %.1fs" % (n, uc.elapsed_s()))

    ids = [str(i) for i in unreal.StreetscapeEditorLibrary.streetscape_actor_ids()]
    eas = unreal.get_editor_subsystem(unreal.EditorActorSubsystem)
    actors = {}
    for a in eas.get_all_level_actors():
        if isinstance(a, unreal.StreetscapeActor):
            actors[str(a.get_editor_property("street_id"))] = a

    per_actor = {}
    stats_written = None
    for k, sid in enumerate(ids):
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

    saved = False
    after_save = {}
    if opts["save"]:
        if not les.save_current_level():
            uc.fail(NAME, "save_current_level failed")
        saved = uc.save_all()
        # PreSave stashes and empties every renderer's UDynamicMesh; PostSaveRoot puts it back, so the meshes must
        # still be there in this session (DESIGN.md 10 - the design's "save then blank" bug)
        for sid in ids:
            st = json.loads(unreal.StreetscapeEditorLibrary.actor_stats_json(sid))
            after_save[sid] = {k: [v["verts"], v["tris"]] for k, v in (st.get("buffers") or {}).items()}
        for sid in ids:
            before = per_actor[sid]["stats"]["buffers"]
            if after_save[sid] != before:
                uc.fail(NAME, "%s: buffers changed across the save: %s -> %s" % (sid, before, after_save[sid]))
        uc.log("buffers unchanged across the save: %s" % json.dumps(after_save, sort_keys=True))

    uc.report(NAME, {
        "mode": "verify" if opts["verify"] else "import",
        "json": src,
        "map": opts["map"],
        "site": site_name,
        "origin": [origin_e, origin_n],
        "terrain": terrain.describe_source() if terrain else None,
        "actors": n,
        "ids": ids,
        "per_actor": per_actor,
        "player_starts": player_starts,
        "game_mode_set": game_mode_set,
        "stats_out": stats_written,
        "saved": saved,
        "buffers_after_save": after_save,
    })


if __name__ == "__main__":
    main(sys.argv)
