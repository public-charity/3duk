"""MeshBuffer / instances / overlay -> bpy objects, and glTF export (geometry.md 5.12).  Imports bpy
lazily so the package stays importable (and testable) without Blender.

Materials are created once per NAME from the document's material hints (flat Principled colour,
roughness, backface culling off for two-sided names).  Instances become linked duplicates of shared
primitive meshes (unit box for posts/sleepers, unit quad for leaf cards) with ``matrix_world`` from the
(4, 4) transform of instance.py scaled by ``size``.  The overlay is an edge-only mesh with an emissive
magenta material.  The vs/vd/vh attributes are dropped here; the .npz stays the numeric reference.
"""
from __future__ import annotations

from typing import Dict, List, Optional

import numpy as np

from .instance import Instance
from .mesh import MeshBuffer

_MATERIALS: Dict[str, object] = {}
_PRIMS: Dict[str, object] = {}

DEFAULT_COLORS = {
    "tarmac": (0.16, 0.16, 0.17), "white_paint": (0.92, 0.92, 0.9), "yellow_paint": (0.95, 0.8, 0.1),
    "concrete_kerb": (0.62, 0.61, 0.58), "paving_slab": (0.55, 0.54, 0.52), "grass": (0.25, 0.42, 0.14),
    "gravel": (0.5, 0.47, 0.42), "brick_red": (0.55, 0.27, 0.2), "coping_concrete": (0.66, 0.65, 0.62),
    "chain_link": (0.55, 0.57, 0.58), "post_steel": (0.35, 0.37, 0.38), "steel_painted_black": (0.05, 0.05, 0.06),
    "wood_fence": (0.45, 0.3, 0.16), "privet_leaf": (0.16, 0.33, 0.1), "ballast": (0.45, 0.43, 0.4),
    "sleeper_concrete": (0.6, 0.6, 0.58), "rail_steel": (0.5, 0.5, 0.52), "stone_flint": (0.5, 0.5, 0.48),
    "concrete_wall": (0.6, 0.6, 0.58), "massing_grey": (0.6, 0.6, 0.6), "terrain": (0.36, 0.4, 0.3),
}


def _bpy():
    import bpy  # noqa: local import
    return bpy


def ensure_material(name: str, hints: Optional[dict] = None, two_sided: bool = False):
    bpy = _bpy()
    if name in _MATERIALS and _MATERIALS[name].name in bpy.data.materials:
        return _MATERIALS[name]
    hint = (hints or {}).get(name)
    color = tuple(hint.base_color) if (hint is not None and getattr(hint, "base_color", None)) else DEFAULT_COLORS.get(name, (0.8, 0.1, 0.8))
    rough = float(hint.roughness) if (hint is not None and getattr(hint, "roughness", None) is not None) else 0.8
    mat = bpy.data.materials.get(name) or bpy.data.materials.new(name)
    mat.use_nodes = True
    bsdf = mat.node_tree.nodes.get("Principled BSDF")
    if bsdf is not None:
        bsdf.inputs["Base Color"].default_value = (color[0], color[1], color[2], 1.0)
        bsdf.inputs["Roughness"].default_value = rough
    mat.diffuse_color = (color[0], color[1], color[2], 1.0)
    mat.roughness = rough
    mat.use_backface_culling = not two_sided
    _MATERIALS[name] = mat
    return mat


def ensure_emissive(name: str, color=(1.0, 0.0, 1.0)):
    bpy = _bpy()
    mat = bpy.data.materials.get(name) or bpy.data.materials.new(name)
    mat.use_nodes = True
    nodes = mat.node_tree.nodes
    bsdf = nodes.get("Principled BSDF")
    if bsdf is not None:
        bsdf.inputs["Base Color"].default_value = (color[0], color[1], color[2], 1.0)
        if "Emission Color" in bsdf.inputs:
            bsdf.inputs["Emission Color"].default_value = (color[0], color[1], color[2], 1.0)
        if "Emission Strength" in bsdf.inputs:
            bsdf.inputs["Emission Strength"].default_value = 5.0
    mat.diffuse_color = (color[0], color[1], color[2], 1.0)
    return mat


