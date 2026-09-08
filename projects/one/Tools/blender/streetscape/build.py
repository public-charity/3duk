"""Build entry points (geometry.md 5.12): build_spline / build_all, the deterministic writer and the CLI.

  python -m streetscape.build --site X.json --terrain DIR --out DIR [--only-layer roads|rail|barriers]

Output per spline: <out>/<safe id>/{road,edge_left,edge_right,hedge_left,hedge_right}.npz,
instances.json, overlay.json, stats.json.  The directory name is the spline id with ':' replaced by
'~' (NTFS refuses ':'; '~' is outside the Id charset so the mapping is reversible); stats.json carries
both.  stats.json keys (DESIGN.md 14): length_m, n_samples, step_min/max/mean, z_raw_nan_count,
bank_min/max, per-buffer {verts, tris, per_material}, overlap_min/max per side, marking_strips,
instance counts, plus terrain provenance and z_ref probes.
"""
from __future__ import annotations

import argparse
import json
import os
import sys
from dataclasses import dataclass, field
from typing import Dict, List, Optional

import numpy as np

from . import schema as S
from .instance import Instance
from .io_json import load_site
from .mesh import MeshBuffer, measure_lateral_overlap, station_values, save_npz_dict
from .spline import Spline, fill_nan_along
from .terrain import Heightfield

OVERLAY_LIFT_M = 0.3
OVERLAY_STEP_M = 2.0


def safe_dir_name(spline_id: str) -> str:
    return spline_id.replace(":", "~")


def spline_id_from_dir(name: str) -> str:
    return name.replace("~", ":")


@dataclass
class BuildResult:
    spline: Spline
    road: Optional[MeshBuffer]
    edge: Dict[int, Optional[MeshBuffer]]
    hedge: Dict[int, Optional[MeshBuffer]]
    instances: List[Instance]
    overlay: Optional[np.ndarray]
    stats: dict = field(default_factory=dict)

    def buffers(self) -> Dict[str, MeshBuffer]:
        out = {}
        if self.road is not None and len(self.road.v):
            out["road"] = self.road
        for side, name in ((S.LEFT, "edge_left"), (S.RIGHT, "edge_right")):
            b = self.edge.get(side)
            if b is not None and len(b.v):
                out[name] = b
        for side, name in ((S.LEFT, "hedge_left"), (S.RIGHT, "hedge_right")):
            b = self.hedge.get(side)
            if b is not None and len(b.v):
                out[name] = b
        return out


def load_terrain(path: str) -> Heightfield:
    """Adapter landscape dir (landscape_manifest.json), step-05 terrain dir (terrain_manifest.json, GDAL)
    or a heightfield .npz cache written by Heightfield.save_npz (what Blender's GDAL-less python reads)."""
    if os.path.isfile(path) and path.lower().endswith(".npz"):
        return Heightfield.from_npz(path)
    if os.path.isfile(os.path.join(path, "landscape_manifest.json")):
        return Heightfield.from_landscape_dir(path)
    if os.path.isfile(os.path.join(path, "terrain_manifest.json")):
        return Heightfield.from_step05_dir(path)
    raise FileNotFoundError("%s: neither landscape_manifest.json nor terrain_manifest.json" % path)


def tiles_under_site(site: S.Site, step05_dir: str, margin_tiles: int = 1):
    """Step-05 tile indices (in the terrain's own grid) covering every spline point of the site +- margin."""
    with open(os.path.join(step05_dir, "terrain_manifest.json"), "r", encoding="utf-8") as fh:
        man = json.load(fh)
    E0, N0, tm = float(man["origin"]["E"]), float(man["origin"]["N"]), float(man["tile_m"])
    dx, dy = site.origin.E - E0, site.origin.N - N0
    keys = set()
    for sp in site.splines:
        for p in sp.points:
            i = int(np.floor((p.x + dx) / tm))
            j = int(np.floor((p.y + dy) / tm))
            for a in range(-margin_tiles, margin_tiles + 1):
                for b in range(-margin_tiles, margin_tiles + 1):
                    keys.add((i + a, j + b))
    return sorted(keys)


