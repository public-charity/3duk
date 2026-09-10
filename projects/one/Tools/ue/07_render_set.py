"""Render the fixed per-commit viewpoint set of Tools/ue/render_set.json (45 frames, 9 towns x 5).

  run_ue_python.ps1 -Script 07_render_set.py -Render -Args "--out C:/.../renders/<hash>"
  run_ue_python.ps1 -Script 07_render_set.py -Render -Args "--out <dir> --only margate,broadstairs/st_peters_high_street"
  run_ue_python.ps1 -Script 07_render_set.py          -Args "--list"

Writes <out>/<town>/<slug>.png, one per location, and a JSON report (--report, default
<out>/render_report.json) that Tools/render_set.ps1 folds into <out>/manifest.json. Drive it through
Tools/render_set.ps1 rather than by hand: that is what resolves the commit hash and writes the manifest.

WHY IT EXISTS: the set is a visual regression baseline. The same camera, to the centimetre and the
degree, at every commit, so two snapshots can be diffed as the land geometry improves. Everything that
decides a frame lives in render_set.json - position, aim, field of view, capture size, exposure - and
NOTHING is a command-line knob that could differ between two runs. --out and --only choose where and
which, never how.

WHAT IT DOES NOT DO: it does not flatter. Exposure is pinned, there is no post-processing, and a frame
that comes back black, empty or blown out FAILS the run instead of being written into a snapshot.

Camera transform, once, in one place (render_set.json states the same rule in words):
    x = E - 627680, y = N - 163080                        local metres, x east, y north
    ground_z = the imported landscape's height at (x, y)  ODN metres, StreetscapeLandscapeImporter
    eye_z = ground_z + camera_height_m                    camera_height_m is ABOVE GROUND
    X_ue = 100*x,  Y_ue = -100*y,  Z_ue = 100*eye_z       Unreal cm, left-handed, +Y south
    yaw  = bearing(camera -> subject) - 90                bearing = atan2(dE, dN), clockwise from north
    pitch = pitch_deg, roll = 0

Capture and region streaming reuse Tools/ue/05_screenshot.py (imported by path - its name starts with a
digit) rather than growing a second implementation of either.
"""
import importlib.util
import json
import math
import os
import sys

import unreal

import ue_common as uc

NAME = "07_render_set"
SCRIPT_DIR = os.path.dirname(os.path.abspath(__file__)).replace("\\", "/")
DEFAULT_SPEC = SCRIPT_DIR + "/render_set.json"


