"""Renderer B: kerb + pavement + drop kerbs + split materials + barriers + embankments
(DESIGN.md 4.2, SCHEMA.md 4.8-4.11; geometry.md 5.8).

Section outward ``o`` from the kerb line (``spline.edge_offset(side)``), ``h`` from the road-edge
level (``spline.edge_height(side)``).  Per station (from the resolved SideSpec):

  A (-tuck_in, -tuck_depth) hard   B (0, -tuck_depth) hard   C (0, hk - r) smooth   L_j lip arc
  D (r, hk) smooth   S (kw * boundary_frac, hk) smooth   E (kw, hk) smooth   F (kw + pw, hk_back) hard
  G (kw + pw, -skirt)

D, S, E share one height: the split boundary is flush by construction.  The S row is always emitted
(at 0.5 * kw with the kerb material where no split is in force) so one row set serves the whole
sweep and a profile switch changes only materials.  Groups: ``kerb``, ``pavement``,
``barrier:<type>:<s0>``, ``embankment:<kind>:<s0>``.
"""
from __future__ import annotations

import math
from typing import List, Tuple

import numpy as np

from . import schema as S
from .instance import Instance, make_transform
from .mesh import MeshBuffer
from .spline import Spline
from .sweep import Section, SectionPoint, sweep


def post_stations(a: float, b: float, pitch: float) -> List[float]:
    """n = floor(D/p) + 1 + [frac(D/p) > 0.5]; posts at a + j p for j < n - 1, the last at b."""
    D = b - a
    if D <= 1e-9 or pitch <= 0:
        return [a] if D <= 1e-9 else [a, b]
    q = D / pitch
    n = int(math.floor(q + 1e-9)) + 1 + (1 if (q - math.floor(q + 1e-9)) > 0.5 else 0)
    out = [a + j * pitch for j in range(max(n - 1, 0))]
    out.append(b)
    return out


def _kerb_section(spec: S.SideSpec, spline: Spline, side: int):
    """Per-station point arrays (N, P) and the material/group layout of the kerb + pavement section."""
    N = spline.n
    m = spec.arc_points
    kw, hk, r = spec.kerb_width, spec.hk, spec.lip_r
    pw, hkb = spec.pavement_width, spec.hk_back
    ti, td, sk = spec.tuck_in, spec.tuck_depth, spec.skirt
    frac = np.where(spec.split, spec.split_frac, 0.5)
    cols_o = [-ti, np.zeros(N), np.zeros(N)]
    cols_h = [-td, -td, hk - r]
    for j in range(1, m + 1):
        th = math.radians(90.0 * j / (m + 1))
        lo = np.zeros(N)
        lh = np.zeros(N)
        for i in range(N):
            kind = spec.lip_kind[i]
            if kind == "radius":
                lo[i] = r[i] - r[i] * math.cos(th)
                lh[i] = hk[i] - r[i] + r[i] * math.sin(th)
            elif kind == "chamfer":
                f = j / (m + 1)
                lo[i] = r[i] * f
                lh[i] = hk[i] - r[i] + r[i] * f
            else:
                lo[i] = 0.0
                lh[i] = hk[i]
        cols_o.append(lo)
        cols_h.append(lh)
    cols_o += [r, kw * frac, kw, kw + pw, kw + pw]
    cols_h += [hk, hk, hk, hkb, -sk]
    O = np.column_stack(cols_o)
    Hh = np.column_stack(cols_h)
    P = O.shape[1]
    # edges: A-B, B-C, C-L1, ..., Lm-D, D-S, S-E, E-F, F-G
    E = P - 1
    mats = np.empty((N, E), dtype=object)
    inner = spec.mat_inner
    kerb = spec.mat_kerb
    outer = spec.mat_outer
    pav = spec.mat_pavement
    top_out = np.where(spec.split, outer, kerb)
    pav_mat = np.where(spec.split, outer, pav)
    n_inner_edges = 2 + (m + 1)          # A-B, B-C, C..D
    for k in range(n_inner_edges):
        mats[:, k] = inner
    mats[:, n_inner_edges] = inner       # D-S (top_in)
    mats[:, n_inner_edges + 1] = top_out  # S-E
    mats[:, n_inner_edges + 2] = pav_mat  # E-F
    mats[:, n_inner_edges + 3] = pav_mat  # F-G
    groups = ["kerb"] * (n_inner_edges + 2) + ["pavement", "pavement"]
    smooth = [False, False, True] + [True] * m + [True, True, True, False, False]
    # nominal v = cumulative section length of the base profile at station 0
    v = [0.0]
    for k in range(1, P):
        v.append(v[-1] + float(np.hypot(O[0, k] - O[0, k - 1], Hh[0, k] - Hh[0, k - 1])))
    pts = tuple(SectionPoint(float(O[0, k]), float(Hh[0, k]), str(mats[0, min(k, E - 1)]), v[k], smooth[k]) for k in range(P))
    return Section(pts, False), O, Hh, mats, groups


