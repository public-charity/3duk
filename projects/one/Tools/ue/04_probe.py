"""04_probe - height / clip / collision probes over the landscape and the streetscape (UE_PLAN.md 5.3 row 4).

Three modes, all headless:

  --points <csv> [--landscape]
      CSV in ("x,y" header plus rows of local metres) -> CSV out on stdout:
      x, y, z_heightfield, z_landscape, z_landscape_collision, clipped
      z_heightfield is the adapter's file (UStreetHeightfieldTerrain, the reference), z_landscape is
      ALandscapeProxy::GetHeightAtLocation on the imported landscape (needs --landscape and -Render), and
      "clipped" is 1 where the heightfield has no ground (outside the clip or outside coverage).

  --actor <spline id> --trace-from-above
      one downward line_trace per spline station over that streetscape actor's road, reporting blocked / free -
      the "the road is walkable after a save" check of UE_PLAN.md 8.7.

  --explorer
      loads the map and prints the game mode, its default pawn class, and every PlayerStart transform
      (UE_PLAN.md 7 / 8.10). PIE cannot be driven from a commandlet, so this proves the wiring, not the walking.

    run_ue_python.ps1 -Script 04_probe.py -Render -Args "--points <csv> --landscape"
"""
import json
import math
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import unreal  # noqa: E402

import ue_common as uc  # noqa: E402

NAME = "04_probe"
DEFAULT_MAP = "/Game/Thanet/Maps/Thanet"


def _n(v):
    return "" if (v is None or (isinstance(v, float) and math.isnan(v))) else "%.4f" % v


def load_map(map_path):
    les = unreal.get_editor_subsystem(unreal.LevelEditorSubsystem)
    world = unreal.get_editor_subsystem(unreal.UnrealEditorSubsystem).get_editor_world()
    if world is None or world.get_name() != map_path.rsplit("/", 1)[-1]:
        if not les.load_level(map_path):
            uc.fail(NAME, "load_level(%s) failed" % map_path)
    return unreal.get_editor_subsystem(unreal.UnrealEditorSubsystem).get_editor_world()


def mode_points(opts):
    imp = unreal.StreetscapeLandscapeImporter
    hf = uc.heightfield(opts["landscape_dir"] or None)
    if hf is None:
        uc.fail(NAME, "no site actor / terrain source in this level")
    land = imp.find_landscape() if opts["landscape"] else None
    if opts["landscape"] and land is None:
        uc.fail(NAME, "--landscape given but the level has no ALandscape")
    rows = []
    with open(opts["points"]) as fh:
        for line in fh:
            line = line.strip()
            if not line or line.lower().startswith("x,"):
                continue
            parts = line.split(",")
            if len(parts) < 2:
                continue
            rows.append((float(parts[0]), float(parts[1])))
    print("x,y,z_heightfield,z_landscape,z_landscape_collision,clipped")
    n_clipped = 0
    n_land_none = 0
    max_dz = 0.0
    for x, y in rows:
        zh = hf.probe_m(x, y)
        zl = imp.probe_height_m(land, x, y, False) if land else float("nan")
        zc = imp.probe_height_m(land, x, y, True) if land else float("nan")
        clipped = 1 if math.isnan(zh) else 0
        n_clipped += clipped
        if land and math.isnan(zl):
            n_land_none += 1
        elif land and not math.isnan(zh):
            max_dz = max(max_dz, abs(zh - zl))
        print("%.4f,%.4f,%s,%s,%s,%d" % (x, y, _n(zh), _n(zl), _n(zc), clipped))
    return {"mode": "points", "points": len(rows), "clipped": n_clipped,
            "landscape": bool(land), "landscape_none": n_land_none,
            "max_abs_dz_m": round(max_dz, 5) if land else None}


def find_streetscape_actor(street_id):
    eas = unreal.get_editor_subsystem(unreal.EditorActorSubsystem)
    for a in eas.get_all_level_actors():
        if a.get_class().get_name() != "StreetscapeActor":
            continue
        if str(a.get_editor_property("street_id")) == street_id or str(a.get_actor_label()) == street_id:
            return a
    return None


