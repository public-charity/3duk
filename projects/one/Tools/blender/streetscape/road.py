"""Renderer A: the road ribbon with camber, skirts and lifted marking strips (DESIGN.md 4.1,
SCHEMA.md 3.7; geometry.md 5.7).  Rail is a profile kind: ``build_road`` dispatches to
``rail.build_rail`` when ``spline.kind == "rail"`` and nothing else here knows about rails.

Groups: ``road``, ``skirt_left``, ``skirt_right``, ``marking:<id>``.  No marking-specific identifiers
exist in this file: a double yellow, a single yellow and a centre dash are rows of profile data.
"""
from __future__ import annotations

import math
from typing import List, Tuple

import numpy as np

from . import schema as S
from .instance import Instance
from .mesh import MeshBuffer
from .spline import Spline
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
    sweep(buf, section, spline.frames, side=+1, lateral=0.0, height=0.0, point_o=D, point_h=H,
          cap_start=False, cap_end=False, group=groups, edge_mat_station=mat_st)

    # -- markings: strips on interpolated frames, heights on the actual road mesh + lift ------------
    L = spline.length
    plan = []   # (marking, [(a, b)], strip offsets)
    ends = []
    for a, b, mlist in spline.road.marking_intervals:
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
