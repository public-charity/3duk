"""Bounded unsaved Landscape read/apply/restore proof, with durable Content hashes.

Run with -Render. The native API owns the rollback snapshot; this diagnostic checks
the composed editor and collision heights independently against candidate raster posts.
Nothing is imported or saved. On interruption, content_before.json survives for an
external integrity check even if Python's finally block never runs.
"""
import json
import importlib.util
import math
import os
from pathlib import Path
import struct
import sys

import unreal
import ue_common as uc
from content_guard import snapshot, require_unchanged

NAME = "diag_terrain_preview"


def candidate_posts(root, bounds):
    manifest = json.loads((root / "landscape_manifest.json").read_text())
    if manifest["tile_m"] != 512 or manifest["res"] != 513 or manifest["px_m"] != 1:
        raise ValueError("diagnostic requires the existing 1 m Thanet raster grid")
    cache = {}
    rows = []
    x1, y1, x2, y2 = bounds
    for y in range(y1, y2+1):
        for x in range(x1, x2+1):
            tx, ty = x//512, y//512
            key = tx, ty
            if key not in cache:
                cache[key] = (root / manifest["heightmap"]["file"].format(i=tx, j=ty)).read_bytes()
            index = (512-(y-ty*512))*513+x-tx*512
            h16 = struct.unpack_from("<H", cache[key], 2*index)[0]
            rows.append({"x": x, "y": y, "candidate_m": (h16-32768)/128})
    return rows


