"""Does the built street sit on the ground?  The measurement, and the gate that keeps it that way.

Two failures are visible from eye level and this module measures both, over the whole built surface
(carriageway + kerb + pavement), not only the crown:

* **penetration** -- ground ABOVE the surface it should be under.  The terrain mesh erupts through
  the carriageway or the pavement.  This is D3, Alex's report.
* **float** -- ground BELOW the outer face of the built block by more than that face is tall, so
  there is daylight under the kerb or the pavement.  Raising the road (docs/TERRAIN_ROADS.md 5.2)
  trades the first for the second; a fix has to answer for both, so both are reported here.

Geometry, per station (DESIGN.md 4.1, 4.2):

    carriageway   d in [-edge_offset(R), +edge_offset(L)]   z = z_ref + d sinB + camber(d) cosB
    kerb          outward a in [0, kw]                      top = road-edge level + hk
    pavement      outward a in [kw, kw + pw]                top = road-edge level + hk..hk_back
    block base    the outer face reaches `skirt` below the road-edge level (0.30 m by default);
                  the road's own skirt row reaches `skirt_drop_m` (0.02 m) where there is no kerb.

Pure numpy: no bpy, no GDAL, no scipy.  ``Heightfield.sampling`` decides whether the terrain is read
with the bilinear rule (the numpy/plugin contract) or the landscape's own triangulated rule -- the
honest measurement of what a camera sees is the second, and both are reported by the driver.
"""
from __future__ import annotations

import numpy as np

from . import schema as S


def station_spans(s: np.ndarray) -> np.ndarray:
    """Arc length each station owns (half to each neighbour), so "km penetrated" is a length."""
    span = np.zeros_like(s)
    if len(s) > 1:
        span[1:-1] = (s[2:] - s[:-2]) / 2.0
        span[0] = (s[1] - s[0]) / 2.0
        span[-1] = (s[-1] - s[-2]) / 2.0
    return span


def carriageway_points(sp, k: int):
    """(N, k) plan x, plan y and world z of the road surface, exactly as Renderer A places its rows."""
    oL = sp.edge_offset(S.LEFT)
    oR = sp.edge_offset(S.RIGHT)
    f = np.linspace(0.0, 1.0, k)[None, :]
    d = (-oR)[:, None] + f * (oL + oR)[:, None]
    h = sp.surface_h(d)
    F = sp.frames
    P = F.p[:, None, :] + d[:, :, None] * F.n[:, None, :] + h[:, :, None] * F.b[:, None, :]
    return P[:, :, 0], P[:, :, 1], P[:, :, 2]


def edge_points(sp, side: int, k: int):
    """(N, k) plan x, y and the world z of the kerb/pavement TOP, plus the block's underside.

    Returns (x, y, z_top, z_base, present).  The strip runs outward from the kerb line to the
    pavement back edge; where there is no kerb or pavement it is one column at the road edge."""
    spec = sp.side_spec[side]
    o = sp.edge_offset(side)
    kw = np.asarray(spec.kerb_width, dtype=np.float64)
    pw = np.asarray(spec.pavement_width, dtype=np.float64)
    hk = np.asarray(spec.hk, dtype=np.float64)
    hk_back = np.asarray(spec.hk_back, dtype=np.float64)
    skirt = np.asarray(spec.skirt, dtype=np.float64)
    present = np.asarray(spec.present, dtype=bool) & ((kw + pw) > 0)
    back = kw + pw
    f = np.linspace(0.0, 1.0, k)[None, :]
    a = f * back[:, None]                                    # outward from the kerb line
    with np.errstate(divide="ignore", invalid="ignore"):
        frac = np.where(pw[:, None] > 0, (a - kw[:, None]) / np.where(pw[:, None] > 0, pw[:, None], 1.0), 0.0)
    frac = np.clip(frac, 0.0, 1.0)
    top_rel = np.where(a <= kw[:, None], hk[:, None], hk[:, None] + (hk_back - hk)[:, None] * frac)
    edge_h = sp.edge_height(side)                            # camber height at the kerb line
    d = side * (o[:, None] + a)
    F = sp.frames
    P = F.p[:, None, :] + d[:, :, None] * F.n[:, None, :] + (edge_h[:, None] + top_rel)[:, :, None] * F.b[:, None, :]
    base = F.p[:, None, :] + d[:, :, None] * F.n[:, None, :] + (edge_h[:, None] - skirt[:, None])[:, :, None] * F.b[:, None, :]
    return P[:, :, 0], P[:, :, 1], P[:, :, 2], base[:, :, 2], present


