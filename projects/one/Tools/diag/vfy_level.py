"""Independent verification of the saved level (written by the verification pass; changes nothing).

  UnrealEditor-Cmd.exe Thanet.uproject -run=pythonscript
      -script="<this file> --points <csv> --out <json> [--no-load-all]" -Render ...

Does four things and prints THANET_OK / THANET_FAIL:
  1. opens /Game/Thanet/Maps/Thanet and counts the external-actor packages on disk by class;
  2. streams the whole world in and counts what actually loaded;
  3. reads the ALandscape back (components, proxies, extent);
  4. probes every CSV point: ALandscapeProxy::GetHeightAtLocation and a downward line trace, and
     compares them with the values the verifier computed from the r16 product outside the engine.
"""
import json
import math
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
UE_TOOLS = os.path.normpath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "ue"))
if UE_TOOLS not in sys.path:
    sys.path.insert(0, UE_TOOLS)

import unreal  # noqa: E402

NAME = "vfy_level"
MAP = "/Game/Thanet/Maps/Thanet"


def log(m):
    print("[vfy] %s" % m)
    unreal.log("[vfy] %s" % m)


def parse(argv):
    o = {"points": "", "out": "", "no_load_all": False, "map": MAP}
    a = list(argv[1:])
    i = 0
    while i < len(a):
        k = a[i][2:].replace("-", "_")
        if k == "no_load_all":
            o[k] = True
            i += 1
        else:
            o[k] = a[i + 1]
            i += 2
    return o


def main(argv):
    opts = parse(argv)
    les = unreal.get_editor_subsystem(unreal.LevelEditorSubsystem)
    if not les.load_level(opts["map"]):
        raise RuntimeError("THANET_FAIL %s load_level failed" % NAME)

    # ---- 1. what is on disk
    ar = unreal.AssetRegistryHelpers.get_asset_registry()
    root = "/Game/__ExternalActors__" + opts["map"][len("/Game"):]
    ar.scan_paths_synchronous([root], True)
    disk = {}
    for d in ar.get_assets_by_path(root, recursive=True):
        cn = str(d.asset_class_path.asset_name)
        disk[cn] = disk.get(cn, 0) + 1
    log("on disk: %s (packages %d)" % (json.dumps(disk, sort_keys=True), sum(disk.values())))

    # ---- 2. stream everything in
    if not opts["no_load_all"]:
        unreal.StreetscapeEditorLibrary.load_region(unreal.Vector(0, 0, 0), 2000000.0)
        log("streamed the world in, rss %.0f MB" % unreal.StreetscapeLandscapeImporter.rss_mb())
    eas = unreal.get_editor_subsystem(unreal.EditorActorSubsystem)
    loaded = {}
    for a in eas.get_all_level_actors():
        cn = str(a.get_class().get_name())
        loaded[cn] = loaded.get(cn, 0) + 1
    log("loaded: %s" % json.dumps(loaded, sort_keys=True))
    census = json.loads(unreal.StreetscapeEditorLibrary.streetscape_census_json())
    log("streetscape census: %s" % json.dumps(census, sort_keys=True))

    # ---- 3. the landscape
    imp = unreal.StreetscapeLandscapeImporter
    land = imp.find_landscape()
    state = json.loads(imp.landscape_state_json(land)) if land is not None else None
    log("landscape state: %s" % json.dumps(state, sort_keys=True))

    # ---- 4. probes
    rows = []
    if opts["points"]:
        with open(opts["points"]) as fh:
            for line in fh:
                line = line.strip()
                if not line or line.startswith("x,"):
                    continue
                p = line.split(",")
                rows.append((float(p[0]), float(p[1]), p[2], float(p[3]), float(p[4])))
    res = {"vertex": [], "road": []}
    traces = {"blocked": 0, "total": 0, "miss": 0}
    world = unreal.get_editor_subsystem(unreal.UnrealEditorSubsystem).get_editor_world()
    for (x, y, kind, z_expect, z_road) in rows:
        zl = imp.probe_height_m(land, x, y, False) if land is not None else float("nan")
        if not (isinstance(zl, float) and math.isnan(zl)):
            res[kind].append(zl - z_expect)
        if kind == "road" and not math.isnan(z_road):
            traces["total"] += 1
            start = unreal.Vector(100.0 * x, -100.0 * y, 100.0 * (z_road + 5.0))
            end = unreal.Vector(100.0 * x, -100.0 * y, 100.0 * (z_road - 5.0))
            hit = unreal.SystemLibrary.line_trace_single(
                world, start, end, unreal.TraceTypeQuery.TRACE_TYPE_QUERY1, True, [], unreal.DrawDebugTrace.NONE, True)
            if hit is None:
                traces["miss"] += 1
            else:
                traces["blocked"] += 1
                traces.setdefault("dz", []).append(hit.location.z / 100.0 - z_road)
                comp = hit.component
                cn = str(comp.get_class().get_name()) if comp else "None"
                traces[cn] = traces.get(cn, 0) + 1

    def stats(v):
        if not v:
            return None
        v = sorted(v)
        n = len(v)
        q = lambda f: v[min(n - 1, int(f * n))]  # noqa: E731
        return {"n": n, "min": round(v[0], 6), "p50": round(q(0.5), 6), "p95": round(q(0.95), 6),
                "max": round(v[-1], 6), "absmax": round(max(abs(v[0]), abs(v[-1])), 6)}

    dz = traces.pop("dz", [])
    payload = {
        "map": opts["map"],
        "disk_packages": disk,
        "loaded_actors": loaded,
        "streetscape_census": census,
        "landscape": state,
        "probe_points": len(rows),
        "engine_minus_r16_at_vertices_m": stats(res["vertex"]),
        "engine_minus_r16_on_roads_m": stats(res["road"]),
        "traces": traces,
        "trace_hit_minus_road_m": stats(dz),
        "rss_mb": round(unreal.StreetscapeLandscapeImporter.rss_mb(), 1),
    }
    if opts["out"]:
        with open(opts["out"], "w") as fh:
            json.dump(payload, fh, indent=1)
    print("THANET_OK %s %s" % (NAME, json.dumps(payload, sort_keys=True)))


main(sys.argv)
