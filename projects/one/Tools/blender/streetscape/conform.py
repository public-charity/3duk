"""Corridor conform -- burn the road corridor into a COPY of the landscape heightmap (D3).

Why this exists
---------------
BRIEF 1.1 forbids following the raw LIDAR point for point: the road sits on a smoothed curve, and
its cross-section is a 6-12 m flat/cambered plank.  The landscape carries the raw 1 m survey.  A
plank on a rough field is below the field somewhere across its width at nearly every station -- the
whole-network measurement before this pass was 89.06 % of 666,314 stations, 866.06 km of 968.84 km,
worst 13.698 m (``projects/one/Saved/Diag/fusion_before_all.json``).  That is what "the road geometry
fuses with the landscape" means, and no smoothing window fixes it (docs/TERRAIN_ROADS.md 4.5).

So the ground under the built surface is conformed to the road.  The SURVEY product
(``data/<site>/out/terrain``) and the adapter's landscape product are never written: this pass reads
them and writes a new product beside them, with a manifest that says in words that it is no longer
the raw survey and a signed delta raster per tile that proves it cell by cell.

The rule, per 1 m landscape cell, from the cell's signed lateral offset ``d`` to the nearest point of
the road centreline (``o`` = ``edge_offset(side)``, ``back`` = kerb + pavement width on that side,
both per station from the profile data):

    |d| <= o                     the road surface itself,  z_ref + d sin B + camber(d) cos B
    o < |d| <= o + back          the kerb/pavement shelf,  held at the road-edge level
    ... + verge                  the verge,                held at the road-edge level
    ... + blend                  smoothstep back to the raw survey value of that cell

everything but the blend tail sunk by ``sink_m`` (0.03 m) so the road, kerb and pavement blocks --
which reach 0.03 m below the road-edge plane at the tuck and 0.30 m at the pavement skirt
(DESIGN.md 4.2) -- cover the ground everywhere instead of meeting it exactly.

The blend length is chosen per station and side so the fill or cut face lies at ``batter_deg``
(1:1.5, the usual earthwork batter) rather than at a fixed width: a fixed 3 m blend turns a 4 m cut
into a 53 deg wall.  It is clamped to [blend_min_m, blend_max_m].

Where two corridors cover a cell the LOWER target wins within a zone, and a nearer zone always wins
over a farther one (built surface > verge > blend).  Taking the minimum is what makes the acceptance
gate provable: no road can be penetrated by ground that another road put there.  Where the two
disagree by a lot it is a grade separation -- a bridge over the railway -- and the minimum is also
the right answer there: the ground follows the lower way and the bridge deck flies over it.

Pure numpy (DESIGN.md 14): no scipy, no GDAL, no bpy, so this runs under the env python, Blender's
python and the test suite alike.
"""
from __future__ import annotations

from dataclasses import dataclass, asdict

import numpy as np

from . import schema as S
from .spline import camber_h

RANK_SURFACE = 0        # the built surface: carriageway + kerb + pavement
RANK_VERGE = 1          # the verge shelf, still held at the road-edge level
RANK_BLEND = 2          # the smoothstep tail back to the survey
RANK_NONE = 3
_U_STEPS = 10000        # blend fraction quantisation inside the arbitration key
_RANK_STRIDE = _U_STEPS + 1
KEY_NONE = np.uint16(RANK_NONE * _RANK_STRIDE)


@dataclass
class CorridorParams:
    """Every number the burn depends on; copied verbatim into the product manifest."""
    sink_m: float = 0.03
    verge_m: float = 2.0
    blend_min_m: float = 3.0
    blend_max_m: float = 12.0
    batter_deg: float = 34.0
    lateral_step_m: float = 0.7
    station_step_m: float = 0.5
    end_overhang_m: float = 1.5
    sag_delta_m: float = 1.5
    sag_factor: float = 1.5
    apron_m: float = 1.5
    clamp_m: float = 2.0
    report_delta_m: float = 2.0
    layers: tuple = ("roads", "rail")

    def to_json(self) -> dict:
        d = asdict(self)
        d["layers"] = list(self.layers)
        d["note"] = ("corridor half-width per side = edge_offset(side) + kerb_width + pavement_width "
                     "(from the profile data, per station) + verge_m + blend; blend is per station and "
                     "side: clamp(|shelf - survey| / tan(batter_deg), blend_min_m, blend_max_m)")
        return d


