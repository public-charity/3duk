"""Build entry points (geometry.md 5.12): build_spline / build_all, the deterministic writer and the CLI.

  python -m streetscape.build --site X.json --terrain DIR --out DIR [--only-layer roads|rail|barriers]
      [--spline <id>[,<id>...]]

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
from .spline import JunctionPlan, Spline, fill_nan_along
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
    junctions: Dict[str, dict] = field(default_factory=dict)

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
    """DESIGN.md 5 rule 2, stated exactly as the code enforces it.

    The ``road`` buffer's stations must EQUAL ``spline.s[spline.active]`` (``np.array_equal``):
    Renderer A sweeps the whole ACTIVE spline -- the whole spline when it stands in no junction, and
    exactly the trimmed run when it does -- so any missing or extra station is a bug.  The junction
    patch and the kerb corners are excluded by group prefix (``mesh.NON_STATION_PREFIXES``) because
    they are not swept along this spline at all.  Every other buffer (``edge_*``, ``hedge_*``)
    is masked -- a barrier, an embankment or a hedge legitimately covers a sub-range -- so the rule there
    is containment: every station a masked buffer carries is a spline station (``np.isin``), never an
    interpolated one.  Marking strips carry interpolated dash-end stations and are excluded by
    ``station_values``.  Neither test tolerates a resampled or drifted station."""
    out = {}
    active_s = spline.s[spline.active]
    for name, buf in buffers.items():
        st = station_values(buf)
        same = bool(np.array_equal(st, active_s)) if name in ("road",) else bool(np.all(np.isin(st, spline.s)))
        if name == "road" and spline.kind is not None and not same:
            raise AssertionError("%s: %s stations differ from the spline stations" % (spline.id, name))
        if not same:
            raise AssertionError("%s: %s carries stations that are not spline stations" % (spline.id, name))
        out[name] = True
    return out


def build_spline(site: S.Site, spline_id: str, terrain: Optional[Heightfield], trim=None,
                 stats: bool = True) -> BuildResult:
    from .road import build_road
    from .edge import build_edge
    from .hedge import build_hedge
    sdef = site.spline(spline_id)
    sp = Spline(sdef, site, terrain, trim=trim)
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
    if stats:
        res.stats = compute_stats(res, terrain_doc)
    return res


def finish_result(res: BuildResult, terrain: Optional[Heightfield], normals: bool = True) -> BuildResult:
    """Normals + stats after the junction geometry has been merged into the buffers."""
    for b in res.buffers().values():
        if normals or len(b.vn) != len(b.v):
            b.compute_normals()
    res.stats = compute_stats(res, terrain)
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
    st["junctions"] = dict(res.junctions)
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


def build_all(site: S.Site, terrain: Optional[Heightfield], only_layer: Optional[str] = None,
              only_ids=None, plan: Optional[JunctionPlan] = None,
              junctions: bool = True) -> Dict[str, BuildResult]:
    """Every spline of the document, optionally filtered by ``source.layer`` and/or by spline id
    (``only_ids``: an iterable, used to pick one real way out of a 300-spline adapter tile).

    JUNCTIONS.  The plan is solved FIRST, in plan geometry only (``JunctionPlan``), so every spline is
    built exactly once with its trim already known.  The patches and the kerb corners are then merged
    into the OWNING spline's own road and edge buffers -- no fourth renderer, no fourth buffer, no new
    material -- and the owner's stats are recomputed so the counts in ``stats.json`` include them.
    ``junctions=False`` gives the untrimmed geometry (what ``conform.py`` burns the corridor from: the
    ground under a junction must still be conformed, and the corridor that covers it comes from the
    UNTRIMMED arms)."""
    from .road import build_junction_patch
    from .edge import build_junction_corners
    if junctions and plan is None:
        plan = JunctionPlan(site)
    if not junctions:
        plan = None
    want = None if only_ids is None else set(only_ids)
    terrain_doc = terrain.rebased(site.origin.E, site.origin.N) if terrain is not None else None
    out = {}
    for sdef in site.splines:
        if only_layer is not None and sdef.source.layer != only_layer:
            continue
        if want is not None and sdef.id not in want:
            continue
        out[sdef.id] = build_spline(site, sdef.id, terrain,
                                    trim=(plan.trim_for(sdef.id) if plan is not None else None),
                                    stats=(plan is None))
    if want is not None and not out:
        raise KeyError("no spline of %s matches --spline %s" % (site.site, sorted(want)))
    if plan is None:
        return out
    splines = {sid: r.spline for sid, r in out.items()}
    touched = set()
    for jid in sorted(plan.arms):
        owner = plan.owner(jid)
        res = out.get(owner)
        if res is None or any(a.spline_id not in splines for a in plan.arms[jid]):
            continue                       # a filtered build: the junction belongs to the full one
        if res.road is None:
            res.road = MeshBuffer()
        info = build_junction_patch(plan, jid, splines, res.road)
        eb = res.edge.get(S.LEFT)
        if eb is None:
            eb = MeshBuffer()
            res.edge[S.LEFT] = eb
        info["corner"] = build_junction_corners(plan, jid, splines, eb)
        res.junctions[jid] = info
        touched.add(owner)
    for sid, res in out.items():
        if res.road is not None and not len(res.road.v):
            res.road = None
        for side in (S.LEFT, S.RIGHT):
            b = res.edge.get(side)
            if b is not None and not len(b.v):
                res.edge[side] = None
        finish_result(res, terrain_doc, normals=(sid in touched))
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
    ap.add_argument("--site", required=False)
    ap.add_argument("--junction-audit", default=None,
                    help="directory of site_*.json to build and measure (SCHEMA.md 4.18); with --out <json>")
    ap.add_argument("--clearance-landscape", default=None,
                    help="landscape dir sampled under every junction patch vertex (the CONFORMED one)")
    ap.add_argument("--terrain", required=False, default=None, help="landscape dir or step-05 terrain dir")
    ap.add_argument("--out", required=True)
    ap.add_argument("--only-layer", default=None, choices=["roads", "rail", "barriers", "authored"])
    ap.add_argument("--spline", default=None, help="comma-separated spline id(s) to build (default: all)")
    ap.add_argument("--fail-on-validate", action="store_true", help="exit 2 when any MeshBuffer.validate() message exists")
    ap.add_argument("--export-terrain-npz", default=None, help="write the loaded heightfield (tiles under the site) as an .npz cache for Blender")
    ap.add_argument("--terrain-tiles", default=None, help="comma list i_j,i_j of step-05 tiles to read (default: the tiles under the splines +- 1)")
    args = ap.parse_args(argv)
    if args.junction_audit:
        return _audit_main(args)
    if not args.site:
        ap.error("--site is required unless --junction-audit is given")
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
    results = build_all(site, terrain, args.only_layer,
                        [v for v in args.spline.split(",") if v] if args.spline else None)
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


# --------------------------------------------------------------------------------------------
# junction audit: the measurement that proves there is no crack (DESIGN.md 5, SCHEMA.md 4.18)
# --------------------------------------------------------------------------------------------

def _ring_at(buf: MeshBuffer, s: float, groups_prefix, tol: float = 1e-12) -> np.ndarray:
    """Distinct vertex positions of ``buf`` at station ``s`` within the named group prefixes."""
    if buf is None or not len(buf.v):
        return np.zeros((0, 3))
    pre = tuple(groups_prefix)
    ids = [i for i, n in enumerate(buf.group_names) if n.startswith(pre)]
    if not ids:
        return np.zeros((0, 3))
    vi = np.unique(buf.f[np.isin(buf.grp, ids)])
    vi = vi[np.abs(buf.vs[vi] - s) <= 1e-9]
    if not len(vi):
        return np.zeros((0, 3))
    from .mesh import distinct_positions
    return distinct_positions(buf.v[vi], tol)


def _max_nearest(A: np.ndarray, B: np.ndarray) -> float:
    """max over a in A of min over b in B of |a - b| (0.0 when A is empty, inf when B is)."""
    if not len(A):
        return 0.0
    if not len(B):
        return float("inf")
    d = np.linalg.norm(A[:, None, :] - B[None, :, :], axis=2)
    return float(d.min(axis=1).max())


def junction_audit(plan, results: Dict[str, BuildResult]) -> dict:
    """Measure, per junction, the worst distance from a point the CARRIAGEWAY (or the KERB) ends on to
    the nearest point the PATCH (or the CORNER) starts on.

    This is the no-crack proof and it is a measurement, not an assertion of construction: the ribbon's
    end ring is read back out of Renderer A's finished buffer and the patch's boundary out of the
    owning spline's finished buffer, in world coordinates, after everything has been built.  A crack of
    w metres anywhere along an arm's end edge shows up here as a nearest-neighbour distance of at least
    w/2 for one of the ribbon's own row vertices."""
    from .spline import arm_station_index
    rep = {"junctions": 0, "patches": 0, "non_monotone": 0, "corners": 0,
           "worst_patch_gap_m": 0.0, "worst_corner_gap_m": 0.0, "worst_overlap_err_m": 0.0,
           "worst_patch_gap_at": None, "worst_corner_gap_at": None, "patch_tris": 0, "patch_verts": 0,
           "corner_tris": 0, "patch_area_m2": 0.0, "patch_overlap_area_m2": 0.0,
           "worst_patch_overlap_area_m2": 0.0}
    for jid in sorted(plan.arms):
        owner = plan.owner(jid)
        res = results.get(owner)
        if res is None or jid not in res.junctions:
            continue
        info = res.junctions[jid]
        rep["junctions"] += 1
        if not info.get("built"):
            continue
        rep["patches"] += 1
        rep["patch_tris"] += int(info.get("tris", 0))
        rep["patch_verts"] += int(info.get("verts", 0))
        rep["corners"] += int(info.get("corner", {}).get("corners", 0))
        rep["corner_tris"] += int(info.get("corner", {}).get("tris", 0))
        if not info.get("monotone", True):
            rep["non_monotone"] += 1
        rep["patch_area_m2"] += float(info.get("area_m2", 0.0))
        rep["patch_overlap_area_m2"] += float(info.get("overlap_area_m2", 0.0))
        rep["worst_patch_overlap_area_m2"] = max(rep["worst_patch_overlap_area_m2"],
                                                 float(info.get("overlap_area_m2", 0.0)))
        patch = _ring_at_group(res.road, "junction:%s" % jid)
        corner = _ring_at_group(res.edge.get(S.LEFT), "corner_")
        for a in plan.arms[jid]:
            arm_res = results.get(a.spline_id)
            if arm_res is None or arm_res.road is None:
                continue
            sp = arm_res.spline
            i = arm_station_index(sp, a.end)
            ribbon = _ring_at(arm_res.road, float(sp.s[i]), ("road", "skirt_"))
            g = _max_nearest(ribbon, patch)
            if g > rep["worst_patch_gap_m"]:
                rep["worst_patch_gap_m"] = g
                rep["worst_patch_gap_at"] = [jid, a.spline_id, a.end]
            for side in (S.LEFT, S.RIGHT):
                eb = arm_res.edge.get(side)
                kerb = _ring_at(eb, float(sp.s[i]), ("kerb", "pavement"))
                if not len(kerb) or not len(corner):
                    continue
                g = _max_nearest(kerb, corner)
                if g > rep["worst_corner_gap_m"]:
                    rep["worst_corner_gap_m"] = g
                    rep["worst_corner_gap_at"] = [jid, a.spline_id, a.end, S.SIDE_NAME[side]]
    return rep


