"""Rail as a road-profile kind (DESIGN.md 6; geometry.md 5.7.5).  Called only from ``road.build_road``.

Ballast bed as the ribbon (top width = the profile's width_m, read through edge_offset), sleepers as
instances at phase + j * pitch, two BS113A rails as a closed 12-point section swept at plus/minus
(half the gauge plus half the head width) = 0.75243 m, the rail base (sleeper.height - embed) + pad
above the ballast top.
"""
from __future__ import annotations

from typing import List, Tuple

import numpy as np

from . import schema as S
from .instance import Instance, make_transform, box_mesh
from .mesh import MeshBuffer
from .spline import Spline
from .sweep import Section, SectionPoint, sweep


def rail_section_points(rs: S.RailSection):
    fw, ft, wt, H, hd, hw = rs.foot_width_m, rs.foot_thickness_m, rs.web_thickness_m, rs.height_m, rs.head_depth_m, rs.head_width_m
    hf, hwt, hh = 0.5 * fw, 0.5 * wt, 0.5 * hw
    return [(-hf, 0.0), (-hf, ft), (-hwt, ft + 0.019), (-hwt, H - hd), (-hh, H - hd), (-hh, H),
            (hh, H), (hh, H - hd), (hwt, H - hd), (hwt, ft + 0.019), (hf, ft), (hf, 0.0)]


def build_rail(spline: Spline, params=None) -> Tuple[MeshBuffer, List[Instance]]:
    buf = MeshBuffer()
    inst: List[Instance] = []
    rp = spline.road_profile
    spec = rp.rail
    N = spline.n
    eL = spline.edge_offset(S.LEFT)
    eR = spline.edge_offset(S.RIGHT)
    depth = float(spec.ballast.depth_m)
    k = float(spec.ballast.shoulder_slope)
    # -- ballast: open 4-point section, shoulders hard, no caps ---------------------------------
    O = np.column_stack([-(eR + depth * k), -eR, eL, eL + depth * k])
    Hh = np.column_stack([np.full(N, -depth), np.zeros(N), np.zeros(N), np.full(N, -depth)])
    bm = spec.ballast.material
    sec = Section((SectionPoint(float(O[0, 0]), -depth, bm, 0.0, True), SectionPoint(float(O[0, 1]), 0.0, bm, 1.0, False),
                   SectionPoint(float(O[0, 2]), 0.0, bm, 2.0, False), SectionPoint(float(O[0, 3]), -depth, bm, 3.0, True)), False)
    # rail is never an arm of a road junction (JunctionPlan drops rail ends -- a level crossing is not
    # a tarmac junction), so spline.active is all-true here; the mask is carried anyway so that a rail
    # spline given a trim by a future junction kind cannot silently ignore it
    sweep(buf, sec, spline.frames, side=+1, lateral=0.0, height=0.0, point_o=O, point_h=Hh,
          mask=spline.active, cap_start=False, cap_end=False, group="ballast")
    # -- sleepers -------------------------------------------------------------------------------
    sl = spec.sleeper
    L = spline.length
    js = []
    j = 0
    while sl.phase_m + j * sl.pitch_m <= L + 1e-9:
        sj = sl.phase_m + j * sl.pitch_m
        if sj >= -1e-9 and spline.s_trim[0] - 1e-9 <= sj <= spline.s_trim[1] + 1e-9:
            js.append(sj)
        j += 1
    if js:
        fr = spline.frames.at(np.array(js))
        for q in range(len(js)):
            p = fr.p[q] + (-sl.embed_m) * fr.b[q]
            M = make_transform(fr.t_h[q], fr.n[q], fr.b[q], p)
            if sl.mode == "merged":
                P, F = box_mesh(M, (sl.width_m, sl.length_m, sl.height_m))
                v0 = buf.append_vertices(P, np.zeros((8, 2)), np.full(8, js[q]), np.zeros(8), np.full(8, -sl.embed_m))
                buf.append_triangles(F + v0, buf.material_id(sl.material), buf.group_id("sleeper"))
            else:
                inst.append(Instance("sleeper", M, (sl.width_m, sl.length_m, sl.height_m), sl.material, spline.id, 0))
    # -- rails ----------------------------------------------------------------------------------
    rs = spec.rail
    pts = rail_section_points(rs)
    v = [0.0]
    for (a, b), (c, d) in zip(pts[:-1], pts[1:]):
        v.append(v[-1] + float(np.hypot(c - a, d - b)))
    rsec = Section(tuple(SectionPoint(o, h, rs.material, vv, False) for (o, h), vv in zip(pts, v)), True)
    lat = 0.5 * float(spec.gauge_m) + 0.5 * rs.head_width_m
    height = (sl.height_m - sl.embed_m) + float(spec.pad_m)
    for name, sign in (("rail:left", +1.0), ("rail:right", -1.0)):
        sweep(buf, rsec, spline.frames, side=+1, lateral=sign * lat, height=height,
              mask=spline.active, cap_start=True, cap_end=True, cap_mat=rs.material, group=name)
    buf.marking_strips = 0  # type: ignore[attr-defined]
    return buf, inst