@dataclass
class MosaicGrid:
    """The site's 1 m sample grid: cell centres on integer local metres, row 0 = north."""
    nx: int
    ny: int
    res: int
    tile_m: float = 512.0
    px_m: float = 1.0

    @property
    def q(self) -> int:
        return self.res - 1

    @property
    def W(self) -> int:
        return self.nx * self.q + 1

    @property
    def H(self) -> int:
        return self.ny * self.q + 1

    def tile_origin(self, i: int, j: int):
        """(row, col) of tile (i, j)'s north-west sample in the mosaic."""
        return (self.ny - 1 - j) * self.q, i * self.q

    @classmethod
    def from_manifest(cls, man: dict) -> "MosaicGrid":
        return cls(nx=int(man["nx"]), ny=int(man["ny"]), res=int(man["res"]),
                   tile_m=float(man["tile_m"]), px_m=float(man.get("px_m", 1.0)))


def smoothstep(t):
    t = np.clip(t, 0.0, 1.0)
    return t * t * (3.0 - 2.0 * t)


class ConformAccumulator:
    """The mosaic-wide arbitration.  One cell, one answer -- which is also what keeps the tile seams
    intact: a sample shared by two tiles is one cell here and is cut out of the mosaic twice."""

    def __init__(self, grid: MosaicGrid):
        self.grid = grid
        self.key = np.full((grid.H, grid.W), KEY_NONE, dtype=np.uint16)
        self.z = np.full((grid.H, grid.W), np.inf, dtype=np.float32)
        self.stats = {"contributions": 0, "cells_touched": 0, "arbitrations": 0,
                      "arbitration_max_drop_m": 0.0, "splines": 0, "splines_skipped": 0}

    # -- the write ---------------------------------------------------------------------------
    def add(self, col, row, z, rank, u=None):
        """One batch of contributions.  Duplicates inside the batch are handled by the same
        lexicographic rule as duplicates across batches: (rank, blend fraction) then lowest z."""
        if col.size == 0:
            return
        ru = (np.asarray(rank, dtype=np.int32) * _RANK_STRIDE)
        if u is not None:
            ru = ru + np.clip(np.rint(np.asarray(u) * _U_STEPS), 0, _U_STEPS).astype(np.int32)
        ru = ru.astype(np.uint16)
        idx = (np.asarray(row, dtype=np.int64) * self.grid.W + np.asarray(col, dtype=np.int64))
        z = np.asarray(z, dtype=np.float32)
        flat_key = self.key.reshape(-1)
        flat_z = self.z.reshape(-1)
        old = flat_key[idx]
        np.minimum.at(flat_key, idx, ru)
        new = flat_key[idx]
        improved = new < old
        if improved.any():                      # a nearer zone displaces whatever was there
            flat_z[idx[improved]] = np.inf
        tied = ru == new
        if tied.any():
            it, zt = idx[tied], z[tied]
            prev = flat_z[it]
            np.minimum.at(flat_z, it, zt)
            drop = prev - flat_z[it]
            hit = np.isfinite(prev) & (drop > 1e-3)
            if hit.any():
                self.stats["arbitrations"] += int(hit.sum())
                self.stats["arbitration_max_drop_m"] = max(self.stats["arbitration_max_drop_m"],
                                                           float(drop[hit].max()))
        self.stats["contributions"] += int(col.size)

    def finish(self):
        self.stats["cells_touched"] = int((self.key != KEY_NONE).sum())
        return self.stats