def ensure_collection(name: str, parent=None):
    bpy = _bpy()
    col = bpy.data.collections.get(name)
    if col is None:
        col = bpy.data.collections.new(name)
        (parent or bpy.context.scene.collection).children.link(col)
    return col


def to_object(buf: MeshBuffer, name: str, collection, hints: Optional[dict] = None):
    """One bpy object per buffer; materials appended in the buffer's id order; per-corner UVs; smooth faces."""
    bpy = _bpy()
    me = bpy.data.meshes.new(name)
    me.from_pydata(buf.v.tolist(), [], buf.f.tolist())
    for mname in buf.material_names:
        me.materials.append(ensure_material(mname, hints, mname in buf.two_sided))
    if len(buf.f):
        me.polygons.foreach_set("material_index", buf.mat.astype(np.int32).tolist())
        me.polygons.foreach_set("use_smooth", [True] * len(buf.f))
        layer = me.uv_layers.new(name="UVMap")
        uv = buf.uv[buf.f.ravel()].astype(np.float32).ravel()
        layer.data.foreach_set("uv", uv.tolist())
    me.update()
    ob = bpy.data.objects.new(name, me)
    collection.objects.link(ob)
    return ob


def _primitive(kind: str):
    bpy = _bpy()
    if kind in _PRIMS and _PRIMS[kind].name in bpy.data.meshes:
        return _PRIMS[kind]
    me = bpy.data.meshes.new("prim_" + kind)
    if kind == "leaf_card":
        v = [(-0.5, -0.5, 0.0), (0.5, -0.5, 0.0), (0.5, 0.5, 0.0), (-0.5, 0.5, 0.0)]
        f = [(0, 1, 2, 3)]
    else:
        v = [(-0.5, -0.5, 0.0), (0.5, -0.5, 0.0), (0.5, 0.5, 0.0), (-0.5, 0.5, 0.0),
             (-0.5, -0.5, 1.0), (0.5, -0.5, 1.0), (0.5, 0.5, 1.0), (-0.5, 0.5, 1.0)]
        f = [(0, 3, 2, 1), (4, 5, 6, 7), (0, 1, 5, 4), (1, 2, 6, 5), (2, 3, 7, 6), (3, 0, 4, 7)]
    me.from_pydata(v, [], f)
    me.update()
    _PRIMS[kind] = me
    return me


def instances_to_objects(instances: List[Instance], collection, hints: Optional[dict] = None, prefix: str = "") -> int:
    """Linked duplicates of shared primitive meshes; one material slot per instance material."""
    bpy = _bpy()
    import mathutils
    n = 0
    by_kind_mat: Dict[tuple, object] = {}
    for k, inst in enumerate(instances):
        key = (inst.kind, inst.material)
        me = by_kind_mat.get(key)
        if me is None:
            base = _primitive("leaf_card" if inst.kind.startswith("leaf") else "box")
            me = base.copy()
            me.name = "prim_%s_%s" % (inst.kind, inst.material)
            me.materials.append(ensure_material(inst.material, hints, inst.kind.startswith("leaf")))
            by_kind_mat[key] = me
        ob = bpy.data.objects.new("%s%s_%d" % (prefix, inst.kind, k), me)
        M = np.array(inst.transform, dtype=np.float64)
        sx, sy, sz = inst.size
        Sm = np.diag([sx, sy, sz if sz > 0 else 1.0, 1.0])
        ob.matrix_world = mathutils.Matrix((M @ Sm).tolist())
        collection.objects.link(ob)
        n += 1
    return n


