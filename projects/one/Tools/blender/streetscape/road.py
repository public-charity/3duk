"""Renderer A: the road ribbon with camber, skirts and lifted marking strips (DESIGN.md 4.1,
SCHEMA.md 3.7; geometry.md 5.7).  Rail is a profile kind: ``build_road`` dispatches to
``rail.build_rail`` when ``spline.kind == "rail"`` and nothing else here knows about rails.

Groups: ``road``, ``skirt_left``, ``skirt_right``, ``marking:<id>``, ``junction:<id>``.  No
marking-specific identifiers exist in this file: a double yellow, a single yellow and a centre dash are
rows of profile data.

A JUNCTION IS ROAD SURFACE, so filling one is this renderer's job and not a fourth renderer's (BRIEF
1.1, "THREE RENDERERS ONLY").  ``build_road`` stops the ribbon at the shared trim; ``build_junction_patch``
fills what it leaves, into the same buffer, with the same material, under the group ``junction:<id>``.
The TRIM itself is one level lower, in spline.py, because Renderer B has to stop at the same place.
"""
from __future__ import annotations

import math
from typing import List, Optional, Tuple

import numpy as np

from . import schema as S
from .instance import Instance
from .mesh import MeshBuffer
from .spline import (JunctionPlan, Spline, corner_curve, corner_frames, resolve_arm_frames)
from .sweep import Section, SectionPoint, sweep, runs_to_quad_mask


def ribbon_rows(spline: Spline):
    """Row layout of the ribbon: (D (N, R), H (N, R), groups (R-1,), n_int).
    Rows run from the right skirt to the left skirt; interior rows at fractions of the surface width
    between -edge_offset_R and +edge_offset_L; skirts at +-(edge_offset + overlap_m) dropped skirt_drop_m."""
    eL = spline.edge_offset(S.LEFT)
    eR = spline.edge_offset(S.RIGHT)
    ov = spline.overlap_m
    sd = spline.skirt_drop_m
    w_max = float((eL + eR).max())
    lss = spline.lateral_station_spacing_m
    n_int = max(7, 2 * int(math.ceil(w_max / (2.0 * lss))) + 1)
    frac = np.arange(n_int, dtype=np.float64) / (n_int - 1)
    D_int = -eR[:, None] + (eL + eR)[:, None] * frac[None, :]
    H_int = spline.surface_h(D_int)
    D = np.column_stack([-(eR + ov), D_int, eL + ov])
    H = np.column_stack([spline.surface_h(-eR) - sd, H_int, spline.surface_h(eL) - sd])
    groups = ["skirt_right"] + ["road"] * (n_int - 1) + ["skirt_left"]
    return D, H, groups, n_int


def mesh_surface_h(spline: Spline, D: np.ndarray, H: np.ndarray, s_q: np.ndarray, d_q: np.ndarray) -> np.ndarray:
    """Height of the ribbon MESH (bilinear rows, quads split on the V(i,k)-V(i+1,k+1) diagonal) at
    parameters (s, d): the marking strips sit exactly lift_m above this (SCHEMA.md 3.7)."""
    s = spline.s
    s_q = np.asarray(s_q, dtype=np.float64)
    d_q = np.asarray(d_q, dtype=np.float64)
    out = np.full(s_q.shape, np.nan)
    i = np.clip(np.searchsorted(s, s_q, side="right") - 1, 0, len(s) - 2)
    t = (s_q - s[i]) / (s[i + 1] - s[i])
    t = np.clip(t, 0.0, 1.0)
    for q in range(len(s_q)):
        ii, tt, d = int(i[q]), float(t[q]), float(d_q[q])
        d0 = (1 - tt) * D[ii] + tt * D[ii + 1]
        k = int(np.clip(np.searchsorted(d0, d, side="right") - 1, 0, D.shape[1] - 2))
        # quad corners in (t, d) space: A=(0, D[i,k]) B=(1, D[i+1,k]) C=(1, D[i+1,k+1]) Dd=(0, D[i,k+1])
        corners = [(0.0, D[ii, k], H[ii, k]), (1.0, D[ii + 1, k], H[ii + 1, k]),
                   (1.0, D[ii + 1, k + 1], H[ii + 1, k + 1]), (0.0, D[ii, k + 1], H[ii, k + 1])]
        best = None
        for tri in ((0, 1, 2), (0, 2, 3)):
            (x1, y1, h1), (x2, y2, h2), (x3, y3, h3) = (corners[j] for j in tri)
            det = (y2 - y3) * (x1 - x3) + (x3 - x2) * (y1 - y3)
            if abs(det) < 1e-18:
                continue
            l1 = ((y2 - y3) * (tt - x3) + (x3 - x2) * (d - y3)) / det
            l2 = ((y3 - y1) * (tt - x3) + (x1 - x3) * (d - y3)) / det
            l3 = 1.0 - l1 - l2
            m = min(l1, l2, l3)
            if best is None or m > best[0]:
                best = (m, l1 * h1 + l2 * h2 + l3 * h3)
        out[q] = best[1] if best is not None else np.nan
    return out