def quantise_h16(z, per_unit=128.0, offset=32768.0):
    """The landscape's own encoding (DESIGN.md 8): the burn is written through it, so what the test
    measures and what the engine imports are the same numbers, not the same intention."""
    return np.clip(np.rint(np.asarray(z, dtype=np.float64) * per_unit) + offset, 0, 65535)


def burn_heightfield(hf, grid: MosaicGrid, acc: "ConformAccumulator", per_unit=128.0, offset=32768.0,
                     quantise: bool = True):
    """A copy of ``hf`` with the accumulator's targets written into its tiles.  Used by the tests and
    by anything that wants the conformed field without going through the product directory."""
    import copy as _copy
    out = _copy.copy(hf)
    out.tiles = {}
    res = grid.res
    changed = 0
    for key, T in hf.tiles.items():
        i, j = key
        r0, c0 = grid.tile_origin(i, j)
        k = acc.key[r0:r0 + res, c0:c0 + res]
        zt = acc.z[r0:r0 + res, c0:c0 + res]
        m = (k != KEY_NONE) & np.isfinite(zt) & np.isfinite(T)
        A = np.array(T, dtype=np.float32)
        if m.any():
            v = np.asarray(zt, dtype=np.float64)[m]
            if quantise:
                v = (quantise_h16(v, per_unit, offset) - offset) / per_unit
            changed += int(m.sum())
            A[m] = v.astype(np.float32)
        out.tiles[key] = A
    out.source = (hf.source or "") + " +conform(%d cells)" % changed
    return out


# -------------------------------------------------------------------------------------------
def dense_stations(sp, step_m: float, overhang_m: float = 0.0, max_turn_rad: float = 0.0):
    """Uniform arc-length samples of the centreline: the stamping rays.  Only the geometry of the
    ray matters here; every height is evaluated at the exact projected station afterwards.

    ``overhang_m`` extends the rays straight on past both ends.  Without it the four cells of the
    quad the road's own end vertex sits in are only partly stamped, and the unstamped corner keeps a
    survey height that can still be above the cap -- measured at 9.3 mm on the first smoke run.  The
    height carried out over the overhang is the end cross-section (the station is clamped to
    [0, L]), which is also what closes the 1-2 m gap where a side road stops short of the way it
    joins.

    ``max_turn_rad`` bounds how far the ray may swing between two samples.  Where a way turns
    sharply the perpendicular rays fan out and leave an unstamped wedge on the OUTSIDE of the
    corner, which the road ribbon's own quad covers -- 19 mm of ground left standing in the
    carriageway of roads:851451479:0 before this was added.  Extra rays are inserted there with the
    position and the direction both interpolated, which is exactly the surface the quad sweeps."""
    step = max(step_m, 1e-6)
    n = max(2, int(np.ceil(sp.length / step)) + 1)

    def frames_at(u):
        x = np.interp(u, sp.s, sp.xy[:, 0])
        y = np.interp(u, sp.s, sp.xy[:, 1])
        tx = np.interp(u, sp.s, sp.t_h_xy[:, 0])
        ty = np.interp(u, sp.s, sp.t_h_xy[:, 1])
        L = np.hypot(tx, ty)
        L[L < 1e-12] = 1.0
        return x, y, tx / L, ty / L

    # every STATION is a ray, not only the uniform grid: the ribbon's rows are the stations, so a
    # station missing from the sweep is a row of road whose ground was never claimed.  Splines whose
    # last few stations sit inside a few centimetres with the tangent swinging 90 degrees (a
    # Catmull-Rom tail on a near-duplicate end point -- roads:30893057:0, roads:169730575:0) are the
    # ones that showed it.
    sd = np.unique(np.concatenate([np.linspace(0.0, sp.length, n), sp.s]))
    x, y, tx, ty = frames_at(sd)
    if max_turn_rad > 0.0 and len(sd) > 2:
        dot = np.clip(tx[:-1] * tx[1:] + ty[:-1] * ty[1:], -1.0, 1.0)
        m = np.maximum(1, np.ceil(np.arccos(dot) / max_turn_rad).astype(np.int64))
        m = np.minimum(m, 256)
        if (m > 1).any():
            idx = np.repeat(np.arange(len(sd) - 1), m)
            off = np.arange(m.sum()) - np.repeat(np.cumsum(m) - m, m)
            f = off / np.repeat(m, m).astype(np.float64)
            sd = np.append(sd[idx] + f * (sd[idx + 1] - sd[idx]), sd[-1])
            # re-interpolated, never lerped between the two ends: the tangent between two rays does not
            # have to lie between their tangents, and lerping it misses exactly the swing that needs
            # the extra rays.
            x, y, tx, ty = frames_at(sd)
    if overhang_m > 0.0:
        m0 = int(np.ceil(overhang_m / step))
        e = np.arange(1, m0 + 1) * step
        sd = np.concatenate([-e[::-1], sd, sp.length + e])
        x = np.concatenate([x[0] - e[::-1] * tx[0], x, x[-1] + e * tx[-1]])
        y = np.concatenate([y[0] - e[::-1] * ty[0], y, y[-1] + e * ty[-1]])
        tx = np.concatenate([np.full(m0, tx[0]), tx, np.full(m0, tx[-1])])
        ty = np.concatenate([np.full(m0, ty[0]), ty, np.full(m0, ty[-1])])
    return sd, x, y, tx, ty


