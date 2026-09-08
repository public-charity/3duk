"""Headless screenshots of a streetscape actor from the three fixed cameras (UE_PLAN.md 5.3 row 5).

  run_ue_python.ps1 -Script 05_screenshot.py -Render -Args "--camera cam1 --actor authored:trinity_square
                                                            --out <dir-or-png> [--w 1280 --h 720]"
  run_ue_python.ps1 -Script 05_screenshot.py -Render -Args "--x 4324 --y 3564.5 --z 60 --yaw 0 --pitch -89
                                                            --out <png> [--fov 60] [--w 1920 --h 1080]"

The second form is the free camera of UE_PLAN.md 5.3 row 5: --x/--y/--z are DOCUMENT metres (x east, y north,
z ODN) and --yaw/--pitch are UE degrees (yaw 0 = +X = east, pitch -90 = straight down); the script does the
(100, -100, 100) conversion. It needs no streetscape actor, so it works on a level that only has the landscape.

--camera takes cam1 | cam2 | cam3 | all; the eye / target / FOV come from
unreal.StreetscapeEditorLibrary.actor_camera_json, which is the C++ mirror of
Tools/blender/streetscape/render.py camera_defs, so the Unreal and Blender renders frame the same thing.

Capture path: a transient SceneCapture2D writing into a TextureRenderTarget2D, exported with
KismetRenderingLibrary.export_render_target (ENG/Classes/Kismet/KismetRenderingLibrary.h:48, :144). Needs the
runner's -Render (an RHI); with the null RHI the capture is black and the script says so instead of pretending.
"""
import json
import os
import sys

import unreal

import ue_common as uc

NAME = "05_screenshot"
DEFAULT_MAP = "/Game/Thanet/Maps/Thanet"
CAMS = ("cam1", "cam2", "cam3")


def force_opaque(path):
    """UE's scene-capture sources write alpha 0, so the exported PNG reads as fully transparent in every viewer.
    Rewrite it with alpha 255 (stdlib zlib only - UE's python has no PIL). Returns (bytes, distinct_rgb)."""
    import struct
    import zlib
    d = open(path, "rb").read()
    if d[:8] != b"\x89PNG\r\n\x1a\n":
        return len(d), 0
    i, idat, w, h, bd, ct = 8, b"", 0, 0, 0, 0
    while i < len(d):
        ln = struct.unpack(">I", d[i:i + 4])[0]
        typ = d[i + 4:i + 8]
        data = d[i + 8:i + 8 + ln]
        i += 12 + ln
        if typ == b"IHDR":
            w, h, bd, ct = struct.unpack(">IIBB", data[:10])
        elif typ == b"IDAT":
            idat += data
        elif typ == b"IEND":
            break
    if ct != 6 or bd != 8:                      # only RGBA8 needs the fix
        return len(d), 0
    raw = zlib.decompress(idat)
    stride = w * 4
    out = bytearray()
    prev = bytearray(stride)
    pos = 0
    for _y in range(h):
        f = raw[pos]
        pos += 1
        line = bytearray(raw[pos:pos + stride])
        pos += stride
        if f == 1:
            for x in range(4, stride):
                line[x] = (line[x] + line[x - 4]) & 255
        elif f == 2:
            for x in range(stride):
                line[x] = (line[x] + prev[x]) & 255
        elif f == 3:
            for x in range(stride):
                a = line[x - 4] if x >= 4 else 0
                line[x] = (line[x] + ((a + prev[x]) >> 1)) & 255
        elif f == 4:
            for x in range(stride):
                a = line[x - 4] if x >= 4 else 0
                b = prev[x]
                c = prev[x - 4] if x >= 4 else 0
                p = a + b - c
                pa, pb, pc = abs(p - a), abs(p - b), abs(p - c)
                pr = a if (pa <= pb and pa <= pc) else (b if pb <= pc else c)
                line[x] = (line[x] + pr) & 255
        out += line
        prev = line
    out[3::4] = b"\xff" * (w * h)
    body = bytearray()
    for y in range(h):
        body += b"\x00" + out[y * stride:(y + 1) * stride]
    distinct = len(set(bytes(out[i:i + 3]) for i in range(0, len(out), 4)))

    def chunk(typ, data):
        return struct.pack(">I", len(data)) + typ + data + struct.pack(">I", zlib.crc32(typ + data) & 0xFFFFFFFF)

    png = b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", w, h, 8, 6, 0, 0, 0))
    png += chunk(b"IDAT", zlib.compress(bytes(body), 9)) + chunk(b"IEND", b"")
    with open(path, "wb") as fh:
        fh.write(png)
    return len(png), distinct