def marking_intervals(m: S.Marking, a: float, b: float, L: float) -> List[Tuple[float, float]]:
    """Painted s-intervals of one marking inside the painted interval [a, b]."""
    lo = max(a, 0.0 if m.s0_m is None else float(m.s0_m))
    hi = min(b, L if m.s1_m is None else float(m.s1_m))
    if hi - lo <= 1e-9:
        return []
    if m.pattern in ("solid", "double"):
        return [(lo, hi)]
    if m.pattern == "dashed":
        period = float(m.dash_m) + float(m.gap_m)
        phase = float(m.phase_m or 0.0)
        out = []
        k = int(math.floor((lo - phase) / period))
        while phase + k * period < hi - 1e-9:
            a0 = phase + k * period
            b0 = a0 + float(m.dash_m)
            x0, x1 = max(lo, a0), min(hi, b0)
            if x1 - x0 > 1e-9:
                out.append((x0, x1))
            k += 1
        return out
    return []


def build_road(spline: Spline, params=None) -> Tuple[MeshBuffer, List[Instance]]:
    if spline.kind == "rail":
        from . import rail
        return rail.build_rail(spline, params)
    buf = MeshBuffer()
    inst: List[Instance] = []
    if spline.kind is None:
        return buf, inst
    D, H, groups, n_int = ribbon_rows(spline)
    N = spline.n
    R = D.shape[1]
    pts = tuple(SectionPoint(0.0, 0.0, "tarmac", 0.0, True) for _ in range(R))
    section = Section(pts, False)
    # UV v = signed d: pass per-station v through point_o (uv uses SectionPoint.v, so build per-row v as d at station 0)
    section = Section(tuple(SectionPoint(float(D[0, r]), float(H[0, r]), "tarmac", float(D[0, r]), True) for r in range(R)), False)
    mat_st = np.empty((N, R - 1), dtype=object)
    for k in range(R - 1):
        mat_st[:, k] = spline.surface_material
    # the junction trim is a mask on the SHARED spline: the carriageway stops at the junction boundary
    # and never crosses it; the hole it leaves is filled by build_junction_patch, in THIS buffer and
    # with THIS material (SCHEMA.md 4.18)
    sweep(buf, section, spline.frames, side=+1, lateral=0.0, height=0.0, point_o=D, point_h=H,
          mask=spline.active, cap_start=False, cap_end=False, group=groups, edge_mat_station=mat_st)

    # -- markings: strips on interpolated frames, heights on the actual road mesh + lift ------------
    L = spline.length
    a_lo, a_hi = spline.s_trim
    plan = []   # (marking, [(a, b)], strip offsets)
    ends = []
    for a, b, mlist in spline.road.marking_intervals:
        a = max(a, a_lo)
        b = min(b, a_hi)
        if b - a <= 1e-9:
            continue
        for m in mlist:
            if m.pattern == "none":
                continue
            ivs = marking_intervals(m, a, b, L)
            if not ivs:
                continue
            plan.append((m, ivs))
            for x0, x1 in ivs:
                ends += [x0, x1]
    n_strips = 0
    if plan:
        fr = spline.frames.insert(np.array(ends))
        s_m = fr.s
        eL = np.interp(s_m, spline.s, spline.edge_offset(S.LEFT))
        eR = np.interp(s_m, spline.s, spline.edge_offset(S.RIGHT))
        for m, ivs in plan:
            if m.anchor == "centre":
                c = np.full(len(s_m), float(m.offset_m))
            elif m.anchor == "edge_left":
                c = eL - float(m.offset_m)
            else:
                c = -eR + float(m.offset_m)
            half = 0.5 * float(m.width_m)
            if m.pattern == "double":
                sep = 0.5 * (float(m.double_gap_m) + float(m.width_m))
                centres = [c - sep, c + sep]
            else:
                centres = [c]
            gname = "marking:%s" % (m.id or "%s_%s" % (m.anchor, m.pattern))
            qm = runs_to_quad_mask(s_m, ivs)
            for cc in centres:
                d0 = cc - half
                d1 = cc + half
                h0 = mesh_surface_h(spline, D, H, s_m, d0) + float(m.lift_m)
                h1 = mesh_surface_h(spline, D, H, s_m, d1) + float(m.lift_m)
                sec = Section((SectionPoint(-half, 0.0, m.material, 0.0, True),
                               SectionPoint(half, 0.0, m.material, float(m.width_m), True)), False)
                res = sweep(buf, sec, fr, side=+1, lateral=cc, height=0.0,
                            point_o=np.column_stack([np.full(len(s_m), -half), np.full(len(s_m), half)]),
                            point_h=np.column_stack([h0, h1]), quad_mask=qm,
                            cap_start=False, cap_end=False, group=gname)
                n_strips += len(res.runs)
    buf.marking_strips = n_strips  # type: ignore[attr-defined]
    return buf, inst