def corridor_half_widths(sp):
    """(N,) per-station built-surface half width per side, from the profile data.

    ``edge_offset`` is the edge contract (DESIGN.md 3.6) -- carriageway plus any parking-bay extra --
    and ``SideSpec.back_offset`` is kerb width + pavement width for that side.  Nothing here computes
    ``width / 2``."""
    out = {}
    for side in (S.LEFT, S.RIGHT):
        spec = sp.side_spec[side]
        back = np.asarray(spec.back_offset, dtype=np.float64) if spec.has_kerb_or_pavement else np.zeros(sp.n)
        out[side] = (np.asarray(sp.edge_offset(side), dtype=np.float64), back)
    return out


def shelf_levels(sp, params: CorridorParams, z_raw_at):
    """Per station and side: the shelf level the built surface holds, the survey level under the far
    edge of the verge, the signed earthwork (shelf - survey; + fills, - cuts) and the blend length
    that puts the fill or cut face at ``batter_deg``.

    Shared by the burn and by the clamped-run report, so the runs handed to the geometry track for
    embankments are exactly the places the burn moved the ground the most."""
    halves = corridor_half_widths(sp)
    sinb = np.sin(np.radians(sp.bank_deg))
    cosb = np.cos(np.radians(sp.bank_deg))
    nfx, nfy = -sp.t_h_xy[:, 1], sp.t_h_xy[:, 0]
    tanb = max(np.tan(np.radians(params.batter_deg)), 1e-3)
    out = {}
    for side in (S.LEFT, S.RIGHT):
        o, back = halves[side]
        core = o + back
        zsh = sp.z_ref + side * o * sinb + sp.surface_h(side * o) * cosb - params.sink_m
        off = float(side) * (core + params.verge_m) * cosb
        zr = z_raw_at(sp.xy[:, 0] + off * nfx, sp.xy[:, 1] + off * nfy)
        earth = zsh - zr
        blend = np.clip(np.abs(np.where(np.isfinite(earth), earth, 0.0)) / tanb,
                        params.blend_min_m, params.blend_max_m)
        out[side] = {"o": o, "core": core, "shelf_z": zsh, "raw_z": zr, "earthwork_m": earth,
                     "blend_m": blend}
    return out