def _ring_at_group(buf: Optional[MeshBuffer], prefix: str, tol: float = 1e-12) -> np.ndarray:
    if buf is None or not len(buf.v):
        return np.zeros((0, 3))
    ids = [i for i, n in enumerate(buf.group_names) if n.startswith(prefix)]
    if not ids:
        return np.zeros((0, 3))
    vi = np.unique(buf.f[np.isin(buf.grp, ids)])
    from .mesh import distinct_positions
    return distinct_positions(buf.v[vi], tol)


def junction_audit_site(site_path: str, terrain: Optional[Heightfield],
                        clearance_terrain: Optional[Heightfield] = None) -> dict:
    """Build one document with its junctions and measure it.  ``clearance_terrain`` (the CONFORMED
    landscape) is sampled under every patch vertex: the patch is new surface that the corridor conform
    never saw, so whether the ground comes through it is a number, not an assumption."""
    from .io_json import load_site
    site = load_site(site_path)
    plan = JunctionPlan(site)
    results = build_all(site, terrain, plan=plan)
    rep = junction_audit(plan, results)
    rep["plan"] = dict(plan.stats)
    rep["notes"] = list(plan.notes[:20])
    trims = [t for v in plan.trims.values() for t in v if t > 0.0]
    rep["trim_m"] = {"n": len(trims),
                     "max": (max(trims) if trims else 0.0),
                     "mean": (float(np.mean(trims)) if trims else 0.0),
                     "p50": (float(np.percentile(trims, 50)) if trims else 0.0),
                     "p95": (float(np.percentile(trims, 95)) if trims else 0.0)}
    rep["trim_total_m"] = float(sum(trims))
    if clearance_terrain is not None:
        ct = clearance_terrain.rebased(site.origin.E, site.origin.N)
        worst = float("inf")
        worst_at = None
        n = 0
        below = 0
        for sid, res in results.items():
            if res.road is None or not res.junctions:
                continue
            ids = [i for i, g in enumerate(res.road.group_names) if g.startswith("junction:")]
            if not ids:
                continue
            vi = np.unique(res.road.f[np.isin(res.road.grp, ids)])
            V = res.road.v[vi]
            z = ct.sample(V[:, 0], V[:, 1])
            ok = np.isfinite(z)
            if not ok.any():
                continue
            clear = V[ok, 2] - z[ok]
            n += int(ok.sum())
            below += int((clear < 0.0).sum())
            k = int(np.argmin(clear))
            if float(clear[k]) < worst:
                worst = float(clear[k])
                worst_at = [sid, float(V[ok][k, 0]), float(V[ok][k, 1])]
        rep["patch_clearance"] = {"n": n, "below_ground": below,
                                  "min_m": (None if worst == float("inf") else worst),
                                  "at": worst_at}
    return rep