def main(argv):
    opts = uc.parse_args(argv, options={"candidate": "", "out": "", "bounds": "8378,4435,8386,4443"}, flags={"capture"})
    if not opts["candidate"] or not opts["out"]:
        uc.fail(NAME, "--candidate and --out required")
    root = Path(opts["out"]).resolve()
    root.mkdir(parents=True, exist_ok=True)
    if (root / "content_before.json").exists():
        raise ValueError("use a fresh output directory to preserve earlier interruption evidence")
    candidate = Path(opts["candidate"]).resolve()
    bounds = list(map(int, opts["bounds"].split(",")))
    if len(bounds) != 4 or not (0 < bounds[2]-bounds[0] <= 64 and 0 < bounds[3]-bounds[1] <= 64):
        raise ValueError("diagnostic rectangle must be 1..64 m on each side")
    rows = candidate_posts(candidate, bounds)
    content = Path(__file__).resolve().parents[2] / "Content"
    before = snapshot(content)
    (root / "content_before.json").write_text(json.dumps(before, sort_keys=True))
    report = {"status": "running", "candidate": str(candidate), "bounds_m": bounds, "rows": rows}

    def checkpoint():
        temp = root / "report.tmp"
        temp.write_text(json.dumps(report, indent=2, allow_nan=False))
        os.replace(str(temp), str(root / "report.json"))

    lib = unreal.StreetscapeEditorLibrary
    imp = unreal.StreetscapeLandscapeImporter
    land = None
    screenshot = None
    camera = None
    world = None
    target = None

    def capture(tag):
        if screenshot is None:
            return
        path = str(root / (tag+".png"))
        if not screenshot.capture(world, camera, target, path, "final_ldr", 0., 0.):
            raise ValueError("capture failed: "+tag)
        size, distinct, luminance = screenshot.force_opaque(path)
        report.setdefault("captures", {})[tag] = dict(path=path, bytes=size,
            distinct_rgb=distinct, mean_luminance=luminance, readiness=screenshot.LAST_CAPTURE_STATE)
        if distinct < 24 or not 4 <= luminance <= 250:
            raise ValueError("empty or overexposed capture: "+tag)
        checkpoint()

    def read(tag):
        for row in rows:
            for collision in (False, True):
                value = imp.probe_height_m(land, row["x"], row["y"], collision)
                if not math.isfinite(value):
                    raise ValueError("missing %s terrain at %s" % (tag, row))
                row[tag + ("_collision_m" if collision else "_editor_m")] = value

    checkpoint()
    try:
        if not unreal.get_editor_subsystem(unreal.LevelEditorSubsystem).load_level("/Game/Thanet/Maps/Thanet"):
            raise ValueError("load failed")
        x1, y1, x2, y2 = bounds
        lib.load_region(unreal.Vector((x1+x2)*50, -(y1+y2)*50, 0), 30000)
        land = imp.find_landscape()
        if land is None:
            raise ValueError("landscape not loaded")
        eas = unreal.get_editor_subsystem(unreal.EditorActorSubsystem)
        paths_before = sorted(a.get_path_name() for a in eas.get_all_level_actors())
        report["landscape"] = json.loads(imp.landscape_state_json(land))
        read("before")
        checkpoint()
        if opts["capture"]:
            spec = importlib.util.spec_from_file_location("terrain_preview_capture", Path(__file__).with_name("05_screenshot.py"))
            screenshot = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(screenshot)
            world = unreal.get_editor_subsystem(unreal.UnrealEditorSubsystem).get_editor_world()
            target = screenshot.make_render_target(world, 1600, 900)
            cx, cy = x1+.85*(x2-x1), y1+.15*(y2-y1)
            tx, ty = (x1+x2)*.5, (y1+y2)*.5
            tz = imp.probe_height_m(land, tx, ty, False)+.5
            cz = imp.probe_height_m(land, cx, cy, False)+12
            camera = {"eye_ue": [cx*100, -cy*100, cz*100],
                "yaw": math.degrees(math.atan2(-(ty-cy), tx-cx)),
                "pitch": math.degrees(math.atan2(tz-cz, math.hypot(tx-cx,ty-cy))),
                "roll": 0., "fov_deg": 65.}
            report["camera"] = camera
            capture("before")
        result = json.loads(lib.preview_landscape_heights_json(str(candidate), *bounds))
        report["preview"] = result
        checkpoint()
        if not result.get("ok") or not result.get("changed_samples"):
            raise ValueError("preview failed or did not exercise a height change: %s" % result)
        read("preview")
        report["preview_max_error_m"] = {
            kind: max(abs(r["preview_"+kind+"_m"]-r["candidate_m"]) for r in rows)
            for kind in ("editor", "collision")}
        checkpoint()
        # ProbeHeightM goes through the engine's floating-point height query.
        # Native uint16 readback remains exact; at ~51 m ODN this query alone has
        # a measured 0.054 mm error, well below the 7.8125 mm encoded height step.
        report["height_query_tolerance_m"] = .0001
        if max(report["preview_max_error_m"].values()) > .0001:
            raise ValueError("composed/collision landscape disagrees with candidate raster")
        capture("preview")
        report["restore"] = json.loads(lib.restore_landscape_preview_json())
        if not report["restore"].get("ok") or not report["restore"].get("restored"):
            raise ValueError("native restoration failed")
        read("restored")
        if any(r["restored_"+k+"_m"] != r["before_"+k+"_m"] for r in rows for k in ("editor", "collision")):
            raise ValueError("restored composed/collision landscape differs from baseline")
        report["composed_and_collision_restored_identically"] = True
        if paths_before != sorted(a.get_path_name() for a in eas.get_all_level_actors()):
            raise ValueError("terrain preview changed actor identities")
        report["actor_identities_unchanged"] = len(paths_before)
        report["status"] = "complete"
    except Exception as exc:
        report.update(status="failed", error=str(exc))
        raise
    finally:
        try:
            report["final_restore"] = json.loads(lib.restore_landscape_preview_json())
            if not report["final_restore"].get("ok"):
                report["status"] = "failed"
                raise ValueError("final restoration failed")
        finally:
            try:
                report["content_integrity"] = require_unchanged(before, snapshot(content))
            except Exception as exc:
                report.update(status="failed", content_error=str(exc))
                raise
            finally:
                checkpoint()
    uc.report(NAME, {"report": str(root / "report.json"), "status": report["status"],
                     "content_integrity": report["content_integrity"]})


if __name__ == "__main__":
    main(sys.argv)
