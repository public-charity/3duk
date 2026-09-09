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

    def __init__(self, sdef: S.SplineDef, site: S.Site, terrain: Heightfield):
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

        # -- stations
        mand = list(s_knots[1:-1]) + list(self.sampling.extra_stations_m or [])
        mand += self.road.mandatory_stations()
        for tl in self.side_tl.values():
            mand += tl.mandatory_stations()
        clamped = [m for m in mand if m > L + 0.01]
        if clamped:
            self.warnings.append("%d station(s) beyond L clamped" % len(clamped))
        self.mandatory_set = sorted(set(float(m) for m in mand if 0.0 < m < L))
        self.s = adaptive_stations(s_d, kappa_abs_d, self.sampling, self.mandatory_set)
        N = len(self.s)
        self.n = N
        self.mandatory = np.isin(self.s, np.array(self.mandatory_set)) if self.mandatory_set else np.zeros(N, dtype=bool)
        self.xy = np.stack([np.interp(self.s, s_d, xy_d[:, 0]), np.interp(self.s, s_d, xy_d[:, 1])], axis=1)
        self.kappa = np.interp(self.s, s_d, kappa_sig_d)
        T_d = dense_tangents(xy_d)
        t_xy = _unit(np.stack([np.interp(self.s, s_d, T_d[:, 0]), np.interp(self.s, s_d, T_d[:, 1])], axis=1))
        self.t_h_xy = t_xy

        # -- width, extras, roll
        base_w = float(road_prof.width_m) if road_prof is not None else 0.0
        w_knots = np.array([base_w if (p.width_m is None or road_prof is None) else float(p.width_m) for p in pts])
        w = np.interp(self.s, s_knots, w_knots)
        for o in self.road.width_overrides:
            w = S.apply_ramped_override(self.s, w, o.s0, o.s1, o.ramp, o.value)
        self.width = w
        self.extra = {}
        for side in (S.LEFT, S.RIGHT):
            e = np.zeros(N)
            for o in self.road.extra_overrides[side]:
                e = S.apply_ramped_override(self.s, e, o.s0, o.s1, o.ramp, o.value)
            self.extra[side] = e
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
            "warnings": list(self.warnings),
        }
