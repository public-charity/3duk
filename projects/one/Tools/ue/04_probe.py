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

  --massing [--load-all] [--massing-at "x,y;..."] [--refresh-collision]
      actor and building totals against massing_manifest.json, plus a per-footprint roof height. FAILS on zero
      actors: in a World Partition commandlet "nothing streamed in" and "nothing there" are the same report.

  --materials [--load-all]
      finishes shader compilation, then reports the material every streetscape / massing component would draw
      with and how many slots fall back to the engine default (the WorldGridMaterial checkerboard).

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
    if opts["sample_mode"]:
        modes = {"bilinear": unreal.StreetHeightSampling.BILINEAR,
                 "triangulated": unreal.StreetHeightSampling.LANDSCAPE_TRIANGULATED}
        if opts["sample_mode"] not in modes:
            uc.fail(NAME, "--sample-mode must be bilinear or triangulated")
        hf.set_sampling(modes[opts["sample_mode"]])
        uc.log("terrain source sampling = %s" % opts["sample_mode"])
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
    if not rows:
        uc.fail(NAME, "--points %s produced 0 usable rows: a probe of nothing is not a probe that passed" % opts["points"])
    if land is not None and n_land_none:
        uc.fail(NAME, "the landscape has no height at %d of %d probe points (--landscape was given, so every point "
                      "inside the imported extent must have one)" % (n_land_none, len(rows)))
    return {"mode": "points", "points": len(rows), "clipped": n_clipped,
            "landscape": bool(land), "landscape_none": n_land_none, "regions_loaded": n_regions,
            "blocked": n_blocked, "unclipped": len(rows) - n_clipped,
            "blocked_matches_unclipped": n_blocked == len(rows) - n_clipped,
            "max_abs_dz_m": round(max_dz, 5) if land else None,
            "sample_mode": opts["sample_mode"] or "bilinear"}


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
    missing = layers.get("ground_layers_missing") or []
    if missing:
        uc.fail(NAME, "the landscape is missing ground layer(s) %s - the import did not write every weightmap" % missing)
    if not layers.get("has_visibility_layer"):
        uc.fail(NAME, "the landscape has no visibility layer, so the clip line is not cut (DESIGN.md 16)")
    if not state.get("components"):
        uc.fail(NAME, "the landscape reports %s components" % state.get("components"))
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


