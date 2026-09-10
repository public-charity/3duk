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
``barrier:<type>:<s0>``, ``embankment:<kind>:<s0>``, ``corner_kerb:<junction>:<k>``,
``corner_pavement:<junction>:<k>``.

At a junction the kerb stops at the SHARED trim (``spline.active``, resolved in spline.py so Renderer A
stops at the identical station) and ``build_junction_corners`` turns the corner between adjacent arms
with a fillet instead of running on into the middle of the crossing (SCHEMA.md 4.18).
"""
from __future__ import annotations

import math
from typing import List, Tuple

import numpy as np

from . import schema as S
from .instance import Instance, make_transform
from .mesh import MeshBuffer
from .spline import JunctionPlan, Spline, corner_curve, corner_frames, resolve_arm_frames
from .sweep import Section, SectionPoint, sweep
from .support import world_section, batter_toes


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


def kerb_columns(kw, hk, r, pw, hkb, ti, td, sk, frac, lip_kind, m: int):
    """(O (M, P), Hh (M, P)) of the kerb + pavement section, from per-station scalars only.

    The ONE definition of the section's shape: ``_kerb_section`` evaluates it along a spline and
    ``build_junction_corner`` evaluates it along a corner arc between two arms, so a corner is the same
    kerb as the straight it grew out of and cannot drift from it (BRIEF 1.1's "same spline" rule applied
    to the one place where there is no spline)."""
    M = len(np.atleast_1d(hk))
    z = np.zeros(M)
    cols_o = [-ti + z, z.copy(), z.copy()]
    cols_h = [-td + z, -td + z, hk - r]
    for j in range(1, m + 1):
        th = math.radians(90.0 * j / (m + 1))
        lo = np.zeros(M)
        lh = np.zeros(M)
        for i in range(M):
            kind = lip_kind[i]
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
    cols_o += [r + z, kw * frac, kw + z, kw + pw, kw + pw]
    cols_h += [hk + z, hk + z, hk + z, hkb + z, -sk + z]
    return np.column_stack(cols_o), np.column_stack(cols_h)


def kerb_layout(m: int):
    """(smooth (P,), groups (E,), n_inner_edges) of the kerb + pavement section."""
    n_inner_edges = 2 + (m + 1)          # A-B, B-C, C..D
    groups = ["kerb"] * (n_inner_edges + 2) + ["pavement", "pavement"]
    smooth = [False, False, True] + [True] * m + [True, True, True, False, False]
    return smooth, groups, n_inner_edges


def _kerb_section(spec: S.SideSpec, spline: Spline, side: int):
    """Per-station point arrays (N, P) and the material/group layout of the kerb + pavement section."""
    N = spline.n
    m = spec.arc_points
    frac = np.where(spec.split, spec.split_frac, 0.5)
    O, Hh = kerb_columns(spec.kerb_width, spec.hk, spec.lip_r, spec.pavement_width, spec.hk_back,
                         spec.tuck_in, spec.tuck_depth, spec.skirt, frac, spec.lip_kind, m)
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
    smooth, groups, n_inner_edges = kerb_layout(m)
    for k in range(n_inner_edges):
        mats[:, k] = inner
    mats[:, n_inner_edges] = inner       # D-S (top_in)
    mats[:, n_inner_edges + 1] = top_out  # S-E
    mats[:, n_inner_edges + 2] = pav_mat  # E-F
    mats[:, n_inner_edges + 3] = pav_mat  # F-G
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
    # the junction trim is a mask on the SHARED spline, so Renderer B stops exactly where Renderer A
    # does: kerb and pavement never run on into the middle of a junction (SCHEMA.md 4.18)
    present = spec.present & spline.active
    if not present.any():
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
              mask=present, cap_start=True, cap_end=True, cap_mat=None, group=groups, edge_mat_station=mats)

    # -- barriers ----------------------------------------------------------------------------------
    hb_all = h0 + spec.hk_back
    for a, b, bar in spec.barrier_timeline:
        if bar is None or bar.type == "none":
            continue
        mask = (s >= a - 1e-9) & (s <= b + 1e-9) & spline.active
        if mask.sum() < 2:
            # a barrier run shorter than one station gap sweeps nothing; say so instead of vanishing
            spline.warnings.append("barrier %s %s [%g, %g] covers %d station(s): nothing swept"
                                   % (S.SIDE_NAME[side], bar.type, a, b, int(mask.sum())))
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
            sj = np.array(post_stations(max(a, spline.s_trim[0]), min(b, spline.s_trim[1]),
                                        float(bar.post_pitch_m)))
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
            ob = o0 + spec.back_offset
            start = frames.p+side*ob[:,None]*frames.n+hb_all[:,None]*frames.b
            zt = terrain.sample(start[:,0],start[:,1])
            dz = start[:,2]-zt
            if np.any(rng & spline.active & ~np.isfinite(dz)):
                raise ValueError("embankment edge has missing terrain")
            valid = np.isfinite(dz) & rng & spline.active
            thr = float(emb.threshold_m)
            want_batter = emb.kind in ("batter", "auto")
            want_wall = emb.kind in ("retaining_wall", "auto")
            allow_down = emb.side in ("both", "auto", "downhill", "left", "right")
            allow_up = emb.side in ("both", "auto", "uphill", "left", "right")
            if want_batter and allow_down:
                mask = valid & (dz > thr)
                if mask.any():
                    run,drop = batter_toes(start,side*n_flat_xy,terrain,mask,
                                           float(emb.slope_ratio),float(emb.toe_extra_m))
                    o_toe,h_toe = world_section(frames,side,run,drop)
                    O = np.column_stack([np.zeros(N),o_toe])
                    Hh = np.column_stack([np.zeros(N),h_toe])
                    sec = Section((SectionPoint(0.0, 0.0, emb.material, 0.0, True),
                                   SectionPoint(1.0, -1.0, emb.material, 1.0, True)), False)
                    sweep(buf, sec, frames, side=side, lateral=ob, height=hb_all, point_o=O, point_h=Hh, mask=mask,
                          cap_start=False, cap_end=False, group="embankment:batter:%g" % a)
            if want_wall:
                # Auto uses a batter downhill. Explicit retaining_wall also
                # supports a raised road, respecting an explicit uphill filter.
                mask = valid & (((dz < -thr)&allow_up) |
                    ((dz > thr)&allow_down&(emb.kind=="retaining_wall")))
                if mask.any():
                    wt = float(emb.wall_thickness_m)
                    outer = start[:,:2]+side*wt*n_flat_xy
                    z_outer = terrain.sample(outer[:,0],outer[:,1])
                    if not np.isfinite(z_outer[mask]).all():
                        raise ValueError("retaining wall footing has missing terrain")
                    top = np.where(mask,np.maximum.reduce([start[:,2],zt,z_outer])-start[:,2],0.)+float(emb.wall_coping_m)
                    base = np.where(mask,np.minimum.reduce([start[:,2],zt,z_outer])-start[:,2],0.)-float(emb.toe_extra_m)
                    runs = [np.zeros(N),np.zeros(N),np.full(N,wt),np.full(N,wt)]
                    pairs = [world_section(frames,side,r,z) for r,z in zip(runs,[base,top,top,base])]
                    O = np.column_stack([pair[0] for pair in pairs])
                    Hh = np.column_stack([pair[1] for pair in pairs])
                    sec = Section((SectionPoint(0.0, -0.3, emb.material, 0.0, False), SectionPoint(0.0, 1.0, emb.material, 1.0, False),
                                   SectionPoint(wt, 1.0, emb.material, 2.0, False), SectionPoint(wt, -0.3, emb.material, 3.0, False)), True)
                    sweep(buf, sec, frames, side=side, lateral=ob, height=hb_all, point_o=O, point_h=Hh, mask=mask,
                          cap_start=True, cap_end=True, cap_mat=emb.material, group="embankment:retaining_wall:%g" % a)
    return buf, inst


# --------------------------------------------------------------------------------------------
# the junction corner (still Renderer B: a kerb that turns is still a kerb -- BRIEF 1.1)
# --------------------------------------------------------------------------------------------

def build_junction_corners(plan: JunctionPlan, junction_id: str, splines, buf: MeshBuffer) -> dict:
    """Sweep the kerb + pavement round the corner between each adjacent pair of arms, into ``buf``.

    The kerb stops at the trim (``build_edge`` masks by ``spline.active``) and this picks it up there:
    the corner's first ring is the arm's own last ring -- same position, same outward normal, same up
    vector -- so there is no kink and no gap at the join, and the fillet turns the corner instead of
    running on into the middle of the junction.

    THE OVERLAP RULE HOLDS ALONG THE CORNER BY CONSTRUCTION.  The corner is swept along the KERB LINE
    (``ArmFrame.p_hi`` / ``p_lo`` are the kerb-line origins, so ``lateral = 0``), and Renderer A's patch
    boundary is that same curve, from the same ``corner_curve`` call, offset outward by the arm's own
    ``overlap_m`` and dropped by its ``skirt_drop_m``.  The road therefore overhangs the corner kerb by
    exactly ``overlap_m`` (40 mm on the UK profiles) at every sample, the same as it does along a
    straight -- measured, not assumed, by ``test_junction.TestCorner.test_overlap_along_corner``.

    The two arms may carry different edge profiles.  Every scalar of the section is linearly
    interpolated along the corner and the material set switches at the midpoint, so a brick kerb meeting
    a concrete one changes over halfway round rather than at a seam.  Sections whose ARC POINT COUNT
    differs cannot be interpolated column for column; those corners are skipped and counted."""
    out = {"corners": 0, "skipped_no_kerb": 0, "skipped_incompatible": 0, "verts": 0, "tris": 0}
    frames = resolve_arm_frames(plan, junction_id, splines)
    if frames is None or len(frames) < 3:
        return out
    j = plan.junction(junction_id)
    node = np.array([j.x, j.y], dtype=np.float64)
    cfg = plan.cfg
    v0, t0 = len(buf.v), len(buf.f)
    for k, af in enumerate(frames):
        nx = frames[(k + 1) % len(frames)]
        sa, ia = af.spline.side_spec[af.side_hi], af.i
        sb, ib = nx.spline.side_spec[nx.side_lo], nx.i
        use_a = bool(sa.has_kerb_or_pavement and sa.present[ia])
        use_b = bool(sb.has_kerb_or_pavement and sb.present[ib])
        if not (use_a or use_b):
            out["skipped_no_kerb"] += 1
            continue
        # one arm kerbed and the other not (a footway meeting a street): run THAT arm's section round
        # the corner unchanged and cap the far end, rather than leaving the kerb hanging at the trim
        cap_start, cap_end = False, False
        if not use_b:
            sb, ib, cap_end = sa, ia, True
        elif not use_a:
            sa, ia, cap_start = sb, ib, True
        if int(sa.arc_points) != int(sb.arc_points):
            out["skipped_incompatible"] += 1
            continue
        P, T = corner_curve(af.p_hi, nx.p_lo, -af.u, nx.u, node,
                            cfg["corner_step_deg"], cfg["corner_handle_frac"])
        fr = corner_frames(P, T, af.n_hi, nx.n_lo)
        fr.s = fr.s + float(af.spline.s[af.i])          # UV u keeps running in metres across the join
        M = len(P)
        t = np.linspace(0.0, 1.0, M)

        def lerp(name):
            return (1.0 - t) * float(getattr(sa, name)[ia]) + t * float(getattr(sb, name)[ib])
        frac_a = float(sa.split_frac[ia]) if bool(sa.split[ia]) else 0.5
        frac_b = float(sb.split_frac[ib]) if bool(sb.split[ib]) else 0.5
        m = int(sa.arc_points)
        half = M // 2
        lip_kind = [str(sa.lip_kind[ia])] * half + [str(sb.lip_kind[ib])] * (M - half)
        O, Hh = kerb_columns(lerp("kerb_width"), lerp("hk"), lerp("lip_r"), lerp("pavement_width"),
                             lerp("hk_back"), lerp("tuck_in"), lerp("tuck_depth"), lerp("skirt"),
                             (1.0 - t) * frac_a + t * frac_b, lip_kind, m)
        P_pts = O.shape[1]
        E = P_pts - 1
        smooth, groups, n_inner = kerb_layout(m)
        mats = np.empty((M, E), dtype=object)
        for row, (spec, idx) in enumerate([(sa, ia)] * half + [(sb, ib)] * (M - half)):
            split = bool(spec.split[idx])
            inner = str(spec.mat_inner[idx])
            for c in range(n_inner + 1):
                mats[row, c] = inner
            mats[row, n_inner + 1] = str(spec.mat_outer[idx]) if split else str(spec.mat_kerb[idx])
            pav = str(spec.mat_outer[idx]) if split else str(spec.mat_pavement[idx])
            mats[row, n_inner + 2] = pav
            mats[row, n_inner + 3] = pav
        v = [0.0]
        for c in range(1, P_pts):
            v.append(v[-1] + float(np.hypot(O[0, c] - O[0, c - 1], Hh[0, c] - Hh[0, c - 1])))
        section = Section(tuple(SectionPoint(float(O[0, c]), float(Hh[0, c]), str(mats[0, min(c, E - 1)]),
                                             v[c], smooth[c]) for c in range(P_pts)), False)
        gnames = ["corner_%s:%s:%d" % (g, junction_id, k) for g in groups]
        sweep(buf, section, fr, side=-1, lateral=0.0, height=0.0, point_o=O, point_h=Hh,
              cap_start=cap_start, cap_end=cap_end, cap_mat=None, group=gnames, edge_mat_station=mats)
        out["corners"] += 1
    out["verts"] = len(buf.v) - v0
    out["tris"] = len(buf.f) - t0
    return out
