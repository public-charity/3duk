"""Is the carriageway hidden by the ground, or is it not drawn at all?

Several render_set frames show a street lined with buildings whose surface is grass: the magenta OSM
overlay and often the footway are drawn, the carriageway is not.  A downward trace at those same
cameras hits the road 3 cm above the landscape (Tools/ue/diag_frame_probe.py), so the geometry exists
and is above the ground by the numbers.  Two explanations remain, and they need opposite fixes:

  * the DRAWN landscape is not the surface the trace queries (LOD, or the render mesh interpolating a
    quad differently from the collision heightfield), so the ground draws over a road that is
    numerically below it -- a capture-side / terrain-resolution problem;
  * the road component is not being drawn at all -- a geometry or culling problem.

Hiding the landscape separates them.  Capture the frame twice from the SAME camera, once as the render
set does and once with every LandscapeProxy hidden:

  road appears when the landscape is hidden -> the ground was drawing over it (first case);
  road still absent                          -> the road is not being rendered (second case).

usage (through Tools/ue/run_ue_python.ps1 -Render):
    -Script diag_road_visibility.py -Args "--only <town>/<slug>[,...] --out <dir> [--report <path>]"
"""
import json
import math
import os
import sys

import unreal

import importlib.util

import ue_common as uc

NAME = "diag_road_visibility"
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__)).replace("\\", "/")
E0, N0 = 627680.0, 163080.0


def _load(mod, fname):
    spec = importlib.util.spec_from_file_location(mod, SCRIPT_DIR + "/" + fname)
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


SS = _load("thanet_screenshot05", "05_screenshot.py")


def main(argv):
    opts = uc.parse_args(argv, options={"spec": "", "only": "", "out": "", "report": "", "warm_s": "0.5"})
    spec_path = opts["spec"] or (SCRIPT_DIR + "/render_set.json")
    spec = json.load(open(spec_path))
    want = [s.strip() for s in (opts["only"] or "").split(",") if s.strip()]
    locs = []
    for t in spec["towns"]:
        for l in t["locations"]:
            lid = "%s/%s" % (t["slug"], l["slug"])
            if lid in want or t["slug"] in want or l["slug"] in want:
                d = dict(l)
                d["id"] = lid
                d["town"] = t["slug"]
                locs.append(d)
    if not locs:
        uc.fail(NAME, "--only %r matched nothing" % opts["only"])
    out = (opts["out"] or (SCRIPT_DIR + "/../../Saved/RoadVisibility")).replace("\\", "/")
    os.makedirs(out, exist_ok=True)

    les = unreal.get_editor_subsystem(unreal.LevelEditorSubsystem)
    world = unreal.get_editor_subsystem(unreal.UnrealEditorSubsystem).get_editor_world()
    if world is None or world.get_name() != spec["map"].rsplit("/", 1)[-1]:
        if not les.load_level(spec["map"]):
            uc.fail(NAME, "load_level(%s) failed" % spec["map"])
        world = unreal.get_editor_subsystem(unreal.UnrealEditorSubsystem).get_editor_world()

    cap = spec["capture"]
    lib = unreal.StreetscapeEditorLibrary
    imp = unreal.StreetscapeLandscapeImporter
    land = imp.find_landscape()
    eas = unreal.get_editor_subsystem(unreal.EditorActorSubsystem)
    rt = SS.make_render_target(world, int(cap["width"]), int(cap["height"]))

    rows = []
    for loc in locs:
        cam_en, sub_en = loc["camera_en"], loc["subject_en"]
        dist_m = math.hypot(sub_en[0] - cam_en[0], sub_en[1] - cam_en[1])
        aerial = loc.get("kind") == "aerial"
        floor_m, margin_m = (1500.0, 900.0) if aerial else (600.0, 400.0)
        centre = [(cam_en[0] + sub_en[0]) / 2.0, (cam_en[1] + sub_en[1]) / 2.0]
        radius_m = max(floor_m, dist_m / 2.0 + margin_m)
        cx, cy = centre[0] - E0, centre[1] - N0
        if not lib.load_region(unreal.Vector(100.0 * cx, -100.0 * cy, 0.0), 100.0 * radius_m):
            uc.fail(NAME, "%s: load_region failed" % loc["id"])
        SS.pin_landscape_lod(cap.get("landscape_lod0_screen_size"))

        camx, camy = loc["camera_en"][0] - E0, loc["camera_en"][1] - N0
        z_land = imp.probe_height_m(land, camx, camy, False)
        eye_z = z_land + float(loc["camera_height_m"])
        bearing = math.degrees(math.atan2(loc["subject_en"][0] - loc["camera_en"][0],
                                          loc["subject_en"][1] - loc["camera_en"][1])) % 360.0
        cam = {"eye_ue": [100.0 * camx, -100.0 * camy, 100.0 * eye_z],
               "yaw": bearing - 90.0, "pitch": float(loc.get("pitch_deg", 0.0)), "roll": 0.0,
               "fov_deg": float(loc.get("fov_deg", 75.0))}

        proxies = [a for a in eas.get_all_level_actors() if isinstance(a, unreal.LandscapeProxy)]
        for hide in (False, True):
            for a in proxies:
                a.set_is_temporarily_hidden_in_editor(hide)
            tag = "landscape_hidden" if hide else "as_rendered"
            png = "%s/%s__%s.png" % (out, loc["id"].replace("/", "__"), tag)
            ok = SS.capture(world, cam, rt, png, cap["source"], float(cap["exposure_ev"]),
                            float(opts["warm_s"]))
            rows.append({"id": loc["id"], "variant": tag, "png": png, "captured": bool(ok),
                         "bytes": (os.path.getsize(png) if os.path.exists(png) else 0),
                         "landscape_proxies_hidden": (len(proxies) if hide else 0)})
            uc.log("%s %s -> %s (%d proxies, %d bytes)"
                   % (loc["id"], tag, "ok" if ok else "FAILED", len(proxies), rows[-1]["bytes"]))
        for a in proxies:
            a.set_is_temporarily_hidden_in_editor(False)

    payload = {"script": NAME, "out": out, "captures": rows}
    if opts["report"]:
        with open(opts["report"], "w") as f:
            json.dump(payload, f, indent=1)
    uc.report(NAME, {"captures": len(rows), "out": out, "report": opts["report"]})


if __name__ == "__main__":
    main(sys.argv)
