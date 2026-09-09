"""Why is there nothing in front of this camera?

A render_set frame that comes back as a flat green plane with the town on the horizon has exactly two
possible causes, and they need opposite fixes:

  * the region did not stream - the World Partition cells around the camera hold no loaded actors, so
    the picture is of the landscape alone.  That is a HARNESS fault and the frame must be re-rendered.
  * the geometry is loaded and simply is not visible - the road is under the ground, or there is
    nothing built there.  That is a MODEL defect and the frame is honest evidence of it.

This asks the engine, at the camera the manifest actually used:

  1. load_region with the render_set plan (same centre, same radius), then count the AStreetscapeActor
     and AStreetscapeMassingActor that are LOADED, binned by distance from the camera;
  2. walk the view ray and, at each station, trace down and compare what the trace hits with the
     landscape height there - "street" means something stands on the ground, "terrain" means bare
     ground, and the clearance is how far above the landscape the hit was.

usage (through Tools/ue/run_ue_python.ps1 -Render):
    -Script diag_frame_probe.py -Args "--spec <render_set.json> --only <town>/<slug>[,...] --report <path>"
"""
import json
import math
import os
import sys

import unreal

import ue_common as uc

NAME = "diag_frame_probe"
E0, N0 = 627680.0, 163080.0
RAY_M = [2.0, 5.0, 10.0, 20.0, 40.0, 80.0, 160.0, 320.0]
BINS_M = [25.0, 50.0, 100.0, 200.0, 400.0, 800.0]


def load_plan(loc):
    """The renderer's own rule, repeated here so the probe streams exactly what the frame streamed."""
    cam, sub = loc["camera_en"], loc["subject_en"]
    d = math.hypot(sub[0] - cam[0], sub[1] - cam[1])
    aerial = loc.get("kind") == "aerial"
    floor_m, margin_m = (1500.0, 900.0) if aerial else (600.0, 400.0)
    return [(cam[0] + sub[0]) / 2.0, (cam[1] + sub[1]) / 2.0], max(floor_m, d / 2.0 + margin_m), d


