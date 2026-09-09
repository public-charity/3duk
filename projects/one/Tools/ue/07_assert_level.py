"""07_assert_level - is the saved level actually the level we claim it is? (the assertion pass of 00_build_level.ps1)

  run_ue_python.ps1 -Script 07_assert_level.py -Render -Args "--data <DATA> [--map /Game/Thanet/Maps/Thanet]
      [--expect-streetscape-actors N] [--expect-landscape-components N] [--expect-massing-actors N]
      [--expect-buildings N] [--census-only] [--out <json>]"

Opens the map in a fresh commandlet, streams the WHOLE world in (World Partition loads nothing on its own in a
commandlet - Tools/ue/README.md), takes a census of every actor class in it, and compares the counts that matter
against the adapter's own manifests:

  landscape   components / streaming proxies   <- landscape_manifest.json (nx, ny, res -> the plan)
  streetscape actors                           <- streetscape_manifest.json splines_by_layer, summed
  massing     actors / buildings               <- massing_manifest.json files / buildings
  explorer    a PlayerStart and a game mode with a default pawn

Every expectation the caller does not give is read from the manifests; --expect-* overrides one. A count that is
short, or a level with no landscape at all, is a THANET_FAIL. --census-only prints the census and expectations
without failing, which is what you want when you are diagnosing rather than gating.

This exists because the level was a hand-assembled artefact nobody could rebuild or check in one command: the
round's headline numbers all came from separate probe runs, and when an actor went missing between two of them
there was nothing that would have noticed.
"""
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import unreal  # noqa: E402

import ue_common as uc  # noqa: E402

NAME = "07_assert_level"
DEFAULT_MAP = "/Game/Thanet/Maps/Thanet"


def census(world):
    eas = unreal.get_editor_subsystem(unreal.EditorActorSubsystem)
    counts = {}
    for a in eas.get_all_level_actors():
        cn = str(a.get_class().get_name())
        counts[cn] = counts.get(cn, 0) + 1
    return counts


def registry_census(map_path):
    """Actor classes counted from the World Partition external-actor packages WITHOUT loading them.

    At site scale the level holds 15,422 streetscape actors and streaming them all in to count them is not a
    check, it is a memory experiment. The asset registry knows every external actor's class from its package
    header, so this is the count that scales - and it is the count of what is ON DISK, which is what a fresh
    editor session would open."""
    ar = unreal.AssetRegistryHelpers.get_asset_registry()
    rel = map_path[len("/Game"):] if map_path.startswith("/Game") else map_path
    root = "/Game/__ExternalActors__" + rel
    ar.scan_paths_synchronous([root], True)
    counts = {}
    for d in ar.get_assets_by_path(root, recursive=True):
        cn = str(d.asset_class_path.asset_name)
        counts[cn] = counts.get(cn, 0) + 1
    return {"root": root, "counts": counts, "packages": sum(counts.values())}


