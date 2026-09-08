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

  --landscape-info [--weights-at "x,y;x,y;..."]
      reads the imported landscape back: label, component and streaming-proxy counts, extent, scale, material,
      every target layer with its ULandscapeLayerInfoObject, and the painted weight of the four ground covers +
      the visibility layer at each --weights-at point (UE_PLAN.md 3.5 / DESIGN.md 9).

    run_ue_python.ps1 -Script 04_probe.py -Render -Args "--points <csv> --landscape"

World Partition: a commandlet loads no actor until a region is, so --points and --landscape-info load a box of
--load-radius-m around every point they touch before probing (Tools/ue/README.md).
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


def load_regions(points, radius_m):
    """Stream in a box of `radius_m` around every point: World Partition loads nothing in a commandlet."""
    if radius_m <= 0:
        return 0
    lib = unreal.StreetscapeEditorLibrary
    seen = set()
    n = 0
    for x, y in points:
        # one adapter per 2*radius cell, so a run of nearby points does not create thousands of adapters
        key = (int(x // (2 * radius_m)), int(y // (2 * radius_m)))
        if key in seen:
            continue
        seen.add(key)
        cx = (key[0] + 0.5) * 2 * radius_m
        cy = (key[1] + 0.5) * 2 * radius_m
        lib.load_region(unreal.Vector(100.0 * cx, -100.0 * cy, 0.0), 100.0 * radius_m * 2.0)
        n += 1
    return n


def mode_points(opts):
    imp = unreal.StreetscapeLandscapeImporter
    hf = uc.heightfield(opts["landscape_dir"] or None)
    if hf is None:
        uc.fail(NAME, "no site actor / terrain source in this level")
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
    n_regions = load_regions(rows, float(opts["load_radius_m"])) if opts["landscape"] else 0
    land = imp.find_landscape() if opts["landscape"] else None
    if opts["landscape"] and land is None:
        uc.fail(NAME, "--landscape given but the level has no ALandscape")
    uc.log("points=%d regions_loaded=%d landscape=%s" % (len(rows), n_regions, land is not None))
    # z_trace is the only honest hole test: EHeightfieldSource::Complex still reports a HEIGHT inside a
    # visibility hole (the sample is there, only its material says "hole"), so ProbeHeightM(..., true) returns a
    # number on the cut side. A line trace is what the explorer actually collides with, and it passes through.
    print("x,y,z_heightfield,z_landscape,z_landscape_collision,clipped,z_trace,blocked")
    n_clipped = 0
    n_land_none = 0
    n_blocked = 0
    max_dz = 0.0
    for x, y in rows:
        zh = hf.probe_m(x, y)
        zl = imp.probe_height_m(land, x, y, False) if land else float("nan")
        zc = imp.probe_height_m(land, x, y, True) if land else float("nan")
        zt = imp.trace_down_zm(x, y, 300.0, -300.0)
        blocked = 0 if (zt is None or math.isnan(zt)) else 1
        n_blocked += blocked
        clipped = 1 if math.isnan(zh) else 0
        n_clipped += clipped
        if land and math.isnan(zl):
            n_land_none += 1
        elif land and not math.isnan(zh):
            max_dz = max(max_dz, abs(zh - zl))
        print("%.4f,%.4f,%s,%s,%s,%d,%s,%d" % (x, y, _n(zh), _n(zl), _n(zc), clipped, _n(zt), blocked))
    return {"mode": "points", "points": len(rows), "clipped": n_clipped,
            "landscape": bool(land), "landscape_none": n_land_none, "regions_loaded": n_regions,
            "blocked": n_blocked, "unclipped": len(rows) - n_clipped,
            "blocked_matches_unclipped": n_blocked == len(rows) - n_clipped,
            "max_abs_dz_m": round(max_dz, 5) if land else None}


GROUND_LAYERS = ("grass", "sand", "rock", "water")


def mode_landscape_info(opts):
    imp = unreal.StreetscapeLandscapeImporter
    land = imp.find_landscape()
    if land is None:
        uc.fail(NAME, "the level has no ALandscape")
    pts = []
    for chunk in (opts["weights_at"] or "").split(";"):
        chunk = chunk.strip()
        if not chunk:
            continue
        a, b = chunk.split(",")
        pts.append((float(a), float(b)))
    if opts["load_all"]:
        # ULandscapeInfo::XYtoComponentMap only holds the components of proxies that are streamed in, so the
        # component / proxy counts are only the WHOLE landscape's when the whole world is loaded (~14 GB RSS).
        unreal.StreetscapeEditorLibrary.load_region(unreal.Vector(0, 0, 0), 2000000.0)
        n_regions = 1
    else:
        n_regions = load_regions(pts, float(opts["load_radius_m"]))
    state = json.loads(imp.landscape_state_json(land))
    layers = json.loads(imp.landscape_layers_json(land))
    hf = uc.heightfield(opts["landscape_dir"] or None)
    vis_name = layers.get("visibility_layer_name")
    samples = []
    for x, y in pts:
        row = {"xy": [x, y],
               "z_heightfield_m": None if hf is None or math.isnan(hf.probe_m(x, y)) else round(hf.probe_m(x, y), 4),
               "z_landscape_m": None if math.isnan(imp.probe_height_m(land, x, y, False)) else round(imp.probe_height_m(land, x, y, False), 4),
               "z_collision_m": None if math.isnan(imp.probe_height_m(land, x, y, True)) else round(imp.probe_height_m(land, x, y, True), 4),
               "w": {}}
        total = 0.0
        for name in GROUND_LAYERS:
            w = imp.probe_layer_weight(land, x, y, name)
            row["w"][name] = None if w < 0 else round(w, 4)
            if w >= 0:
                total += w
        row["w_sum"] = round(total, 4)
        if vis_name:
            v = imp.probe_layer_weight(land, x, y, vis_name)
            row["visibility"] = None if v < 0 else round(v, 4)
        samples.append(row)
    eas = unreal.get_editor_subsystem(unreal.EditorActorSubsystem)
    n_landscape_actors = 0
    n_proxy_actors = 0
    for a in eas.get_all_level_actors():
        cn = a.get_class().get_name()
        if cn == "Landscape":
            n_landscape_actors += 1
        elif cn == "LandscapeStreamingProxy":
            n_proxy_actors += 1
    out = {"mode": "landscape_info", "state": state, "layers": layers, "samples": samples,
           "regions_loaded": n_regions, "landscape_actors": n_landscape_actors,
           "landscape_streaming_proxy_actors": n_proxy_actors, "load_all": bool(opts["load_all"])}
    print(json.dumps(out, sort_keys=True))
    return {"mode": "landscape_info", "label": state.get("label"), "components": state.get("components"),
            "landscape_actors": n_landscape_actors, "landscape_streaming_proxy_actors": n_proxy_actors,
            "load_all": bool(opts["load_all"]), "rss_mb": round(imp.rss_mb(), 1),
            "proxies": state.get("proxies"), "extent": state.get("extent"), "scale": state.get("scale"),
            "material": state.get("material"), "component_size_quads": state.get("component_size_quads"),
            "num_subsections": state.get("num_subsections"),
            "target_layer_count": layers.get("target_layer_count"),
            "target_layers": [l["name"] for l in layers.get("target_layers", [])],
            "has_visibility_layer": layers.get("has_visibility_layer"),
            "ground_layers_found": layers.get("ground_layers_found"),
            "ground_layers_missing": layers.get("ground_layers_missing"),
            "samples": len(samples)}


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


def _class_path(cls):
    return str(cls.get_path_name()) if cls else None


def mode_explorer(opts):
    world = unreal.get_editor_subsystem(unreal.UnrealEditorSubsystem).get_editor_world()
    ws = world.get_world_settings()
    map_gm = ws.get_editor_property("default_game_mode")
    # SoftClassPath prints as an opaque struct (it has no exported fields): resolve it with
    # SystemLibrary.get_class_from_soft_path, which loads the class if necessary.
    project_scp = unreal.get_default_object(unreal.GameMapsSettings).get_editor_property("global_default_game_mode")
    project_gm = unreal.SystemLibrary.get_class_from_soft_path(project_scp)
    gm_cls = map_gm or project_gm
    source = "world settings (the map overrides it)" if map_gm else "project GlobalDefaultGameMode"
    pawn_cls = None
    if gm_cls is not None:
        cdo = unreal.get_default_object(gm_cls)
        pawn_cls = cdo.get_editor_property("default_pawn_class") if cdo else None

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

    # The pawn itself: spawn one (transient - it is destroyed again), build its Enhanced Input objects and read the
    # bindings back. PIE cannot run in a commandlet, so this is the wiring, not the walking.
    pawn_report = {}
    if pawn_cls is not None:
        p = eas.spawn_actor_from_class(pawn_cls, unreal.Vector(0, 0, 100000), unreal.Rotator(0, 0, 0))
        try:
            p.build_input_objects()
            mc = p.get_editor_property("mapping_context")
            pawn_report = {
                "class": _class_path(pawn_cls),
                "walk_speed_cms": p.get_editor_property("walk_speed"),
                "walk_sprint_multiplier": p.get_editor_property("walk_sprint_multiplier"),
                "fly_speed_cms": p.get_editor_property("fly_speed"),
                "fly_sprint_speed_cms": p.get_editor_property("fly_sprint_speed"),
                "capsule_radius_cm": p.get_editor_property("capsule_component").get_editor_property("capsule_radius"),
                "capsule_half_height_cm": p.get_editor_property("capsule_component").get_editor_property("capsule_half_height"),
                "camera_relative_cm": [round(v, 2) for v in (
                    p.get_editor_property("camera").get_editor_property("relative_location").x,
                    p.get_editor_property("camera").get_editor_property("relative_location").y,
                    p.get_editor_property("camera").get_editor_property("relative_location").z)],
                "controller_rotation_yaw": bool(p.get_editor_property("use_controller_rotation_yaw")),
                "max_step_height_cm": p.get_editor_property("character_movement").get_editor_property("max_step_height"),
                "jump_z_velocity": p.get_editor_property("character_movement").get_editor_property("jump_z_velocity"),
                "braking_deceleration_flying": p.get_editor_property("character_movement").get_editor_property("braking_deceleration_flying"),
                "mapping_context": str(mc.get_name()) if mc else None,
                "bindings": str(p.describe_bindings()),
            }
            p.set_flying(True)
            pawn_report["movement_mode_after_fly_toggle"] = str(p.get_editor_property("character_movement").get_editor_property("movement_mode"))
            pawn_report["max_fly_speed_after_fly_toggle"] = p.get_editor_property("character_movement").get_editor_property("max_fly_speed")
            p.set_flying(False)
            pawn_report["movement_mode_after_walk_toggle"] = str(p.get_editor_property("character_movement").get_editor_property("movement_mode"))
            pawn_report["overlay_components_toggled"] = int(p.set_overlay_visible(True))
        finally:
            eas.destroy_actor(p)

    out = {"mode": "explorer",
           "game_mode": _class_path(gm_cls), "game_mode_source": source,
           "map_default_game_mode": _class_path(map_gm),
           "project_default_game_mode": _class_path(project_gm),
           "default_pawn_class": _class_path(pawn_cls),
           "pawn": pawn_report,
           "player_starts": starts,
           "note": "Play In Editor cannot be driven from a commandlet; this proves the class wiring, the tuning "
                   "numbers, the input bindings and the spawn point - it does not walk the pawn."}
    print(json.dumps(out, sort_keys=True))
    return out


def mode_massing(opts):
    """Count the massing actors and trace down onto named footprints: the hit is the roof, at base_z + h."""
    imp = unreal.StreetscapeLandscapeImporter
    eas = unreal.get_editor_subsystem(unreal.EditorActorSubsystem)
    pts = []
    for chunk in (opts["massing_at"] or "").split(";"):
        chunk = chunk.strip()
        if not chunk:
            continue
        a, b = chunk.split(",")
        pts.append((float(a), float(b)))
    if opts["load_all"]:
        unreal.StreetscapeEditorLibrary.load_region(unreal.Vector(0, 0, 0), 2000000.0)
    else:
        load_regions(pts, float(opts["load_radius_m"]))
    actors = [a for a in eas.get_all_level_actors() if a.get_class().get_name() == "StreetscapeMassingActor"]
    total = {"buildings": 0, "verts": 0, "tris": 0, "rings": 0, "hole_rings": 0}
    tiles = []
    zmin, zmax = None, None
    for a in actors:
        s = a.get_editor_property("stats")
        total["buildings"] += int(s.get_editor_property("buildings"))
        total["verts"] += int(s.get_editor_property("verts"))
        total["tris"] += int(s.get_editor_property("tris"))
        total["rings"] += int(s.get_editor_property("rings"))
        total["hole_rings"] += int(s.get_editor_property("hole_rings"))
        if int(s.get_editor_property("buildings")) > 0:
            lo = float(s.get_editor_property("min_zm"))
            hi = float(s.get_editor_property("max_zm"))
            zmin = lo if zmin is None else min(zmin, lo)
            zmax = hi if zmax is None else max(zmax, hi)
        tiles.append([int(a.get_editor_property("tile_x")), int(a.get_editor_property("tile_y"))])
    land = imp.find_landscape()
    probes = []
    for x, y in pts:
        # geometry: a vertical ray against the tile's own mesh (no physics involved)
        roof = None
        for a in actors:
            v = a.sample_top_zm(x, y)
            if v is not None and not math.isnan(v):
                roof = v if roof is None else max(roof, v)
        zg = imp.probe_height_m(land, x, y, False)
        # physics: what the explorer would stand on, before and after a collision rebuild
        zt_before = imp.trace_down_zm(x, y, 300.0, -300.0)
        probes.append({"xy": [x, y],
                       "roof_z_m": None if roof is None else round(roof, 4),
                       "landscape_z_m": None if math.isnan(zg) else round(zg, 4),
                       "trace_z_m_before_refresh": None if (zt_before is None or math.isnan(zt_before)) else round(zt_before, 4)})
    if opts["refresh_collision"]:
        tris = 0
        for a in actors:
            tris += int(a.refresh_collision())
        for p in probes:
            zt = imp.trace_down_zm(p["xy"][0], p["xy"][1], 300.0, -300.0)
            p["trace_z_m_after_refresh"] = None if (zt is None or math.isnan(zt)) else round(zt, 4)
        total["collision_tris_refreshed"] = tris
    out = {"mode": "massing", "actors": len(actors), "totals": total, "z_min_m": zmin, "z_max_m": zmax,
           "tiles": len(tiles), "probes": probes, "refreshed_collision": bool(opts["refresh_collision"])}
    print(json.dumps(out, sort_keys=True))
    return out


def main(argv):
    opts = uc.parse_args(argv, flags=("landscape", "trace_from_above", "explorer", "landscape_info", "load_all", "massing",
                                      "refresh_collision"), options={
        "points": "", "actor": "", "map": DEFAULT_MAP, "step_m": "1.0", "landscape_dir": "",
        "load_radius_m": "300", "weights_at": "", "massing_at": "",
    })
    load_map(opts["map"])
    if opts["explorer"]:
        payload = mode_explorer(opts)
    elif opts["landscape_info"]:
        payload = mode_landscape_info(opts)
    elif opts["massing"]:
        payload = mode_massing(opts)
    elif opts["actor"]:
        payload = mode_actor(opts)
    elif opts["points"]:
        payload = mode_points(opts)
    else:
        uc.fail(NAME, "one of --points, --actor, --explorer, --landscape-info or --massing is required")
    uc.report(NAME, payload)


if __name__ == "__main__":
    main(sys.argv)