def main(argv):
    opts = uc.parse_args(argv, options={"spec": "", "only": "", "report": "", "map": ""})
    spec_path = opts["spec"] or os.path.join(os.path.dirname(__file__), "render_set.json").replace("\\", "/")
    spec = json.load(open(spec_path))
    want = [s.strip() for s in (opts["only"] or "").split(",") if s.strip()]
    locs = []
    for t in spec["towns"]:
        for l in t["locations"]:
            lid = "%s/%s" % (t["slug"], l["slug"])
            if not want or lid in want or t["slug"] in want or l["slug"] in want:
                d = dict(l)
                d["id"] = lid
                d["town"] = t["slug"]
                locs.append(d)
    if not locs:
        uc.fail(NAME, "--only %r matched no location in %s" % (opts["only"], spec_path))

    map_path = opts["map"] or spec["map"]
    les = unreal.get_editor_subsystem(unreal.LevelEditorSubsystem)
    world = unreal.get_editor_subsystem(unreal.UnrealEditorSubsystem).get_editor_world()
    if world is None or world.get_name() != map_path.rsplit("/", 1)[-1]:
        if not les.load_level(map_path):
            uc.fail(NAME, "load_level(%s) failed" % map_path)
    lib = unreal.StreetscapeEditorLibrary
    imp = unreal.StreetscapeLandscapeImporter
    land = imp.find_landscape()
    eas = unreal.get_editor_subsystem(unreal.EditorActorSubsystem)

    out = []
    for loc in locs:
        centre, radius_m, dist_m = load_plan(loc)
        cx, cy = centre[0] - E0, centre[1] - N0
        if not lib.load_region(unreal.Vector(100.0 * cx, -100.0 * cy, 0.0), 100.0 * radius_m):
            uc.fail(NAME, "%s: load_region failed" % loc["id"])
        camx, camy = loc["camera_en"][0] - E0, loc["camera_en"][1] - N0
        bearing = math.degrees(math.atan2(loc["subject_en"][0] - loc["camera_en"][0],
                                          loc["subject_en"][1] - loc["camera_en"][1])) % 360.0
        ux, uy = math.sin(math.radians(bearing)), math.cos(math.radians(bearing))

        street = [0] * (len(BINS_M) + 1)
        massing = [0] * (len(BINS_M) + 1)
        nearest_street, nearest_massing = None, None
        for a in eas.get_all_level_actors():
            cn = a.get_class().get_name()
            if cn not in ("StreetscapeActor", "StreetscapeMassingActor"):
                continue
            p = a.get_actor_location()
            d = math.hypot(p.x / 100.0 - camx, -p.y / 100.0 - camy)
            b = len(BINS_M)
            for k, edge in enumerate(BINS_M):
                if d <= edge:
                    b = k
                    break
            if cn == "StreetscapeActor":
                street[b] += 1
                if nearest_street is None or d < nearest_street[1]:
                    nearest_street = (str(a.get_editor_property("street_id")), d)
            else:
                massing[b] += 1
                if nearest_massing is None or d < nearest_massing[1]:
                    nearest_massing = (a.get_actor_label(), d)

        # What the loaded actors actually amount to: an actor that streamed in but never built its
        # buffers draws nothing, which looks exactly like a road buried under the ground.
        try:
            census = json.loads(lib.streetscape_census_json())
        except Exception as e:                          # noqa: BLE001
            census = {"error": str(e)}

        # The nearest road actor's own buffers, for the same reason at one place instead of in aggregate.
        near_stats = None
        if nearest_street is not None:
            try:
                near_stats = json.loads(lib.actor_stats_json(nearest_street[0]))
            except Exception as e:                      # noqa: BLE001
                near_stats = {"error": str(e)}

        ray = []
        for s in [0.0] + RAY_M:
            x, y = camx + ux * s, camy + uy * s
            zl = imp.probe_height_m(land, x, y, False) if land is not None else float("nan")
            zt = imp.trace_down_zm(x, y, (zl if zl == zl else 0.0) + 60.0, (zl if zl == zl else 0.0) - 60.0)
            hit = zt is not None and zt == zt
            clr = (zt - zl) if (hit and zl == zl) else None
            ray.append({"along_m": s, "en": [round(x + E0, 2), round(y + N0, 2)],
                        "landscape_z_m": None if zl != zl else round(zl, 3),
                        "trace_z_m": None if not hit else round(zt, 3),
                        "clearance_m": None if clr is None else round(clr, 3),
                        "what": ("nothing" if not hit else
                                 ("street" if clr is not None and clr > 0.015 else "terrain"))})
        rec = {"id": loc["id"], "kind": loc.get("kind"), "camera_en": loc["camera_en"],
               "subject_en": loc["subject_en"], "subject_distance_m": round(dist_m, 1),
               "load_centre_en": [round(v, 2) for v in centre], "load_radius_m": round(radius_m, 1),
               "bins_m": BINS_M + ["beyond"],
               "streetscape_actors_loaded_by_bin": street,
               "massing_actors_loaded_by_bin": massing,
               "streetscape_actors_loaded_total": sum(street),
               "massing_actors_loaded_total": sum(massing),
               "nearest_streetscape_actor": (None if nearest_street is None else
                                             {"id": nearest_street[0], "distance_m": round(nearest_street[1], 1)}),
               "nearest_massing_actor": (None if nearest_massing is None else
                                         {"label": nearest_massing[0], "distance_m": round(nearest_massing[1], 1)}),
               "view_ray": ray,
               "census_of_loaded_streetscape": census,
               "nearest_street_actor_stats": near_stats,
               "rss_mb": round(float(imp.rss_mb()), 1)}
        uc.log("%s: %d streetscape / %d massing actors loaded within 800 m; ray %s"
               % (loc["id"], sum(street[:-1]), sum(massing[:-1]),
                  "".join({"street": "S", "terrain": "t", "nothing": "."}[r["what"]] for r in ray)))
        out.append(rec)

    payload = {"script": NAME, "spec": spec_path, "map": map_path, "locations": out}
    if opts["report"]:
        with open(opts["report"], "w") as f:
            json.dump(payload, f, indent=1)
    uc.report(NAME, {"locations": len(out), "report": opts["report"]})


if __name__ == "__main__":
    main(sys.argv)