# --------------------------------------------------------------------------------------------
# the junction surface (still Renderer A: a junction is tarmac -- BRIEF 1.1 "THREE RENDERERS ONLY")
# --------------------------------------------------------------------------------------------

def arm_end_row(spline: Spline, i: int, reverse: bool):
    """The ribbon's cross-section at station index ``i`` as world positions, ordered anticlockwise
    about the junction (``reverse`` for an arm whose travel runs INTO the junction).

    These are the ribbon's OWN rows, computed by the ribbon's OWN expression
    ``p + d n + h b`` from ``ribbon_rows``, so the patch's boundary is not a second transcription of
    where the carriageway ends -- it IS where the carriageway ends, to the last bit."""
    D, H, _groups, _n_int = ribbon_rows(spline)
    cols = list(range(D.shape[1]))
    if reverse:
        cols.reverse()
    p, n, b = spline.frames.p[i], spline.frames.n[i], spline.frames.b[i]
    return np.array([p + D[i, c] * n + H[i, c] * b for c in cols])


def junction_boundary(plan: JunctionPlan, junction_id: str, splines):
    """The closed anticlockwise boundary of one junction patch, or None.

    It is built from exactly two kinds of piece and nothing else:

      * each arm's own ribbon end row (``arm_end_row``), skirt column to skirt column;
      * between adjacent arms, the interior samples of the kerb corner fillet, offset outward by that
        arm's ``overlap_m`` and dropped by its ``skirt_drop_m`` -- i.e. the same skirt the ribbon
        carries, continued round the corner.

    So every boundary vertex is either a ribbon vertex or a point on the curve Renderer B sweeps its
    corner kerb along, and the patch can meet neither with a crack.  Returns
    ``(loop (K, 3), arm_slices, corner_specs)``."""
    frames = resolve_arm_frames(plan, junction_id, splines)
    if frames is None or len(frames) < 3:
        return None
    cfg = plan.cfg
    j = plan.junction(junction_id)
    node = np.array([j.x, j.y], dtype=np.float64)
    loop = []
    arm_slices = []
    corner_specs = []
    for k, af in enumerate(frames):
        rows = arm_end_row(af.spline, af.i, af.arm.end != "start")
        arm_slices.append((len(loop), len(loop) + len(rows)))
        loop.extend(rows)
        nx = frames[(k + 1) % len(frames)]
        P, T = corner_curve(af.p_hi, nx.p_lo, -af.u, nx.u, node,
                            cfg["corner_step_deg"], cfg["corner_handle_frac"])
        fr = corner_frames(P, T, af.n_hi, nx.n_lo)
        ov0, ov1 = float(af.spline.overlap_m[af.i]), float(nx.spline.overlap_m[nx.i])
        sd0, sd1 = float(af.spline.skirt_drop_m[af.i]), float(nx.spline.skirt_drop_m[nx.i])
        t = np.linspace(0.0, 1.0, len(P))
        ov = (1.0 - t) * ov0 + t * ov1
        sd = (1.0 - t) * sd0 + t * sd1
        corner_specs.append((af, nx, P, T, fr, ov, sd))
        for q in range(1, len(P) - 1):
            loop.append(fr.p[q] - ov[q] * fr.n[q] - sd[q] * fr.b[q])
    return np.array(loop, dtype=np.float64), arm_slices, corner_specs