def audit_spline(sp, hf, k_road: int = 9, k_edge: int = 5) -> dict:
    """Per-station penetration and float for one spline.  All arrays are (N,)."""
    N = sp.n
    X, Y, Z = carriageway_points(sp, k_road)
    zt = hf.sample(X.ravel(), Y.ravel()).reshape(X.shape)
    clear = Z - zt
    ok = np.isfinite(clear)
    with np.errstate(invalid="ignore"):
        min_clear = np.where(ok, clear, np.inf).min(axis=1)
        max_clear = np.where(ok, clear, -np.inf).max(axis=1)
    any_ok = ok.any(axis=1)
    min_clear[~any_ok] = np.nan
    max_clear[~any_ok] = np.nan

    pen_edge = np.zeros(N)
    float_edge = np.zeros(N)
    edge_any = np.zeros(N, dtype=bool)
    for side in (S.LEFT, S.RIGHT):
        ex, ey, etop, ebase, present = edge_points(sp, side, k_edge)
        if not present.any():
            continue
        zte = hf.sample(ex.ravel(), ey.ravel()).reshape(ex.shape)
        good = np.isfinite(zte) & present[:, None]
        # ground above the kerb/pavement top
        p = np.where(good, zte - etop, -np.inf).max(axis=1)
        pen_edge = np.maximum(pen_edge, np.where(np.isfinite(p), np.maximum(p, 0.0), 0.0))
        # daylight under the outer face: only the OUTERMOST column can be seen from outside
        gap = np.where(good[:, -1], ebase[:, -1] - zte[:, -1], -np.inf)
        float_edge = np.maximum(float_edge, np.where(np.isfinite(gap), np.maximum(gap, 0.0), 0.0))
        edge_any |= present & np.isfinite(zte).any(axis=1)

    # Where there is no kerb/pavement the road's own skirt is the only thing hiding a gap, and the only
    # place a gap can be SEEN is the ribbon's two edges: a dip under the middle of the carriageway is
    # covered by the carriageway itself.  (With a kerb the outer face of the pavement block is the
    # visible edge, handled above.)
    skirt_drop = np.asarray(sp.skirt_drop_m, dtype=np.float64)
    edge_clear = np.where(ok[:, [0, -1]], clear[:, [0, -1]], -np.inf).max(axis=1)
    float_road = np.where(edge_any, 0.0, np.maximum(0.0, edge_clear - skirt_drop))
    float_road[~np.isfinite(float_road)] = 0.0

    pen = np.maximum(np.maximum(0.0, -min_clear), pen_edge)
    flt = np.maximum(float_edge, float_road)
    return {"s": sp.s, "span": station_spans(sp.s), "min_clear": min_clear, "max_clear": max_clear,
            "penetration": pen, "float": flt, "pen_carriageway": np.maximum(0.0, -min_clear),
            "pen_edge": pen_edge, "valid": np.isfinite(min_clear), "xy": sp.xy}