def spline_targets(sp, params: CorridorParams, z_raw_at, stats=None):
    """Yield ``(cx, cy, z, rank, u)`` batches: cell centres in LOCAL METRES (integer valued, x east /
    y north from the site origin -- the caller turns them into mosaic row/col), the target height,
    the zone rank and the blend fraction.

    ``z_raw_at(x, y)`` samples the *unconformed* landscape (the blend tail has to reach the survey
    value of the very cell it is writing, or the corridor edge would step)."""
    halves = corridor_half_widths(sp)
    oL, backL = halves[S.LEFT]
    oR, backR = halves[S.RIGHT]
    coreL = oL + backL
    coreR = oR + backR
    reach_L = coreL + params.verge_m + params.blend_max_m
    reach_R = coreR + params.verge_m + params.blend_max_m
    kinds = np.array(sp.camber_kind, dtype=object)
    sinb = np.sin(np.radians(sp.bank_deg))
    cosb = np.cos(np.radians(sp.bank_deg))

    # the shelf level per station and side, and the survey level under the far edge of the verge:
    # together they set how long the blend has to be for a batter_deg face.
    shelf = shelf_levels(sp, params, z_raw_at)
    # shelf_z already carries the sink; the zone evaluator adds it back for the road surface itself
    zshelf = {side: shelf[side]["shelf_z"] + params.sink_m for side in (S.LEFT, S.RIGHT)}
    blend = {side: shelf[side]["blend_m"] for side in (S.LEFT, S.RIGHT)}

    reach_max = float(max(np.max(reach_L + blend[S.LEFT]), np.max(reach_R + blend[S.RIGHT])))
    sd, dx, dy, dtx, dty = dense_stations(sp, params.station_step_m, params.end_overhang_m,
                                          max_turn_rad=0.5 / max(reach_max, 1e-3))
    dnx, dny = -dty, dtx
    sd_c = np.clip(sd, 0.0, sp.length)
    reach_d = np.maximum(np.interp(sd_c, sp.s, reach_L + blend[S.LEFT]),
                         np.interp(sd_c, sp.s, reach_R + blend[S.RIGHT]))
    valid_d = np.isfinite(np.interp(sd_c, sp.s, sp.z_ref))

    step = max(params.lateral_step_m, 1e-3)
    block = max(1, int(200000 / max(int(np.ceil(2 * reach_d.max() / step)) + 1, 1)))
    for a in range(0, len(sd), block):
        b = min(a + block, len(sd))
        R = float(reach_d[a:b].max())
        lat = np.arange(-R, R + 0.5 * step, step)
        if lat.size == 0:
            continue
        keep = valid_d[a:b]
        if not keep.any():
            continue
        PX = (dx[a:b, None] + lat[None, :] * dnx[a:b, None]).ravel()
        PY = (dy[a:b, None] + lat[None, :] * dny[a:b, None]).ravel()
        # Every ladder point claims the FOUR cells of the unit square it falls in, not just the
        # nearest one: a cell is stamped whenever a ladder point lands within 1 m of it in x and y.
        # Rounding to the nearest cell only reaches 0.5 m, and that is not enough where the rays fan
        # out -- a way whose last five stations sit inside 8 cm with the tangent swinging 90 deg
        # (roads:30893057:0) left its own carriageway cell unstamped and 0.096 m of ground standing
        # in it.  Each stamped cell is then projected on its own, so the extra reach costs coverage,
        # never accuracy.
        fx, fy = np.floor(PX), np.floor(PY)
        cx = np.concatenate([fx, fx + 1.0, fx, fx + 1.0])
        cy = np.concatenate([fy, fy, fy + 1.0, fy + 1.0])
        rep = lambda v: np.tile(np.repeat(v[a:b], lat.size), 4)          # noqa: E731
        ex = cx - rep(dx)
        ey = cy - rep(dy)
        tX = rep(dtx)
        tY = rep(dty)
        along = ex * tX + ey * tY
        latc = ex * (-tY) + ey * tX
        s_star = rep(sd) + along
        ok = np.tile(np.repeat(keep, lat.size), 4)
        if not ok.any():
            continue
        cx, cy, latc, s_star = cx[ok], cy[ok], latc[ok], s_star[ok]
        yield _evaluate(sp, params, cx, cy, latc, s_star, kinds, sinb, cosb,
                        oL, oR, coreL, coreR, zshelf, blend, z_raw_at, stats)