def _wall_section(H: float, t: float, ov: float, ch: float, skirt: float, mat: str, coping: str) -> Section:
    pts = [(0.0, -skirt, mat), (0.0, H, coping), (-ov, H, coping), (-ov, H + ch, coping), (t + ov, H + ch, coping),
           (t + ov, H, coping), (t, H, mat), (t, -skirt, mat)]
    v = [0.0]
    for (o0, h0, _), (o1, h1, _) in zip(pts[:-1], pts[1:]):
        v.append(v[-1] + float(np.hypot(o1 - o0, h1 - h0)))
    return Section(tuple(SectionPoint(o, h, m, vv, False) for (o, h, m), vv in zip(pts, v)), True)


def _square_section(oc: float, hc: float, a: float, mat: str) -> Section:
    pts = [(oc - a, hc - a), (oc - a, hc + a), (oc + a, hc + a), (oc + a, hc - a)]
    v = [0.0, 2 * a, 4 * a, 6 * a]
    return Section(tuple(SectionPoint(o, h, mat, vv, False) for (o, h), vv in zip(pts, v)), True)


def build_edge(spline: Spline, side: int, terrain=None, params=None) -> Tuple[MeshBuffer, List[Instance]]:
    buf = MeshBuffer()
    inst: List[Instance] = []
    spec = spline.side_spec[side]
    if not spec.present.any():
        return buf, inst
    o0 = spline.edge_offset(side)
    h0 = spline.edge_height(side)
    s = spline.s
    N = spline.n
    frames = spline.frames

    # -- kerb + pavement ---------------------------------------------------------------------------
    if spec.has_kerb_or_pavement:
        section, O, Hh, mats, groups = _kerb_section(spec, spline, side)
        sweep(buf, section, frames, side=side, lateral=o0, height=h0, point_o=O, point_h=Hh,
              mask=spec.present, cap_start=True, cap_end=True, cap_mat=None, group=groups, edge_mat_station=mats)

    # -- barriers ----------------------------------------------------------------------------------
    hb_all = h0 + spec.hk_back
    for a, b, bar in spec.barrier_timeline:
        if bar is None or bar.type == "none":
            continue
        mask = (s >= a - 1e-9) & (s <= b + 1e-9)
        if not mask.any():
            continue
        ob = o0 + spec.back_offset + float(bar.offset_m)
        H = float(bar.height_m)
        t = float(bar.thickness_m)
        gname = "barrier:%s:%g" % (bar.type, a)
        if bar.type in S.WALL_TYPES:
            sec = _wall_section(H, t, float(bar.coping_overhang_m), float(bar.coping_height_m), float(bar.skirt_m),
                                bar.material, bar.coping_material)
            sweep(buf, sec, frames, side=side, lateral=ob, height=hb_all, mask=mask, cap_start=True, cap_end=True,
                  cap_mat=bar.material, group=gname)
        else:
            # posts
            kind = "post_round" if bar.type in S.FENCE_TYPES else "post_square"
            ps = float(bar.post_size_m)
            post_h = H + 0.05 if bar.type in S.FENCE_TYPES else H
            sj = np.array(post_stations(a, b, float(bar.post_pitch_m)))
            fr = frames.at(sj)
            ob_j = np.interp(sj, s, ob)
            hb_j = np.interp(sj, s, hb_all)
            for q in range(len(sj)):
                p = fr.p[q] + side * (ob_j[q] + 0.5 * t) * fr.n[q] + hb_j[q] * fr.b[q]
                inst.append(Instance(kind, make_transform(fr.t_h[q], fr.n[q], fr.b[q], p), (ps, ps, post_h),
                                     bar.post_material, spline.id, side))
            if bar.type in S.FENCE_TYPES:
                sec = Section((SectionPoint(0.5 * t, 0.05, bar.material, 0.0, True),
                               SectionPoint(0.5 * t, H, bar.material, H - 0.05, True)), False)
                sweep(buf, sec, frames, side=side, lateral=ob, height=hb_all, mask=mask, cap_start=False,
                      cap_end=False, group=gname, two_sided=True)
            else:
                a_r = 0.5 * float(bar.rail_size_m)
                for hr in bar.effective_rails():
                    sec = _square_section(0.5 * t, float(hr), a_r, bar.material)
                    sweep(buf, sec, frames, side=side, lateral=ob, height=hb_all, mask=mask, cap_start=True,
                          cap_end=True, cap_mat=bar.material, group=gname)

    # -- embankments --------------------------------------------------------------------------------
    if terrain is not None:
        n_flat_xy = frames.n_flat[:, :2]
        for a, b, emb in spec.embankment_timeline:
            if emb is None:
                continue
            if emb.side in ("left", "right") and emb.side != S.SIDE_NAME[side]:
                continue
            rng = (s >= a - 1e-9) & (s <= b + 1e-9)
            xy_b = spline.xy + side * (o0 + spec.back_offset)[:, None] * n_flat_xy
            z_b = spline.z_ref + h0 + spec.hk_back
            zt = terrain.sample(xy_b[:, 0], xy_b[:, 1])
            dz = z_b - zt
            valid = np.isfinite(dz) & rng
            thr = float(emb.threshold_m)
            want_batter = emb.kind in ("batter", "auto")
            want_wall = emb.kind in ("retaining_wall", "auto")
            allow_down = emb.side in ("both", "auto", "downhill", "left", "right")
            allow_up = emb.side in ("both", "auto", "uphill", "left", "right")
            ob = o0 + spec.back_offset
            if want_batter and allow_down:
                mask = valid & (dz > thr)
                if mask.any():
                    dzp = np.where(mask, dz, 0.0) + float(emb.toe_extra_m)
                    O = np.column_stack([np.zeros(N), float(emb.slope_ratio) * dzp])
                    Hh = np.column_stack([np.zeros(N), -dzp])
                    sec = Section((SectionPoint(0.0, 0.0, emb.material, 0.0, True),
                                   SectionPoint(1.0, -1.0, emb.material, 1.0, True)), False)
                    sweep(buf, sec, frames, side=side, lateral=ob, height=hb_all, point_o=O, point_h=Hh, mask=mask,
                          cap_start=False, cap_end=False, group="embankment:batter:%g" % a)
            if want_wall and allow_up:
                mask = valid & (dz < -thr)
                if mask.any():
                    wt = float(emb.wall_thickness_m)
                    top = np.where(mask, np.abs(dz), 0.0) + float(emb.wall_coping_m)
                    sk = spec.skirt
                    O = np.column_stack([np.zeros(N), np.zeros(N), np.full(N, wt), np.full(N, wt)])
                    Hh = np.column_stack([-sk, top, top, -sk])
                    sec = Section((SectionPoint(0.0, -0.3, emb.material, 0.0, False), SectionPoint(0.0, 1.0, emb.material, 1.0, False),
                                   SectionPoint(wt, 1.0, emb.material, 2.0, False), SectionPoint(wt, -0.3, emb.material, 3.0, False)), True)
                    sweep(buf, sec, frames, side=side, lateral=ob, height=hb_all, point_o=O, point_h=Hh, mask=mask,
                          cap_start=True, cap_end=True, cap_mat=emb.material, group="embankment:retaining_wall:%g" % a)
    return buf, inst