def rule_delta(sp, hf, k_road: int = 9):
    """The same landscape, the same corridor points, read with BOTH interpolation rules.

    Between its 1 m posts a landscape is not one surface but two candidate ones: ``bilinear``, which
    is the numpy/plugin contract (DESIGN.md 8) and the rule the corridor conform was burned against,
    and ``landscape_triangulated``, which is what ALandscape's own triangle pair returns and what the
    camera sees (docs/TERRAIN_ROADS.md 3.3).  They can differ by up to ``|twist| / 4`` of a quad --
    6.12 m at the site maximum -- so "the road is above the ground" is not one claim but two, and the
    only way to know whether the difference matters is to measure it INSIDE the corridors rather than
    over the isle at large.  This is that measurement, per spline; ``road_fusion_audit.py --rules``
    aggregates it.

    Returns ``(delta, clear_bilinear, clear_triangulated)`` over the carriageway grid with the
    off-coverage points dropped: ``delta = z_bilinear - z_triangulated`` and each clearance is
    ``z_road - z_ground``, so a NEGATIVE clearance is ground standing in the carriageway.
    ``hf.sampling`` is restored, so an audit that samples with one rule is unaffected by this call.
    """
    X, Y, Z = carriageway_points(sp, k_road)
    x, y, z = X.ravel(), Y.ravel(), Z.ravel()
    prev = hf.sampling
    try:
        hf.sampling = "bilinear"
        zb = hf.sample(x, y)
        hf.sampling = "landscape_triangulated"
        zt = hf.sample(x, y)
    finally:
        hf.sampling = prev
    ok = np.isfinite(zb) & np.isfinite(zt)
    return (zb[ok] - zt[ok]).astype(np.float32), (z[ok] - zb[ok]).astype(np.float32), (z[ok] - zt[ok]).astype(np.float32)


def rule_summary(delta, clear_b, clear_t) -> dict:
    """Aggregate ``rule_delta`` output into the block ``road_fusion_audit.py --rules`` reports."""
    def dist(v, name):
        v = np.asarray(v, dtype=np.float64)
        v = v[np.isfinite(v)]
        if v.size == 0:
            return {"n": 0, "name": name}
        return {"n": int(v.size), "name": name, "min": float(v.min()), "max": float(v.max()),
                "p50": _pct(v, 50), "p95": _pct(v, 95), "p99": _pct(v, 99), "p999": _pct(v, 99.9),
                "mean": float(v.mean()),
                "frac_gt_0.03": float((v > 0.03).mean()), "frac_gt_0.10": float((v > 0.10).mean())}
    delta = np.concatenate(delta) if isinstance(delta, list) else np.asarray(delta)
    clear_b = np.concatenate(clear_b) if isinstance(clear_b, list) else np.asarray(clear_b)
    clear_t = np.concatenate(clear_t) if isinstance(clear_t, list) else np.asarray(clear_t)
    return {"points": int(delta.size),
            "abs_bilinear_minus_triangulated_m": dist(np.abs(delta), "|bilinear - triangulated|"),
            "signed_bilinear_minus_triangulated_m": dist(delta, "bilinear - triangulated"),
            "clearance_bilinear_m": dist(clear_b, "road - ground (bilinear)"),
            "clearance_triangulated_m": dist(clear_t, "road - ground (triangulated)"),
            "points_with_ground_above_road_bilinear": int((clear_b < 0).sum()),
            "points_with_ground_above_road_triangulated": int((clear_t < 0).sum()),
            "note": ("measured at the carriageway points of every audited spline.  If the two rules "
                     "disagree by less than the sink, the sampling rule is not what hides a road.")}


def terrain_slope_deg(hf, x, y, step=1.0):
    zx1 = hf.sample(x + step, y)
    zx0 = hf.sample(x - step, y)
    zy1 = hf.sample(x, y + step)
    zy0 = hf.sample(x, y - step)
    return np.degrees(np.arctan(np.hypot((zx1 - zx0) / (2 * step), (zy1 - zy0) / (2 * step))))


def _pct(v, q):
    v = np.asarray(v, dtype=np.float64)
    return float(np.percentile(v, q)) if v.size else 0.0


