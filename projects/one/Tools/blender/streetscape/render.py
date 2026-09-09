"""EEVEE renders from the three fixed cameras of geometry.md 5.12 (BRIEF section 8: Workbench is not
selectable under ``blender -b`` on this machine, so ``BLENDER_EEVEE`` it is).

  cam1  eye level on the LEFT pavement at s = 10, 0.9 m behind the kerb line, 1.7 m above the pavement,
        looking along +t_h, 60 deg FOV
  cam2  three-quarter aerial: 40 m behind the first width knot, 25 m up, 35 m to the right, aimed at it
  cam3  kerb close-up: at the first drop kerb, 6 m away on the carriageway side, 1.0 m up, aimed at the kerb
"""
from __future__ import annotations

import math
import os
from typing import Dict, Tuple

import numpy as np

from . import schema as S


def _bpy():
    import bpy  # noqa
    return bpy


def _first_width_knot(sp) -> float:
    w = sp.width
    ch = np.where(np.abs(np.diff(w)) > 1e-9)[0]
    return float(sp.s[ch[0]]) if len(ch) else float(sp.length / 2.0)


def _first_drop_kerb(sp):
    best = None
    for side in (S.LEFT, S.RIGHT):
        for dk in sp.side_tl[side].drop_kerbs:
            if best is None or dk.s_m < best[1]:
                best = (side, dk.s_m, dk.length_m)
    return best


def camera_defs(sp) -> Dict[str, Tuple[np.ndarray, np.ndarray, float]]:
    """{name: (eye, target, fov_deg)} in document-local metres."""
    fr = sp.frames
    out = {}
    # cam1
    s1 = min(10.0, sp.length * 0.25)
    f1 = fr.at(np.array([s1]))
    o_l = float(np.interp(s1, sp.s, sp.edge_offset(S.LEFT)))
    spec = sp.side_spec[S.LEFT]
    h_pav = float(np.interp(s1, sp.s, sp.edge_height(S.LEFT) + spec.hk_back)) if spec.present.any() else 0.0
    eye = f1.p[0] + (o_l + 0.9) * f1.n_flat[0] + (h_pav + 1.7) * np.array([0.0, 0.0, 1.0])
    ahead = fr.at(np.array([min(sp.length, s1 + 30.0)]))
    target = ahead.p[0] + np.array([0.0, 0.0, 1.0])
    out["cam1"] = (eye, target, 60.0)
    # cam2
    sk = _first_width_knot(sp)
    fk = fr.at(np.array([sk]))
    eye = fk.p[0] - 40.0 * fk.t_h[0] - 35.0 * fk.n_flat[0] + np.array([0.0, 0.0, 25.0])
    out["cam2"] = (eye, fk.p[0].copy(), 50.0)
    # cam3
    dk = _first_drop_kerb(sp)
    if dk is not None:
        side, s_d, ln = dk
        s3 = s_d + ln / 2.0
    else:
        side, s3 = S.LEFT, sp.length / 2.0
    f3 = fr.at(np.array([s3]))
    o3 = float(np.interp(s3, sp.s, sp.edge_offset(side)))
    kerb = f3.p[0] + side * o3 * f3.n_flat[0]
    eye = kerb - side * 6.0 * f3.n_flat[0] - 2.0 * f3.t_h[0] + np.array([0.0, 0.0, 1.0])
    out["cam3"] = (eye, kerb, 45.0)
    return out


def _look_at(cam_ob, eye, target):
    import mathutils
    eye_v = mathutils.Vector(tuple(map(float, eye)))
    tgt_v = mathutils.Vector(tuple(map(float, target)))
    direction = tgt_v - eye_v
    rot = direction.to_track_quat("-Z", "Y")
    cam_ob.location = eye_v
    cam_ob.rotation_euler = rot.to_euler()


def setup_render(resolution=(1920, 1080), samples: int = 16):
    bpy = _bpy()
    scene = bpy.context.scene
    scene.render.engine = "BLENDER_EEVEE"
    scene.render.resolution_x = int(resolution[0])
    scene.render.resolution_y = int(resolution[1])
    scene.render.resolution_percentage = 100
    scene.render.image_settings.file_format = "PNG"
    scene.render.image_settings.color_mode = "RGB"
    scene.render.image_settings.color_depth = "8"
    scene.render.image_settings.compression = 60
    try:
        scene.eevee.taa_render_samples = samples
    except Exception:
        pass
    # world + sun
    world = scene.world or bpy.data.worlds.new("World")
    scene.world = world
    world.use_nodes = True
    bg = world.node_tree.nodes.get("Background")
    if bg is not None:
        bg.inputs[0].default_value = (0.55, 0.65, 0.8, 1.0)
        bg.inputs[1].default_value = 0.6
    # These are technical renders: the point is to READ the materials (yellow paint vs white paint,
    # grass vs concrete kerb face, brick vs coping, ballast vs sleeper).  AgX plus a 6.0 sun drove every
    # albedo above ~0.25 into clipped white -- the ballast, sleepers and rails of a rail spline came out
    # as one white mass.  "Standard" with a 3.0 sun keeps a 0.6 albedo at ~0.57 and stays material-true.
    try:
        scene.view_settings.view_transform = "Standard"
    except Exception:
        pass
    if "sun" not in bpy.data.objects:
        light = bpy.data.lights.new("sun", type="SUN")
        light.energy = 3.0
        light.angle = math.radians(2.0)
        sun = bpy.data.objects.new("sun", light)
        scene.collection.objects.link(sun)
        sun.rotation_euler = (math.radians(50.0), math.radians(10.0), math.radians(35.0))
    return scene


def render_cameras(sp, out_dir: str, prefix: str, resolution=(1920, 1080)) -> Dict[str, str]:
    bpy = _bpy()
    scene = setup_render(resolution)
    os.makedirs(out_dir, exist_ok=True)
    written = {}
    for name, (eye, target, fov) in camera_defs(sp).items():
        cam_name = "%s_%s" % (prefix, name)
        cam_data = bpy.data.cameras.get(cam_name) or bpy.data.cameras.new(cam_name)
        cam_data.lens_unit = "FOV"
        cam_data.angle = math.radians(fov)
        cam_data.clip_start = 0.05
        cam_data.clip_end = 2000.0
        cam_ob = bpy.data.objects.get(cam_name) or bpy.data.objects.new(cam_name, cam_data)
        if cam_ob.name not in scene.collection.objects:
            scene.collection.objects.link(cam_ob)
        _look_at(cam_ob, eye, target)
        scene.camera = cam_ob
        path = os.path.join(out_dir, "%s_%s.png" % (prefix, name))
        scene.render.filepath = path
        bpy.ops.render.render(write_still=True)
        written[name] = path
    return written