def build_overlay(sdef: S.SplineDef, terrain: Optional[Heightfield], site: S.Site) -> Optional[np.ndarray]:
    """Raw overlay polyline densified at 2 m, re-draped on the terrain and lifted 0.3 m (DESIGN.md 5.5)."""
    if sdef.overlay is None:
        return None
    pts = np.array([[p[0], p[1]] for p in sdef.overlay.pts], dtype=np.float64)
    dense = [pts[0]]
    for a, b in zip(pts[:-1], pts[1:]):
        d = float(np.hypot(*(b - a)))
        n = int(d // OVERLAY_STEP_M)
        for k in range(1, n + 1):
            t = k * OVERLAY_STEP_M / d
            if t < 1.0:
                dense.append(a + (b - a) * t)
        dense.append(b)
    D = np.array(dense)
    if terrain is not None:
        z = terrain.rebased(site.origin.E, site.origin.N).sample(D[:, 0], D[:, 1])
    else:
        z = np.full(len(D), np.nan)
    z, _ = fill_nan_along(z)
    return np.column_stack([D, z + OVERLAY_LIFT_M])


def _assert_stations(spline: Spline, buffers: Dict[str, MeshBuffer]) -> dict:
    """DESIGN.md 5 rule 2: every buffer's non-marking stations equal spline.s exactly."""
    out = {}
    for name, buf in buffers.items():
        st = station_values(buf)
        same = bool(np.array_equal(st, spline.s)) if name in ("road",) else bool(np.all(np.isin(st, spline.s)))
        if name == "road" and spline.kind is not None and not same:
            raise AssertionError("%s: %s stations differ from the spline stations" % (spline.id, name))
        if not same:
            raise AssertionError("%s: %s carries stations that are not spline stations" % (spline.id, name))
        out[name] = True
    return out


def build_spline(site: S.Site, spline_id: str, terrain: Optional[Heightfield]) -> BuildResult:
    from .road import build_road
    from .edge import build_edge
    from .hedge import build_hedge
    sdef = site.spline(spline_id)
    sp = Spline(sdef, site, terrain)
    terrain_doc = terrain.rebased(site.origin.E, site.origin.N) if terrain is not None else None
    instances: List[Instance] = []
    road, inst = build_road(sp)
    instances += inst
    edge: Dict[int, Optional[MeshBuffer]] = {}
    hedge: Dict[int, Optional[MeshBuffer]] = {}
    for side in (S.LEFT, S.RIGHT):
        e, inst = build_edge(sp, side, terrain_doc)
        edge[side] = e if len(e.v) else None
        instances += inst
        h, inst = build_hedge(sp, side)
        hedge[side] = h if len(h.v) else None
        instances += inst
    for b in (road, *edge.values(), *hedge.values()):
        if b is not None and len(b.v) and len(b.vn) != len(b.v):
            b.compute_normals()
    res = BuildResult(sp, road if len(road.v) else None, edge, hedge, instances, build_overlay(sdef, terrain, site))
    res.stats = compute_stats(res, terrain_doc)
    return res


def compute_stats(res: BuildResult, terrain: Optional[Heightfield]) -> dict:
    sp = res.spline
    st = sp.stats()
    st["spline_id"] = sp.id
    st["out_dir_name"] = safe_dir_name(sp.id)
    st["site"] = sp.site.site
    st["origin"] = {"E": sp.site.origin.E, "N": sp.site.origin.N}
    bufs = res.buffers()
    st["stations_identical"] = _assert_stations(sp, bufs)
    st["buffers"] = {name: b.stats() for name, b in bufs.items()}
    st["validate"] = {name: b.validate() for name, b in bufs.items()}
    ov = {}
    for side, name in ((S.LEFT, "left"), (S.RIGHT, "right")):
        e = res.edge.get(side)
        if res.road is not None and e is not None and "kerb" in e.group_names:
            spec = sp.side_spec[side]
            m = measure_lateral_overlap(res.road, e, side, tuck_depth=float(spec.tuck_depth.min()))
            ov[name] = {"min": round(m["min_m"], 9), "max": round(m["max_m"], 9)}
    st["overlap"] = ov
    if ov:
        st["overlap_min"] = round(min(v["min"] for v in ov.values()), 9)
        st["overlap_max"] = round(max(v["max"] for v in ov.values()), 9)
    else:
        st["overlap_min"] = None
        st["overlap_max"] = None
    st["marking_strips"] = int(getattr(res.road, "marking_strips", 0)) if res.road is not None else 0
    counts: Dict[str, int] = {}
    for i in res.instances:
        counts[i.kind] = counts.get(i.kind, 0) + 1
    st["instances"] = counts
    st["terrain"] = terrain.describe() if terrain is not None else None
    probes = [float(q) for q in np.arange(0.0, sp.length + 1e-9, 10.0)]
    st["z_ref_probe"] = {("%g" % q): round(float(np.interp(q, sp.s, sp.z_ref)), 4) for q in probes}
    st["z_raw_probe"] = {("%g" % q): (round(float(np.interp(q, sp.s, sp.z_raw)), 4) if np.isfinite(np.interp(q, sp.s, sp.z_raw)) else None) for q in probes}
    st["edge_offset_probe"] = {("%g" % q): [round(float(np.interp(q, sp.s, sp.edge_offset(S.LEFT))), 4),
                                            round(float(np.interp(q, sp.s, sp.edge_offset(S.RIGHT))), 4)] for q in probes}
    st["overlay_points"] = int(len(res.overlay)) if res.overlay is not None else 0
    st["sampling"] = {k: v for k, v in sp.sampling.to_dict().items()}
    st["mandatory_stations"] = [round(float(x), 6) for x in sp.mandatory_set]
    return st


def build_all(site: S.Site, terrain: Optional[Heightfield], only_layer: Optional[str] = None) -> Dict[str, BuildResult]:
    out = {}
    for sdef in site.splines:
        if only_layer is not None and sdef.source.layer != only_layer:
            continue
        out[sdef.id] = build_spline(site, sdef.id, terrain)
    return out


def _json_dump(obj, path: str) -> None:
    with open(path, "w", encoding="utf-8", newline="\n") as fh:
        json.dump(obj, fh, indent=1, sort_keys=False, allow_nan=True)
        fh.write("\n")


def write_result(res: BuildResult, out_root: str) -> str:
    d = os.path.join(out_root, safe_dir_name(res.spline.id))
    os.makedirs(d, exist_ok=True)
    for name, buf in res.buffers().items():
        buf.save_npz(os.path.join(d, name + ".npz"))
    _json_dump([i.to_json() for i in res.instances], os.path.join(d, "instances.json"))
    _json_dump({"spline_id": res.spline.id, "lift_m": OVERLAY_LIFT_M,
                "pts": [[round(float(x), 6) for x in p] for p in res.overlay]} if res.overlay is not None else None,
               os.path.join(d, "overlay.json"))
    _json_dump(res.stats, os.path.join(d, "stats.json"))
    sp = res.spline
    save_npz_dict(os.path.join(d, "spline.npz"), {"s": sp.s, "xy": sp.xy, "z_raw": sp.z_raw, "z_ref": sp.z_ref,
                  "bank_deg": sp.bank_deg, "width": sp.width, "edge_offset_left": sp.edge_offset(S.LEFT),
                  "edge_offset_right": sp.edge_offset(S.RIGHT), "mandatory": sp.mandatory})
    return d


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description="Build every spline of a Streetscape document (numpy only).")
    ap.add_argument("--site", required=True)
    ap.add_argument("--terrain", required=False, default=None, help="landscape dir or step-05 terrain dir")
    ap.add_argument("--out", required=True)
    ap.add_argument("--only-layer", default=None, choices=["roads", "rail", "barriers", "authored"])
    ap.add_argument("--fail-on-validate", action="store_true", help="exit 2 when any MeshBuffer.validate() message exists")
    ap.add_argument("--export-terrain-npz", default=None, help="write the loaded heightfield (tiles under the site) as an .npz cache for Blender")
    ap.add_argument("--terrain-tiles", default=None, help="comma list i_j,i_j of step-05 tiles to read (default: the tiles under the splines +- 1)")
    args = ap.parse_args(argv)
    site = load_site(args.site)
    terrain = None
    if args.terrain:
        if os.path.isdir(args.terrain) and os.path.isfile(os.path.join(args.terrain, "terrain_manifest.json")):
            tiles = tiles_under_site(site, args.terrain) if args.terrain_tiles is None else [tuple(int(v) for v in t.split("_")) for t in args.terrain_tiles.split(",")]
            terrain = Heightfield.from_step05_dir(args.terrain, tiles=tiles)
        else:
            terrain = load_terrain(args.terrain)
        if args.export_terrain_npz:
            terrain.save_npz(args.export_terrain_npz)
            print("terrain cache written: %s (%d tiles)" % (args.export_terrain_npz, len(terrain.tiles)))
    results = build_all(site, terrain, args.only_layer)
    os.makedirs(args.out, exist_ok=True)
    problems = 0
    index = {}
    for sid, res in results.items():
        d = write_result(res, args.out)
        index[sid] = os.path.relpath(d, args.out)
        msgs = {k: v for k, v in res.stats["validate"].items() if v}
        if msgs:
            problems += 1
            print("VALIDATE %s: %s" % (sid, msgs))
        st = res.stats
        print("%s: L=%.3f N=%d overlap=%s/%s strips=%d buffers=%s instances=%s" % (
            sid, st["length_m"], st["n_samples"], st["overlap_min"], st["overlap_max"], st["marking_strips"],
            {k: (v["verts"], v["tris"]) for k, v in st["buffers"].items()}, st["instances"]))
    _json_dump({"site": os.path.abspath(args.site), "terrain": (terrain.describe() if terrain else None),
                "splines": index}, os.path.join(args.out, "index.json"))
    if problems and args.fail_on_validate:
        return 2
    return 0


if __name__ == "__main__":
    sys.exit(main())
