"""Independent in-engine probe (verification pass; changes nothing, saves nothing).

Loads /Game/Thanet/Maps/Thanet, streams a box around each probe point, and for every point compares
what the ENGINE says with what the verifier computed from the r16 product outside the engine:
  kind=vertex  ALandscapeProxy::GetHeightAtLocation vs the conformed hm_*.r16 post
  kind=road    the same, plus a downward line trace from 5 m above the built road surface
"""
import json
import math
import os
import sys

sys.path.insert(0, os.path.normpath(os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "ue")))

import unreal  # noqa: E402

NAME = "vfy_probe"
MAP = "/Game/Thanet/Maps/Thanet"


def log(m):
    print("[vfy] %s" % m)
    unreal.log("[vfy] %s" % m)


def main(argv):
    opts = {"points": "", "out": "", "radius_m": "250"}
    a = list(argv[1:])
    i = 0
    while i < len(a):
        opts[a[i][2:].replace("-", "_")] = a[i + 1]
        i += 2

    les = unreal.get_editor_subsystem(unreal.LevelEditorSubsystem)
    if not les.load_level(MAP):
        raise RuntimeError("THANET_FAIL %s load_level failed" % NAME)

    rows = []
    with open(opts["points"]) as fh:
        for line in fh:
            line = line.strip()
            if not line or line.startswith("x,"):
                continue
            p = line.split(",")
            rows.append((float(p[0]), float(p[1]), p[2], float(p[3]), float(p[4])))
    log("%d probe points" % len(rows))

    r = float(opts["radius_m"])
    lib = unreal.StreetscapeEditorLibrary
    seen = set()
    n_reg = 0
    for (x, y, kind, ze, zr) in rows:
        key = (int(x // (2 * r)), int(y // (2 * r)))
        if key in seen:
            continue
        seen.add(key)
        cx = (key[0] + 0.5) * 2 * r
        cy = (key[1] + 0.5) * 2 * r
        lib.load_region(unreal.Vector(100.0 * cx, -100.0 * cy, 0.0), 100.0 * r * 2.0)
        n_reg += 1
    log("loaded %d regions, rss %.0f MB" % (n_reg, unreal.StreetscapeLandscapeImporter.rss_mb()))

    imp = unreal.StreetscapeLandscapeImporter
    land = imp.find_landscape()
    if land is None:
        raise RuntimeError("THANET_FAIL %s no ALandscape" % NAME)
    world = unreal.get_editor_subsystem(unreal.UnrealEditorSubsystem).get_editor_world()

    res = {"vertex": [], "road": []}
    n_none = {"vertex": 0, "road": 0}
    tr = {"total": 0, "blocked": 0, "miss": 0, "by_component": {}}
    dz = []
    land_above_road = 0
    for (x, y, kind, z_expect, z_road) in rows:
        zl = imp.probe_height_m(land, x, y, False)
        if isinstance(zl, float) and math.isnan(zl):
            n_none[kind] += 1
        else:
            res[kind].append(zl - z_expect)
            if kind == "road" and zl > z_road:
                land_above_road += 1
        if kind == "road":
            tr["total"] += 1
            zt = imp.trace_down_zm(x, y, z_road + 5.0, z_road - 5.0)
            if zt is None or (isinstance(zt, float) and math.isnan(zt)):
                tr["miss"] += 1
            else:
                tr["blocked"] += 1
                dz.append(zt - z_road)

    def stats(v):
        if not v:
            return None
        v = sorted(v)
        n = len(v)
        return {"n": n, "min": round(v[0], 6), "p50": round(v[n // 2], 6),
                "p95": round(v[min(n - 1, int(0.95 * n))], 6), "max": round(v[-1], 6),
                "absmax": round(max(abs(v[0]), abs(v[-1])), 6)}

    payload = {
        "points": len(rows),
        "regions_loaded": n_reg,
        "engine_minus_r16_at_vertices_m": stats(res["vertex"]),
        "engine_minus_r16_on_roads_m": stats(res["road"]),
        "landscape_none": n_none,
        "road_points_with_landscape_above_road_surface": land_above_road,
        "traces": tr,
        "trace_hit_minus_road_surface_m": stats(dz),
        "rss_mb": round(unreal.StreetscapeLandscapeImporter.rss_mb(), 1),
    }
    if opts["out"]:
        with open(opts["out"], "w") as fh:
            json.dump(payload, fh, indent=1)
    print("THANET_OK %s %s" % (NAME, json.dumps(payload, sort_keys=True)))


main(sys.argv)