def build_junction_patch(plan: JunctionPlan, junction_id: str, splines, buf: MeshBuffer,
                         material: Optional[str] = None) -> dict:
    """Fill one junction, into ``buf`` -- the owning spline's ROAD buffer, with the road's own material.

    WHY A FAN AND NOT A CONSTRAINED TRIANGULATION.  Because a fan CANNOT leave a hole, for any apex:

        let p be a point inside the closed boundary and C the apex.  The ray from C through p is
        continued past p; the boundary is bounded, so it crosses some boundary edge (B_k, B_k+1) at a
        point q beyond p.  Then p lies on the segment C->q, so p lies in the triangle (C, B_k, B_k+1).
        Every interior point is therefore covered by some fan triangle.  QED.

    That holds whether or not the boundary is star-shaped about the node, which matters because it is
    not always: at an acute fork the kerb corner wraps round a nose that the node sees from behind.  A
    CDT would triangulate such a boundary without overlap, but it may insert vertices (which would pull
    a boundary edge off the ribbon and open the very crack this is here to prevent), its diagonals
    depend on insertion order (so it is not free-of-charge deterministic), and it degenerates
    unpredictably on the rare self-intersecting boundary of an unseparable pair, where the fan merely
    double-covers.  The fan's price is that double cover: where a boundary edge runs backwards in
    bearing about the node, its triangle is inverted and its area is covered twice.  ``overlap_area_m2``
    below measures exactly that, per junction, so it is a reported number and not a hope.

    WHY IT IS A SURFACE AND NOT A DISC AT ONE z.  Every boundary vertex carries the height its own arm's
    carriageway has there -- camber, bank, grade and all -- and the apex sits at the HIGHEST arm crown,
    so on a slope the patch is a tilted cone that meets each arm at that arm's level.  The apex is the
    max and not the mean deliberately: the corridor conform arbitrates overlapping corridors to the
    higher target, and a max of near-linear arm surfaces is convex, so the chord from the apex to any
    boundary point stays at or above every arm surface it spans."""
    out = {"built": False, "verts": 0, "tris": 0, "monotone": True, "arms": 0}
    res = junction_boundary(plan, junction_id, splines)
    if res is None:
        return out
    loop, arm_slices, _corners = res
    if len(loop) < 3:
        return out
    j = plan.junction(junction_id)
    frames = resolve_arm_frames(plan, junction_id, splines)
    z_apex = max(float(af.spline.frames.p[af.i][2]) for af in frames)
    centre = np.array([j.x, j.y, z_apex], dtype=np.float64)

    ang = np.arctan2(loop[:, 1] - j.y, loop[:, 0] - j.x)
    step = np.diff(np.concatenate([ang, ang[:1]]))
    step = (step + np.pi) % (2.0 * np.pi) - np.pi
    out["monotone"] = bool(np.all(step > 1e-12) and abs(float(step.sum()) - 2.0 * np.pi) < 1e-6)

    if material is None:
        material = str(frames[0].spline.surface_material[frames[0].i])
    gid = buf.group_id("junction:%s" % junction_id)
    mid = buf.material_id(material)
    V = np.vstack([centre[None, :], loop])
    uv = np.column_stack([V[:, 0] - j.x, V[:, 1] - j.y])
    s_owner = float(frames[0].spline.s[frames[0].i])
    first = buf.append_vertices(V, uv, np.full(len(V), s_owner), np.zeros(len(V)), np.zeros(len(V)))
    K = len(loop)
    tri = [(0, 1 + k, 1 + (k + 1) % K) for k in range(K)]
    T = np.array([[first + x, first + y, first + z] for x, y, z in tri], dtype=np.int64)
    # plan areas of what is actually emitted: the boundary's own area is the shoelace of the loop, so
    # the excess is the area some triangle covers twice (0 when nothing is inverted)
    Vp = np.vstack([centre[None, :], loop])[:, :2]
    idx = np.array(tri, dtype=np.int64)
    A0, A1, A2 = Vp[idx[:, 0]], Vp[idx[:, 1]], Vp[idx[:, 2]]
    sa = 0.5 * ((A1[:, 0] - A0[:, 0]) * (A2[:, 1] - A0[:, 1]) - (A2[:, 0] - A0[:, 0]) * (A1[:, 1] - A0[:, 1]))
    shoe = 0.5 * float(np.sum(loop[:, 0] * np.roll(loop[:, 1], -1) - np.roll(loop[:, 0], -1) * loop[:, 1]))
    out["area_m2"] = abs(shoe)
    out["overlap_area_m2"] = float(max(0.0, float(np.abs(sa).sum()) - abs(shoe)))
    a, b, c = buf.v[T[:, 0]], buf.v[T[:, 1]], buf.v[T[:, 2]]
    fn = np.cross(b - a, c - a)
    T[fn[:, 2] < 0] = T[fn[:, 2] < 0][:, [0, 2, 1]]
    area = 0.5 * np.linalg.norm(fn, axis=1)
    T = T[area >= 1e-10]
    buf.append_triangles(T, mid, gid)
    out.update({"built": True, "verts": int(len(V)), "tris": int(len(T)), "arms": len(frames),
                "boundary": int(K), "trim_radius_m": float(plan.trim_radius[junction_id]),
                "z_apex": z_apex})
    return out