def _audit_main(args) -> int:
    import glob
    import time
    t0 = time.time()
    terrain = load_terrain(args.terrain) if args.terrain else None
    clear = load_terrain(args.clearance_landscape) if args.clearance_landscape else None
    files = sorted(glob.glob(os.path.join(args.junction_audit, "site_*.json")))
    total = {"documents": 0, "junctions": 0, "patches": 0, "non_monotone": 0, "corners": 0,
             "patch_tris": 0, "patch_verts": 0, "corner_tris": 0, "patch_area_m2": 0.0,
             "patch_overlap_area_m2": 0.0, "splines_trimmed": 0, "splines_degenerate": 0,
             "splines_untrimmable": 0, "arms": 0, "arms_dropped": 0, "arms_unseparable": 0,
             "junctions_skipped_arms": 0, "junctions_skipped_kind": 0, "trim_total_m": 0.0,
             "trimmed_ends": 0}
    worst = {"patch_gap_m": 0.0, "patch_gap_at": None, "corner_gap_m": 0.0, "corner_gap_at": None,
             "patch_overlap_area_m2": 0.0, "trim_m": 0.0,
             "patch_clearance_min_m": None, "patch_clearance_at": None, "patch_below_ground": 0,
             "patch_clearance_n": 0}
    per_doc = {}
    for k, f in enumerate(files):
        rep = junction_audit_site(f, terrain, clear)
        name = os.path.splitext(os.path.basename(f))[0]
        per_doc[name] = rep
        total["documents"] += 1
        for key in ("junctions", "patches", "non_monotone", "corners", "patch_tris", "patch_verts",
                    "corner_tris", "patch_area_m2", "patch_overlap_area_m2"):
            total[key] += rep[key]
        for key in ("splines_trimmed", "splines_degenerate", "splines_untrimmable", "arms",
                    "arms_dropped", "arms_unseparable", "junctions_skipped_arms",
                    "junctions_skipped_kind"):
            total[key] += rep["plan"][key]
        total["trim_total_m"] += rep["trim_total_m"]
        total["trimmed_ends"] += rep["trim_m"]["n"]
        if rep["worst_patch_gap_m"] > worst["patch_gap_m"]:
            worst["patch_gap_m"], worst["patch_gap_at"] = rep["worst_patch_gap_m"], rep["worst_patch_gap_at"]
        if rep["worst_corner_gap_m"] > worst["corner_gap_m"]:
            worst["corner_gap_m"], worst["corner_gap_at"] = rep["worst_corner_gap_m"], rep["worst_corner_gap_at"]
        worst["patch_overlap_area_m2"] = max(worst["patch_overlap_area_m2"], rep["worst_patch_overlap_area_m2"])
        worst["trim_m"] = max(worst["trim_m"], rep["trim_m"]["max"])
        pc = rep.get("patch_clearance")
        if pc and pc["min_m"] is not None:
            worst["patch_clearance_n"] += pc["n"]
            worst["patch_below_ground"] += pc["below_ground"]
            if worst["patch_clearance_min_m"] is None or pc["min_m"] < worst["patch_clearance_min_m"]:
                worst["patch_clearance_min_m"], worst["patch_clearance_at"] = pc["min_m"], pc["at"]
        print("[%3d/%d] %-16s junctions=%-3d patches=%-3d corners=%-3d trimmed=%-3d worst_gap=%.3g"
              % (k + 1, len(files), name, rep["junctions"], rep["patches"], rep["corners"],
                 rep["plan"]["splines_trimmed"], rep["worst_patch_gap_m"]), flush=True)
    total["wall_clock_s"] = round(time.time() - t0, 1)
    out = {"totals": total, "worst": worst, "per_document": per_doc}
    _json_dump(out, args.out)
    print("JUNCTION_AUDIT %s" % json.dumps({"totals": total, "worst": worst}, sort_keys=True))
    return 0