def built_surface(sp, s_star, d, kinds, sinb, cosb, oL, oR):
    """The height of the BUILT surface at (arc position, signed lateral offset), laterally clamped to
    the kerb line so that beyond the carriageway it returns the road-edge level -- the shelf the kerb,
    pavement and verge are held at.  One function, so the burn, the sag correction and the shelf all
    speak about the same surface."""
    s_star = np.clip(s_star, 0.0, sp.length)
    z_ref = np.interp(s_star, sp.s, sp.z_ref)
    sb = np.interp(s_star, sp.s, sinb)
    cb = np.interp(s_star, sp.s, cosb)
    o_l = np.interp(s_star, sp.s, oL)
    o_r = np.interp(s_star, sp.s, oR)
    dc = np.clip(d, -o_r, o_l)
    k = np.clip(np.searchsorted(sp.s, s_star, side="right") - 1, 0, sp.n - 1)
    w = np.interp(s_star, sp.s, sp.width)
    cf = np.interp(s_star, sp.s, sp.crossfall_pct)
    cm = np.interp(s_star, sp.s, sp.camber_m)
    return z_ref + dc * sb + camber_h(kinds[k], w, cf, cm, dc) * cb


def sag_correction(sp, s_star, d, kinds, sinb, cosb, oL, oR, base, delta, factor=1.0):
    """How far the LANDSCAPE can rise above the road between two cells, and therefore how much
    further the burn has to sink.

    The landscape interpolates linearly between its 1 m posts; the road surface does not have to be
    linear between them.  Where the surface is convex -- the sag of a vertical curve, the kink where
    a steep OSM way leaves its junction, the corner where the cambered carriageway meets the flat
    kerb shelf -- the straight line between two burned posts lies ABOVE the surface it was burned
    from, and the road fuses again by exactly that much.  Measured on the A-road at Manston
    (roads:32352025:0 station 0, a 145 % grade off the junction) it was 0.264 m, the single worst
    residual of the first full run.

    The excess is the second difference, so subtract it: one term along the road, one across it, each
    clamped at zero because a crest (concave) interpolates BELOW the surface and needs nothing.  It is
    measured at several half-spans up to ``delta`` and the largest kept, because a kink shorter than
    the span reads as almost straight at that span: on the cliff footway roads:1387728616:0, whose
    z_ref climbs 9.3 -> 19.6 m in 2.5 m, the 1.5 m span alone left 0.472 m standing.  A straight grade,
    however steep, has a second difference of zero at every span and is not touched -- which is why
    this is the correction and a plain minimum over a stencil is not (that would sink a 10 % grade by
    a tenth of the span and make the road float)."""
    out = None
    for f in (1.0, 2.0 / 3.0, 1.0 / 3.0):
        h = delta * f
        a = built_surface(sp, s_star + h, d, kinds, sinb, cosb, oL, oR)
        b = built_surface(sp, s_star - h, d, kinds, sinb, cosb, oL, oR)
        c = built_surface(sp, s_star, d + h, kinds, sinb, cosb, oL, oR)
        e = built_surface(sp, s_star, d - h, kinds, sinb, cosb, oL, oR)
        v = np.maximum(0.0, 0.5 * (a + b) - base) + np.maximum(0.0, 0.5 * (c + e) - base)
        out = v if out is None else np.maximum(out, v)
    return out * factor