def make_render_target(world, w, h):
    """RenderingLibrary.create_render_target2d: UTextureRenderTarget2D::UpdateResource is not exposed to Python."""
    return unreal.RenderingLibrary.create_render_target2d(
        world, int(w), int(h), unreal.TextureRenderTargetFormat.RTF_RGBA8,
        unreal.LinearColor(0.05, 0.06, 0.08, 1.0), False, False)


SOURCES = {
    "final_ldr": unreal.SceneCaptureSource.SCS_FINAL_COLOR_LDR,
    "scene_hdr": unreal.SceneCaptureSource.SCS_SCENE_COLOR_HDR,
    "base_color": unreal.SceneCaptureSource.SCS_BASE_COLOR,
}


def capture(world, cam, rt, out_png, source, ev, warm_s):
    eye = cam["eye_ue"]
    loc = unreal.Vector(eye[0], eye[1], eye[2])
    rot = unreal.Rotator(cam["roll"], cam["pitch"], cam["yaw"])
    actor = unreal.EditorLevelLibrary.spawn_actor_from_class(unreal.SceneCapture2D, loc, rot)
    try:
        comp = actor.get_editor_property("capture_component2d")
        comp.set_editor_property("texture_target", rt)
        comp.set_editor_property("capture_source", SOURCES[source])
        comp.set_editor_property("fov_angle", float(cam["fov_deg"]))
        comp.set_editor_property("capture_every_frame", False)
        comp.set_editor_property("capture_on_movement", False)
        # A commandlet has no eye-adaptation history, so the default histogram auto-exposure blows the frame out to
        # white on the first capture. Pin it: manual exposure at a fixed EV.
        pp = comp.get_editor_property("post_process_settings")
        pp.set_editor_property("override_auto_exposure_method", True)
        pp.set_editor_property("auto_exposure_method", unreal.AutoExposureMethod.AEM_MANUAL)
        pp.set_editor_property("override_auto_exposure_bias", True)
        pp.set_editor_property("auto_exposure_bias", float(ev))
        pp.set_editor_property("override_auto_exposure_apply_physical_camera_exposure", True)
        pp.set_editor_property("auto_exposure_apply_physical_camera_exposure", False)
        comp.set_editor_property("post_process_settings", pp)
        # The first capture is what queues the project materials for SM6 compilation; until those shader maps exist
        # the renderer substitutes the engine default (the grey grid). Capture, wait for the async compiler, capture
        # again - --warm-s 0 skips the wait when the DDC is already warm.
        comp.capture_scene()
        if warm_s > 0:
            import time
            deadline = time.time() + warm_s
            while time.time() < deadline:
                unreal.SystemLibrary.execute_console_command(world, "r.ShaderCompiler.DumpCompileJobInputs 0")
                time.sleep(1.0)
        comp.capture_scene()
        comp.capture_scene()
        d = os.path.dirname(out_png)
        if d and not os.path.isdir(d):
            os.makedirs(d)
        unreal.RenderingLibrary.export_render_target(world, rt, d, os.path.basename(out_png))
    finally:
        unreal.EditorLevelLibrary.destroy_actor(actor)
    return os.path.isfile(out_png)