def overlay_to_object(pts: np.ndarray, name: str, collection):
    bpy = _bpy()
    me = bpy.data.meshes.new(name)
    edges = [(i, i + 1) for i in range(len(pts) - 1)]
    me.from_pydata([tuple(map(float, p)) for p in pts], edges, [])
    me.materials.append(ensure_emissive("overlay_magenta"))
    me.update()
    ob = bpy.data.objects.new(name, me)
    collection.objects.link(ob)
    return ob


TERRAIN_PATCH_SINK_M = 0.3   # the raw DTM already carries the real road's crown; the patch is context, not the road


def terrain_patch_to_object(terrain, site, bbox, name: str, collection, step: float = 1.0, sink_m: float = TERRAIN_PATCH_SINK_M):
    """A shaded ground patch (x0, y0, x1, y1) of the heightfield, sunk sink_m below the DTM so it stays under
    the road/kerb skirts (0.30 m) and renders show the road in context."""
    bpy = _bpy()
    x0, y0, x1, y1 = bbox
    xs = np.arange(x0, x1 + 1e-9, step)
    ys = np.arange(y0, y1 + 1e-9, step)
    X, Y = np.meshgrid(xs, ys)
    Z = terrain.rebased(site.origin.E, site.origin.N).sample(X.ravel(), Y.ravel()).reshape(X.shape)
    ok = np.isfinite(Z)
    if not ok.any():
        return None
    Z = np.where(ok, Z, np.nanmin(Z[ok])) - sink_m
    nx, ny = len(xs), len(ys)
    verts = np.column_stack([X.ravel(), Y.ravel(), Z.ravel()])
    faces = []
    for j in range(ny - 1):
        for i in range(nx - 1):
            a = j * nx + i
            faces.append((a, a + 1, a + nx + 1, a + nx))
    me = bpy.data.meshes.new(name)
    me.from_pydata(verts.tolist(), [], faces)
    me.materials.append(ensure_material("terrain"))
    me.polygons.foreach_set("use_smooth", [True] * len(faces))
    me.update()
    ob = bpy.data.objects.new(name, me)
    collection.objects.link(ob)
    return ob


def clear_scene():
    bpy = _bpy()
    for ob in list(bpy.data.objects):
        bpy.data.objects.remove(ob, do_unlink=True)
    for me in list(bpy.data.meshes):
        if me.users == 0:
            bpy.data.meshes.remove(me)
    _MATERIALS.clear()
    _PRIMS.clear()


def build_scene(results: dict, site, terrain=None, terrain_margin_m: float = 30.0) -> dict:
    """Collections per spline: <id>.road / .edge_left / ... / .instances / .overlay; returns {id: {name: object}}."""
    from . import schema as S
    hints = site.materials
    out = {}
    root = ensure_collection("streetscape")
    all_xy = []
    for sid, res in results.items():
        col = ensure_collection(sid, root)
        objs = {}
        for name, buf in res.buffers().items():
            objs[name] = to_object(buf, "%s.%s" % (sid, name), col, hints)
        if res.instances:
            icol = ensure_collection("%s.instances" % sid, col)
            objs["instances"] = instances_to_objects(res.instances, icol, hints, prefix="%s." % sid)
        if res.overlay is not None:
            objs["overlay"] = overlay_to_object(res.overlay, "%s.overlay" % sid, col)
        out[sid] = objs
        all_xy.append(res.spline.xy)
    if terrain is not None and all_xy:
        xy = np.vstack(all_xy)
        bbox = (np.floor(xy[:, 0].min() - terrain_margin_m), np.floor(xy[:, 1].min() - terrain_margin_m),
                np.ceil(xy[:, 0].max() + terrain_margin_m), np.ceil(xy[:, 1].max() + terrain_margin_m))
        tcol = ensure_collection("terrain", root)
        terrain_patch_to_object(terrain, site, bbox, "terrain_patch", tcol)
    return out


def export_gltf(path: str) -> None:
    bpy = _bpy()
    bpy.ops.export_scene.gltf(filepath=path, export_format="GLB", use_selection=False, export_yup=True, export_apply=True)