def _evaluate(sp, params, cx, cy, lat, s_star, kinds, sinb, cosb,
              oL, oR, coreL, coreR, zshelf, blend, z_raw_at, stats=None):
    s_star = np.clip(s_star, 0.0, sp.length)
    cb = np.interp(s_star, sp.s, cosb)
    left = lat >= 0.0
    o = np.where(left, np.interp(s_star, sp.s, oL), np.interp(s_star, sp.s, oR))
    core = np.where(left, np.interp(s_star, sp.s, coreL), np.interp(s_star, sp.s, coreR))
    bl = np.where(left, np.interp(s_star, sp.s, blend[S.LEFT]), np.interp(s_star, sp.s, blend[S.RIGHT]))
    d = lat / np.where(np.abs(cb) > 1e-6, cb, 1.0)
    ad = np.abs(d)

    reach = core + params.verge_m + bl
    inside = ad <= core + params.verge_m
    rank = np.full(cx.shape, RANK_NONE, dtype=np.int32)
    z = np.full(cx.shape, np.nan)
    u = np.zeros(cx.shape)

    if inside.any():
        si, di = s_star[inside], d[inside]
        base = built_surface(sp, si, di, kinds, sinb, cosb, oL, oR)
        sag = sag_correction(sp, si, di, kinds, sinb, cosb, oL, oR, base, params.sag_delta_m,
                             params.sag_factor)
        zi = base - params.sink_m - sag
        idx = np.where(inside)[0]
        # the apron: cells outside the built surface but close enough that the landscape's linear
        # interpolation at the pavement's outer edge reads them.  They arbitrate as built surface, so a
        # neighbouring way cannot raise them and push its ground up through this way's pavement --
        # measured at 0.121 m on the A299 slip road before this was added.
        rank[idx] = np.where(ad[inside] <= core[inside] + params.apron_m, RANK_SURFACE, RANK_VERGE)
        z[idx] = zi

    m_blend = (~inside) & (ad <= reach)
    if m_blend.any():
        sb_ = s_star[m_blend]
        db = d[m_blend]
        side_o = np.where(db >= 0, 1.0, -1.0) * (core[m_blend] + params.verge_m)
        shelf = built_surface(sp, sb_, side_o, kinds, sinb, cosb, oL, oR)
        shelf = shelf - params.sink_m - sag_correction(sp, sb_, side_o, kinds, sinb, cosb, oL, oR,
                                                       shelf, params.sag_delta_m, params.sag_factor)
        t = (ad[m_blend] - (core[m_blend] + params.verge_m)) / np.maximum(bl[m_blend], 1e-6)
        zr = z_raw_at(cx[m_blend], cy[m_blend])
        wgt = smoothstep(t)
        zb = (1.0 - wgt) * shelf + wgt * zr
        good = np.isfinite(zb)
        sel = np.where(m_blend)[0][good]
        rank[sel] = RANK_BLEND
        z[sel] = zb[good]
        u[sel] = t[good]

    # Outside the built surface and its apron the ground may move by at most `clamp_m`.  Without it a
    # cliff-top way whose verge edge hangs 17 m over the beach builds a 17 m earth shelf out of the
    # chalk face, and a promenade under a cliff cuts a 14 m notch into it -- measured on
    # roads:28875046:0 (+17.472 m) and roads:179363634:0 (-14.624 m).  The BUILT surface is never
    # clamped: it is what the acceptance gate is about, and clamping it would be the fusion again.
    # The step left at the apron edge is a real retaining wall or embankment, and its run is written
    # to conform_clamped.json for Renderer B (BRIEF 1.1's own answer to this case).
    m_out = (rank == RANK_VERGE) | (rank == RANK_BLEND)
    if params.clamp_m > 0 and m_out.any():
        zr = z_raw_at(cx[m_out], cy[m_out])
        zc = np.clip(z[m_out], zr - params.clamp_m, zr + params.clamp_m)
        good = np.isfinite(zr)
        hit = good & (np.abs(zc - z[m_out]) > 1e-9)
        z[np.where(m_out)[0][good]] = zc[good]
        if stats is not None:
            stats["cells_clamped"] = stats.get("cells_clamped", 0) + int(hit.sum())

    keep = (rank != RANK_NONE) & np.isfinite(z)
    return cx[keep], cy[keep], z[keep], rank[keep], u[keep]