def main(argv):
    opts = uc.parse_args(
        argv,
        flags=("no_load_region",),
        options={"camera": "all", "actor": "", "out": "", "map": DEFAULT_MAP, "w": "1280", "h": "720", "radius_m": "400", "site_radius_m": "20000", "source": "final_ldr", "ev": "0", "warm_s": "0",
                 "x": "", "y": "", "z": "", "yaw": "0", "pitch": "-30", "roll": "0", "fov": "60"},
    )
    if not opts["out"]:
        uc.fail(NAME, "--out <dir or .png> is required")
    free = opts["x"] != "" and opts["y"] != "" and opts["z"] != ""
    if not free and not opts["actor"]:
        uc.fail(NAME, "--actor <spline id> (or --x --y --z for the free camera) is required")
    cams = CAMS if opts["camera"] == "all" else tuple(c for c in CAMS if c == opts["camera"])
    if not free and not cams:
        uc.fail(NAME, "--camera must be one of cam1|cam2|cam3|all")

    les = unreal.get_editor_subsystem(unreal.LevelEditorSubsystem)
    if not les.load_level(opts["map"]):
        uc.fail(NAME, "load_level(%s) failed" % opts["map"])

    if free:
        return main_free(opts, les)

    # World Partition commandlets skip LoadLastLoadedRegions (WorldPartition.cpp:880-886), so nothing is loaded yet
    # and streetscape_actor_ids() would be empty: pull the whole site in FIRST, then read the cameras off the actor.
    world = unreal.get_editor_subsystem(unreal.UnrealEditorSubsystem).get_editor_world()
    if not opts["no_load_region"]:
        unreal.StreetscapeEditorLibrary.load_region(unreal.Vector(0.0, 0.0, 0.0), float(opts["site_radius_m"]) * 100.0)

    ids = [str(i) for i in unreal.StreetscapeEditorLibrary.streetscape_actor_ids()]
    if opts["actor"] not in ids:
        uc.fail(NAME, "actor %r not in the level (have %s)" % (opts["actor"], ids))
    text = unreal.StreetscapeEditorLibrary.actor_camera_json(opts["actor"])
    if not text:
        uc.fail(NAME, "actor_camera_json(%s) returned nothing" % opts["actor"])
    defs = json.loads(text)
    if not opts["no_load_region"]:
        eye = defs[cams[0]]["eye_ue"]
        unreal.StreetscapeEditorLibrary.load_region(unreal.Vector(eye[0], eye[1], eye[2]), float(opts["radius_m"]) * 100.0)

    out = opts["out"].replace("\\", "/")
    single_png = out.lower().endswith(".png")
    if single_png and len(cams) != 1:
        uc.fail(NAME, "--out is a .png but --camera asks for %d cameras" % len(cams))

    rt = make_render_target(world, opts["w"], opts["h"])
    written = {}
    for cam in cams:
        png = out if single_png else ("%s/%s_%s.png" % (out.rstrip("/"), opts["actor"].replace(":", "~"), cam))
        ok = capture(world, defs[cam], rt, png, opts["source"], float(opts["ev"]), float(opts["warm_s"]))
        if not ok:
            uc.fail(NAME, "no PNG at %s (needs the runner's -Render)" % png)
        nbytes, distinct = force_opaque(png)
        written[cam] = {"png": png, "bytes": nbytes, "distinct_rgb": distinct, "eye_ue": defs[cam]["eye_ue"],
                        "pitch": defs[cam]["pitch"], "yaw": defs[cam]["yaw"], "fov_deg": defs[cam]["fov_deg"]}
        uc.log("%s -> %s (%d bytes, %d distinct RGB)" % (cam, png, nbytes, distinct))
        if distinct < 4:
            uc.fail(NAME, "%s: only %d distinct colours - the capture rendered nothing" % (cam, distinct))

    uc.report(NAME, {
        "actor": opts["actor"],
        "map": opts["map"],
        "size": [int(opts["w"]), int(opts["h"])],
        "source": opts["source"],
        "ev": float(opts["ev"]),
        "cameras": written,
    })


def main_free(opts, les):
    """--x/--y/--z (document metres) + --yaw/--pitch (UE degrees): one capture, no streetscape actor needed."""
    world = unreal.get_editor_subsystem(unreal.UnrealEditorSubsystem).get_editor_world()
    x, y, z = float(opts["x"]), float(opts["y"]), float(opts["z"])
    eye = [100.0 * x, -100.0 * y, 100.0 * z]
    if not opts["no_load_region"]:
        unreal.StreetscapeEditorLibrary.load_region(unreal.Vector(eye[0], eye[1], eye[2]), float(opts["radius_m"]) * 100.0)
    cam = {"eye_ue": eye, "yaw": float(opts["yaw"]), "pitch": float(opts["pitch"]), "roll": float(opts["roll"]),
           "fov_deg": float(opts["fov"])}
    png = opts["out"].replace("\\", "/")
    if not png.lower().endswith(".png"):
        uc.fail(NAME, "--out must be a .png for the free camera")
    rt = make_render_target(world, opts["w"], opts["h"])
    if not capture(world, cam, rt, png, opts["source"], float(opts["ev"]), float(opts["warm_s"])):
        uc.fail(NAME, "no PNG at %s (needs the runner's -Render)" % png)
    nbytes, distinct = force_opaque(png)
    uc.log("free camera -> %s (%d bytes, %d distinct RGB)" % (png, nbytes, distinct))
    if distinct < 4:
        uc.fail(NAME, "only %d distinct colours - the capture rendered nothing" % distinct)
    uc.report(NAME, {"png": png, "bytes": nbytes, "distinct_rgb": distinct, "eye_ue": eye,
                     "local_m": [x, y, z], "yaw": cam["yaw"], "pitch": cam["pitch"], "fov_deg": cam["fov_deg"],
                     "size": [int(opts["w"]), int(opts["h"])], "source": opts["source"], "map": opts["map"]})


if __name__ == "__main__":
    main(sys.argv)