def probe_one_actor(actor, imp, land, hf, step_m):
    """Per-station: does a downward trace hit the street, and how far is the ALandscape below the road surface?

    The corridor gate of docs/TERRAIN_ROADS.md is measured against the conformed heightfield in numpy; this is the
    same question asked of the engine's own collision: the trace must land on the STREET (not the ground), and the
    landscape must be below it.
    """
    spline = actor.get_editor_property("spline")
    if spline is None:
        return None
    length_cm = spline.get_spline_length()
    step_cm = max(10.0, float(step_m) * 100.0)
    n = max(2, int(length_cm // step_cm) + 1)
    top_m, bot_m = 300.0, -300.0
    sid = str(actor.get_editor_property("street_id"))
    stats = unreal.StreetscapeEditorLibrary.actor_stats_json(sid)
    if stats:
        bb = ((json.loads(stats).get("buffers") or {}).get("road") or {}).get("bbox")
        if bb and len(bb) == 2:
            bot_m, top_m = float(bb[0][2]) - 5.0, float(bb[1][2]) + 5.0
    blocked = 0
    on_terrain = 0
    clear = []
    land_none = 0
    for i in range(n):
        d = min(length_cm, i * step_cm)
        p = spline.get_location_at_distance_along_spline(d, unreal.SplineCoordinateSpace.WORLD)
        x, y = p.x / 100.0, -p.y / 100.0
        zt = imp.trace_down_zm(x, y, top_m, bot_m)
        hit = not (zt is None or math.isnan(zt))
        blocked += int(hit)
        zl = imp.probe_height_m(land, x, y, False) if land is not None else float("nan")
        zh = hf.probe_m(x, y) if hf is not None else float("nan")
        if hit and not math.isnan(zh) and abs(zt - zh) < 0.02:
            on_terrain += 1
        if hit and land is not None:
            if math.isnan(zl):
                land_none += 1
            else:
                clear.append(zt - zl)
    clear.sort()
    return {"id": sid, "length_m": round(length_cm / 100.0, 2), "stations": n, "blocked": blocked,
            "stations_within_2cm_of_the_survey": on_terrain, "landscape_none": land_none,
            "clearance_points": len(clear),
            "clearance_min_m": round(clear[0], 4) if clear else None,
            "clearance_p50_m": round(clear[len(clear) // 2], 4) if clear else None,
            "clearance_max_m": round(clear[-1], 4) if clear else None,
            "all_blocked": blocked == n}


def mode_actor_sample(opts):
    """A deterministic sample of ROAD actors, every one of which must be walkable and clear of the landscape."""
    lib = unreal.StreetscapeEditorLibrary
    imp = unreal.StreetscapeLandscapeImporter
    lib.load_region(unreal.Vector(0, 0, 0), 2000000.0)
    eas = unreal.get_editor_subsystem(unreal.EditorActorSubsystem)
    by_id = {}
    for a in eas.get_all_level_actors():
        if a.get_class().get_name() == "StreetscapeActor":
            sid = str(a.get_editor_property("street_id"))
            if sid.startswith("roads:") and a.get_editor_property("road") is not None:
                by_id[sid] = a
    ids = sorted(by_id)
    if not ids:
        uc.fail(NAME, "no road AStreetscapeActor in the level to sample")
    want = max(1, int(opts["actor_sample"]))
    picked = [ids[(k * len(ids)) // want] for k in range(want)]
    land = imp.find_landscape()
    if land is None:
        uc.fail(NAME, "the level has no ALandscape to measure the corridor clearance against")
    hf = uc.heightfield(opts["landscape_dir"] or None)
    rows = []
    for sid in picked:
        r = probe_one_actor(by_id[sid], imp, land, hf, float(opts["step_m"]))
        if r is None:
            uc.fail(NAME, "actor %s has no spline component" % sid)
        rows.append(r)
        uc.log("%s: %d/%d stations blocked, clearance %s .. %s m, %d station(s) within 2 cm of the survey"
               % (sid, r["blocked"], r["stations"], r["clearance_min_m"], r["clearance_max_m"],
                  r["stations_within_2cm_of_the_survey"]))
    mins = [r["clearance_min_m"] for r in rows if r["clearance_min_m"] is not None]
    out = {"mode": "actor_sample", "road_actors_in_level": len(ids), "sampled": len(rows),
           "stations": sum(r["stations"] for r in rows),
           "blocked": sum(r["blocked"] for r in rows),
           "stations_within_2cm_of_the_survey": sum(r["stations_within_2cm_of_the_survey"] for r in rows),
           "survey_note": ("the road is built on the SMOOTHED survey (BRIEF 1.1), so on flat ground its surface IS "
                           "within 2 cm of the raw survey height - this count is a diagnostic, not a fault. The "
                           "gate is the clearance below: the ALandscape must be strictly under the street."),
           "clearance_min_m": min(mins) if mins else None,
           "clearance_worst_actor": min(rows, key=lambda r: (r["clearance_min_m"] is None, r["clearance_min_m"]))["id"] if mins else None,
           "actors_all_blocked": sum(1 for r in rows if r["all_blocked"]),
           "rows": rows}
    print(json.dumps(out, sort_keys=True))
    bad = [r["id"] for r in rows if not r["all_blocked"]]
    if bad:
        uc.fail(NAME, "%d of %d sampled road(s) are not walkable at every station: %s" % (len(bad), len(rows), bad))
    # The gate is the corridor clearance of docs/TERRAIN_ROADS.md, asked of the engine's own collision: the
    # trace lands on the street and the ALandscape is strictly below it. 5 mm is that document's own --gate-m.
    if not mins:
        uc.fail(NAME, "no sampled station produced a clearance measurement")
    if min(mins) <= 0.005:
        uc.fail(NAME, "the landscape is within 5 mm of, or above, the road surface at some sampled station "
                      "(min clearance %s m, worst %s)" % (min(mins), out["clearance_worst_actor"]))
    return {k: v for k, v in out.items() if k != "rows"}


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

    # The spline COMPONENT's own points carry z = 0: the interchange documents deliberately have no z on their
    # waypoints (heights are sampled and smoothed at build time, BRIEF 1.1). Tracing from spline_z +/- 5 m
    # therefore ran from +5 m to -5 m ODN - twenty metres below Margate - and reported "0 of 172 stations block"
    # for a road that is perfectly solid. Take the vertical window from the ROAD BUFFER's own bounding box, which
    # is in the same document frame and is what was actually built.
    top_m, bot_m = 300.0, -300.0
    stats = lib.actor_stats_json(opts["actor"])
    if stats:
        bb = ((json.loads(stats).get("buffers") or {}).get("road") or {}).get("bbox")
        if bb and len(bb) == 2:
            bot_m, top_m = float(bb[0][2]) - 5.0, float(bb[1][2]) + 5.0
    hf = uc.heightfield(opts["landscape_dir"] or None)
    uc.log("trace window %.2f .. %.2f m ODN (from the road buffer's bbox)" % (bot_m, top_m))

    blocked = 0
    buried = 0
    rows = []
    for i in range(n):
        d = min(length_cm, i * step_cm)
        p = spline.get_location_at_distance_along_spline(d, unreal.SplineCoordinateSpace.WORLD)
        x, y, z = p.x / 100.0, -p.y / 100.0, p.z / 100.0
        zt = imp.trace_down_zm(x, y, top_m, bot_m)
        hit = not (zt is None or math.isnan(zt))
        blocked += int(hit)
        zh = hf.probe_m(x, y) if hf is not None else float("nan")
        # the trace lands on whatever is highest. Landing within 2 cm of the RAW terrain means the street is not
        # what was hit: the landscape is over it (the streetscape does not carve the terrain, BRIEF 1.1).
        on_terrain = bool(hit and not math.isnan(zh) and abs(zt - zh) < 0.02)
        buried += int(on_terrain)
        rows.append({"s_m": round(d / 100.0, 2), "xy": [round(x, 3), round(y, 3)], "z_spline_m": round(z, 3),
                     "trace_z_m": None if not hit else round(zt, 3), "blocked": hit,
                     "z_heightfield_m": None if math.isnan(zh) else round(zh, 3),
                     "hit_is_terrain": on_terrain,
                     "dz_terrain_m": None if (not hit or math.isnan(zh)) else round(zt - zh, 4)})
    print(json.dumps({"actor": opts["actor"], "length_m": round(length_cm / 100.0, 3), "stations": len(rows),
                      "blocked": blocked, "rows": rows[:10]}, sort_keys=True))
    dzs = [r["dz_terrain_m"] for r in rows if r["dz_terrain_m"] is not None]
    out = {"mode": "actor", "actor": opts["actor"], "length_m": round(length_cm / 100.0, 3),
           "stations": len(rows), "blocked": blocked,
           "trace_window_m": [round(bot_m, 2), round(top_m, 2)],
           "all_blocked": blocked == len(rows) and len(rows) > 0,
           "stations_where_the_hit_is_the_terrain": buried,
           "max_dz_above_terrain_m": round(max(dzs), 4) if dzs else None,
           "min_dz_above_terrain_m": round(min(dzs), 4) if dzs else None}
    if not out["all_blocked"]:
        uc.fail(NAME, "a downward trace over the road blocks at only %d of %d stations - the road is not walkable "
                      "(UE_PLAN 8.7 / STAGES FD.4). %s" % (blocked, len(rows), json.dumps(out, sort_keys=True)))
    return out


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
    # this mode existed to prove the explorer is wired up, and it reported success on a level with no game mode,
    # no pawn and no spawn point at all - three separate ways for "the explorer does not exist" to read as a pass.
    problems = []
    if gm_cls is None:
        problems.append("no game mode (neither the map's World Settings nor the project default resolves)")
    if pawn_cls is None:
        problems.append("the game mode has no default pawn class")
    if not starts:
        problems.append("the level has no PlayerStart, so Play would spawn at the world origin")
    if problems:
        uc.fail(NAME, "explorer wiring: %s" % "; ".join(problems))
    return out


def mode_census(opts):
    """The size of the network the level holds (D5): actors, components, verts, tris, instances, RSS."""
    lib = unreal.StreetscapeEditorLibrary
    t0 = uc.elapsed_s()
    if opts["census_at"]:
        # census of ONE neighbourhood: the same region a screenshot loads, so "what does the capture actually see"
        # can be answered without streaming the isle
        a, b = (float(v) for v in opts["census_at"].split(","))
        r = float(opts["load_radius_m"]) * 100.0
        lib.load_region(unreal.Vector(100.0 * a, -100.0 * b, 0.0), r)
        uc.log("census: loaded a %g m box at (%g, %g)" % (r / 100.0, a, b))
    elif not opts["no_load_all"]:
        lib.load_region(unreal.Vector(0, 0, 0), 2000000.0)
    uc.log("census: world streamed in after %.1fs" % (uc.elapsed_s() - t0))
    cen = json.loads(lib.streetscape_census_json())
    cen["load_seconds"] = round(uc.elapsed_s() - t0, 1)
    cen["mode"] = "census"
    print(json.dumps(cen, sort_keys=True))
    if opts["census_out"]:
        out = opts["census_out"].replace("\\", "/")
        d = os.path.dirname(out)
        if d and not os.path.isdir(d):
            os.makedirs(d)
        with open(out, "w", newline="\n") as fh:
            json.dump(cen, fh, indent=1, sort_keys=True)
            fh.write("\n")
        cen["census_out"] = out
    # a census of an empty world is the World Partition trap again: say so instead of printing zeros as a result
    if int(cen.get("actors") or 0) == 0:
        uc.fail(NAME, "the level holds 0 AStreetscapeActor (streamed: %s)" % (not opts["no_load_all"]))
    if int(cen.get("actors_without_samples") or 0) > 0:
        uc.fail(NAME, "%d of %d streetscape actor(s) have no samples: their meshes were never built, so their "
                      "vertices are missing from this census" % (cen["actors_without_samples"], cen["actors"]))
    if opts["expect_actors"] and int(cen.get("actors") or 0) != int(opts["expect_actors"]):
        uc.fail(NAME, "census found %s streetscape actor(s), --expect-actors %s" % (cen.get("actors"), opts["expect_actors"]))
    return cen


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
           "tiles": len(tiles), "probes": probes, "refreshed_collision": bool(opts["refresh_collision"]),
           "load_all": bool(opts["load_all"])}
    print(json.dumps(out, sort_keys=True))
    # "nothing streamed in" and "nothing there" look identical in a World Partition commandlet, so zero actors
    # against a manifest that lists files is a failure, not a report of zeros.
    if not actors:
        expect = None
        mpath = (opts["landscape_dir"] or uc.data_dir()).rstrip("/")
        mpath = uc.data_dir() + "/massing/massing_manifest.json"
        if os.path.isfile(mpath):
            with open(mpath) as fh:
                expect = json.load(fh).get("files")
        if expect:
            uc.fail(NAME, "found 0 AStreetscapeMassingActor while %s lists %d file(s)%s"
                    % (mpath, expect, "" if opts["load_all"] else " - and no --load-all / --massing-at was given, so nothing was streamed in"))
        uc.fail(NAME, "found 0 AStreetscapeMassingActor and no massing_manifest.json to compare against")
    return out


def mode_materials(opts):
    """What material every streetscape / massing component would actually draw with, and whether the shader
    compiler still has work queued. Separates 'the material table did not resolve' from 'the shader map was not
    ready, so the engine substituted WorldGridMaterial' when a capture comes back grey."""
    lib = unreal.StreetscapeEditorLibrary
    lib.load_region(unreal.Vector(0, 0, 0), 2000000.0) if opts["load_all"] else None
    waited = lib.finish_shader_compilation()
    audit = json.loads(lib.material_audit_json())
    audit["shader_jobs_waited_on"] = waited
    print(json.dumps(audit, sort_keys=True))
    if audit.get("components", 0) == 0:
        uc.fail(NAME, "no streetscape or massing components in the level (use --load-all to stream them in)")
    # a slot resolving to WorldGridMaterial or to nothing is a material table that did not resolve: the checkerboard
    # in a capture. It was reported as a number and nothing failed on it.
    bad = int(audit.get("slots_using_engine_default") or 0) + int(audit.get("slots_null") or 0)
    if bad and not opts["allow_default_materials"]:
        uc.fail(NAME, "%d of %d material slot(s) fall back to the engine default or are null (%s) - pass "
                      "--allow-default-materials to accept that on purpose"
                % (bad, audit.get("slots"), json.dumps({k: audit.get(k) for k in
                   ("slots_using_engine_default", "slots_null", "shader_jobs_remaining")}, sort_keys=True)))
    return {"mode": "materials", "components": audit["components"], "slots": audit["slots"],
            "slots_using_engine_default": audit["slots_using_engine_default"], "slots_null": audit["slots_null"],
            "distinct_materials": audit["distinct_materials"], "shader_jobs_waited_on": waited,
            "shader_jobs_remaining": audit.get("shader_jobs_remaining")}


def main(argv):
    opts = uc.parse_args(argv, flags=("landscape", "trace_from_above", "explorer", "landscape_info", "load_all", "massing",
                                      "refresh_collision", "materials", "census", "no_load_all",
                                      "allow_default_materials"), options={
        "points": "", "actor": "", "map": DEFAULT_MAP, "step_m": "1.0", "landscape_dir": "",
        "load_radius_m": "300", "weights_at": "", "massing_at": "", "sample_mode": "",
        "census_out": "", "expect_actors": "", "actor_sample": "", "census_at": "",
    })
    load_map(opts["map"])
    if opts["census"]:
        payload = mode_census(opts)
    elif opts["actor_sample"]:
        payload = mode_actor_sample(opts)
    elif opts["materials"]:
        payload = mode_materials(opts)
    elif opts["explorer"]:
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
        uc.fail(NAME, "one of --points, --actor, --actor-sample, --explorer, --landscape-info, --massing, --materials or --census is required")
    uc.report(NAME, payload)


if __name__ == "__main__":
    main(sys.argv)