def junction_surface(plan: JunctionPlan, junction_id: str, splines):
    """``(loop (K, 3), apex (3,))`` -- the patch as a plan polygon with its apex, or None.

    The hook the CORRIDOR CONFORM needs.  ``conform.py`` burns the ground from the arms' corridors, and
    a corridor is a band along a spline: between two arms, close to the node, there are wedges that no
    band covers as CORE -- only as feathered blend -- and the patch lays new tarmac across exactly those
    wedges.  Measured over the isle, 825 of 87,912 patch vertices (0.94 %) sit below the conformed
    ground for that reason, worst 2.86 m.  Rasterising this polygon into the corridor as core, with
    ``junction_target_z`` as its target surface, is what closes that; nothing in this module can do it,
    because the conform product is not this track's to write."""
    res = junction_boundary(plan, junction_id, splines)
    if res is None:
        return None
    loop, _slices, _corners = res
    if len(loop) < 3:
        return None
    frames = resolve_arm_frames(plan, junction_id, splines)
    j = plan.junction(junction_id)
    apex = np.array([j.x, j.y, max(float(af.spline.frames.p[af.i][2]) for af in frames)])
    return loop, apex


def junction_target_z(loop: np.ndarray, apex: np.ndarray, x, y) -> np.ndarray:
    """Height of the patch surface at plan positions (x, y); NaN outside it.  The same fan
    ``build_junction_patch`` emits, evaluated barycentrically, so the burn and the mesh are one
    surface rather than two transcriptions of one."""
    x = np.atleast_1d(np.asarray(x, dtype=np.float64))
    y = np.atleast_1d(np.asarray(y, dtype=np.float64))
    out = np.full(x.shape, np.nan)
    K = len(loop)
    ax, ay, az = float(apex[0]), float(apex[1]), float(apex[2])
    for k in range(K):
        b = loop[k]
        c = loop[(k + 1) % K]
        det = (b[1] - c[1]) * (ax - c[0]) + (c[0] - b[0]) * (ay - c[1])
        if abs(det) < 1e-18:
            continue
        l1 = ((b[1] - c[1]) * (x - c[0]) + (c[0] - b[0]) * (y - c[1])) / det
        l2 = ((c[1] - ay) * (x - c[0]) + (ax - c[0]) * (y - c[1])) / det
        l3 = 1.0 - l1 - l2
        inside = (l1 >= -1e-9) & (l2 >= -1e-9) & (l3 >= -1e-9) & ~np.isfinite(out)
        if inside.any():
            out[inside] = (l1 * az + l2 * b[2] + l3 * c[2])[inside]
    return out
