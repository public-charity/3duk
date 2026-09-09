"""The one cross-section sweep (DESIGN.md 4, geometry.md 5.5).

A ``Section`` is a list of ``SectionPoint`` (o, h, material, v, smooth) in the (o, h) plane of the
station frame: o along the banked normal n (outward for side sweeps, signed for centre sweeps), h along
the banked up vector b.  Orientation rule: walking the points in listed order with o to the right and h
up, the EXPOSED surface is on the LEFT (open sections list the visible surface so; closed sections are
listed clockwise).  The winding of every quad is nevertheless decided geometrically from that rule,
so one routine is correct for both sides and for centre sweeps.

Rows: a hard (smooth=False) interior point of an open section, or any hard point of a closed one, is
emitted twice so the two edges get separate normals; R = P + #hard_interior (open), P + #hard (closed).
Quads split on the V(i,k)-V(i+1,k+1) diagonal; triangles below 1e-10 m^2 are skipped.  Caps close every
run of emitted quads with the ring's own vertices (watertight).  UV u = s, v = SectionPoint.v.

CAP GROUP CONVENTION (normative, and the C++ ``FStreetSweep::Sweep`` does the same): an end cap is one
polygon spanning the WHOLE section ring, so it cannot belong to one section edge's group.  Every cap
triangle is filed under ``grp_ids[0]`` -- the group of section edge 0.  On the kerb+pavement section that
puts the pavement rows' share of the two end caps under the ``kerb`` group, so ``stats.json``'s per-group
vertex/triangle split is approximate at a mask-run end (2 stations of 116 on the test stretch) and exact
everywhere else.  This is a CONVENTION, not an accident: ``per_group`` is a Blender-vs-Unreal parity key,
so the two implementations must file caps identically.  Changing it (e.g. to a dedicated "cap" group, or
splitting the cap by each ear-clipped triangle's source edge) means changing both sides and re-freezing
``renders/trinity_square.stats.json`` in the same commit.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import List, Optional, Sequence, Tuple, Union

import numpy as np

from .mesh import MeshBuffer, triangulate_polygon_2d, polygon_area_2d
from .spline import Frames


@dataclass(frozen=True)
class SectionPoint:
    o: float
    h: float
    mat: str
    v: float
    smooth: bool = False


@dataclass(frozen=True)
class Section:
    points: Tuple[SectionPoint, ...]
    closed: bool = False

    @property
    def n_points(self) -> int:
        return len(self.points)

    @property
    def n_edges(self) -> int:
        return len(self.points) if self.closed else len(self.points) - 1


def open_section(pts: Sequence[Tuple[float, float, str]], smooth: Union[bool, Sequence[bool]] = False,
                 v: Optional[Sequence[float]] = None) -> Section:
    """Convenience: pts = [(o, h, mat)], v defaults to cumulative section length."""
    if v is None:
        v = [0.0]
        for (o0, h0, _), (o1, h1, _) in zip(pts[:-1], pts[1:]):
            v.append(v[-1] + float(np.hypot(o1 - o0, h1 - h0)))
    if isinstance(smooth, bool):
        smooth = [smooth] * len(pts)
    return Section(tuple(SectionPoint(float(o), float(h), m, float(vv), bool(sm)) for (o, h, m), vv, sm in zip(pts, v, smooth)), False)


def closed_section(pts: Sequence[Tuple[float, float, str]], smooth: Union[bool, Sequence[bool]] = False,
                   v: Optional[Sequence[float]] = None) -> Section:
    if v is None:
        v = [0.0]
        for (o0, h0, _), (o1, h1, _) in zip(pts[:-1], pts[1:]):
            v.append(v[-1] + float(np.hypot(o1 - o0, h1 - h0)))
    if isinstance(smooth, bool):
        smooth = [smooth] * len(pts)
    return Section(tuple(SectionPoint(float(o), float(h), m, float(vv), bool(sm)) for (o, h, m), vv, sm in zip(pts, v, smooth)), True)


@dataclass
class SweepResult:
    vidx: np.ndarray            # (N, R) vertex ids, -1 where not emitted
    row_point: np.ndarray       # (R,) section point index of each row
    edge_rows: np.ndarray       # (E, 2) [start row, end row] of each section edge
    tri_range: Tuple[int, int]
    n_quads: int
    runs: List[Tuple[int, int]]  # station index ranges [i0, i1] of the emitted runs


def _rows(section: Section):
    """Row layout: returns (row_point (R,), edge_rows (E, 2))."""
    P = section.n_points
    before = np.zeros(P, dtype=np.int64)   # row used by the edge arriving at the point
    after = np.zeros(P, dtype=np.int64)    # row used by the edge leaving the point
    row_point = []
    r = 0
    for k, pt in enumerate(section.points):
        two = (not pt.smooth) and (section.closed or (0 < k < P - 1))
        before[k] = r
        row_point.append(k)
        r += 1
        if two:
            after[k] = r
            row_point.append(k)
            r += 1
        else:
            after[k] = before[k]
    E = section.n_edges
    edge_rows = np.zeros((E, 2), dtype=np.int64)
    for k in range(E):
        k1 = (k + 1) % P
        edge_rows[k] = (after[k], before[k1])
    return np.array(row_point, dtype=np.int64), edge_rows


def sweep(buf: MeshBuffer, section: Section, frames: Frames, *,
          side: int = +1,
          lateral=0.0, height=0.0,
          point_o: Optional[np.ndarray] = None, point_h: Optional[np.ndarray] = None,
          mask: Optional[np.ndarray] = None, quad_mask: Optional[np.ndarray] = None,
          cap_start: bool = True, cap_end: bool = True, cap_mat: Optional[str] = None,
          group: Union[str, Sequence[str]] = "",
          edge_mat: Optional[Sequence[str]] = None, edge_mat_station: Optional[np.ndarray] = None,
          two_sided: bool = False) -> SweepResult:
    """Sweep ``section`` along ``frames``.

    lateral / height: (N,) or scalar offsets of the section origin (outward and up).
    point_o / point_h: (N, P) per-station overrides of every point's o / h.
    mask: (N,) bool station present; quad_mask: (N-1,) bool quad (i, i+1) emitted.
    group: one name for every triangle, or one name per section edge (len E).
    edge_mat: material per section edge (default: the edge's start point mat);
    edge_mat_station: (N, E) object array of material names per station and edge (quad (i, i+1) uses row i).
    """
    N = len(frames)
    P = section.n_points
    E = section.n_edges
    pts = section.points
    O = np.broadcast_to(np.array([p.o for p in pts], dtype=np.float64), (N, P)) if point_o is None else np.asarray(point_o, dtype=np.float64)
    Hh = np.broadcast_to(np.array([p.h for p in pts], dtype=np.float64), (N, P)) if point_h is None else np.asarray(point_h, dtype=np.float64)
    lat = np.broadcast_to(np.asarray(lateral, dtype=np.float64), (N,))
    hgt = np.broadcast_to(np.asarray(height, dtype=np.float64), (N,))
    m = np.ones(N, dtype=bool) if mask is None else np.asarray(mask, dtype=bool)
    qm = np.ones(max(N - 1, 0), dtype=bool) if quad_mask is None else np.asarray(quad_mask, dtype=bool)
    quad_ok = m[:-1] & m[1:] & qm if N > 1 else np.zeros(0, dtype=bool)
    # a station is emitted when it takes part in a quad (isolated masked stations emit nothing)
    v_ok = np.zeros(N, dtype=bool)
    v_ok[:-1] |= quad_ok
    v_ok[1:] |= quad_ok

    row_point, edge_rows = _rows(section)
    R = len(row_point)
    vidx = np.full((N, R), -1, dtype=np.int64)
    tri0 = len(buf.f)
    st_idx = np.where(v_ok)[0]
    if len(st_idx) == 0:
        return SweepResult(vidx, row_point, edge_rows, (tri0, tri0), 0, [])

    # -- vertices ------------------------------------------------------------------------------
    o_rows = O[:, row_point]                              # (N, R)
    h_rows = Hh[:, row_point]
    d_all = side * (lat[:, None] + o_rows)                # signed lateral (N, R)
    hh_all = hgt[:, None] + h_rows
    Vall = (frames.p[:, None, :] + d_all[:, :, None] * frames.n[:, None, :] + hh_all[:, :, None] * frames.b[:, None, :])
    vv = np.array([pts[k].v for k in row_point], dtype=np.float64)
    Vsel = Vall[st_idx].reshape(-1, 3)
    uv = np.stack([np.repeat(frames.s[st_idx], R), np.tile(vv, len(st_idx))], axis=1)
    s_attr = np.repeat(frames.s[st_idx], R)
    d_attr = d_all[st_idx].reshape(-1)
    h_attr = hh_all[st_idx].reshape(-1)
    first = buf.append_vertices(Vsel, uv, s_attr, d_attr, h_attr)
    vidx[st_idx] = (first + np.arange(len(st_idx) * R)).reshape(len(st_idx), R)

    # -- materials / groups per edge ---------------------------------------------------------
    if isinstance(group, str):
        grp_ids = [buf.group_id(group)] * E
    else:
        grp_ids = [buf.group_id(g) for g in group]
        assert len(grp_ids) == E, "group list must have one entry per section edge"
    if edge_mat is None:
        edge_mat = [pts[k].mat for k in range(E)]
    mat_default = [buf.material_id(mname) for mname in edge_mat]
    if two_sided:
        for mname in set(edge_mat):
            buf.two_sided.add(mname)
    mat_station = None
    if edge_mat_station is not None:
        ems = np.asarray(edge_mat_station, dtype=object)
        names = sorted(set(str(x) for x in ems.ravel()))
        lut = {nm: buf.material_id(nm) for nm in names}
        mat_station = np.vectorize(lambda x: lut[str(x)], otypes=[np.int32])(ems)
        if two_sided:
            for nm in names:
                buf.two_sided.add(nm)

    # -- quads ---------------------------------------------------------------------------------
    qi = np.where(quad_ok)[0]
    n_quads = 0
    if len(qi):
        for k in range(E):
            r0, r1 = edge_rows[k]
            a = vidx[qi, r0]
            b = vidx[qi + 1, r0]
            c = vidx[qi + 1, r1]
            d = vidx[qi, r1]
            ok = (a >= 0) & (b >= 0) & (c >= 0) & (d >= 0)
            if not ok.any():
                continue
            a, b, c, d, q = a[ok], b[ok], c[ok], d[ok], qi[ok]
            T = np.concatenate([np.stack([a, b, c], axis=1), np.stack([a, c, d], axis=1)])
            # exposed normal from the section edge direction at station i, mapped to world
            k1 = (k + 1) % P
            do = O[q, k1] - O[q, k]
            dh = Hh[q, k1] - Hh[q, k]
            want = side * (-dh)[:, None] * frames.n[q] + do[:, None] * frames.b[q]
            want = np.concatenate([want, want])
            Pa, Pb, Pc = buf.v[T[:, 0]], buf.v[T[:, 1]], buf.v[T[:, 2]]
            fn = np.cross(Pb - Pa, Pc - Pa)
            flip = np.sum(fn * want, axis=1) < 0
            T[flip] = T[flip][:, [0, 2, 1]]
            area = 0.5 * np.linalg.norm(fn, axis=1)
            keep = area >= 1e-10
            if mat_station is not None:
                mids = np.concatenate([mat_station[q, k], mat_station[q, k]])
            else:
                mids = np.full(len(T), mat_default[k], dtype=np.int32)
            buf.append_triangles(T[keep], mids[keep], grp_ids[k])
            n_quads += int(ok.sum())

    # -- caps ----------------------------------------------------------------------------------
    runs: List[Tuple[int, int]] = []
    if len(qi):
        start = int(qi[0])
        prev = start
        for i in qi[1:]:
            if i != prev + 1:
                runs.append((start, prev + 1))
                start = int(i)
            prev = int(i)
        runs.append((start, prev + 1))
    if (cap_start or cap_end) and runs:
        cap_mid = buf.material_id(cap_mat if cap_mat is not None else pts[0].mat)
        cap_gid = grp_ids[0]      # module docstring, "CAP GROUP CONVENTION": mirrored by FStreetSweep::Sweep
        # ring: one row per point (the 'before' row; positions coincide for hard points)
        ring_rows = np.array([int(np.where(row_point == k)[0][0]) for k in range(P)], dtype=np.int64)
        for (i0, i1) in runs:
            for i, is_start in ((i0, True), (i1, False)):
                if (is_start and not cap_start) or ((not is_start) and not cap_end):
                    continue
                ring = vidx[i, ring_rows]
                if (ring < 0).any():
                    continue
                pts2 = np.stack([O[i], Hh[i]], axis=1)
                # drop consecutive coincident points (collapsed lip) for a clean polygon
                keep = np.ones(P, dtype=bool)
                for k in range(1, P):
                    if np.hypot(*(pts2[k] - pts2[k - 1])) < 1e-12:
                        keep[k] = False
                if keep.sum() >= 3 and np.hypot(*(pts2[keep][-1] - pts2[keep][0])) < 1e-12:
                    keep[np.where(keep)[0][-1]] = False
                if keep.sum() < 3 or abs(polygon_area_2d(pts2[keep])) < 1e-12:
                    continue
                normal_hint = -frames.t_h[i] if is_start else frames.t_h[i]
                tris = triangulate_polygon_2d(pts2[keep])
                ring_k = ring[keep]
                T = ring_k[tris]
                Pa, Pb, Pc = buf.v[T[:, 0]], buf.v[T[:, 1]], buf.v[T[:, 2]]
                fn = np.cross(Pb - Pa, Pc - Pa)
                flip = (fn @ normal_hint) < 0
                T[flip] = T[flip][:, [0, 2, 1]]
                area = 0.5 * np.linalg.norm(fn, axis=1)
                buf.append_triangles(T[area >= 1e-10], cap_mid, cap_gid)
    return SweepResult(vidx, row_point, edge_rows, (tri0, len(buf.f)), n_quads, runs)


def runs_to_quad_mask(s: np.ndarray, intervals: Sequence[Tuple[float, float]]) -> np.ndarray:
    """(N-1,) quad mask: quad (i, i+1) emitted when it lies inside one of the closed intervals."""
    s = np.asarray(s, dtype=np.float64)
    qm = np.zeros(max(len(s) - 1, 0), dtype=bool)
    for a, b in intervals:
        qm |= (s[:-1] >= a - 1e-9) & (s[1:] <= b + 1e-9)
    return qm