def _load_screenshot_module():
    """05_screenshot.py holds the capture, the PNG opacity fix, the LOD pin and the black-frame guards.
    Its module name starts with a digit so `import` cannot reach it; load it by path."""
    path = SCRIPT_DIR + "/05_screenshot.py"
    spec = importlib.util.spec_from_file_location("thanet_screenshot05", path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


SS = _load_screenshot_module()


# ---- the spec -----------------------------------------------------------------------------------------------------

def read_spec(path):
    with open(path) as fh:
        spec = json.load(fh)
    if int(spec.get("schema_version", 0)) != 1:
        uc.fail(NAME, "%s: schema_version %r is not 1" % (path, spec.get("schema_version")))
    for key in ("origin", "capture", "towns", "map"):
        if key not in spec:
            uc.fail(NAME, "%s: missing %r" % (path, key))
    return spec


def flatten(spec):
    """[(town_slug, location)] in the spec's own fixed order."""
    out = []
    seen = set()
    for town in spec["towns"]:
        for loc in town["locations"]:
            lid = "%s/%s" % (town["slug"], loc["slug"])
            if loc.get("id") and loc["id"] != lid:
                uc.fail(NAME, "location id %r does not match %s" % (loc["id"], lid))
            if lid in seen:
                uc.fail(NAME, "duplicate location id %s" % lid)
            seen.add(lid)
            out.append((town["slug"], loc))
    return out


def select(items, only):
    """--only accepts a comma-separated list of town slugs, '<town>/<slug>' ids, or bare location slugs."""
    if not only:
        return items
    wanted = [w.strip() for w in only.split(",") if w.strip()]
    picked, matched = [], set()
    for town, loc in items:
        lid = "%s/%s" % (town, loc["slug"])
        for w in wanted:
            if w == town or w == lid or w == loc["slug"]:
                picked.append((town, loc))
                matched.add(w)
                break
    missing = [w for w in wanted if w not in matched]
    if missing:
        uc.fail(NAME, "--only matched nothing for %s" % ", ".join(missing))
    return picked


# ---- geometry -----------------------------------------------------------------------------------------------------

def bearing_deg(cam_en, subj_en):
    """Degrees clockwise from grid north, camera -> subject (BRIEF 4.2)."""
    return math.degrees(math.atan2(subj_en[0] - cam_en[0], subj_en[1] - cam_en[1])) % 360.0


def local_m(en, origin):
    return en[0] - origin["E"], en[1] - origin["N"]


def load_plan(spec, loc):
    """Region centre (survey E/N) and radius in metres, from the rule stated in the spec header.

    Centred on the camera-subject MIDPOINT, not the camera: two aerials stand over open sea whose tiles
    carry terrain but neither streetscape nor massing, so a camera-centred box streams empty water and
    photographs a hole where the town should be.
    """
    ce, se = loc["camera_en"], loc["subject_en"]
    dist = math.hypot(se[0] - ce[0], se[1] - ce[1])
    if loc["kind"] == "aerial":
        floor_m, margin_m = 1500.0, 900.0
    else:
        floor_m, margin_m = 600.0, 400.0
    return [(ce[0] + se[0]) / 2.0, (ce[1] + se[1]) / 2.0], max(floor_m, dist / 2.0 + margin_m), dist


# ---- ground -------------------------------------------------------------------------------------------------------

def make_heightfield(spec):
    """A private UStreetHeightfieldTerrain over the CONFORMED product - the one 00_build_level.ps1 imports.

    Private, i.e. unreal.new_object rather than ue_common.heightfield(): that helper repoints the level's
    site actor, which dirties a World Partition package. A render must not modify the level it photographs.
    Sampling is set to LandscapeTriangulated so this reference agrees with the surface the landscape draws
    and the pawn collides with, rather than with the numpy bilinear contract.
    """
    land_dir = uc.data_dir() + "/landscape_conformed"
    if not os.path.isfile(land_dir + "/landscape_manifest.json"):
        uc.log("no landscape_conformed at %s - heightfield cross-check disabled" % land_dir)
        return None, land_dir
    hf = unreal.new_object(unreal.StreetHeightfieldTerrain)
    hf.set_editor_property("landscape_dir", land_dir)
    hf.set_sampling(unreal.StreetHeightSampling.LANDSCAPE_TRIANGULATED)
    if not hf.load():
        uc.log("heightfield load(%s) failed - cross-check disabled" % land_dir)
        return None, land_dir
    uc.log("heightfield: %s (%d tiles, triangulated sampling)" % (land_dir, hf.num_tiles()))
    return hf, land_dir


def _num(v):
    return None if v is None or (isinstance(v, float) and math.isnan(v)) else round(float(v), 3)


def landscape_lod(cap):
    """Apply the spec's landscape LOD policy, then READ BACK what the resident proxies actually carry.

    History, because this one property produced sixteen false frames.  `capture.landscape_lod0_screen_size`
    was introduced at 8.0 in the belief that a LARGER LOD0ScreenSize keeps the landscape at LOD 0 further
    out.  It is the opposite.  LOD0ScreenSize is the screen size at which LOD 0 STOPS: screen size falls
    with distance, so a threshold of 8.0 is above anything the ground ever subtends and every landscape
    component draws at its COARSEST level, whose vertices are nowhere near the surface GetHeightAtLocation
    returns.  That is what drew grass over carriageways the numbers put 3 cm above the ground, and it is
    why b1cd3e5's own INDEX.md could report "the capture already pins the landscape to LOD 0" while
    photographing the exact artefact the pin was meant to remove.

    Measured single-variable A/B, same commit, same cameras, one editor session, nine frames that had lost
    their road (projects/one/Saved/Clearance/frames_v4/): mean grass fraction over the lower half of the
    frame 0.739 with the 8.0 pin against 0.159 with the level's own saved settings.  The saved proxies
    carry the engine defaults (0.5 / 1.25 / 3.0) and are correct, so the policy is now to leave them alone:
    the spec sets landscape_lod0_screen_size null and this function only records the state.

    A non-null value still applies, unchanged, so the experiment is repeatable from the spec - but whatever
    happens, the values actually in force go into the report and from there into the snapshot manifest, so
    no future reader has to take a comment's word for what the landscape was doing.
    """
    ss = cap.get("landscape_lod0_screen_size")
    applied = SS.pin_landscape_lod(ss) if ss else None
    eas = unreal.get_editor_subsystem(unreal.EditorActorSubsystem)
    seen = {}
    n = 0
    for a in eas.get_all_level_actors():
        if not isinstance(a, unreal.LandscapeProxy):
            continue
        n += 1
        key = (round(float(a.get_editor_property("lod0_screen_size")), 4),
               round(float(a.get_editor_property("lod_distribution_setting")), 4),
               round(float(a.get_editor_property("lod0_distribution_setting")), 4))
        seen[key] = seen.get(key, 0) + 1
    state = {
        "spec_landscape_lod0_screen_size": ss,
        "pin_applied": bool(ss),
        "proxies_pinned": applied,
        "proxies_resident": n,
        "in_force": [{"lod0_screen_size": k[0], "lod_distribution_setting": k[1],
                      "lod0_distribution_setting": k[2], "proxies": v}
                     for k, v in sorted(seen.items())],
    }
    uc.log("landscape LOD: %s" % json.dumps(state, sort_keys=False))
    return state


def ground_at(land, hf, x, y):
    """(ground_z_m, source, {measurements}) at document metres.

    The LANDSCAPE is the authority - it is the surface in the frame. The conformed heightfield and a
    downward line trace are recorded beside it so a disagreement is visible in the manifest instead of
    silently moving the camera; neither is allowed to override the landscape or to fail the run, because a
    terrain disagreement is exactly the kind of defect this render set exists to photograph.
    """
    imp = unreal.StreetscapeLandscapeImporter
    z_land = imp.probe_height_m(land, x, y, False) if land is not None else float("nan")
    z_hf = hf.probe_m(x, y) if hf is not None else float("nan")
    z_trace = imp.trace_down_zm(x, y, 800.0, -300.0)
    m = {"landscape_m": _num(z_land), "heightfield_conformed_m": _num(z_hf), "trace_down_m": _num(z_trace)}
    if m["landscape_m"] is not None and m["heightfield_conformed_m"] is not None:
        m["landscape_minus_heightfield_m"] = round(m["landscape_m"] - m["heightfield_conformed_m"], 3)
    if m["landscape_m"] is not None:
        return float(z_land), "landscape", m
    if m["heightfield_conformed_m"] is not None:
        return float(z_hf), "heightfield_conformed", m
    return None, "none", m


# ---- main ---------------------------------------------------------------------------------------------------------

def main(argv):
    opts = uc.parse_args(
        argv,
        flags=("list", "no_load_region"),
        options={"out": "", "only": "", "spec": DEFAULT_SPEC, "map": "", "radius_m": "",
                 "report": "", "warm_s": "0"},
    )
    spec = read_spec(opts["spec"])
    items = select(flatten(spec), opts["only"])
    cap = spec["capture"]
    origin = spec["origin"]

    if opts["list"]:
        for town, loc in items:
            ce, se = loc["camera_en"], loc["subject_en"]
            centre, radius, dist = load_plan(spec, loc)
            print("%-46s %-8s E%10.2f N%10.2f h%7.2f yaw%8.2f pitch%7.2f fov%6.1f dist%8.1f load_r%7.0f"
                  % ("%s/%s" % (town, loc["slug"]), loc["kind"], ce[0], ce[1], loc["camera_height_m"],
                     bearing_deg(ce, se) - 90.0, loc["pitch_deg"], loc["fov_deg"], dist, radius))
        return uc.report(NAME, {"listed": len(items), "spec": opts["spec"],
                                "towns": [t["slug"] for t in spec["towns"]],
                                "locations_total": sum(len(t["locations"]) for t in spec["towns"])})

    if not opts["out"]:
        uc.fail(NAME, "--out <dir> is required (Tools/render_set.ps1 passes renders/<commit>)")
    out_root = opts["out"].replace("\\", "/").rstrip("/")
    if not os.path.isdir(out_root):
        os.makedirs(out_root)

    map_path = opts["map"] or spec["map"]
    les = unreal.get_editor_subsystem(unreal.LevelEditorSubsystem)
    if not les.load_level(map_path):
        uc.fail(NAME, "load_level(%s) failed" % map_path)
    world = unreal.get_editor_subsystem(unreal.UnrealEditorSubsystem).get_editor_world()

    land = unreal.StreetscapeLandscapeImporter.find_landscape()
    if land is None:
        uc.fail(NAME, "%s has no ALandscape - there is nothing to photograph" % map_path)
    hf, land_dir = make_heightfield(spec)

    guard_opts = {"min_distinct": cap["guards"]["min_distinct_rgb"],
                  "min_lum": cap["guards"]["min_mean_luminance"],
                  "max_lum": cap["guards"]["max_mean_luminance"]}
    rt = SS.make_render_target(world, cap["width"], cap["height"])
    audit = None
    records = []
    lib = unreal.StreetscapeEditorLibrary

    for town, loc in items:
        lid = "%s/%s" % (town, loc["slug"])
        ce, se = loc["camera_en"], loc["subject_en"]
        x, y = local_m(ce, origin)
        centre_en, radius_m, dist_m = load_plan(spec, loc)
        if opts["radius_m"]:
            radius_m = float(opts["radius_m"])

        if not opts["no_load_region"]:
            cx, cy = local_m(centre_en, origin)
            if not lib.load_region(unreal.Vector(100.0 * cx, -100.0 * cy, 0.0), 100.0 * radius_m):
                uc.fail(NAME, "%s: load_region(%.1f, %.1f, r=%.0f m) failed - World Partition streams "
                              "nothing in a commandlet, so the frame would be empty" % (lid, cx, cy, radius_m))
        # AFTER the stream: proxies that were not resident a moment ago carry their own LOD properties,
        # so both the policy and the read-back have to happen once the region is in (see landscape_lod).
        lod_state = landscape_lod(cap)

        ground_z, ground_src, ground_m = ground_at(land, hf, x, y)
        if ground_z is None:
            uc.fail(NAME, "%s: no ground at local (%.2f, %.2f) from the landscape or the heightfield - the "
                          "camera would hang in space" % (lid, x, y))
        eye_z = ground_z + float(loc["camera_height_m"])
        yaw = bearing_deg(ce, se) - 90.0
        cam = {"eye_ue": [100.0 * x, -100.0 * y, 100.0 * eye_z],
               "yaw": yaw, "pitch": float(loc["pitch_deg"]), "roll": 0.0,
               "fov_deg": float(loc["fov_deg"])}

        if audit is None:
            audit = SS.material_audit()
            uc.log("material audit: %s"
                   % json.dumps({k: v for k, v in audit.items() if k != "sample_components"}, sort_keys=True)[:600])

        png_rel = "%s/%s.png" % (town, loc["slug"])
        png = "%s/%s" % (out_root, png_rel)
        if not SS.capture(world, cam, rt, png, cap["source"], float(cap["exposure_ev"]), float(opts["warm_s"])):
            uc.fail(NAME, "%s: no PNG at %s (the runner needs -Render for an RHI)" % (lid, png))
        nbytes, distinct, lum = SS.force_opaque(png)

        rec = {
            "id": lid, "town": town, "slug": loc["slug"], "kind": loc["kind"], "title": loc["title"],
            "camera_en": ce, "subject_en": se, "camera_height_m": loc["camera_height_m"],
            "pitch_deg": loc["pitch_deg"], "fov_deg": loc["fov_deg"],
            "local_m": [round(x, 3), round(y, 3)],
            "ground_z_m": round(ground_z, 3), "ground_source": ground_src, "ground": ground_m,
            "eye_z_m": round(eye_z, 3),
            "eye_ue_cm": [round(v, 1) for v in cam["eye_ue"]],
            # 6 dp, not 3: the manifest is the RECORD of the transform that was applied, and a reader
            # comparing two snapshots must be able to prove the camera did not move.
            "bearing_deg": round(bearing_deg(ce, se), 6), "yaw_deg": round(yaw, 6),
            "pitch_applied_deg": cam["pitch"], "roll_deg": 0.0,
            "subject_distance_m": round(dist_m, 2),
            "load_centre_en": [round(v, 2) for v in centre_en], "load_radius_m": round(radius_m, 1),
            "png": png_rel, "bytes": nbytes, "distinct_rgb": distinct, "mean_luminance": round(lum, 2),
            "rss_mb": round(float(unreal.StreetscapeLandscapeImporter.rss_mb()), 1),
            "landscape_lod": lod_state,
            "capture_readiness": dict(SS.LAST_CAPTURE_STATE),
        }
        records.append(rec)
        uc.log("%-46s -> %s  eye_ue=(%.1f, %.1f, %.1f) yaw=%.2f pitch=%.2f fov=%.1f  ground=%.3f (%s) "
               "%d bytes, %d distinct RGB, luminance %.2f, rss %.0f MB"
               % (lid, png_rel, cam["eye_ue"][0], cam["eye_ue"][1], cam["eye_ue"][2], yaw, cam["pitch"],
                  cam["fov_deg"], ground_z, ground_src, nbytes, distinct, lum, rec["rss_mb"]))
        SS.guard(lid, distinct, lum, guard_opts, audit)

    report_path = (opts["report"] or (out_root + "/render_report.json")).replace("\\", "/")
    d = os.path.dirname(report_path)
    if d and not os.path.isdir(d):
        os.makedirs(d)
    payload = {
        "script": NAME,
        "spec": opts["spec"].replace("\\", "/"),
        "spec_schema_version": spec["schema_version"],
        "map": map_path,
        "out": out_root,
        "engine_version": unreal.SystemLibrary.get_engine_version(),
        "landscape_dir": land_dir,
        "capture": cap,
        "origin": origin,
        "images": len(records),
        "locations": records,
        "materials": audit,
    }
    with open(report_path, "w") as fh:
        json.dump(payload, fh, indent=2, sort_keys=False)
        fh.write("\n")
    uc.log("report -> %s" % report_path)

    uc.report(NAME, {
        "images": len(records),
        "out": out_root,
        "report": report_path,
        "map": map_path,
        "size": [cap["width"], cap["height"]],
        "min_bytes": min([r["bytes"] for r in records]) if records else 0,
        "min_distinct_rgb": min([r["distinct_rgb"] for r in records]) if records else 0,
        "mean_luminance_range": [min([r["mean_luminance"] for r in records]),
                                 max([r["mean_luminance"] for r in records])] if records else [],
        "max_landscape_minus_heightfield_m": max(
            [abs(r["ground"].get("landscape_minus_heightfield_m") or 0.0) for r in records]) if records else 0.0,
        "rss_mb": round(float(unreal.StreetscapeLandscapeImporter.rss_mb()), 1),
    })


if __name__ == "__main__":
    main(sys.argv)