def mode_actor(opts):
    lib = unreal.StreetscapeEditorLibrary
    imp = unreal.StreetscapeLandscapeImporter
    lib.load_region(unreal.Vector(0, 0, 0), 2000000.0)
    actor = find_streetscape_actor(opts["actor"])
    if actor is None:
        uc.fail(NAME, "no AStreetscapeActor with id %r (ids: %s)" % (opts["actor"], [str(i) for i in lib.streetscape_actor_ids()]))
    spline = actor.get_editor_property("spline")
    if spline is None:
        uc.fail(NAME, "actor %s has no spline component" % opts["actor"])
    length_cm = spline.get_spline_length()
    step_cm = float(opts["step_m"]) * 100.0
    n = max(2, int(length_cm // step_cm) + 1)
    blocked = 0
    rows = []
    for i in range(n):
        d = min(length_cm, i * step_cm)
        p = spline.get_location_at_distance_along_spline(d, unreal.SplineCoordinateSpace.WORLD)
        x, y, z = p.x / 100.0, -p.y / 100.0, p.z / 100.0
        zt = imp.trace_down_zm(x, y, z + 5.0, z - 5.0)
        hit = not (zt is None or math.isnan(zt))
        blocked += int(hit)
        rows.append({"s_m": round(d / 100.0, 2), "xy": [round(x, 3), round(y, 3)], "z_spline_m": round(z, 3),
                     "trace_z_m": None if not hit else round(zt, 3), "blocked": hit,
                     "dz_m": None if not hit else round(zt - z, 4)})
    print(json.dumps({"actor": opts["actor"], "length_m": round(length_cm / 100.0, 3), "stations": len(rows),
                      "blocked": blocked, "rows": rows[:10]}, sort_keys=True))
    return {"mode": "actor", "actor": opts["actor"], "length_m": round(length_cm / 100.0, 3),
            "stations": len(rows), "blocked": blocked,
            "all_blocked": blocked == len(rows) and len(rows) > 0,
            "max_abs_dz_m": round(max((abs(r["dz_m"]) for r in rows if r["dz_m"] is not None), default=float("nan")), 4)}


def mode_explorer(opts):
    world = unreal.get_editor_subsystem(unreal.UnrealEditorSubsystem).get_editor_world()
    ws = world.get_world_settings()
    gm_cls = ws.get_editor_property("default_game_mode")
    source = "world settings"
    gm_path = str(unreal.get_default_object(unreal.GameMapsSettings).get_editor_property("global_default_game_mode"))
    if gm_cls is None:
        # the map does not override it: the project's GlobalDefaultGameMode applies
        gm_cls = unreal.load_class(None, gm_path.split("'")[-2] if "'" in gm_path else gm_path)
        source = "project (GlobalDefaultGameMode %s)" % gm_path
    gm_name = str(gm_cls.get_name()) if gm_cls else None
    pawn_name = None
    if gm_cls is not None:
        cdo = unreal.get_default_object(gm_cls)
        pawn_cls = cdo.get_editor_property("default_pawn_class") if cdo else None
        pawn_name = str(pawn_cls.get_name()) if pawn_cls else None

    eas = unreal.get_editor_subsystem(unreal.EditorActorSubsystem)
    unreal.StreetscapeEditorLibrary.load_region(unreal.Vector(0, 0, 0), 2000000.0)
    starts = []
    for a in eas.get_all_level_actors():
        if a.get_class().get_name() == "PlayerStart":
            loc = a.get_actor_location()
            rot = a.get_actor_rotation()
            starts.append({"label": str(a.get_actor_label()),
                           "location_cm": [round(loc.x, 2), round(loc.y, 2), round(loc.z, 2)],
                           "location_local_m": [round(loc.x / 100.0, 3), round(-loc.y / 100.0, 3), round(loc.z / 100.0, 3)],
                           "rotation": [round(rot.pitch, 2), round(rot.yaw, 2), round(rot.roll, 2)]})
    out = {"mode": "explorer", "game_mode": gm_name, "game_mode_source": source, "global_default_game_mode": gm_path, "default_pawn_class": pawn_name,
           "player_starts": starts,
           "note": "Play In Editor cannot be driven from a commandlet; this proves the class wiring and the spawn point, not the walking."}
    print(json.dumps(out, sort_keys=True))
    return out


def main(argv):
    opts = uc.parse_args(argv, flags=("landscape", "trace_from_above", "explorer"), options={
        "points": "", "actor": "", "map": DEFAULT_MAP, "step_m": "1.0", "landscape_dir": "",
    })
    load_map(opts["map"])
    if opts["explorer"]:
        payload = mode_explorer(opts)
    elif opts["actor"]:
        payload = mode_actor(opts)
    elif opts["points"]:
        payload = mode_points(opts)
    else:
        uc.fail(NAME, "one of --points, --actor or --explorer is required")
    uc.report(NAME, payload)


if __name__ == "__main__":
    main(sys.argv)
