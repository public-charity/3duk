"""The shared spline (DESIGN.md 3, SCHEMA.md 3; geometry.md 5.4).

Build order (every step is a module-level function so the tests can call them alone):
  merge_points -> catmull_rom_dense -> resolve timelines (schema.py) -> adaptive_stations with the
  mandatory set -> width / extras / roll -> heights (terrain sample, fill, moving average, pins) ->
  bank (probes, moving average, clamp, roll mask, rate limit) -> Frames -> SideSpec per side.

The edge contract: ``Spline.edge_offset(side)`` (= w/2 + extra(side)) and ``Spline.edge_height(side)``
are the ONLY functions in the package that know where the kerb line is (DESIGN.md 3.6).  road.py,
edge.py and hedge.py never compute width/2 themselves (tests/test_examples.py greps for it).
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Dict, List, Optional

import numpy as np

from . import schema as S
from .terrain import Heightfield

Z_AXIS = np.array([0.0, 0.0, 1.0])


# --------------------------------------------------------------------------------------------
# 5.4.0 duplicate merge
# --------------------------------------------------------------------------------------------

def merge_points(points: List[S.Point], tol: float = 1e-6):
    """Merge consecutive points closer than tol (later point's z/roll/width win, tags unioned).
    Returns (merged list, number merged)."""
    out: List[S.Point] = []
    merged = 0
    for p in points:
        if out and np.hypot(p.x - out[-1].x, p.y - out[-1].y) < tol:
            q = out[-1]
            out[-1] = S.Point(x=p.x, y=p.y,
                              z=p.z if p.z is not None else q.z,
                              roll_deg=p.roll_deg if p.roll_deg is not None else q.roll_deg,
                              width_m=p.width_m if p.width_m is not None else q.width_m,
                              tags=list(dict.fromkeys(list(q.tags) + list(p.tags))))
            merged += 1
        else:
            out.append(S.Point(x=p.x, y=p.y, z=p.z, roll_deg=p.roll_deg, width_m=p.width_m, tags=list(p.tags)))
    return out, merged


# --------------------------------------------------------------------------------------------
# 5.4.1 curve
# --------------------------------------------------------------------------------------------

def catmull_rom_dense(P: np.ndarray, alpha: float = 0.5, max_chord_m: float = 0.1):
    """Centripetal Catmull-Rom through P (K, 2).  Returns (s_d (D,), xy_d (D, 2), s_knots (K,))."""
    P = np.asarray(P, dtype=np.float64)
    K = len(P)
    if K < 2:
        raise ValueError("a spline needs at least two distinct points")
    if K == 2:
        chord = float(np.hypot(*(P[1] - P[0])))
        n = max(8, int(np.ceil(chord / max_chord_m))) + 1
        t = np.linspace(0.0, 1.0, n)[:, None]
        xy = P[0] + t * (P[1] - P[0])
        seg = np.hypot(np.diff(xy[:, 0]), np.diff(xy[:, 1]))
        s = np.concatenate([[0.0], np.cumsum(seg)])
        return s, xy, np.array([0.0, s[-1]])
    ext = np.vstack([2 * P[0] - P[1], P, 2 * P[-1] - P[-2]])
    pieces = []
    knots = [0.0]
    total = 0.0
    for i in range(K - 1):
        P0, P1, P2, P3 = ext[i], ext[i + 1], ext[i + 2], ext[i + 3]
        chord = float(np.hypot(*(P2 - P1)))
        n = max(8, int(np.ceil(chord / max_chord_m))) + 1
        t0 = 0.0
        t1 = t0 + float(np.hypot(*(P1 - P0))) ** alpha
        t2 = t1 + chord ** alpha
        t3 = t2 + float(np.hypot(*(P3 - P2))) ** alpha
        # degenerate phantom spacing (phantom coincides) cannot happen: |P1-P0| = |P2-P1| > 0 at the ends
        t = np.linspace(t1, t2, n)[:, None]
        A1 = (t1 - t) / (t1 - t0) * P0 + (t - t0) / (t1 - t0) * P1
        A2 = (t2 - t) / (t2 - t1) * P1 + (t - t1) / (t2 - t1) * P2
        A3 = (t3 - t) / (t3 - t2) * P2 + (t - t2) / (t3 - t2) * P3
        B1 = (t2 - t) / (t2 - t0) * A1 + (t - t0) / (t2 - t0) * A2
        B2 = (t3 - t) / (t3 - t1) * A2 + (t - t1) / (t3 - t1) * A3
        C = (t2 - t) / (t2 - t1) * B1 + (t - t1) / (t2 - t1) * B2
        C[0] = P1
        C[-1] = P2
        seg = np.hypot(np.diff(C[:, 0]), np.diff(C[:, 1]))
        total += float(seg.sum())
        knots.append(total)
        pieces.append(C if i == 0 else C[1:])
    xy = np.vstack(pieces)
    seg = np.hypot(np.diff(xy[:, 0]), np.diff(xy[:, 1]))
    s = np.concatenate([[0.0], np.cumsum(seg)])
    knots = np.array(knots)
    knots[-1] = s[-1]
    return s, xy, knots


def dense_tangents(xy: np.ndarray):
    """Unit tangent at every dense point (central differences, forward/backward at the ends)."""
    d = np.gradient(xy, axis=0)
    n = np.hypot(d[:, 0], d[:, 1])
    n[n == 0] = 1.0
    return d / n[:, None]


def dense_curvature(s_d: np.ndarray, xy_d: np.ndarray):
    """(kappa_abs (D,), kappa_signed (D,)) = |dT/ds| from consecutive unit tangents of the dense curve."""
    T = dense_tangents(xy_d)
    dT = np.gradient(T, axis=0)
    ds = np.gradient(s_d)
    ds[ds == 0] = 1e-12
    kappa = np.hypot(dT[:, 0], dT[:, 1]) / ds
    cross = T[:, 0] * dT[:, 1] - T[:, 1] * dT[:, 0]
    return kappa, np.where(cross >= 0, kappa, -kappa)


# --------------------------------------------------------------------------------------------
# 5.4.2 stations
# --------------------------------------------------------------------------------------------

def adaptive_stations(s_d: np.ndarray, kappa_d: np.ndarray, sampling: S.Sampling, mandatory) -> np.ndarray:
    """March step(k) = clip(step_m / (1 + gain k), min_step, step_m); merge with the mandatory set.

    What this guarantees, exactly (``expected.json`` ``stationing``; asserted by
    ``test_spline.TestStationingGuarantee`` on every fixture):

      * every gap <= ``step_m + min_step_m``.  The march stops while ``s + step_at(s) < L - min_step``
        and then appends ``L``, so the FINAL gap alone may exceed ``step_m`` by up to ``min_step``;
        every adaptive-to-adaptive gap before it is <= ``step_m``.
      * NO lower bound.  Mandatory stations (waypoints, segment/marking boundaries, drop kerbs and their
        ramps -- SCHEMA.md 3.2) are deduped only within 1e-9, so two of them may land arbitrarily close;
        ``min_step_m`` bounds the adaptive march, not the realised gaps.  Adaptive stations within
        ``min_step/2`` of a mandatory one are dropped, which is why a mandatory station never *adds* a
        short gap next to an adaptive one -- only next to another mandatory one.

    Tightening either bound would change N for every spline, hence ``fixtures/expected.json``, the frozen
    parity reference and the C++ ``FStreetSplineMath`` port that reproduces them bit for bit; do not
    change the march without that whole chain."""
    L = float(s_d[-1])
    step_m = float(sampling.step_m)
    min_step = float(sampling.min_step_m)
    gain = float(sampling.curvature_gain)

    def step_at(s):
        k = float(np.interp(s, s_d, kappa_d))
        return float(np.clip(step_m / (1.0 + gain * k), min_step, step_m))

    adaptive = [0.0]
    s = 0.0
    while s + step_at(s) < L - min_step:
        s += step_at(s)
        adaptive.append(s)
    adaptive.append(L)
    mand = sorted(set(float(m) for m in mandatory if 0.0 < m < L))
    # dedupe mandatory stations within 1e-9 of each other (keep the first)
    md: List[float] = []
    for m in mand:
        if not md or m - md[-1] > 1e-9:
            md.append(m)
    mand = md
    if mand:
        marr = np.array(mand)
        keep = []
        for a in adaptive:
            j = np.searchsorted(marr, a)
            near = False
            for jj in (j - 1, j):
                if 0 <= jj < len(marr) and abs(a - marr[jj]) <= min_step / 2 + 1e-12:
                    near = True
            if not near:
                keep.append(a)
        adaptive = keep
    st = np.array(sorted(set(adaptive) | set(mand)))
    if st[0] != 0.0:
        st = np.concatenate([[0.0], st])
    if st[-1] != L:
        st = np.concatenate([st, [L]])
    return st


# --------------------------------------------------------------------------------------------
# 5.4.3 width (the ONE definition; Spline and JunctionPlan both call it)
# --------------------------------------------------------------------------------------------

def resolve_widths(pts, s_knots, road_prof, road_tl, s):
    """(width (M,), {side: extra (M,)}) at arc lengths ``s``.

    Extracted so ``JunctionPlan`` can ask for the half-width at a candidate trim station without
    building the whole ``Spline`` (which needs terrain) and without a second transcription of the
    width rule -- ``Spline.edge_offset`` stays the only place that adds ``w/2 + extra`` together."""
    s = np.atleast_1d(np.asarray(s, dtype=np.float64))
    base_w = float(road_prof.width_m) if road_prof is not None else 0.0
    w_knots = np.array([base_w if (p.width_m is None or road_prof is None) else float(p.width_m) for p in pts])
    w = np.interp(s, s_knots, w_knots)
    for o in road_tl.width_overrides:
        w = S.apply_ramped_override(s, w, o.s0, o.s1, o.ramp, o.value)
    extra = {}
    for side in (S.LEFT, S.RIGHT):
        e = np.zeros(len(s))
        for o in road_tl.extra_overrides[side]:
            e = S.apply_ramped_override(s, e, o.s0, o.s1, o.ramp, o.value)
        extra[side] = e
    return w, extra


# --------------------------------------------------------------------------------------------
# 5.4.5 heights
# --------------------------------------------------------------------------------------------

def fill_nan_along(z: np.ndarray):
    """Carry the nearest valid value forward then backward; all-NaN -> zeros.  Returns (filled, all_nan)."""
    z = np.array(z, dtype=np.float64, copy=True)
    ok = np.isfinite(z)
    if not ok.any():
        return np.zeros_like(z), True
    idx = np.where(ok, np.arange(len(z)), -1)
    np.maximum.accumulate(idx, out=idx)
    first = int(np.argmax(ok))
    idx[idx < 0] = first
    out = z[idx]
    # backward fill for the leading NaNs (already handled by 'first'); forward fill above
    return out, False


def moving_average_arclength(s: np.ndarray, z: np.ndarray, W: float, passes: int = 1) -> np.ndarray:
    """Centred ARC-LENGTH moving average with the window shrinking to zero at both ends:
    hw_i = min(W/2, s_i - s_0, s_N - s_i); z'_i = (1 / 2 hw_i) * integral of the piecewise-linear z(s)
    over [s_i - hw_i, s_i + hw_i] (trapezoidal weights, so the result does not depend on how densely
    the stations happen to be placed inside the window; hw_i = 0 -> z_i).  Passes repeat it."""
    s = np.asarray(s, dtype=np.float64)
    z = np.array(z, dtype=np.float64, copy=True)
    if passes <= 0 or W <= 0 or len(s) < 3:
        return z
    hw = np.minimum(np.minimum(W / 2.0, s - s[0]), s[-1] - s)
    a = s - hw
    b = s + hw
    ka = np.clip(np.searchsorted(s, a, side="right") - 1, 0, len(s) - 2)   # segment containing a
    kb = np.clip(np.searchsorted(s, b, side="right") - 1, 0, len(s) - 2)   # segment containing b
    ds = np.diff(s)
    for _ in range(int(passes)):
        seg = 0.5 * (z[1:] + z[:-1]) * ds
        C = np.concatenate([[0.0], np.cumsum(seg)])               # C[k] = integral_0^{s_k} z ds

        def cum_at(x, k):
            zx = z[k] + (z[k + 1] - z[k]) * (x - s[k]) / ds[k]
            return C[k] + (x - s[k]) * 0.5 * (z[k] + zx)
        Ia = cum_at(a, ka)
        Ib = cum_at(b, kb)
        width = b - a
        out = np.where(width > 1e-12, (Ib - Ia) / np.where(width > 1e-12, width, 1.0), z)
        z = out
    return z


def apply_pins(z: np.ndarray, s: np.ndarray, pins, blend: float) -> np.ndarray:
    """pins: [(s_k, z_pin)]; z += (z_pin - z(s_k)) * max(0, 1 - |s - s_k| / blend)."""
    z = np.array(z, dtype=np.float64, copy=True)
    for s_k, z_pin in pins:
        z_at = float(np.interp(s_k, s, z))
        w = np.maximum(0.0, 1.0 - np.abs(s - s_k) / blend)
        z = z + (z_pin - z_at) * w
    return z


# --------------------------------------------------------------------------------------------
# 5.4.6 bank
# --------------------------------------------------------------------------------------------

def camber_h(kinds, w, cf, cm, d) -> np.ndarray:
    """Camber height at signed lateral offset ``d`` (DESIGN.md 4.1), broadcast over its arguments.

    The one definition of the road surface's cross-section: ``Spline.surface_h`` is this function
    evaluated per station, and ``conform.py`` is this function evaluated per 1 m landscape cell at an
    interpolated station -- so the ground burned under the carriageway is the carriageway, by
    construction rather than by a second transcription of the formula.

    ``kinds`` is an object array (or scalar) of "parabolic" | "planar" | "none"; ``w`` the surface
    width, ``cf`` the crossfall percentage, ``cm`` an explicit camber height in metres (NaN = derive
    it from ``cf``).
    """
    d = np.asarray(d, dtype=np.float64)
    with np.errstate(divide="ignore", invalid="ignore"):
        c = np.where(np.isfinite(cm), cm, (cf / 100.0) * w / 4.0)
        para = np.where(w > 0, -c * (2.0 * d / np.where(w > 0, w, 1.0)) ** 2, 0.0)
    planar = -(cf / 100.0) * np.abs(d)
    return np.where(kinds == "parabolic", para, np.where(kinds == "planar", planar, 0.0))


def rate_limit(beta: np.ndarray, s: np.ndarray, r: float) -> np.ndarray:
    """Forward then backward pass: |d beta / ds| <= r (deg/m)."""
    b = np.array(beta, dtype=np.float64, copy=True)
    if r <= 0 or len(b) < 2:
        return b
    ds = np.diff(s)
    for i in range(1, len(b)):
        lim = r * ds[i - 1]
        b[i] = min(max(b[i], b[i - 1] - lim), b[i - 1] + lim)
    for i in range(len(b) - 2, -1, -1):
        lim = r * ds[i]
        b[i] = min(max(b[i], b[i + 1] - lim), b[i + 1] + lim)
    return b


# --------------------------------------------------------------------------------------------
# 5.4.7 frames
# --------------------------------------------------------------------------------------------

def _unit(v: np.ndarray) -> np.ndarray:
    n = np.linalg.norm(v, axis=-1, keepdims=True)
    n[n == 0] = 1.0
    return v / n


@dataclass
class Frames:
    s: np.ndarray       # (N,)
    p: np.ndarray       # (N, 3) position incl. z_ref
    t_h: np.ndarray     # (N, 3) unit horizontal tangent
    n_flat: np.ndarray  # (N, 3) Z x t_h
    n: np.ndarray       # (N, 3) banked left normal
    b: np.ndarray       # (N, 3) t_h x n

    @staticmethod
    def build(s, p, t_h, bank_deg) -> "Frames":
        t_h = _unit(np.asarray(t_h, dtype=np.float64))
        n_flat = np.stack([-t_h[:, 1], t_h[:, 0], np.zeros(len(t_h))], axis=1)
        beta = np.radians(np.asarray(bank_deg, dtype=np.float64))
        n = n_flat * np.cos(beta)[:, None] + Z_AXIS[None, :] * np.sin(beta)[:, None]
        b = np.cross(t_h, n)
        return Frames(np.asarray(s, dtype=np.float64), np.asarray(p, dtype=np.float64), t_h, n_flat, n, b)

    def __len__(self):
        return len(self.s)

    def at(self, s_query) -> "Frames":
        """Frames at arbitrary s: p linear, t_h / n interpolated and renormalised, b = t_h x n."""
        sq = np.atleast_1d(np.asarray(s_query, dtype=np.float64))
        p = np.stack([np.interp(sq, self.s, self.p[:, k]) for k in range(3)], axis=1)
        t_h = _unit(np.stack([np.interp(sq, self.s, self.t_h[:, k]) for k in range(3)], axis=1))
        n = np.stack([np.interp(sq, self.s, self.n[:, k]) for k in range(3)], axis=1)
        n = n - np.sum(n * t_h, axis=1, keepdims=True) * t_h
        n = _unit(n)
        n_flat = _unit(np.cross(Z_AXIS[None, :], t_h))
        b = np.cross(t_h, n)
        return Frames(sq, p, t_h, n_flat, n, b)

    def insert(self, s_extra) -> "Frames":
        """Union of the stations with s_extra (duplicates within 1e-9 dropped, existing frames kept exact)."""
        extra = np.atleast_1d(np.asarray(s_extra, dtype=np.float64))
        extra = extra[(extra >= self.s[0]) & (extra <= self.s[-1])]
        new = []
        for e in np.unique(extra):
            j = np.searchsorted(self.s, e)
            near = (j < len(self.s) and abs(self.s[j] - e) <= 1e-9) or (j > 0 and abs(self.s[j - 1] - e) <= 1e-9)
            if not near and (not new or e - new[-1] > 1e-9):
                new.append(e)
        if not new:
            return self
        fx = self.at(np.array(new))
        s_all = np.concatenate([self.s, fx.s])
        order = np.argsort(s_all, kind="stable")
        cat = lambda a, b: np.concatenate([a, b])[order]  # noqa: E731
        return Frames(s_all[order], cat(self.p, fx.p), cat(self.t_h, fx.t_h), cat(self.n_flat, fx.n_flat),
                      cat(self.n, fx.n), cat(self.b, fx.b))

    def subset(self, mask: np.ndarray) -> "Frames":
        return Frames(self.s[mask], self.p[mask], self.t_h[mask], self.n_flat[mask], self.n[mask], self.b[mask])


# --------------------------------------------------------------------------------------------
# the Spline
# --------------------------------------------------------------------------------------------

class Spline:
    """Everything the renderers read, built once from a SplineDef + Site + Heightfield."""

    def __init__(self, sdef: S.SplineDef, site: S.Site, terrain: Heightfield, trim=None):
        """``trim`` = ``(t_start, t_end)`` arc lengths, in metres, cut off each end because that end
        stands in a junction (SCHEMA.md 4.18).  It is resolved once per site by ``JunctionPlan`` and
        handed in here, so Renderer A and Renderer B read ONE trimmed extent and cannot drift.

        The trim is a MASK, not a re-basing of s.  s is the document's own coordinate: every
        ``Segment.s0_m/s1_m``, marking interval, drop kerb, barrier run and hedge run in the JSON is
        expressed in it, and ``Junction.ends`` is per end.  Re-basing would silently move every
        authored s, would have to be mirrored in the adapter and in the C++ port, and would make
        ``length_m`` mean something different from the document.  Masking changes only which stations
        are EMITTED: ``self.length`` stays the document's arc length, ``self.s`` still spans [0, L],
        every timeline keeps its meaning, and the two trim stations are added to the mandatory set so
        they exist EXACTLY (``s[active][0] == s_trim[0]``) in every renderer's station list."""
        self.sdef = sdef
        self.site = site
        self.id = sdef.id
        self.warnings: List[str] = []
        terrain = terrain.rebased(site.origin.E, site.origin.N) if terrain is not None else None
        self.terrain = terrain

        # -- points and curve
        pts, merged = merge_points(sdef.points)
        self.points = pts
        self.points_merged = merged
        if merged:
            self.warnings.append("%d consecutive duplicate point(s) merged" % merged)
        if len(pts) < 2:
            raise S.SchemaError(["spline %s: fewer than 2 distinct points" % sdef.id])
        P = np.array([[p.x, p.y] for p in pts])
        s_d, xy_d, s_knots = catmull_rom_dense(P)
        self.s_dense, self.xy_dense, self.s_knots = s_d, xy_d, s_knots
        self.length = float(s_d[-1])
        L = self.length
        kappa_abs_d, kappa_sig_d = dense_curvature(s_d, xy_d)

        # -- profiles, sampling, timelines
        pid = sdef.profile_ids.road
        road_prof = site.profiles.road[pid] if pid is not None else None
        self.sampling = S.resolve_sampling(sdef, road_prof)
        ramp = float(self.sampling.width_ramp_m)
        self.road = S.resolve_road(sdef, site, L, ramp_default=ramp)
        self.side_tl: Dict[int, S.SideTimeline] = {
            S.LEFT: S.resolve_side(sdef, S.LEFT, site, L, ramp_default=ramp),
            S.RIGHT: S.resolve_side(sdef, S.RIGHT, site, L, ramp_default=ramp),
        }
        self.kind: Optional[str] = self.road.kind
        problem = S.road_kinds_consistent(sdef, site)
        if problem:
            raise S.SchemaError([problem])

        # -- junction trim (a mask on s, resolved by JunctionPlan; see the class docstring)
        t0, t1 = (0.0, 0.0) if trim is None else (max(0.0, float(trim[0])), max(0.0, float(trim[1])))
        self.trim_m = (t0, t1)
        self.s_trim = (t0, max(t0, L - t1))
        self.trimmed = bool(t0 > 0.0 or t1 > 0.0)

        # -- stations
        mand = list(s_knots[1:-1]) + list(self.sampling.extra_stations_m or [])
        elevation = sdef.elevation_profile
        if elevation:
            elev = np.array([[k.s_m, k.z_m, k.bank_deg] for k in elevation], dtype=float)
            if (len(elev) < 2 or not np.isfinite(elev).all() or elev[0, 0] != 0.0
                    or np.any(np.diff(elev[:, 0]) <= 0.0) or abs(elev[-1, 0] - L) > 1e-5
                    or np.any(np.abs(elev[:, 2]) > 45.0)):
                raise S.SchemaError([self.id + ": elevation_profile must cover exactly [0, length] with finite increasing knots and bank within +/-45 degrees"])
            elev[-1, 0] = L
            mand += list(elev[1:-1, 0])
        mand += self.road.mandatory_stations()
        for tl in self.side_tl.values():
            mand += tl.mandatory_stations()
        mand += [x for x in self.s_trim if 0.0 < x < L]
        clamped = [m for m in mand if m > L + 0.01]
        if clamped:
            self.warnings.append("%d station(s) beyond L clamped" % len(clamped))
        self.mandatory_set = sorted(set(float(m) for m in mand if 0.0 < m < L))
        self.s = adaptive_stations(s_d, kappa_abs_d, self.sampling, self.mandatory_set)
        N = len(self.s)
        self.n = N
        self.mandatory = np.isin(self.s, np.array(self.mandatory_set)) if self.mandatory_set else np.zeros(N, dtype=bool)
        # the active (untrimmed) run: closed on both trim stations, which are in self.s exactly
        a0, a1 = self.s_trim
        self.active = (self.s >= a0 - 1e-12) & (self.s <= a1 + 1e-12)
        if int(self.active.sum()) < 2:
            self.active = np.ones(N, dtype=bool)
            self.trimmed = False
            self.s_trim = (0.0, L)
            self.trim_m = (0.0, 0.0)
            self.warnings.append("junction trim would leave fewer than 2 stations: not trimmed")
        self.xy = np.stack([np.interp(self.s, s_d, xy_d[:, 0]), np.interp(self.s, s_d, xy_d[:, 1])], axis=1)
        self.kappa = np.interp(self.s, s_d, kappa_sig_d)
        T_d = dense_tangents(xy_d)
        t_xy = _unit(np.stack([np.interp(self.s, s_d, T_d[:, 0]), np.interp(self.s, s_d, T_d[:, 1])], axis=1))
        self.t_h_xy = t_xy

        # -- width, extras, roll
        self.width, self.extra = resolve_widths(pts, s_knots, road_prof, self.road, self.s)
        w = self.width
        has_roll = np.array([p.roll_deg is not None for p in pts])
        if has_roll.any():
            roll_vals = np.array([0.0 if p.roll_deg is None else float(p.roll_deg) for p in pts])
            self.roll_pl = np.interp(self.s, s_knots[has_roll], roll_vals[has_roll])
            self.roll_mask = np.interp(self.s, s_knots, has_roll.astype(np.float64))
        else:
            self.roll_pl = np.zeros(N)
            self.roll_mask = np.zeros(N)

        # -- per-station road profile scalars
        profs = self.road.profile_at(self.s)
        self.profile_at = profs
        self.camber_kind = [("none" if p is None or p.kind == "rail" else p.camber.kind) for p in profs]
        base_cf = float(road_prof.camber.crossfall_pct) if (road_prof is not None and road_prof.camber.crossfall_pct is not None) else 0.0
        cf = np.full(N, base_cf)
        for o in self.road.crossfall_overrides:
            cf = S.apply_ramped_override(self.s, cf, o.s0, o.s1, o.ramp, o.value)
        self.crossfall_pct = cf
        base_cm = float(road_prof.camber.camber_m) if (road_prof is not None and road_prof.camber.camber_m is not None) else np.nan
        cm = np.full(N, base_cm)
        for o in self.road.camber_m_overrides:
            cm = S.apply_ramped_override(self.s, cm, o.s0, o.s1, o.ramp, o.value)
        self.camber_m = cm
        self.surface_material = np.array([(p.surface_material if p is not None else "tarmac") for p in profs], dtype=object)
        self.overlap_m = np.array([(p.overlap_m if p is not None else 0.04) for p in profs])
        self.skirt_drop_m = np.array([(p.skirt_drop_m if p is not None else 0.02) for p in profs])
        self.lateral_station_spacing_m = float(min([p.lateral_station_spacing_m for p in profs if p is not None] or [1.0]))
        self.road_profile = road_prof

        # -- heights
        if terrain is not None:
            self.z_raw = terrain.sample(self.xy[:, 0], self.xy[:, 1])
        else:
            self.z_raw = np.full(N, np.nan)
        self.z_raw_nan_count = int(np.sum(~np.isfinite(self.z_raw)))
        z_fill, all_nan = fill_nan_along(self.z_raw)
        if all_nan:
            self.warnings.append("no terrain under any station: heights set to 0")
        elif self.z_raw_nan_count:
            self.warnings.append("%d station(s) without terrain filled along s" % self.z_raw_nan_count)
        self.z_fill = z_fill
        W = float(self.sampling.smoothing_window_m)
        passes = int(self.sampling.smoothing_passes)
        z_s = moving_average_arclength(self.s, z_fill, W, passes)
        pins = [(float(s_knots[k]), float(p.z)) for k, p in enumerate(pts) if p.z is not None]
        self.pins = pins
        self.z_ref = apply_pins(z_s, self.s, pins, float(self.sampling.pin_blend_m)) if pins else z_s
        if elevation:
            self.z_ref = np.interp(self.s, elev[:, 0], elev[:, 1])

        # -- bank
        n_flat_xy = np.stack([-t_xy[:, 1], t_xy[:, 0]], axis=1)
        h_probe = np.maximum(w / 2.0, float(self.sampling.bank_probe_min_half_width_m))
        if terrain is not None:
            pl = self.xy + h_probe[:, None] * n_flat_xy
            pr = self.xy - h_probe[:, None] * n_flat_xy
            zl = terrain.sample(pl[:, 0], pl[:, 1])
            zr = terrain.sample(pr[:, 0], pr[:, 1])
            beta_raw = np.degrees(np.arctan2(zl - zr, 2.0 * h_probe))
            beta_raw[~np.isfinite(beta_raw)] = 0.0
        else:
            beta_raw = np.zeros(N)
        self.bank_raw = beta_raw
        bmax = float(self.sampling.bank_max_deg)
        beta_t = np.clip(moving_average_arclength(self.s, beta_raw, W, 1), -bmax, bmax)
        self.bank_terrain = beta_t
        beta = (1.0 - self.roll_mask) * beta_t + self.roll_mask * self.roll_pl
        self.bank_unlimited = beta
        self.bank_deg = rate_limit(beta, self.s, float(self.sampling.bank_rate_max_deg_per_m))
        if elevation:
            self.bank_deg = np.interp(self.s, elev[:, 0], elev[:, 2])

        # -- frames
        p3 = np.column_stack([self.xy, self.z_ref])
        t3 = np.column_stack([t_xy, np.zeros(N)])
        self.frames = Frames.build(self.s, p3, t3, self.bank_deg)

        # -- side specs (the one SideTimeline evaluation both B and C read)
        self.side_spec: Dict[int, S.SideSpec] = {side: tl.evaluate(self.s) for side, tl in self.side_tl.items()}

    # -- the edge contract --------------------------------------------------------------------
    def edge_offset(self, side: int) -> np.ndarray:
        """(N,) outward distance of the kerb line from the centreline on that side: w/2 + extra(side)."""
        return self.width / 2.0 + self.extra[side]

    def edge_height(self, side: int) -> np.ndarray:
        """(N,) road-surface height at the kerb line relative to z_ref (<= 0): surface_h(side * edge_offset)."""
        return self.surface_h(side * self.edge_offset(side))

    def surface_h(self, d) -> np.ndarray:
        """Camber height at signed lateral d per station ((N,) or (N, K))."""
        d = np.asarray(d, dtype=np.float64)
        w = self.width if d.ndim == 1 else self.width[:, None]
        cf = self.crossfall_pct if d.ndim == 1 else self.crossfall_pct[:, None]
        cm = self.camber_m if d.ndim == 1 else self.camber_m[:, None]
        kinds = np.array(self.camber_kind, dtype=object)
        if d.ndim == 2:
            kinds = kinds[:, None]
        return camber_h(kinds, w, cf, cm, d)

    # -- stats ------------------------------------------------------------------------------------
    def stats(self) -> dict:
        gaps = np.diff(self.s)
        return {
            "length_m": round(self.length, 6),
            "n_samples": int(self.n),
            "points_merged": int(self.points_merged),
            "step_min": round(float(gaps.min()), 6) if len(gaps) else 0.0,
            "step_max": round(float(gaps.max()), 6) if len(gaps) else 0.0,
            "step_mean": round(float(gaps.mean()), 6) if len(gaps) else 0.0,
            "z_raw_nan_count": int(self.z_raw_nan_count),
            "bank_min": round(float(self.bank_deg.min()), 6),
            "bank_max": round(float(self.bank_deg.max()), 6),
            "w_max": round(float((self.edge_offset(S.LEFT) + self.edge_offset(S.RIGHT)).max()), 6),
            "kind": self.kind,
            "trimmed": bool(self.trimmed),
            "trim_m": [round(float(self.trim_m[0]), 6), round(float(self.trim_m[1]), 6)],
            "s_trim": [round(float(self.s_trim[0]), 6), round(float(self.s_trim[1]), 6)],
            "n_active": int(self.active.sum()),
            "warnings": list(self.warnings),
        }


# --------------------------------------------------------------------------------------------
# junctions: the shared trim (SCHEMA.md 4.18, DESIGN.md 3.9)
# --------------------------------------------------------------------------------------------

@dataclass
class JunctionArm:
    """One spline end standing in a junction, resolved in PLAN only (no terrain needed)."""
    junction_id: str
    spline_id: str
    end: str                # "start" | "end"
    s_trim: float           # arc length of the trim station on that spline
    trim_m: float           # arc length removed from that end
    u: np.ndarray           # (2,) outward unit tangent at the trim station, pointing AWAY from the junction
    p: np.ndarray           # (2,) plan position of the trim station
    e_left: float           # edge_offset(LEFT) at the trim station
    e_right: float          # edge_offset(RIGHT) at the trim station
    overlap_m: float        # road skirt overhang at the trim station
    phi: float = 0.0        # bearing of the TRIM POINT about the node -- the angular order key
    half_ang: float = 0.0   # angular half-width the arm's end edge subtends at the node, measured
    radius_m: float = 0.0   # the trim radius THIS arm was solved at

    @property
    def half_extent_m(self) -> float:
        """The arm's true plan half-extent at the trim: the outer edge of its skirt row."""
        return max(self.e_left, self.e_right) + self.overlap_m


def _first_crossing(s_d: np.ndarray, xy_d: np.ndarray, end: str, cx: float, cy: float, d: float):
    """Arc length where the dense centreline first reaches plan distance ``d`` from (cx, cy), scanning
    inward from ``end``.  None when the whole curve stays inside the disc."""
    r = np.hypot(xy_d[:, 0] - cx, xy_d[:, 1] - cy)
    idx = np.where(r >= d)[0]
    if len(idx) == 0:
        return None
    if end == "start":
        k = int(idx[0])
        if k == 0:
            return 0.0
        r0, r1 = float(r[k - 1]), float(r[k])
        t = 0.0 if r1 == r0 else (d - r0) / (r1 - r0)
        return float(s_d[k - 1] + t * (s_d[k] - s_d[k - 1]))
    k = int(idx[-1])
    if k == len(r) - 1:
        return float(s_d[-1])
    r0, r1 = float(r[k]), float(r[k + 1])
    t = 0.0 if r1 == r0 else (r0 - d) / (r0 - r1)
    return float(s_d[k] + t * (s_d[k + 1] - s_d[k]))


def _wrap_two_pi(a: float) -> float:
    return float(a % (2.0 * np.pi))


def _wrap_pi(a: float) -> float:
    return float((a + np.pi) % (2.0 * np.pi) - np.pi)


class JunctionPlan:
    """The junction geometry of one document, solved once, in plan, before any Spline is built.

    Why here and not in a renderer: Renderer A stops the carriageway at the trim and Renderer B stops
    the kerb at the same trim.  If either one computed the trim itself they would disagree the moment a
    width or a profile changed -- exactly the drift BRIEF 1.1 warns about.  One spline, one trim, every
    renderer reads it.

    Why in plan and not from built Splines: the trim criterion is a plan distance from the junction
    node, so it needs no terrain; solving it first means every spline is built exactly ONCE, with its
    trim already known, instead of being built, measured and rebuilt.

    THE TRIM RADIUS, derived (never stored).  Order the arms by ``phi_i``, the bearing of the arm's
    TRIM POINT about the node, and give arm i the half-extent ``e_i = max(e_left, e_right) + overlap``
    -- the outer edge of its skirt row, which is where the ribbon actually ends in plan.  At trim radius
    ``d`` that arm subtends about ``atan(e_i / d)`` there (``half_ang``, measured exactly from its own
    two skirt corners rather than assumed).  The patch that fills the junction is a fan from the node,
    and that fan is free of self-overlap exactly when its boundary is angularly monotone about the node
    -- i.e. when no two neighbouring arms overlap in bearing.  Requiring EACH arm to take at most half
    of EACH of its two adjacent gaps is sufficient and gives a closed form, with ``D_i`` the smaller of
    arm i's two adjacent gaps:

        atan(e_i / d) <= (D_i - clearance) / 2      =>      requirement_i = e_i / tan((D_i - eps) / 2)

        d = clamp(max over arms of requirement_i, radius_m, max_trim_radius_m)   (_solve_radii)

    (Adjacent arms i, j then satisfy ``half_i + half_j <= D_ij - eps``, which is the non-overlap
    condition itself.)  That is what "the trim distance must account for the junction radius AND the
    width of the road being trimmed" means numerically: a 12 m trunk arm needs pushing back until its
    6.04 m half-extent subtends less than half the gap to its neighbour, so the neighbour's ribbon has
    somewhere to end and no notch is left between them.

    ``phi`` is the bearing of the trim POINT and not of the outward TANGENT because on a spline that
    curves near its end the tangent swings far faster than the node direction does, and a fixed point
    solved on the tangent oscillates instead of converging.  Measured on junction 16_10:0, where a
    footway leaves the node alongside its parent road: on the tangent it settled on a 17.09 m radius
    whose own arms were still 0.1 deg apart, with 128.6 m2 of its 221.7 m2 patch covered twice; on the
    node bearing it converges at 16.90 m with 8.6 m2 of 335.8 m2 -- a fifteen-fold reduction on the
    worst junction on the isle.

    Because ``e`` and ``phi`` are read at the trim station and the trim station depends on ``d``, the
    solve is a fixed-point iteration from ``d = radius_m``, run to convergence within ``ITERS`` passes;
    an arm already inside its share of both gaps asks for no change at all.

    DEGENERACY.  A spline trimmed at both ends keeps at least ``min_remaining_m``; when the two trims
    would leave less, BOTH are scaled by one common factor k in [0, 1] so the spline shortens
    symmetrically instead of vanishing or inverting, and the arms are then re-derived at the scaled
    trims so the patch still meets the ribbon exactly.  A spline shorter than ``min_remaining_m`` to
    begin with is not trimmed at all."""

    ITERS = 8

    def __init__(self, site: S.Site, defaults=None):
        cfg = dict(S.JUNCTION_DEFAULTS)
        if defaults:
            cfg.update(defaults)
        self.cfg = cfg
        self.site = site
        self._by_id = {sp.id: sp for sp in site.splines}
        self._junc_by_id = {j.id: j for j in site.junctions}
        self.arms: Dict[str, List[JunctionArm]] = {}
        self.trim_radius: Dict[str, float] = {}
        self.trims: Dict[str, List[float]] = {}
        self.notes: List[str] = []
        self.stats = {"junctions": 0, "junctions_built": 0, "junctions_skipped_kind": 0,
                      "junctions_skipped_arms": 0, "arms": 0, "arms_dropped": 0,
                      "splines_trimmed": 0, "splines_degenerate": 0, "splines_untrimmable": 0,
                      "arms_unseparable": 0}
        self._curves: Dict[str, tuple] = {}
        self._build()

    # -- per-spline plan geometry, cached ------------------------------------------------------
    def _curve(self, spline_id: str):
        if spline_id not in self._curves:
            sdef = self._by_id[spline_id]
            pts, _ = merge_points(sdef.points)
            P = np.array([[p.x, p.y] for p in pts])
            s_d, xy_d, s_knots = catmull_rom_dense(P)
            L = float(s_d[-1])
            pid = sdef.profile_ids.road
            road_prof = self.site.profiles.road[pid] if pid is not None else None
            sampling = S.resolve_sampling(sdef, road_prof)
            road_tl = S.resolve_road(sdef, self.site, L, ramp_default=float(sampling.width_ramp_m))
            T_d = dense_tangents(xy_d)
            self._curves[spline_id] = (pts, s_d, xy_d, s_knots, T_d, road_prof, road_tl, L)
        return self._curves[spline_id]

    def _arm_at(self, junction_id, spline_id, end, cx, cy, d) -> Optional[JunctionArm]:
        pts, s_d, xy_d, s_knots, T_d, road_prof, road_tl, L = self._curve(spline_id)
        s_t = _first_crossing(s_d, xy_d, end, cx, cy, d)
        if s_t is None:
            s_t = L if end == "start" else 0.0            # the whole spline is inside the disc
        return self._arm_from_station(junction_id, spline_id, end, s_t, cx, cy)

    def _arm_from_station(self, junction_id, spline_id, end, s_t, cx, cy) -> JunctionArm:
        pts, s_d, xy_d, s_knots, T_d, road_prof, road_tl, L = self._curve(spline_id)
        s_t = float(min(max(s_t, 0.0), L))
        px = float(np.interp(s_t, s_d, xy_d[:, 0]))
        py = float(np.interp(s_t, s_d, xy_d[:, 1]))
        tx = float(np.interp(s_t, s_d, T_d[:, 0]))
        ty = float(np.interp(s_t, s_d, T_d[:, 1]))
        u = np.array([tx, ty], dtype=np.float64)
        n = float(np.hypot(*u))
        u = u / n if n > 0 else np.array([1.0, 0.0])
        if u[0] * (px - cx) + u[1] * (py - cy) < 0.0:      # orient AWAY from the junction node
            u = -u
        w, extra = resolve_widths(pts, s_knots, road_prof, road_tl, np.array([s_t]))
        prof = road_tl.profile_at(np.array([s_t]))[0]
        ov = float(prof.overlap_m) if prof is not None else 0.04
        arm = JunctionArm(junction_id, spline_id, end, s_t, (s_t if end == "start" else L - s_t),
                          u, np.array([px, py]), float(w[0] / 2.0 + extra[S.LEFT][0]),
                          float(w[0] / 2.0 + extra[S.RIGHT][0]), ov)
        # The angular order key is the bearing of the TRIM POINT about the node, not of the tangent.
        # The fan's validity is a statement about where the arms' end edges SIT around the node, and on
        # a spline that curves near its end the tangent swings far faster than the node direction does
        # -- solving on the tangent made the fixed-point iteration oscillate (measured: junction
        # 16_10:0 settled on a 17.09 m radius whose own arms were 0.1 deg apart).
        arm.phi = float(np.arctan2(py - cy, px - cx))
        n_plan = np.array([-u[1], u[0]])                       # left of travel-outward
        e = arm.half_extent_m
        half = 0.0
        for c in (np.array([px, py]) + e * n_plan, np.array([px, py]) - e * n_plan):
            half = max(half, abs(_wrap_pi(float(np.arctan2(c[1] - cy, c[0] - cx)) - arm.phi)))
        arm.half_ang = half
        return arm

    # -- the solve -----------------------------------------------------------------------------
    def _solve_radii(self, arms: List[JunctionArm], r_floor: float):
        """([d_i], [unseparable_i]) -- the trim radius of each arm.

        Each arm states a REQUIREMENT from its own half-extent and its own smaller adjacent gap
        (the formula in the class docstring).  The junction then takes ONE radius, the largest
        requirement any arm makes, because a junction has one size: a 12 m trunk crossing a 4 m lane
        makes a big junction for both of them, and letting the lane stop 2 m from the node while the
        trunk stops 6 m away leaves a long radial corner between them that wraps a nose the fan then
        has to cover twice.  Measured on the synthetic ``junction_widths``: 0.96 m2 of double cover
        with per-arm radii, 0.00 m2 with the common one.

        Two escapes keep that from being destructive:

          * UNSEPARABLE.  Two OSM ways can leave the same node 2 degrees apart (parallel carriageways,
            or a stub beside its parent).  Separating THOSE would need ``e / tan(1 deg)`` = 340 m of
            trim to fix a ribbon overlap that exists along the whole length of both arms anyway, so a
            requirement above ``max_trim_radius_m`` is dropped from the maximum instead of driving it:
            the pair is recorded (``arms_unseparable``, and the patch boundary is then reported
            non-monotone) and no road is thrown away for nothing.
          * LENGTH.  No arm gives up more than ``max_trim_frac_of_length`` of its own spline to one
            junction, whatever the angles ask for."""
        eps = np.radians(float(self.cfg["clearance_deg"]))
        cap = float(self.cfg["max_trim_radius_m"])
        n = len(arms)
        order = sorted(range(n), key=lambda i: _wrap_two_pi(arms[i].phi))
        gap_next = [0.0] * n
        for k in range(n):
            i, j = order[k], order[(k + 1) % n]
            gap_next[i] = _wrap_two_pi(arms[j].phi - arms[i].phi) if n > 1 else 2.0 * np.pi
        req = [0.0] * n
        unsep = [False] * n
        for k in range(n):
            i, pv = order[k], order[(k - 1) % n]
            delta = min(gap_next[i], gap_next[pv]) if n > 1 else 2.0 * np.pi
            target = 0.5 * (delta - eps)
            if target >= 0.5 * np.pi - 1e-9 or (target > 1e-9 and arms[i].half_ang <= target):
                q = arms[i].radius_m                       # already inside its share of both gaps
            elif target <= 1e-9:
                q = float("inf")
            else:
                q = arms[i].half_extent_m / float(np.tan(target))
            req[i] = q
            unsep[i] = bool(q > cap)
        common = max([r_floor] + [req[i] for i in range(n) if not unsep[i]])
        common = min(common, cap)
        frac = float(self.cfg["max_trim_frac_of_length"])
        d = []
        for i in range(n):
            # never give up more than max_trim_frac_of_length of the arm's own spline to one junction
            d.append(min(common, max(r_floor, frac * self._curve(arms[i].spline_id)[7])))
        return d, unsep

    def _build(self):
        pending: Dict[str, List[JunctionArm]] = {}
        for j in self.site.junctions:
            self.stats["junctions"] += 1
            if j.kind != "disc":
                self.stats["junctions_skipped_kind"] += 1
                continue
            keys, seen = [], set()
            radius_overrides = []
            for e in j.ends:
                k = (e.spline_id, e.end)
                if k in seen:
                    continue
                seen.add(k)
                sdef = self._by_id.get(e.spline_id)
                if sdef is None:
                    self.stats["arms_dropped"] += 1
                    self.notes.append("%s: end %s %s is not in this document" % (j.id, e.spline_id, e.end))
                    continue
                if sdef.profile_ids.road is None or self.site.profiles.road[sdef.profile_ids.road].kind == "rail":
                    self.stats["arms_dropped"] += 1     # a level crossing is not a tarmac junction
                    continue
                keys.append(k)
                radius_overrides.append(e.trim_radius_m)
            if len(keys) < 3:
                self.stats["junctions_skipped_arms"] += 1
                continue
            r_floor = float(j.radius_m or 0.0)
            d = [max(r_floor, 1e-6)] * len(keys)
            arms: List[JunctionArm] = []
            unsep = [False] * len(keys)
            for _ in range(self.ITERS):
                arms = [self._arm_at(j.id, sid, end, j.x, j.y, d[q]) for q, (sid, end) in enumerate(keys)]
                for q, a in enumerate(arms):
                    a.radius_m = d[q]
                if j.trim_radius_m is not None:
                    d_new, unsep = [float(j.trim_radius_m)] * len(keys), [False] * len(keys)
                else:
                    d_new, unsep = self._solve_radii(arms, r_floor)
                # An explicit end overrides the common solve for that arm only.
                # The common minimum-remaining reconciliation below still owns
                # every renderer's actual trim and mandatory station.
                for q, value in enumerate(radius_overrides):
                    if value is not None:
                        d_new[q] = float(value)
                        unsep[q] = False
                if max(abs(x - y) for x, y in zip(d_new, d)) < 1e-9:
                    d = d_new
                    break
                d = d_new
            arms = [self._arm_at(j.id, sid, end, j.x, j.y, d[q]) for q, (sid, end) in enumerate(keys)]
            for q, a in enumerate(arms):
                a.radius_m = d[q]
            self.stats["arms_unseparable"] += int(sum(1 for x in unsep if x))
            self.trim_radius[j.id] = float(max(d))
            pending[j.id] = arms
            for a in arms:
                self.trims.setdefault(a.spline_id, [0.0, 0.0])
                slot = 0 if a.end == "start" else 1
                self.trims[a.spline_id][slot] = max(self.trims[a.spline_id][slot], a.trim_m)

        # -- degeneracy: one common scale factor per spline, then re-derive the arms ------------
        keep = float(self.cfg["min_remaining_m"])
        scale: Dict[str, float] = {}
        for sid, (t0, t1) in list(self.trims.items()):
            L = self._curve(sid)[7]
            if t0 + t1 <= L - keep:
                continue
            if L <= keep or (t0 + t1) <= 0.0:
                self.trims[sid] = [0.0, 0.0]
                scale[sid] = 0.0
                self.stats["splines_untrimmable"] += 1
                self.notes.append("%s: L=%.3f m cannot be trimmed (min_remaining_m %.3f)" % (sid, L, keep))
                continue
            k = max(0.0, (L - keep) / (t0 + t1))
            self.trims[sid] = [t0 * k, t1 * k]
            scale[sid] = k
            self.stats["splines_degenerate"] += 1
            self.notes.append("%s: trims scaled by %.6f to keep %.3f m of L=%.3f m" % (sid, k, keep, L))
        for jid, arms in pending.items():
            out = []
            for a in arms:
                if a.spline_id in scale:
                    L = self._curve(a.spline_id)[7]
                    t = self.trims[a.spline_id][0 if a.end == "start" else 1]
                    s_t = t if a.end == "start" else L - t
                    a = self._arm_from_station(jid, a.spline_id, a.end, s_t, self._node(jid)[0], self._node(jid)[1])
                out.append(a)
            out.sort(key=lambda a: (_wrap_two_pi(a.phi), a.spline_id, a.end))
            self.arms[jid] = out
            self.stats["arms"] += len(out)
            self.stats["junctions_built"] += 1
        self.stats["splines_trimmed"] = sum(1 for v in self.trims.values() if v[0] > 0.0 or v[1] > 0.0)

    def _node(self, jid: str):
        j = self._junc_by_id[jid]
        return (j.x, j.y, j.z)

    # -- what the builders ask for --------------------------------------------------------------
    def trim_for(self, spline_id: str):
        """(t_start, t_end) in metres for one spline; (0, 0) when it stands in no junction."""
        t = self.trims.get(spline_id)
        return (0.0, 0.0) if t is None else (float(t[0]), float(t[1]))

    def owner(self, junction_id: str) -> Optional[str]:
        """The spline whose road buffer carries this junction's patch: the first arm in the canonical
        (bearing, spline id, end) order, so the assignment is deterministic and document-order free."""
        arms = self.arms.get(junction_id) or []
        return arms[0].spline_id if arms else None

    def junctions_owned_by(self, spline_id: str) -> List[str]:
        return sorted(jid for jid in self.arms if self.owner(jid) == spline_id)

    def junction(self, junction_id: str) -> S.Junction:
        return self._junc_by_id[junction_id]


# --------------------------------------------------------------------------------------------
# junctions: the shared corner geometry that Renderer A and Renderer B must agree on
# --------------------------------------------------------------------------------------------

@dataclass
class ArmFrame:
    """One arm of a junction resolved against its BUILT spline: the station index of the trim, the
    outward direction, and the two kerb-line origins (position, outward normal, up) that the corner
    fillets start and end on.  ``lo`` is the side at the lower bearing about the junction node and
    ``hi`` the side at the higher bearing, so walking the arms anticlockwise walks lo -> hi."""
    arm: JunctionArm
    spline: "Spline"
    i: int
    u: np.ndarray            # (3,) outward horizontal unit, away from the node
    side_lo: int
    side_hi: int
    p_lo: np.ndarray         # (3,) kerb-line origin, low-bearing side
    n_lo: np.ndarray         # (3,) INWARD unit normal there (= -side * frames.n), the corner Frames' n
    b_lo: np.ndarray         # (3,) up (= frames.b)
    p_hi: np.ndarray
    n_hi: np.ndarray
    b_hi: np.ndarray


def arm_station_index(sp: "Spline", end: str) -> int:
    """Index in ``sp.s`` of the trim station of that end (the first / last active station)."""
    idx = np.where(sp.active)[0]
    return int(idx[0]) if end == "start" else int(idx[-1])


def resolve_arm_frames(plan: JunctionPlan, junction_id: str, splines: Dict[str, "Spline"]):
    """[ArmFrame] in anticlockwise order, or None when an arm's spline is missing from ``splines``."""
    out: List[ArmFrame] = []
    for a in plan.arms.get(junction_id, []):
        sp = splines.get(a.spline_id)
        if sp is None or sp.kind is None:
            return None
        i = arm_station_index(sp, a.end)
        t_h = sp.frames.t_h[i]
        u = t_h if a.end == "start" else -t_h
        side_lo = S.RIGHT if a.end == "start" else S.LEFT
        side_hi = S.LEFT if a.end == "start" else S.RIGHT
        ends = {}
        for tag, side in (("lo", side_lo), ("hi", side_hi)):
            o0 = float(sp.edge_offset(side)[i])
            h0 = float(sp.edge_height(side)[i])
            p = sp.frames.p[i] + side * o0 * sp.frames.n[i] + h0 * sp.frames.b[i]
            ends[tag] = (p, -side * sp.frames.n[i], sp.frames.b[i])
        out.append(ArmFrame(a, sp, i, u, side_lo, side_hi,
                            ends["lo"][0], ends["lo"][1], ends["lo"][2],
                            ends["hi"][0], ends["hi"][1], ends["hi"][2]))
    return out or None


def corner_curve(A, B, dir0, dir1, node_xy, step_deg: float, handle_frac: float):
    """The kerb corner between two arms: a cubic fillet from ``A`` leaving along ``dir0`` and arriving
    at ``B`` along ``dir1``, sampled at ``step_deg`` of turn.

    Why a cubic and not a circle: a single circular arc can be tangent to BOTH kerb lines at BOTH trim
    ends only when the two ends happen to be equidistant from the intersection of their normals -- true
    for a symmetric right-angle crossroads, false for a skew crossing or two arms of different width.
    The handle length ``m = (4/3) tan(|tau|/4) r`` is the standard circular-arc handle, so where a
    circle does exist this curve IS that circle to 2e-4 of its radius, and where it does not the curve
    is still G1 at both ends -- which is what "no kink between the kerb and the corner" actually
    requires.  ``handle_frac`` caps the handle at a fraction of the endpoint's distance to the node so
    the fillet can never fold back through the junction.

    Sampling also bounds segment length to 1 m and cubic-to-chord deviation to
    10 mm. Endpoint angle alone misses long curves and internal S bends. Uniform
    parameter spacing preserves the shared bank/profile interpolation in A and B.
    Derivative control cones bound actual turn, including between sample points.

    Returns ``(P (M+1, 3), T (M+1, 3))`` -- points and horizontal unit tangents, ``P[0] == A`` and
    ``P[-1] == B`` exactly."""
    A = np.asarray(A, dtype=np.float64)
    B = np.asarray(B, dtype=np.float64)
    if not np.isfinite(np.r_[A,B,dir0,dir1,node_xy,step_deg,handle_frac]).all() or not 0<step_deg<=90 or handle_frac<=0:
        raise ValueError("invalid corner curve inputs")
    d0 = np.array([dir0[0], dir0[1], 0.0]); d0 /= max(float(np.hypot(d0[0], d0[1])), 1e-18)
    d1 = np.array([dir1[0], dir1[1], 0.0]); d1 /= max(float(np.hypot(d1[0], d1[1])), 1e-18)
    if np.linalg.norm(d0)<.5 or np.linalg.norm(d1)<.5:raise ValueError('invalid corner direction')
    chord = float(np.linalg.norm(B[:2] - A[:2]))
    tau = float(np.arctan2(d0[0] * d1[1] - d0[1] * d1[0], d0[0] * d1[0] + d0[1] * d1[1]))
    if chord < 1e-9:
        return np.vstack([A, B]), np.vstack([d0, d1])
    if abs(tau) < 1e-6:
        m = chord/3.  # continuous circular-handle limit; retains parallel-end tangency
        M = 1
    else:
        r = chord / (2.0 * np.sin(abs(tau) / 2.0))
        m = (4.0 / 3.0) * np.tan(abs(tau) / 4.0) * r
        angular=np.degrees(abs(tau))/float(step_deg)
        if not np.isfinite(angular) or angular>4096:raise ValueError('corner turn resolution exceeds 4096 segments')
        M = max(2, int(np.ceil(angular)))
    cap = handle_frac * min(float(np.linalg.norm(A[:2] - np.asarray(node_xy))),
                            float(np.linalg.norm(B[:2] - np.asarray(node_xy))))
    m = min(m, cap)
    P0, P3 = A, B
    P1 = A + m * d0
    P2 = B - m * d1
    # ||C'|| <= 3 max control-leg length; ||C''|| <= 6 max second difference.
    # The linear interpolation error is <= max ||C''|| * dt^2 / 8.
    speed = 3*max(np.linalg.norm(P1-P0),np.linalg.norm(P2-P1),np.linalg.norm(P3-P2))
    accel = 6*max(np.linalg.norm(P2-2*P1+P0),np.linalg.norm(P3-2*P2+P1))
    if not np.isfinite([speed,accel]).all() or speed>4096 or accel>8*.01*4096**2:
        raise ValueError('corner length/deviation resolution exceeds 4096 segments')
    M=max(M,int(np.ceil(speed-1e-10)),int(np.ceil(np.sqrt(accel/(8*.01))-1e-10)))
    cosine=np.cos(np.radians(step_deg))
    while M<=4096:
        t = np.linspace(0.0, 1.0, M + 1)[:, None]
        om = 1.0 - t
        P = om ** 3 * P0 + 3 * om ** 2 * t * P1 + 3 * om * t ** 2 * P2 + t ** 3 * P3
        dP = 3 * om ** 2 * (P1 - P0) + 6 * om * t * (P2 - P1) + 3 * t ** 2 * (P3 - P2)
        q1=P[:-1]+dP[:-1]/(3*M);q2=P[1:]-dP[1:]/(3*M)
        control=np.stack([dP[:-1,:2]/(3*M),q2[:,:2]-q1[:,:2],dP[1:,:2]/(3*M)],axis=1)
        norm=np.linalg.norm(control,axis=2)
        valid=True
        for a,b in ((0,1),(1,2),(0,2)):
            use=(norm[:,a]>1e-12)&(norm[:,b]>1e-12)
            dot=np.sum(control[:,a]*control[:,b],axis=1)
            if np.any(dot[use] < (cosine-1e-12)*norm[use,a]*norm[use,b]):valid=False;break
        if valid:break
        M*=2
    else:
        raise ValueError("corner curve cannot meet quality limits within 4096 segments; possible cusp or oversized corner")
    dP[:, 2] = 0.0
    nrm = np.hypot(dP[:, 0], dP[:, 1])
    bad = nrm < 1e-12
    if bad.any():
        fb = B[:2] - A[:2]
        dP[bad, 0], dP[bad, 1] = fb[0], fb[1]
        nrm = np.hypot(dP[:, 0], dP[:, 1])
    T = dP / nrm[:, None]
    if m > 0.0:
        T[0] = d0
        T[-1] = d1
    P[0] = A
    P[-1] = B
    return P, T


def corner_frames(P: np.ndarray, T: np.ndarray, n0, n1) -> Frames:
    """Frames along the actual corner tangents, with transported horizontal normals
    and a linear blend of the endpoint bank angles. Blending world normals can
    reverse the frame inside an S bend. ``b = T x n`` stays up for upright endpoint
    banks; ``side = -1`` puts the extrusion away from the junction. Projected endpoint
    normals remain exact, preserving the arm/corner seam.

    ``Frames.s`` carries the cumulative plan length along the corner, so the sweep's UV u keeps running
    in metres across the join."""
    n0 = np.asarray(n0, dtype=np.float64)
    n1 = np.asarray(n1, dtype=np.float64)
    M = len(T)
    t = np.linspace(0.0, 1.0, M)[:, None]
    n_flat = _unit(np.cross(np.broadcast_to(Z_AXIS, T.shape), T))
    first = _unit((n0 - np.dot(n0, T[0]) * T[0])[None, :])[0]
    last = _unit((n1 - np.dot(n1, T[-1]) * T[-1])[None, :])[0]
    # Interpolating world normals can reverse the frame on a long/S-shaped bend.
    # Transport the horizontal left normal along the actual tangent, blending
    # only the signed bank angle. Endpoint rings remain exactly coincident.
    bank0=np.arctan2(first[2],np.dot(first,n_flat[0]))
    bank1=np.arctan2(last[2],np.dot(last,n_flat[-1]))
    bank=(1-t)*bank0+t*bank1
    n=np.cos(bank)*n_flat+np.sin(bank)*Z_AXIS
    n[0],n[-1]=first,last
    b = np.cross(T, n)
    seg = np.hypot(np.diff(P[:, 0]), np.diff(P[:, 1]))
    s = np.concatenate([[0.0], np.cumsum(seg)])
    return Frames(s, P, T, n_flat, n, b)