def _dist(v):
    v = np.asarray(v, dtype=np.float64)
    if v.size == 0:
        return {"n": 0}
    return {"n": int(v.size), "max": float(v.max()), "p99": _pct(v, 99), "p95": _pct(v, 95),
            "p50": _pct(v, 50), "mean": float(v.mean())}


def aggregate(records, gate_m=0.005, float_gate_m=0.125):
    """records: [(cls, slope_or_None, audit_spline result)] -> the report block."""
    if not records:
        return {"stations_with_terrain": 0}
    cat = lambda key: np.concatenate([r[key] for _, _, r in records])       # noqa: E731
    valid = cat("valid")
    pen = cat("penetration")[valid]
    flt = cat("float")[valid]
    penc = cat("pen_carriageway")[valid]
    pene = cat("pen_edge")[valid]
    span = cat("span")[valid]
    mc = cat("min_clear")[valid]
    cls = np.concatenate([np.full(len(r["valid"]), c, dtype=object) for c, _, r in records])[valid]
    sl = np.concatenate([(np.full(len(r["valid"]), np.nan) if s is None else s) for _, s, r in records])[valid]
    hit = pen > gate_m
    fhit = flt > float_gate_m
    out = {
        "splines": len(records),
        "stations_with_terrain": int(valid.sum()),
        "stations_penetrated": int(hit.sum()),
        "fraction_stations_penetrated": float(hit.mean()) if pen.size else 0.0,
        "carriageway_km_total": float(span.sum()) / 1000.0,
        "carriageway_km_penetrated": float(span[hit].sum()) / 1000.0,
        "fraction_length_penetrated": float(span[hit].sum() / span.sum()) if span.sum() else 0.0,
        "penetration_gate_m": gate_m,
        "penetration_m_over_penetrated_stations": _dist(pen[hit]),
        "penetration_m_over_all_stations": _dist(pen),
        "penetration_carriageway_m": _dist(penc),
        "penetration_kerb_pavement_m": _dist(pene),
        "float_gate_m": float_gate_m,
        "stations_floating": int(fhit.sum()),
        "fraction_stations_floating": float(fhit.mean()) if flt.size else 0.0,
        "float_km": float(span[fhit].sum()) / 1000.0,
        "float_m_over_all_stations": _dist(flt),
        "float_m_over_floating_stations": _dist(flt[fhit]),
        "min_clearance_m_distribution": {"min": float(mc.min()), "p01": _pct(mc, 1), "p05": _pct(mc, 5),
                                         "p50": _pct(mc, 50), "p95": _pct(mc, 95), "max": float(mc.max())},
    }
    by_cls = {}
    for c in sorted(set(cls.tolist())):
        m = cls == c
        by_cls[c] = {"stations": int(m.sum()), "fraction_penetrated": float(hit[m].mean()),
                     "km_total": float(span[m].sum()) / 1000.0,
                     "km_penetrated": float(span[m & hit].sum()) / 1000.0,
                     "pen_max_m": float(pen[m].max()), "pen_p95_m": _pct(pen[m & hit], 95),
                     "pen_p50_m": _pct(pen[m & hit], 50),
                     "float_max_m": float(flt[m].max()), "fraction_floating": float(fhit[m].mean())}
    out["by_class"] = by_cls
    by_slope = {}
    for lo, hi in ((0, 2), (2, 5), (5, 10), (10, 20), (20, 90)):
        m = np.isfinite(sl) & (sl >= lo) & (sl < hi)
        by_slope["%d-%d deg" % (lo, hi)] = {
            "stations": int(m.sum()),
            "fraction_penetrated": float(hit[m].mean()) if m.any() else 0.0,
            "km_total": float(span[m].sum()) / 1000.0,
            "km_penetrated": float(span[m & hit].sum()) / 1000.0,
            "pen_max_m": float(pen[m].max()) if m.any() else 0.0,
            "pen_p95_m": _pct(pen[m & hit], 95),
            "float_max_m": float(flt[m].max()) if m.any() else 0.0}
    out["by_terrain_slope"] = by_slope
    return out
