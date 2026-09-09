"""Renderer C: the volumetric hedge (DESIGN.md 4.3, SCHEMA.md 4.12; geometry.md 5.9).

Reads the SAME SideSpec Renderer B read: inner face at
  o_h = edge_offset + kw + pw + [barrier.offset_m + barrier.thickness_m if a barrier is in force] + hedge.offset_m,
base h0 + hk_back - base_sink_m.  Swept closed rounded-rectangle volume, per-vertex ``fbm3`` displacement
along the section-space outward normal (base row undisplaced), leaf cards as an instance list.
"""
from __future__ import annotations

import math
from typing import List, Tuple

import numpy as np

from . import schema as S
from . import noise
from .instance import Instance, make_transform
from .mesh import MeshBuffer
from .spline import Spline
from .sweep import Section, SectionPoint, sweep


def hedge_section_points(W: float, H: float, r: float, m: int, top: str) -> List[Tuple[float, float]]:
    """Closed clockwise polygon in (o, h): (0,0) up the inner face, over the top, down the outer face."""
    pts = [(0.0, 0.0)]
    if top == "rounded":
        cy = H - 0.5 * W
        pts.append((0.0, cy))
        n = 2 * m + 3
        for j in range(1, n - 1):
            th = math.pi - math.pi * j / (n - 1)
            pts.append((0.5 * W + (0.5 * W) * math.cos(th), cy + (0.5 * W) * math.sin(th)))
        pts.append((W, cy))
    else:
        pts.append((0.0, H - r))
        for j in range(1, m + 1):
            th = math.pi - (0.5 * math.pi) * j / (m + 1)
            pts.append((r + r * math.cos(th), H - r + r * math.sin(th)))
        if top == "domed":
            rise = 0.15 * W
            x0, x1 = r, W - r
            n = 2 * m + 1
            for j in range(n):
                f = j / (n - 1)
                x = x0 + (x1 - x0) * f
                pts.append((x, H + rise * math.sin(math.pi * f)))
        else:
            pts.append((r, H))
            pts.append((W - r, H))
        for j in range(1, m + 1):
            th = (0.5 * math.pi) - (0.5 * math.pi) * j / (m + 1)
            pts.append((W - r + r * math.cos(th), H - r + r * math.sin(th)))
        pts.append((W, H - r))
    pts.append((W, 0.0))
    # drop coincident consecutive points (r = 0)
    out = [pts[0]]
    for p in pts[1:]:
        if math.hypot(p[0] - out[-1][0], p[1] - out[-1][1]) > 1e-12:
            out.append(p)
    return out


def section_outward_normals(pts: List[Tuple[float, float]]) -> np.ndarray:
    """Outward normal per point of a closed CW polygon: normalised mean of the adjacent edges' left perps."""
    P = np.array(pts)
    n = len(P)
    out = np.zeros((n, 2))
    for k in range(n):
        d_prev = P[k] - P[k - 1]
        d_next = P[(k + 1) % n] - P[k]
        perp = np.array([-d_prev[1], d_prev[0]]) / max(np.hypot(*d_prev), 1e-12) + np.array([-d_next[1], d_next[0]]) / max(np.hypot(*d_next), 1e-12)
        nn = np.hypot(*perp)
        out[k] = perp / nn if nn > 1e-12 else 0.0
    return out


