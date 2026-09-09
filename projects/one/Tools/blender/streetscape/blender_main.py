"""Blender headless entry point (STAGES.md command conventions):

  "C:/Program Files/Blender Foundation/Blender 5.2/blender.exe" -b --python blender_main.py -- \\
      --site X.json --terrain <landscape dir | step-05 dir | heightfield .npz> --out DIR [--gltf] [--render]
      [--renders DIR] [--only-layer rail] [--spline <id>[,<id>...]] [--resolution 1920x1080]

Builds every spline with the numpy core (build_all), writes the .npz/stats.json products, creates the bpy
scene through bpy_bridge, then optionally exports one GLB and renders the three fixed cameras per spline.
Exit code 1 on any MeshBuffer.validate() message.  Blender's python has no GDAL, so a step-05 terrain
directory must be given as the .npz cache written by ``python -m streetscape.build --export-terrain-npz``.
Also runnable under the env python without bpy for the numeric part (--no-bpy).
"""
from __future__ import annotations

import argparse
import os
import sys
import time

HERE = os.path.dirname(os.path.abspath(__file__))
PKG_PARENT = os.path.dirname(HERE)
if PKG_PARENT not in sys.path:
    sys.path.insert(0, PKG_PARENT)

from streetscape import __version__  # noqa: E402
from streetscape.build import build_all, load_terrain, write_result, safe_dir_name  # noqa: E402
from streetscape.io_json import load_site  # noqa: E402


def parse_args(argv):
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--site", required=True)
    ap.add_argument("--terrain", default=None)
    ap.add_argument("--out", required=True)
    ap.add_argument("--renders", default=None, help="render directory (default <out>/renders)")
    ap.add_argument("--gltf", action="store_true")
    ap.add_argument("--render", action="store_true")
    ap.add_argument("--only-layer", default=None, choices=["roads", "rail", "barriers", "authored"])
    ap.add_argument("--spline", default=None, help="comma-separated spline id(s) to build and render (default: all)")
    ap.add_argument("--resolution", default="1920x1080")   # STAGES.md FD.1 task 1: 1920x1080 PNG
    ap.add_argument("--no-bpy", action="store_true", help="numeric build only (env python)")
    ap.add_argument("--no-terrain-patch", action="store_true")
    return ap.parse_args(argv)


def main(argv=None) -> int:
    if argv is None:
        argv = sys.argv[sys.argv.index("--") + 1:] if "--" in sys.argv else sys.argv[1:]
    args = parse_args(argv)
    t0 = time.time()
    site = load_site(args.site)
    terrain = load_terrain(args.terrain) if args.terrain else None
    results = build_all(site, terrain, args.only_layer,
                        [v for v in args.spline.split(",") if v] if args.spline else None)
    os.makedirs(args.out, exist_ok=True)
    problems = 0
    for sid, res in results.items():
        write_result(res, args.out)
        msgs = {k: v for k, v in res.stats["validate"].items() if v}
        if msgs:
            problems += 1
            print("VALIDATE %s: %s" % (sid, msgs))
        st = res.stats
        print("BUILT %s L=%.3f N=%d overlap=%s/%s strips=%d instances=%s" % (
            sid, st["length_m"], st["n_samples"], st["overlap_min"], st["overlap_max"], st["marking_strips"], st["instances"]))
    print("numeric build: %.1f s" % (time.time() - t0))
    if args.no_bpy:
        return 1 if problems else 0
    from streetscape import bpy_bridge, render
    bpy_bridge.clear_scene()
    bpy_bridge.build_scene(results, site, None if args.no_terrain_patch else terrain)
    print("bpy scene: %.1f s" % (time.time() - t0))
    if args.gltf:
        base = os.path.splitext(os.path.basename(args.site))[0]
        if len(results) == 1:
            base = safe_dir_name(next(iter(results)))
        gpath = os.path.join(args.out, base + ".glb")
        bpy_bridge.export_gltf(gpath)
        print("GLB %s %d bytes" % (gpath, os.path.getsize(gpath)))
    if args.render:
        w, h = (int(v) for v in args.resolution.lower().split("x"))
        rdir = args.renders or os.path.join(args.out, "renders")
        for sid, res in results.items():
            paths = render.render_cameras(res.spline, rdir, safe_dir_name(sid), (w, h))
            for name, p in paths.items():
                print("RENDER %s %s %d bytes" % (sid, p, os.path.getsize(p)))
        print("renders: %.1f s" % (time.time() - t0))
    print("STREETSCAPE_OK version=%s splines=%d problems=%d" % (__version__, len(results), problems))
    return 1 if problems else 0


if __name__ == "__main__":
    code = main()
    if code:
        sys.exit(code)