def main(argv):
    opts = uc.parse_args(argv, flags=("census_only", "no_load_all"), options={
        "data": "", "map": DEFAULT_MAP, "out": "",
        "expect_streetscape_actors": "", "expect_landscape_components": "",
        "expect_massing_actors": "", "expect_buildings": "",
    })
    data = (opts["data"] or uc.data_dir()).replace("\\", "/").rstrip("/")

    les = unreal.get_editor_subsystem(unreal.LevelEditorSubsystem)
    if not les.load_level(opts["map"]):
        uc.fail(NAME, "load_level(%s) failed" % opts["map"])

    disk = registry_census(opts["map"])
    uc.log("external-actor census (on disk, nothing loaded): %s" % json.dumps(disk, sort_keys=True))

    if not opts["no_load_all"]:
        unreal.StreetscapeEditorLibrary.load_region(unreal.Vector(0, 0, 0), 2000000.0)
        uc.log("streamed the whole world in (rss %.0f MB) after %.1fs"
               % (unreal.StreetscapeLandscapeImporter.rss_mb(), uc.elapsed_s()))

    world = unreal.get_editor_subsystem(unreal.UnrealEditorSubsystem).get_editor_world()
    actors = census(world)
    uc.log("actor census (streamed in): %s" % json.dumps(actors, sort_keys=True))

    # ---- what the manifests say there should be
    expect = {}
    def manifest(rel):
        p = "%s/%s" % (data, rel)
        if not os.path.isfile(p):
            return None
        with open(p) as fh:
            return json.load(fh)

    lm = manifest("landscape/landscape_manifest.json")
    sm = manifest("streetscape/streetscape_manifest.json")
    mm = manifest("massing/massing_manifest.json")
    if sm:
        expect["streetscape_actors"] = sum(int(v) for v in (sm.get("splines_by_layer") or {}).values())
    if mm:
        expect["massing_actors"] = int(mm.get("files") or 0)
        expect["buildings"] = int(mm.get("buildings") or 0)
    if lm:
        imp = unreal.StreetscapeLandscapeImporter
        plan = json.loads(imp.plan_site_json("%s/landscape/landscape_manifest.json" % data, 127, 2, 4))
        if not plan.get("error"):
            expect["landscape_components"] = int(plan.get("components_planned") or 0)
            expect["landscape_proxies"] = int(plan.get("proxies_expected") or 0)
    for key, opt in (("streetscape_actors", "expect_streetscape_actors"),
                     ("landscape_components", "expect_landscape_components"),
                     ("massing_actors", "expect_massing_actors"),
                     ("buildings", "expect_buildings")):
        if opts[opt]:
            expect[key] = int(opts[opt])

    # ---- what the level actually holds
    imp = unreal.StreetscapeLandscapeImporter
    land = imp.find_landscape()
    dc = disk["counts"]

    def count(cls):
        """On-disk count when the registry knows about the class, else what actually streamed in."""
        return dc.get(cls, actors.get(cls, 0))

    got = {
        "streetscape_actors": count("StreetscapeActor"),
        "massing_actors": count("StreetscapeMassingActor"),
        "landscape_actors": count("Landscape"),
        "landscape_proxy_actors": count("LandscapeStreamingProxy"),
        "player_starts": count("PlayerStart"),
        "site_actors": count("StreetscapeSiteActor"),
        "streetscape_actors_streamed": actors.get("StreetscapeActor", 0),
        "massing_actors_streamed": actors.get("StreetscapeMassingActor", 0),
    }
    state = None
    if land is not None:
        state = json.loads(imp.landscape_state_json(land))
        got["landscape_components"] = state.get("components")
        got["landscape_proxies"] = state.get("proxies")
        got["landscape_extent"] = state.get("extent")
    buildings = 0
    n_massing_loaded = 0
    eas = unreal.get_editor_subsystem(unreal.EditorActorSubsystem)
    for a in eas.get_all_level_actors():
        if a.get_class().get_name() == "StreetscapeMassingActor":
            buildings += int(a.get_editor_property("stats").get_editor_property("buildings"))
            n_massing_loaded += 1
    # buildings can only be counted from actors that are actually loaded
    got["buildings"] = buildings if n_massing_loaded == got["massing_actors"] else None
    got["massing_actors_counted_for_buildings"] = n_massing_loaded

    ws = world.get_world_settings()
    gm = ws.get_editor_property("default_game_mode")
    if gm is None:
        gm = unreal.SystemLibrary.get_class_from_soft_path(
            unreal.get_default_object(unreal.GameMapsSettings).get_editor_property("global_default_game_mode"))
    pawn = None
    if gm is not None:
        cdo = unreal.get_default_object(gm)
        pawn = cdo.get_editor_property("default_pawn_class") if cdo else None
    got["game_mode"] = str(gm.get_path_name()) if gm else None
    got["default_pawn_class"] = str(pawn.get_path_name()) if pawn else None

    # ---- compare
    problems = []
    if opts["no_load_all"]:
        # nothing is streamed, so the only landscape number that exists is the on-disk proxy count
        expect.pop("landscape_components", None)
        got["landscape_proxies"] = got["landscape_proxy_actors"]
    for key, want in sorted(expect.items()):
        have = got.get(key)
        if have is None:
            if opts["no_load_all"] and key in ("buildings",):
                continue                          # buildings need loaded actors; --no-load-all cannot count them
            problems.append("%s: nothing in the level to compare against %d" % (key, want))
        elif int(have) != int(want):
            problems.append("%s: level has %s, manifests expect %d" % (key, have, want))
    if land is None and not opts["no_load_all"]:
        problems.append("the level has no ALandscape")
    if got["site_actors"] != 1:
        problems.append("expected exactly one StreetscapeSiteActor, found %d" % got["site_actors"])
    if got["player_starts"] < 1:
        problems.append("no PlayerStart: the explorer has nowhere to spawn")
    if not got["default_pawn_class"]:
        problems.append("the map's game mode has no default pawn class")

    payload = {"map": opts["map"], "data": data, "census": actors, "external_actors": disk, "expect": expect, "got": got,
               "landscape_state": state, "problems": problems, "census_only": bool(opts["census_only"]),
               "rss_mb": round(imp.rss_mb(), 1)}
    if opts["out"]:
        out = opts["out"].replace("\\", "/")
        os.makedirs(os.path.dirname(out), exist_ok=True)
        with open(out, "w", newline="\n") as fh:
            json.dump(payload, fh, indent=1, sort_keys=True)
            fh.write("\n")
        payload["out"] = out
    if problems and not opts["census_only"]:
        uc.fail(NAME, "the level is not what the manifests describe: %s | %s"
                % ("; ".join(problems), json.dumps({"expect": expect, "got": got}, sort_keys=True)))
    uc.report(NAME, payload)


if __name__ == "__main__":
    main(sys.argv)