def build_hedge(spline: Spline, side: int, params=None) -> Tuple[MeshBuffer, List[Instance]]:
    buf = MeshBuffer()
    inst: List[Instance] = []
    spec = spline.side_spec[side]
    o0 = spline.edge_offset(side)
    h0 = spline.edge_height(side)
    s = spline.s
    N = spline.n
    frames = spline.frames
    bars = spec.barrier_at(s)
    bar_step = np.array([(float(b.offset_m) + float(b.thickness_m)) if (b is not None and b.type != "none") else 0.0 for b in bars])
    for a, b, hs in spec.hedge_timeline:
        if hs is None:
            continue
        prof = hs.profile
        mask = (s >= a - 1e-9) & (s <= b + 1e-9) & spline.active
        if mask.sum() < 2:
            # a hedge run that lands between two stations sweeps nothing; say so instead of vanishing
            spline.warnings.append("hedge %s [%g, %g] covers %d station(s): nothing swept"
                                   % (S.SIDE_NAME[side], a, b, int(mask.sum())))
            continue
        W = float(hs.width_m)
        H = float(hs.height_m) + float(prof.base_sink_m)
        r = min(float(prof.corner_radius_m), 0.5 * W, 0.5 * H)
        m = int(prof.corner_points)
        pts = hedge_section_points(W, H, r, m, prof.top_profile)
        v = [0.0]
        for (x0, y0), (x1, y1) in zip(pts[:-1], pts[1:]):
            v.append(v[-1] + math.hypot(x1 - x0, y1 - y0))
        sec = Section(tuple(SectionPoint(o, h, prof.material, vv, True) for (o, h), vv in zip(pts, v)), True)
        o_h = o0 + spec.back_offset + bar_step + float(hs.offset_m)
        hb = h0 + spec.hk_back - float(prof.base_sink_m)
        v_first = len(buf.v)
        t_first = len(buf.f)
        res = sweep(buf, sec, frames, side=side, lateral=o_h, height=hb, mask=mask, cap_start=True, cap_end=True,
                    cap_mat=prof.material, group="hedge:%g" % a)
        # -- noise displacement along the section-space outward normal (base row h <= 0.05 fixed)
        A = float(prof.noise_amplitude_m)
        if A > 0:
            normals2 = section_outward_normals(pts)
            rows = res.row_point
            for i in np.where(mask)[0]:
                ids = res.vidx[i]
                ok = ids >= 0
                if not ok.any():
                    continue
                ids = ids[ok]
                pk = rows[ok]
                hsec = np.array([pts[k][1] for k in pk])
                move = hsec > 0.05
                if not move.any():
                    continue
                ids = ids[move]
                pk = pk[move]
                dir_w = side * normals2[pk, 0][:, None] * frames.n[i][None, :] + normals2[pk, 1][:, None] * frames.b[i][None, :]
                q = buf.v[ids] / float(prof.noise_scale_m)
                delta = A * np.clip(noise.fbm3(q, int(prof.noise_seed)), -1.0, 1.0)
                buf.v[ids] = buf.v[ids] + delta[:, None] * dir_w
        # -- leaf cards
        fol = prof.foliage
        if fol.mode in ("cards", "instances") and fol.density_per_m2 > 0:
            F = buf.f[t_first:]
            Pa, Pb, Pc = buf.v[F[:, 0]], buf.v[F[:, 1]], buf.v[F[:, 2]]
            fn = np.cross(Pb - Pa, Pc - Pa)
            area = 0.5 * np.linalg.norm(fn, axis=1)
            # section height of the triangle relative to the hedge base (vh is above z_ref; subtract the base at the vertex)
            hrel = ((buf.vh[F[:, 0]] - np.interp(buf.vs[F[:, 0]], s, hb)) + (buf.vh[F[:, 1]] - np.interp(buf.vs[F[:, 1]], s, hb)) + (buf.vh[F[:, 2]] - np.interp(buf.vs[F[:, 2]], s, hb))) / 3.0
            seed = int(fol.seed)
            kind = "leaf_card" if fol.mode == "cards" else "foliage_mesh:%s" % (fol.mesh_id or "")
            mat = fol.material or prof.material
            size = (float(fol.card_size_m), float(fol.card_size_m), 0.0)
            tri_base = np.arange(len(F)) + t_first
            frac = noise.unit_noise01(tri_base, seed)
            counts = np.floor(area * float(fol.density_per_m2) + frac).astype(int)
            counts[hrel <= 0.05] = 0
            for ti in np.where(counts > 0)[0]:
                nrm = fn[ti] / max(np.linalg.norm(fn[ti]), 1e-12)
                for c in range(int(counts[ti])):
                    base = int(tri_base[ti]) * 4096 + 3 * c
                    u1 = float(noise.unit_noise01(base + 1, seed))
                    u2 = float(noise.unit_noise01(base + 2, seed))
                    rot = 2 * math.pi * float(noise.unit_noise01(base + 3, seed))
                    r1 = math.sqrt(u1)
                    l1, l2, l3 = 1 - r1, r1 * (1 - u2), r1 * u2
                    p = l1 * Pa[ti] + l2 * Pb[ti] + l3 * Pc[ti]
                    e = Pb[ti] - Pa[ti]
                    e = e - np.dot(e, nrm) * nrm
                    e /= max(np.linalg.norm(e), 1e-12)
                    f2 = np.cross(nrm, e)
                    tx = math.cos(rot) * e + math.sin(rot) * f2
                    ty = np.cross(nrm, tx)
                    inst.append(Instance(kind, make_transform(tx, ty, nrm, p), size, mat, spline.id, side))
    buf.compute_normals()
    return buf, inst
