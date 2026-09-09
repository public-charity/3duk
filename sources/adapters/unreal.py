#!/usr/bin/env python3
"""Neutral pipeline output -> Streetscape-frame products for Unreal and Blender.

Run after the pipeline (steps 05-11), from the repo root, with the GDAL environment:

    PATH=/c/Users/Shadow/code/3duk-env/env/Library/bin:$PATH SITE=<site> \\
        C:/Users/Shadow/code/3duk-env/env/python.exe sources/adapters/unreal.py \\
        [--only landscape,streetscape,massing,furniture] [--strict]

--only rebuilds a subset; the root manifest then carries the other products' entries over from the
manifest it replaces (never null: they are still on disk) and records what it rebuilt in partial_run.
--strict turns the four "step NN not run" warnings (no coast/, networks/, massing/, furniture/, no
linear_manifest.json) into refusals: stage 1 legitimately runs the adapter before step 09 exists, so
they are warnings by default, but a full-pipeline run should not degrade a product in silence.

Reads data/<site>/out/ (terrain, networks incl. step 11, coast, massing, furniture and their
manifests) plus data/<site>/derived/<site>.gpkg (the raw OSM way geometry and other_tags -- the one
product not in out/), and writes data/<site>/out/unreal/ (PIPELINE_CHANGES.md 13). It mirrors
sources/adapters/unity.py in shape -- need(), one function per product, a _note-carrying unreal.json,
refusal over silent clipping -- but bakes NO engine frame: everything it writes is the Streetscape
frame of BRIEF.md 4.2 / DESIGN.md 2:

  coordinates   x = E - E0, y = N - N0 (local metres), z = ODN metres unchanged, right-handed, Z up
  heightmaps    16-bit h16 = round(z*128) + 32768, north row first, NO flip (the landscape importer
                indexes row 0 as the smallest UE Y, which is north)
  orientation   bearing (cw from grid north) kept; heading_deg = ((90 - bearing + 180) mod 360) - 180

The x100 / Y-flip / yaw sign to Unreal (X_ue = 100x, Y_ue = -100y, Z_ue = 100z; yaw_ue = bearing - 90)
are applied ONLY by the Unreal plugin's JSON loader and landscape importer; they are quoted in every
manifest for the record and never applied here. Module level does no site I/O (lib.load() runs inside
main()), so sources/tests/test_unreal_adapter.py can unit-test the pure functions after loading this
file with importlib. Runs under the fake GDAL of sources/tests/fake_osgeo with numpy only.
"""
import glob, json, math, os, subprocess, sys
from collections import Counter, defaultdict
import numpy as np
from osgeo import gdal, ogr
gdal.UseExceptions(); ogr.UseExceptions()

SOURCES = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
REPO = os.path.dirname(SOURCES)
sys.path.insert(0, SOURCES)
import lib

ADP_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "unreal.json")
SCHEMA_VERSION = "1.0.0"
FRAME = "local-metres, X east, Y north, Z up"        # the schema const, verbatim
FRAME_NOTE = ("x = E - E0 (east), y = N - N0 (north), z = ODN metres unchanged; right-handed, Z up. Unreal: X_ue = 100*x, "
              "Y_ue = -100*y, Z_ue = 100*z (cm, +Y south); yaw_ue = bearing - 90 = -heading_deg. Applied only by the Unreal loader/importer.")
GENERATOR_STEM = "sources/adapters/unreal.py"


def need(path, what):
    if not os.path.exists(path):
        sys.exit(f"unreal adapter: {what} missing at {path}; run the pipeline first")
    return path


def _jload(path):
    with open(path, encoding="utf-8") as fh:
        return json.load(fh)


def _jdump(obj, path, indent=1):
    with open(path, "w", encoding="utf-8", newline="\n") as fh:
        json.dump(obj, fh, indent=indent, separators=None if indent else (",", ":"))
        fh.write("\n")


def _clear(directory, *patterns):
    """Remove this adapter's own products of a previous run so stale tiles never sit beside new ones."""
    for pat in patterns:
        for old in glob.glob(os.path.join(directory, pat)):
            os.remove(old)


# =============================================================================================
# pure functions -- unit-tested by sources/tests/test_unreal_adapter.py
# =============================================================================================

def encode_h16(z_m, per_unit=128, offset=32768):
    """Landscape height encoding: h16 = round(z_m * per_unit) + offset as '<u2' (LANDSCAPE_ZSCALE = 1/128,
    MidValue 32768; LandscapeDataAccess.h:13, :27). Refuses a value outside 0..65535 instead of wrapping."""
    z = np.asarray(z_m, dtype=np.float64)
    h = np.rint(z * per_unit) + offset
    if not np.all(np.isfinite(h)):
        sys.exit("unreal adapter: encode_h16 met a non-finite elevation (fill the raster first)")
    if h.min() < 0 or h.max() > 65535:
        lo, hi = (h.min() - offset) / per_unit, (h.max() - offset) / per_unit
        sys.exit(f"unreal adapter: elevation {lo}..{hi} m does not fit the h16 window "
                 f"{-offset / per_unit}..{(65535 - offset) / per_unit} m")
    return h.astype("<u2")


def decode_h16(h16, per_unit=128, offset=32768):
    """z_m = (h16 - offset) / per_unit as float64; |decode(encode(z)) - z| <= 1/(2*per_unit) = 1/256 m."""
    return (np.asarray(h16).astype(np.float64) - offset) / per_unit


def check_range(range_m, limit_m):
    """Refuse a site whose true elevation range falls outside the encodable window. The old Unity path
    clipped in silence and produced plateaus; GetTexHeight (LandscapeDataAccess.h:35) would too."""
    lo, hi = float(range_m[0]), float(range_m[1])
    if lo < limit_m[0] or hi > limit_m[1]:
        sys.exit(f"unreal adapter: site elevation {lo}..{hi} m does not fit the landscape encoding window "
                 f"{limit_m[0]}..{limit_m[1]} m (landscape.range_limit_m in sources/adapters/unreal.json) "
                 f"-- encoding as-is would clamp real ground. Refusing.")


def survey_to_local(E, N, z, E0, N0):
    return (E - E0, N - N0, z)


def local_to_ue_cm(x, y, z):
    """The Unreal plugin's conversion, quoted for tests and docs only; never applied to a product."""
    return (100.0 * x, -100.0 * y, 100.0 * z)


def bearing_to_heading_deg(b):
    """Right-handed angle from +X (east) toward +Y (north), in [-180, 180). bearing 270 -> -180, 131 -> -41."""
    return ((90.0 - float(b) + 180.0) % 360.0) - 180.0


def bearing_to_ue_yaw(b):
    """yaw_ue = bearing - 90 (mod 360) = -heading_deg. Loader only; quoted for tests and docs."""
    return (float(b) - 90.0) % 360.0


def visibility_weight(d_m, px_m=1.0):
    """Landscape visibility weight for a vertex d_m metres INTO the clipped half-plane:
    round(clamp(2/3 + d/(3 px), 0, 1) * 255): 170 on the line, 255 from 1 px into the cut, 0 from 2 px
    into the kept side. The render threshold is 2/3 (LandscapeDataAccess.h:19), so the edge is the line."""
    d = np.asarray(d_m, dtype=np.float64)
    w = np.clip(2.0 / 3.0 + d / (3.0 * px_m), 0.0, 1.0) * 255.0
    return np.rint(w).astype(np.uint8)


def catmull_rom_dense(P, alpha=0.5, n=32):
    """The schema interpolant (SCHEMA.md 3.1): centripetal Catmull-Rom (Barry-Goldman) through P (K x 2)
    with phantom end points, n samples per segment. K == 2 -> the straight chord. Returns (M x 2)."""
    P = np.asarray(P, dtype=np.float64)
    K = len(P)
    if K < 2:
        return P.copy()
    if K == 2:
        t = np.linspace(0.0, 1.0, n)[:, None]
        return P[0] + t * (P[1] - P[0])
    ext = np.vstack([2 * P[0] - P[1], P, 2 * P[-1] - P[-2]])
    pieces = []
    for i in range(K - 1):
        P0, P1, P2, P3 = ext[i], ext[i + 1], ext[i + 2], ext[i + 3]
        t0 = 0.0
        t1 = t0 + max(np.linalg.norm(P1 - P0) ** alpha, 1e-9)
        t2 = t1 + max(np.linalg.norm(P2 - P1) ** alpha, 1e-9)
        t3 = t2 + max(np.linalg.norm(P3 - P2) ** alpha, 1e-9)
        t = np.linspace(t1, t2, n)[:, None]
        A1 = (t1 - t) / (t1 - t0) * P0 + (t - t0) / (t1 - t0) * P1
        A2 = (t2 - t) / (t2 - t1) * P1 + (t - t1) / (t2 - t1) * P2
        A3 = (t3 - t) / (t3 - t2) * P2 + (t - t2) / (t3 - t2) * P3
        B1 = (t2 - t) / (t2 - t0) * A1 + (t - t0) / (t2 - t0) * A2
        B2 = (t3 - t) / (t3 - t1) * A2 + (t - t1) / (t3 - t1) * A3
        C = (t2 - t) / (t2 - t1) * B1 + (t - t1) / (t2 - t1) * B2
        pieces.append(C if i == 0 else C[1:])
    return np.vstack(pieces)


def _dist_to_polyline(P, Q):
    """Distance of every point of P (M x 2) to the polyline Q (S x 2): min over segments of the
    point-to-segment distance (not point-to-sample, so a coarse sampling cannot overstate it)."""
    P = np.asarray(P, dtype=np.float64); Q = np.asarray(Q, dtype=np.float64)
    if len(Q) == 1:
        return np.hypot(P[:, 0] - Q[0, 0], P[:, 1] - Q[0, 1])
    A, B = Q[:-1], Q[1:]
    AB = B - A
    L2 = (AB * AB).sum(axis=1)
    L2 = np.where(L2 > 0, L2, 1.0)
    out = np.empty(len(P))
    step = max(1, 400000 // max(len(A), 1))          # bound the M x S working set
    for k in range(0, len(P), step):
        p = P[k:k + step]
        AP = p[:, None, :] - A[None, :, :]
        t = np.clip((AP * AB[None, :, :]).sum(axis=2) / L2[None, :], 0.0, 1.0)
        D = AP - t[:, :, None] * AB[None, :, :]
        out[k:k + step] = np.sqrt((D * D).sum(axis=2)).min(axis=1)
    return out


def _dp_indices(xy, tol, lo, hi):
    """Douglas-Peucker on xy[lo..hi] (inclusive), returning the kept interior indices."""
    kept = []
    stack = [(lo, hi)]
    while stack:
        a, b = stack.pop()
        if b - a < 2:
            continue
        seg = xy[a + 1:b]
        d = _dist_to_polyline(seg, xy[[a, b]])
        k = int(np.argmax(d))
        if d[k] > tol:
            m = a + 1 + k
            kept.append(m)
            stack.append((a, m)); stack.append((m, b))
    return kept


THIN_SAMPLES = 32                 # interpolant samples per segment while thinning (fast)
THIN_VERIFY_SAMPLES = 128         # ... and for the deviation that is measured and reported


def thin_against_interpolant(xy, tol_m, keep=(), samples=THIN_SAMPLES, verify_samples=THIN_VERIFY_SAMPLES):
    """PIPELINE_CHANGES.md 13.7: keep the first and last vertex and every index in `keep`, start from
    Douglas-Peucker at tol_m, then add the original vertex farthest from the centripetal Catmull-Rom
    through the kept points while that distance exceeds tol_m. tol_m <= 0 keeps everything.
    Returns (sorted kept indices, max deviation of any original vertex from the final curve).

    The deviation is measured against the interpolant SAMPLED as a polyline, and the chords of a
    curved segment lie inside the curve, so a coarse sampling understates the deviation of the curve
    a consumer actually reconstructs (measured: 0.09999 m at 32 samples/segment against 0.10027 m
    converged, on Thanet's worst spline). The thinning therefore runs a second pass at
    verify_samples (converged to ~1e-5 m; 32 -> 128 changes the measure by <= 0.3 mm and 128 -> 512
    by <= 1.3e-5 m) and keeps adding vertices until the DENSE measure is within tol_m too. The
    returned deviation is that dense one, so `thin_max_dev_m` is a claim about the shipped curve
    rather than about our sampling of it."""
    xy = np.asarray(xy, dtype=np.float64)
    K = len(xy)
    if K <= 2:
        return list(range(K)), 0.0
    forced = sorted(set([0, K - 1]) | set(int(k) for k in keep if 0 <= int(k) < K))
    if tol_m <= 0:
        return list(range(K)), 0.0
    kept = set(forced)
    for a, b in zip(forced, forced[1:]):
        kept.update(_dp_indices(xy, tol_m, a, b))
    idx = sorted(kept)
    dev_max = 0.0
    for n in (samples, verify_samples):
        for _ in range(K + 1):
            dev = _dist_to_polyline(xy, catmull_rom_dense(xy[idx], n=n))
            dev[idx] = 0.0
            dev_max = float(dev.max())
            if dev_max <= tol_m:
                break
            kept.add(int(np.argmax(dev))); idx = sorted(kept)
    return idx, dev_max


def _locate_on_polyline(p, raw):
    """Project p onto the raw polyline (K x 2). Returns (u metres along the way, distance). Ties go to the
    smallest u, so a closed loop's first vertex keys to segment 0 rather than to the closing segment."""
    raw = np.asarray(raw, dtype=np.float64)
    if len(raw) == 1:
        return 0.0, float(math.hypot(p[0] - raw[0, 0], p[1] - raw[0, 1]))
    A, B = raw[:-1], raw[1:]
    AB = B - A
    L = np.hypot(AB[:, 0], AB[:, 1])
    L2 = np.where(L > 0, L * L, 1.0)
    AP = np.asarray(p, dtype=np.float64)[None, :] - A
    t = np.clip((AP * AB).sum(axis=1) / L2, 0.0, 1.0)
    t = np.where(L > 0, t, 0.0)
    D = AP - t[:, None] * AB
    d = np.hypot(D[:, 0], D[:, 1])
    best = d.min()
    k = int(np.flatnonzero(d <= best + 1e-9)[0])
    cum = np.concatenate([[0.0], np.cumsum(L)])
    return float(cum[k] + t[k] * L[k]), float(best)


def order_runs(raw_xy, runs):
    """PIPELINE_CHANGES.md 13.6: order the tile runs of one (layer, osm_id) along the raw OSM way by
    projecting each run's first vertex onto it. Returns [{'rec', 'segment_index', 'u', 'dist_m',
    'from', 'to'}] where from/to are 'seam' (the runs share the seam vertex exactly), 'gap' (an
    off-grid / off-clip excursion between them) or None at the way's ends."""
    keyed = []
    for k, rec in enumerate(runs):
        p = rec["pts"][0]
        u, d = _locate_on_polyline((p[0], p[1]), raw_xy)
        keyed.append((u, k, d, rec))
    keyed.sort(key=lambda t: (t[0], t[1]))
    out = [{"rec": rec, "segment_index": i, "u": u, "dist_m": d, "from": None, "to": None}
           for i, (u, k, d, rec) in enumerate(keyed)]
    for a, b in zip(out, out[1:]):
        pa, pb = a["rec"]["pts"][-1], b["rec"]["pts"][0]
        kind = "seam" if (pa[0] == pb[0] and pa[1] == pb[1]) else "gap"
        a["to"] = kind; b["from"] = kind
    return out


def relink_runs(kept_runs):
    """Re-index the runs of one way that survived the degenerate drop, and re-judge each join on the
    two survivors' own end points. `order_runs` numbered ALL the way's runs and described each join
    with the run that was then its neighbour; after a drop those numbers and flags describe runs that
    are not in the product: `segment_index` would no longer index `segment_count = len(kept_runs)`,
    a survivor whose neighbour was dropped would keep a 'seam'/'gap' flag toward nothing (so its end
    is never registered as a way end and the seam count includes a join that does not exist), and the
    join between two survivors would be inherited rather than measured. Mutates and returns kept_runs
    ([(ordered entry, merged points)])."""
    for k, (o_, _) in enumerate(kept_runs):
        o_["segment_index"] = k
        o_["from"] = o_["to"] = None
    for (oa, pa), (ob, pb) in zip(kept_runs, kept_runs[1:]):
        kind = "seam" if (pa[-1][0] == pb[0][0] and pa[-1][1] == pb[0][1]) else "gap"
        oa["to"] = kind; ob["from"] = kind
    return kept_runs


def nearest_z(xy, chain_xyz):
    """z of the step-06/11 vertex nearest to xy (chain_xyz: M x 3)."""
    c = np.asarray(chain_xyz, dtype=np.float64)
    d = np.hypot(c[:, 0] - xy[0], c[:, 1] - xy[1])
    return float(c[int(np.argmin(d)), 2])


def _clip_pieces(pieces, f):
    """Clip polyline pieces ([(E, N, u, is_cross)] lists) against the half-plane f(E, N) >= 0, inserting
    the crossing point on the boundary. Returns (pieces, dropped original vertices)."""
    out, dropped = [], 0
    for piece in pieces:
        vals = [float(f(p[0], p[1])) for p in piece]
        cur = []
        for k, (p, fp) in enumerate(zip(piece, vals)):
            if fp >= 0.0:
                cur.append(p)
            else:
                if not p[3]: dropped += 1
            if k + 1 < len(piece):
                q, fq = piece[k + 1], vals[k + 1]
                if (fp >= 0.0) != (fq >= 0.0):
                    t = fp / (fp - fq)
                    cross = (p[0] + (q[0] - p[0]) * t, p[1] + (q[1] - p[1]) * t, p[2] + (q[2] - p[2]) * t, True)
                    if fp >= 0.0:
                        cur.append(cross); out.append(cur); cur = []
                    else:
                        cur = [cross]
        if cur: out.append(cur)
    return [pc for pc in out if len(pc) >= 1], dropped


def clip_polyline(xy_list, cfg, clip):
    """PIPELINE_CHANGES.md 13.9: the raw OSM way clipped to the grid rectangle (four half-planes) and
    then to the clip half-plane, with the exact crossing point inserted on each boundary. Returns
    (pieces, n_dropped): every piece is a list of (E, N, u, is_cross) with u the arc-length parameter
    along the raw way (interpolated on inserted crossings); n_dropped counts raw vertices removed."""
    E0, N0, T = cfg["origin"]["E"], cfg["origin"]["N"], cfg["tile_m"]
    E1, N1 = E0 + cfg["nx"] * T, N0 + cfg["ny"] * T
    u, pts = 0.0, []
    for k, (e, n) in enumerate(xy_list):
        if k: u += math.hypot(e - xy_list[k - 1][0], n - xy_list[k - 1][1])
        pts.append((float(e), float(n), u, False))
    pieces, dropped = [pts], 0
    for f in (lambda e, n: e - E0, lambda e, n: E1 - e, lambda e, n: n - N0, lambda e, n: N1 - n):
        pieces, d = _clip_pieces(pieces, f); dropped += d
    if clip is not None:
        pieces, d = _clip_pieces(pieces, lambda e, n: -float(clip.signed_distance_out(e, n))); dropped += d
    return pieces, dropped


def parse_height_m(text):
    """OSM height string -> metres, or None. Fallback only: step 11 emits h. First token; unit suffix
    m (default) / cm / mm / ft or ' (x 0.3048)."""
    if text is None: return None
    s = str(text).strip().lower().replace(",", ".")
    import re
    m = re.match(r"^([0-9]*\.?[0-9]+)\s*(mm|cm|m|feet|ft|')?", s)      # longest unit first: '1200mm' is not 1200 m
    if not m: return None
    v = float(m.group(1)); unit = m.group(2) or "m"
    return v * {"m": 1.0, "cm": 0.01, "mm": 0.001, "ft": 0.3048, "feet": 0.3048, "'": 0.3048}[unit]


def classify_barrier(cls, rec, adp):
    """First matching type rule of unreal.json barrier.type_rules wins ([cls, {field: value}, type]).
    Returns (type, height_m, thickness_m, material, height_src) or None for a class with no rule.
    height_src: the record's h_src ('osm' / 'default' from step 11), 'adapter_parsed' (an OSM height
    string parsed here) or 'adapter_default' (unreal.json default_height_m)."""
    B = adp["barrier"]
    btype = None
    for rcls, cond, t in B["type_rules"]:
        if rcls == cls and all(rec.get(k) == v for k, v in cond.items()):
            btype = t; break
    if btype is None:
        return None
    h, src = rec.get("h"), rec.get("h_src") or "osm"
    if h is None:
        h = parse_height_m(rec.get("height")); src = "adapter_parsed"
    if h is None:
        h = B["default_height_m"].get(btype); src = "adapter_default"
    return (btype, h, B["default_thickness_m"].get(btype), B["material_by_type"].get(btype), src)


def rail_profile_for(gauge_m, adp):
    """(profile id, gauge_unmapped) for a rail record's gauge in metres."""
    if gauge_m is not None:
        pid = adp["rail_profile_by_gauge_m"].get(f"{float(gauge_m):.3f}")
        if pid: return pid, False
    return adp["rail_profile_fallback"], True


def profile_ids_for(layer, cls, tags, adp):
    """The five ProfileIds keys for a spline (PIPELINE_CHANGES.md 13.5 / 13.12). tags: the stringified
    source tags (sidewalk*, ...). Refuses an unmapped road class. Barrier classes map through the
    'kerb' / 'hedge' / barrier-segment split. A rail spline's road profile is deliberately NOT decided
    here -- the caller fills ids['road'] from rail_profile_for(<the record's numeric gauge>) so that
    gauge reaches a profile id down exactly one path (the OSM `gauge` tag string is step 11's input,
    not a second source of truth)."""
    ids = {"road": None, "edge_left": None, "edge_right": None, "hedge_left": None, "hedge_right": None}
    if layer == "roads":
        road = adp["road_profile_by_class"].get(cls)
        if road is None:
            sys.exit(f"unreal adapter: highway class {cls!r} has no entry in unreal.json road_profile_by_class")
        ids["road"] = road
        if cls in adp["path_classes"]:
            return ids
        # sidewalk rule (13.5): both/yes/absent -> both sides; left/right (or sidewalk:left|right=yes alone)
        # -> that side only; no/separate -> none. The per-side tags are read only without a plain sidewalk tag.
        sw, swl, swr, swb = (tags.get(k) for k in ("sidewalk", "sidewalk:left", "sidewalk:right", "sidewalk:both"))
        off = ("no", "separate", "none")
        left, right = True, True
        if sw is not None:
            if sw in off: left = right = False
            elif sw == "left": right = False
            elif sw == "right": left = False
        elif swb is not None:
            left = right = swb not in off
        elif swl is not None or swr is not None:
            if swl == "yes" and swr is None: left, right = True, False
            elif swr == "yes" and swl is None: left, right = False, True
            else: left, right = swl not in off, swr not in off
        edge = adp["edge_profile_default"]
        ids["edge_left"] = edge if left else None
        ids["edge_right"] = edge if right else None
        return ids
    if layer == "rail":
        return ids                                   # ids['road'] is the caller's, via rail_profile_for
    if layer == "barriers":
        if cls == "kerb":
            ids["edge_left"] = adp["edge_profile_default"]
        elif cls == "hedge":
            ids["hedge_left"] = adp["barrier"]["hedge_profile"]
        else:
            ids["edge_left"] = adp["barrier"]["edge_profile"]
        return ids
    sys.exit(f"unreal adapter: unknown layer {layer!r}")


def load_profiles(profiles_dir):
    """{kind: {id: profile}} from projects/one/schema/profiles/*.json ({kind, id, profile} files).
    Refuses a bad shape, an id that differs from the file name, or a duplicate id."""
    if not os.path.isdir(profiles_dir):
        sys.exit(f"unreal adapter: profiles_dir {profiles_dir} does not exist")
    out, seen = {"road": {}, "edge": {}, "hedge": {}}, {}
    for path in sorted(glob.glob(os.path.join(profiles_dir, "*.json"))):
        d = _jload(path)
        stem = os.path.basename(path)[:-5]
        if not isinstance(d, dict) or d.get("kind") not in out or not isinstance(d.get("profile"), dict) or not isinstance(d.get("id"), str):
            sys.exit(f"unreal adapter: profile file {path} is not {{kind: road|edge|hedge, id, profile}}")
        if d["id"] != stem:
            sys.exit(f"unreal adapter: profile id {d['id']!r} != file name {stem!r} in {path}")
        if d["id"] in seen:
            sys.exit(f"unreal adapter: duplicate profile id {d['id']!r} ({seen[d['id']]} and {path})")
        seen[d["id"]] = path
        out[d["kind"]][d["id"]] = d["profile"]
    return out


def git_sha():
    """The commit the products claim to come from, with '-dirty' when the adapter's OWN source or
    settings differ from it -- a product written from uncommitted code must not claim a clean sha."""
    try:
        r = subprocess.run(["git", "rev-parse", "--short", "HEAD"], cwd=REPO, capture_output=True, text=True, timeout=20)
        s = r.stdout.strip()
        if r.returncode != 0 or not s:
            return "unknown"
        d = subprocess.run(["git", "status", "--porcelain", "--", "sources/adapters/unreal.py", "sources/adapters/unreal.json"],
                           cwd=REPO, capture_output=True, text=True, timeout=20)
        return s + ("-dirty" if d.returncode == 0 and d.stdout.strip() else "")
    except Exception:
        return "unknown"


def check_adapter_settings(adp, tuning, profiles):
    """Start-up refusals: every profile id the class map can produce must exist in profiles_dir, and every
    class of tuning.json roads.widths_m must have a road profile mapping."""
    S = adp["streetscape"]
    for cls, pid in S["road_profile_by_class"].items():
        if pid not in profiles["road"]:
            sys.exit(f"unreal adapter: road_profile_by_class[{cls!r}] = {pid!r} is not in profiles_dir")
    for g, pid in S["rail_profile_by_gauge_m"].items():
        if pid not in profiles["road"]:
            sys.exit(f"unreal adapter: rail_profile_by_gauge_m[{g!r}] = {pid!r} is not in profiles_dir")
    if S["rail_profile_fallback"] not in profiles["road"]:
        sys.exit(f"unreal adapter: rail_profile_fallback {S['rail_profile_fallback']!r} is not in profiles_dir")
    if S["edge_profile_default"] not in profiles["edge"]:
        sys.exit(f"unreal adapter: edge_profile_default {S['edge_profile_default']!r} is not in profiles_dir")
    if S["barrier"]["edge_profile"] not in profiles["edge"]:
        sys.exit(f"unreal adapter: barrier.edge_profile {S['barrier']['edge_profile']!r} is not in profiles_dir")
    if S["barrier"]["hedge_profile"] not in profiles["hedge"]:
        sys.exit(f"unreal adapter: barrier.hedge_profile {S['barrier']['hedge_profile']!r} is not in profiles_dir")
    widths = tuning.get("roads", {}).get("widths_m", {})
    missing = sorted(c for c in widths if not c.startswith("_") and c not in S["road_profile_by_class"])
    if missing:
        sys.exit(f"unreal adapter: tuning.json roads.widths_m classes without a road profile mapping: {missing}")


# =============================================================================================
# products
# =============================================================================================

def _epsg_of(cfg):
    """The site's EPSG code as a string, or None if crs is not written as 'EPSG:<code>'."""
    crs = str(cfg.get("crs", ""))
    return crs.split(":", 1)[1].strip() if crs.upper().startswith("EPSG:") and ":" in crs else None


def check_georef(path, gt, want, proj, epsg, tol_m=1e-6):
    """Refuse a source raster whose own georeference is not the one its tile index implies, or whose
    projection is not the site CRS. Shape alone cannot catch a tile that carries a NEIGHBOUR's data:
    the product would be self-consistent and silently misplaced. `want` is the expected geotransform."""
    if gt is None or len(gt) != 6 or any(abs(float(a) - float(b)) > tol_m for a, b in zip(gt, want)):
        sys.exit(f"unreal adapter: {path} is georeferenced at {tuple(gt) if gt else None} but its tile index "
                 f"implies {tuple(want)} -- the raster does not cover the tile its name claims; re-run the step "
                 f"that wrote it")
    if epsg is not None and epsg not in str(proj or ""):
        sys.exit(f"unreal adapter: {path} carries projection {str(proj)[:60]!r}, which does not mention the site "
                 f"CRS EPSG:{epsg} -- the raster is in another CRS or unprojected; re-run the step that wrote it")


def _seam_qa(edges, per_unit):
    """Neighbouring tiles share an edge of samples (513 verts per 512 m tile, the last column of one
    IS the first column of the next), and the landscape has one vertex there: if the two tiles carry
    different heights the importer must silently pick one.

    Three counts, because they fail for three different reasons:
      * `_all`      -- EVERY shared sample, kept or clipped. Both fills that reach this product are
                       now decided once over the site mosaic (step 05's coverage gaps, this adapter's
                       clipped cells), so this must be 0. It was 35,951 samples and 10.95 m on the
                       Thanet product built the old per-tile way (TERRAIN_ROADS.md 2.4).
      * plain       -- samples both tiles mark keep: the ones a player can stand on. 28,725 and 5.34 m.
      * `fill_free` -- samples on an edge where NEITHER tile needed a fill at all. Those are copied
                       straight from one source composite and cannot legitimately differ by any rule:
                       a difference there means the terrain product was written by more than one run.
    """
    q = {"edges_compared": 0, "samples_compared": 0, "samples_disagreeing": 0,
         "samples_disagreeing_on_fill_free_edges": 0, "max_disagreement_m": 0.0, "max_at": None,
         "samples_compared_all": 0, "samples_disagreeing_all": 0, "max_disagreement_all_m": 0.0,
         "max_at_all": None,
         "note": "Shared-edge samples of the h16 tiles. `samples_compared`/`samples_disagreeing` count only "
                 "the samples both clip masks mark keep; the `_all` pair counts every shared sample "
                 "including the invented ground behind the clip. Both must be 0: step 05 fills coverage "
                 "gaps once over the site mosaic and this adapter fills the clipped cells the same way, so "
                 "no shared sample is decided twice. Non-zero means a stale or torn terrain product -- "
                 "re-run step 05 for the whole site, then this adapter."}
    for (i, j), E in edges.items():
        for (di, dj), a_side, b_side in (((1, 0), "e", "w"), ((0, 1), "n", "s")):
            F = edges.get((i + di, j + dj))
            if F is None:
                continue
            a, ka = E[a_side]
            b, kb = F[b_side]
            both = ka & kb
            q["edges_compared"] += 1
            q["samples_compared"] += int(both.sum())
            d_all = a.astype(np.int64) - b.astype(np.int64)
            q["samples_compared_all"] += int(d_all.size)
            n_all = int((d_all != 0).sum())
            if n_all:
                q["samples_disagreeing_all"] += n_all
                worst_all = float(np.abs(d_all).max()) / per_unit
                if worst_all > q["max_disagreement_all_m"]:
                    q["max_disagreement_all_m"] = round(worst_all, 4)
                    q["max_at_all"] = {"tiles": [[i, j], [i + di, j + dj]], "cells": n_all}
            d = d_all[both]
            n_bad = int((d != 0).sum())
            if not n_bad:
                continue
            q["samples_disagreeing"] += n_bad
            fill_free = E["fill"] == "none" and F["fill"] == "none"
            if fill_free:
                q["samples_disagreeing_on_fill_free_edges"] += n_bad
            worst = float(np.abs(d).max()) / per_unit
            if worst > q["max_disagreement_m"]:
                q["max_disagreement_m"] = round(worst, 4)
                q["max_at"] = {"tiles": [[i, j], [i + di, j + dj]], "fill_free": fill_free}
    return q


def landscape(cfg, adp, src, out, clip, warnings, strict=False):
    """hm_*.r16, clip_*.r8, vis_*.r8 (straddle tiles), weight_*_*.r8, landscape_manifest.json (13.3)."""
    L = adp["landscape"]
    enc = L["encoding"]; per_unit, offset = enc["per_unit"], enc["offset"]
    d = os.path.join(src, "terrain")
    tm = _jload(need(os.path.join(d, "terrain_manifest.json"), "terrain manifest"))
    E0, N0 = tm["origin"]["E"], tm["origin"]["N"]
    T, RES, NX, NY = tm["tile_m"], tm["res"], cfg["nx"], cfg["ny"]
    px_m = T / (RES - 1)
    # clip consistency: the terrain product must have been written for THIS clip
    tclip = tm.get("clip")
    if clip is not None:
        want = clip.stamp()
        if tclip is None:
            sys.exit("unreal adapter: the site config carries a clip but terrain_manifest.json has none -- "
                     "stale terrain product; re-run step 05")
        if [list(map(float, p)) for p in tclip.get("line", [])] != want["line"] or tclip.get("keep") != want["keep"] or tclip.get("type") != want["type"]:
            sys.exit(f"unreal adapter: terrain_manifest.json clip {tclip.get('line')} {tclip.get('keep')} differs from the "
                     f"site config clip {want['line']} {want['keep']} -- stale terrain product; re-run step 05")
    elif tclip is not None:
        sys.exit("unreal adapter: terrain_manifest.json carries a clip but the site config has none -- stale terrain product")
    check_range(tm["range_m"], L["range_limit_m"])
    water_level = cfg.get("water_level")
    # coast (weights) is optional at stage 1: weights null per tile and a warning
    cd = os.path.join(src, "coast")
    cm = None
    if os.path.isdir(cd):
        cm = _jload(need(os.path.join(cd, "coast_manifest.json"), "coast manifest"))
    elif strict:
        sys.exit(f"unreal adapter: --strict and no coast/ directory at {cd} (step 09 has not run); "
                 "the landscape would carry no weightmaps at all")
    else:
        warnings.append("step 09 not run: no coast/ directory, weightmaps absent (weights: null on every tile)")
    bands = cm["bands"] if cm else ["grass", "sand", "rock", "water"]
    class_res = cm["class_res"] if cm else None
    no_dtm = set(tuple(t) for t in (cm.get("tiles_without_dtm", []) if cm else []))
    accept = L["weight_sum_accept"]
    epsg = _epsg_of(cfg)
    clipped_away = set(tuple(t) for t in (cm.get("tiles_clipped", []) if cm else []))
    if cm is not None:
        # Before anything is cleared or written: coast/ must hold a ground raster for every terrain
        # tile it does not itself declare absent. A half-written or half-regenerated coast/ (two
        # tracks building at once -- it has happened) would otherwise ship a landscape missing most
        # of its ground cover and exit 0. PIPELINE_CHANGES.md 13.10 lists a missing source as a refusal.
        torn = [[t["x"], t["y"]] for t in tm["tiles"]
                if (t["x"], t["y"]) not in no_dtm and (t["x"], t["y"]) not in clipped_away
                and not os.path.exists(os.path.join(cd, f"ground_x{t['x']}_y{t['y']}.tif"))]
        if torn:
            sys.exit(f"unreal adapter: {len(torn)} of {len(tm['tiles'])} terrain tile(s) are absent from "
                     f"coast_manifest.json tiles_without_dtm ({len(no_dtm)} listed) and tiles_clipped but have no "
                     f"ground_x{{i}}_y{{j}}.tif in {cd} (e.g. {torn[:8]}) -- the coast product is incomplete or is "
                     "being rewritten; re-run step 09, then this adapter. Nothing was written.")
    o = os.path.join(out, "landscape"); lib.mkdirs(o)
    _clear(o, "hm_x*_y*.r16", "clip_x*_y*.r8", "vis_x*_y*.r8", "weight_*_x*_y*.r8")
    tiles, hist = [], Counter()
    n_hm = n_vis = n_wt = n_null = 0
    no_ground_raster, degraded, invented = [], 0, []
    edges = {}                                       # (i, j) -> the four border rows/columns, for seam QA
    rt_cells, rt_sq, rt_max, rt_at = 0, 0.0, 0.0, None    # measured h16 <-> GeoTIFF agreement (D2)

    # ---- decide the clipped-cell fill ONCE, over the site mosaic ------------------------------
    # Step 05 writes the cells outside the clip as NoData on purpose; the h16 cannot carry a hole, so
    # they are filled here. Filling them per tile is the same defect as filling coverage gaps per
    # tile: two neighbours invent different heights for the row they SHARE and the importer has to
    # pick a side -- 35,951 shared samples of the Thanet product differed, the worst by 10.95 m
    # (projects/one/docs/TERRAIN_ROADS.md 2.4). So the fill comes from one mosaic filled once.
    # ONLY the invention comes from the mosaic: every surveyed cell below is still read from its own
    # tile, so a terrain product torn across two runs still shows up in seam_qa instead of being
    # quietly smoothed over here. A site without a clip has no NoData at all and skips all of this.
    mcfg = {"nx": NX, "ny": NY, "grid_res": RES, "tile_m": T, "origin": {"E": E0, "N": N0}}
    by_pos = {(t["x"], t["y"]): t for t in tm["tiles"]}
    fill_mos, fill_method = None, "none"
    if clip is not None and any(int(t.get("clipped_cells", 0)) for t in tm["tiles"]):
        def _read_for_fill(i, j):
            t = by_pos.get((i, j))
            if t is None:
                return None
            p = os.path.join(d, t["file"])
            if not os.path.exists(p):
                return None                          # the loop below refuses with the proper message
            ds_ = gdal.Open(p)
            b_ = ds_.GetRasterBand(1)
            arr = b_.ReadAsArray().astype(np.float32)
            if arr.shape != (RES, RES):
                return None
            return np.where(lib.nodata_mask(arr, b_.GetNoDataValue()), np.nan, arr)

        fill_mos, minfo = lib.assemble_mosaic(mcfg, _read_for_fill, label="unreal adapter clip fill")
        mbad = ~np.isfinite(fill_mos)
        n_fill = int(mbad.sum())
        if n_fill:
            fill_method = lib.fill_nodata(fill_mos, mbad, label="site mosaic (cells outside the clip)", px_m=px_m)
        n_clipped = sum(int(t.get("clipped_cells", 0)) for t in tm["tiles"])
        print(f"landscape : clipped-cell fill '{fill_method}' decided once over a {minfo['shape'][1]} x "
              f"{minfo['shape'][0]} mosaic of {minfo['tiles']} tiles: {n_clipped:,} clipped cells inside those "
              f"tiles, {n_fill - n_clipped:,} more at grid positions that hold no tile at all (filled with them "
              f"and never exported); {minfo['overlap_conflicts']} shared-cell conflicts", flush=True)
        del mbad
    for t in tm["tiles"]:
        i, j = t["x"], t["y"]
        path = need(os.path.join(d, t["file"]), f"terrain tile {t['file']}")
        ds = gdal.Open(path)                       # keep the dataset alive while its band is read
        band = ds.GetRasterBand(1)
        a = band.ReadAsArray().astype(np.float64)
        if a.shape != (RES, RES):
            sys.exit(f"unreal adapter: {t['file']} is {a.shape[1]}x{a.shape[0]}, manifest res is {RES}")
        gt = ds.GetGeoTransform()
        check_georef(path, gt, (E0 + i * T - px_m / 2, px_m, 0.0, N0 + (j + 1) * T + px_m / 2, 0.0, -px_m),
                     ds.GetProjection(), epsg)
        if str(t.get("fill", "")).startswith("all-nodata"):     # step 05: not one surveyed cell in the tile
            invented.append([i, j])
        bad = lib.nodata_mask(a, band.GetNoDataValue())
        n_bad = int(bad.sum())
        if clip is not None:
            if n_bad != int(t.get("clipped_cells", 0)):
                sys.exit(f"unreal adapter: {t['file']} has {n_bad} NoData cells but terrain_manifest says clipped_cells "
                         f"{t.get('clipped_cells')} -- the terrain product and its manifest disagree; re-run step 05")
        elif n_bad:
            sys.exit(f"unreal adapter: {t['file']} has {n_bad} NoData cells on a site without a clip -- step 05 should have filled them")
        clip_fill = "none"
        if n_bad:
            # from the site mosaic, so the two tiles that share a clipped sample agree to the bit
            a[bad] = fill_mos[lib.mosaic_window(mcfg, i, j)][bad]
            clip_fill = fill_method
            if clip_fill.startswith("median"):
                degraded += 1
        h16 = encode_h16(a, per_unit, offset)
        # D2, measured rather than asserted: how far the 16-bit landscape height is from the
        # metre-true GeoTIFF it was encoded from. Surveyed cells only -- a clipped cell's "source"
        # is the sentinel, not a height. The encoding bounds this by half a quantum; the manifest
        # publishes the number actually reached so the engine side can assert against it.
        if n_bad < RES * RES:
            err = np.abs(decode_h16(h16, per_unit, offset) - a)[~bad]
            rt_cells += int(err.size)
            rt_sq += float(np.square(err).sum())
            if err.size and float(err.max()) > rt_max:
                rt_max, rt_at = float(err.max()), [i, j]
        hm_name = L["heightmap_name"].format(i=i, j=j)
        h16.astype("<u2").tofile(os.path.join(o, hm_name)); n_hm += 1
        clip_name = L["clip_name"].format(i=i, j=j)
        np.where(bad, 0, 255).astype(np.uint8).tofile(os.path.join(o, clip_name))
        keep_m = ~bad                                # .copy(): a slice is a VIEW, and keeping 391 views
        edges[(i, j)] = {"n": (h16[0].copy(), keep_m[0].copy()),        # alive would keep 391 full tiles
                         "s": (h16[-1].copy(), keep_m[-1].copy()),      # alive with them (~300 MB)
                         "w": (h16[:, 0].copy(), keep_m[:, 0].copy()),
                         "e": (h16[:, -1].copy(), keep_m[:, -1].copy()),
                         "fill": str(t.get("fill", "none"))}
        vis_name = None
        state = t.get("clip_state", "inside")
        if clip is not None and state == "straddle":
            E = gt[0] + (np.arange(RES) + 0.5) * gt[1]
            N = gt[3] + (np.arange(RES) + 0.5) * gt[5]
            dist = clip.signed_distance_out(E[None, :], N[:, None])
            vis_name = L["vis_name"].format(i=i, j=j)
            visibility_weight(dist, px_m).tofile(os.path.join(o, vis_name)); n_vis += 1
        weights = None
        gpath = os.path.join(cd, f"ground_x{i}_y{j}.tif")
        if cm is not None and (i, j) not in no_dtm and os.path.exists(gpath):
            g = gdal.Open(gpath)
            if g.RasterCount < 4:
                sys.exit(f"unreal adapter: {gpath} has {g.RasterCount} bands, expected 4 ({bands})")
            arrs = [g.GetRasterBand(b + 1).ReadAsArray() for b in range(4)]
            for arr in arrs:
                if arr.shape != (class_res, class_res):
                    sys.exit(f"unreal adapter: {gpath} is {arr.shape[1]}x{arr.shape[0]}, coast manifest class_res is {class_res}")
            gcell = T / float(class_res)
            check_georef(gpath, g.GetGeoTransform(), (E0 + i * T, gcell, 0.0, N0 + (j + 1) * T, 0.0, -gcell),
                         g.GetProjection(), epsg)
            s = sum(arr.astype(np.int64) for arr in arrs)
            badsum = (s != 0) & ((s < accept[0]) | (s > accept[1]))
            if badsum.any():
                r, c = np.argwhere(badsum)[0]
                sys.exit(f"unreal adapter: {gpath}: bands sum to {int(s[r, c])} at ({int(r)}, {int(c)}); accepted sums are 0 "
                         f"or {accept[0]}..{accept[1]} (step 09 contract)")
            for v, n in zip(*np.unique(s, return_counts=True)):
                hist[int(v)] += int(n)
            weights = {}
            for b, arr in zip(bands, arrs):
                wname = L["weight_name"].format(band=b, i=i, j=j)
                arr.astype(np.uint8).tofile(os.path.join(o, wname)); weights[b] = wname
            n_wt += 1
        else:
            n_null += 1
            if cm is not None and (i, j) not in no_dtm and (i, j) not in clipped_away:
                no_ground_raster.append([i, j])
        tiles.append({"x": i, "y": j,
                      "files": {"heightmap": hm_name, "clip": clip_name, "vis": vis_name, "weights": weights},
                      "min_m": t["min_m"], "max_m": t["max_m"], "h16_min": int(h16.min()), "h16_max": int(h16.max()),
                      "clip_state": state, "clipped_cells": int(t.get("clipped_cells", 0)), "clip_fill": clip_fill,
                      "source_nodata_cells": t.get("nodata_cells", 0), "source_fill": t.get("fill", "none"),
                      "slope_max_deg": t.get("slope_max_deg"), "slope_p99_deg": t.get("slope_p99_deg"),
                      "cells_over_45deg": t.get("cells_over_45deg"), "quad_origin": [T * i, T * (NY - 1 - j)]})
    if cm is not None and cm.get("water_level") is not None:
        water_level = cm["water_level"]                # the manifest's value, when step 09 ran
    if degraded:
        warnings.append(f"{degraded} tile(s) clipped-cell fill was 'median (degraded)' (scipy absent); the clip mask carries the truth")
    if no_ground_raster:                             # a raster that vanished after the pre-check above
        sys.exit(f"unreal adapter: {len(no_ground_raster)} terrain tile(s) lost their ground_x{{i}}_y{{j}}.tif in {cd} "
                 f"while this run was reading it (e.g. {no_ground_raster[:8]}) -- coast/ is being rewritten; re-run "
                 "step 09, then this adapter")
    n_invented = len(invented)
    empty_fill = tm.get("empty_fill_m")
    if "tiles_fabricated" in tm and sorted([list(t) for t in tm["tiles_fabricated"]]) != sorted(invented):
        sys.exit(f"unreal adapter: terrain_manifest.json lists {len(tm['tiles_fabricated'])} tiles_fabricated but "
                 f"{n_invented} tile(s) carry an 'all-nodata' fill -- the manifest and its own tiles disagree; re-run step 05")
    if n_invented:
        water = set(tuple(t) for t in (cm.get("water_tiles", []) if cm else []))
        outside = [t for t in invented if tuple(t) not in water]
        warnings.append(f"{n_invented} tile(s) had NO surveyed cell at all: step 05 filled every one of their "
                        f"cells from the nearest surveyed cell in the site mosaic, which may be hundreds of metres "
                        f"away (terrain_manifest fill_reach_max_m per tile), so "
                        f"{n_invented * T * T / 1e6:.1f} km2 of this landscape is fabricated, not survey; "
                        + (f"all {n_invented} are in coast water_tiles -- mask or water-fill them in the importer"
                           if not outside else f"{len(outside)} of them are NOT in coast water_tiles: {outside[:8]}")
                        + "; the list is landscape_manifest.tiles_fabricated")
    seam_qa = _seam_qa(edges, per_unit)
    if seam_qa["samples_disagreeing_on_fill_free_edges"]:
        warnings.append(f"{seam_qa['samples_disagreeing_on_fill_free_edges']} shared-edge sample(s) differ between "
                        "neighbouring tiles that BOTH had full source coverage -- two tiles cut from one mosaic cannot "
                        "disagree about a shared vertex: the terrain product was written by more than one run; re-run "
                        "step 05 for the whole site (landscape_manifest.seam_qa carries the worst case)")
    elif seam_qa["samples_disagreeing_all"]:
        warnings.append(f"{seam_qa['samples_disagreeing_all']} of {seam_qa['samples_compared_all']} shared-edge samples "
                        f"differ between neighbouring tiles (max {seam_qa['max_disagreement_all_m']} m; "
                        f"{seam_qa['samples_disagreeing']} of them on ground both tiles keep). This must be 0: step 05 "
                        "fills coverage gaps once over the site mosaic and this adapter fills the clipped cells the "
                        "same way, so no shared sample is decided twice. A non-zero count means the terrain product on "
                        "disk predates that fix or was written by more than one run -- re-run step 05 for the whole "
                        "site, then this adapter. See landscape_manifest.seam_qa")
    pad_h16 = int(encode_h16(water_level if water_level is not None else 0.0, per_unit, offset))
    no_ground = sorted(set(map(tuple, list(no_dtm) + [tuple(t) for t in no_ground_raster])))
    man = {"site": cfg["site"], "crs": tm["crs"], "origin": {"E": E0, "N": N0}, "vertical_datum": tm.get("vertical_datum"),
           "tile_m": T, "res": RES, "nx": NX, "ny": NY, "weight_res": class_res, "px_m": px_m,
           "frame": FRAME, "frame_note": FRAME_NOTE,
           "heightmap": {"file": L["heightmap_name"], "dtype": "uint16 little-endian, row-major", "shape": [RES, RES], "row0": "north", "col0": "west",
                         "row_flip_for_ue": False,
                         "z_encoding": {"formula": f"h16 = round(z_m * {per_unit}) + {offset}", "per_unit": per_unit, "offset": offset,
                                        "scale_z_cm": L["z_scale_cm"], "decode": f"z_m = (h16 - {offset}) / {per_unit}",
                                        "quantum_m": 1.0 / per_unit, "max_roundtrip_error_m": 0.5 / per_unit},
                         "roundtrip_measured": {
                             "cells": rt_cells, "max_m": rt_max,
                             "rms_m": (rt_sq / rt_cells) ** 0.5 if rt_cells else 0.0,
                             "bound_m": 0.5 / per_unit, "worst_tile": rt_at,
                             "note": "max |(h16 - offset)/per_unit - z| over every SURVEYED cell of every tile, "
                                     "measured on this run, not asserted. Cells outside the clip are excluded: their "
                                     "source value is the NoData sentinel, not a height. This is the whole distance "
                                     "between the landscape's heights and the step-05 GeoTIFF they came from, so a "
                                     "consumer comparing an in-engine height against the survey may assert against "
                                     "this number and attribute anything larger to its own sampling rule (the "
                                     "landscape interpolates a quad as two triangles, an f(x,y) bilinear sampler "
                                     "does not; that difference is bounded by |twist|/4 of the quad and is much "
                                     "larger than this -- projects/one/docs/TERRAIN_ROADS.md 3)."},
                         "range_limit_m": L["range_limit_m"], "window_m": [-offset / per_unit, round((65535 - offset) / per_unit, 3)]},
           # What this product does NOT settle. The bytes are one surface sampled at the grid posts;
           # between the posts two consumers can still disagree, and the whole of the "two terrain
           # truths" defect turned out to be exactly that (TERRAIN_ROADS.md 3: agreement at the posts
           # 0.53 mm, off-post disagreement up to 1.9 m on steep ground). Stated here so nobody has to
           # rediscover it: roundtrip_measured is the distance to the survey, this is the distance
           # between two readers of the same bytes.
           "sampling_note": {
               "at_grid_posts": "one value, no ambiguity: heightmap row r, col c IS the landscape vertex; "
                                "roundtrip_measured bounds how far it is from the step-05 GeoTIFF",
               "between_grid_posts": "the ALandscape interpolates each quad as TWO TRIANGLES (Chaos "
                                     "FHeightField::GetHeightAt); a plain f(x, y) heightfield sampler "
                                     "usually interpolates it BILINEARLY. For a quad z00, z10, z01, z11 "
                                     "with twist T = z00 + z11 - z10 - z01 the two rules differ by at most "
                                     "|T|/4, at the quad centre -- nothing to do with the encoding, and far "
                                     "larger than the quantum. A consumer that must sit ON the landscape "
                                     "(a road, a probe, a pawn) has to use the landscape's rule."},
           "clip_mask": {"file": L["clip_name"], "semantics": "255 keep, 0 clipped-or-nodata after step 05; verification only",
                         "fill": fill_method, "fill_scope": "the whole site mosaic, once",
                         "fill_note": "The h16 cannot carry a hole, so the cells this mask marks 0 are filled with the "
                                      "nearest kept height. That nearest neighbour is found over the WHOLE SITE, not "
                                      "inside one tile, so two tiles sharing a clipped sample fill it identically "
                                      "(seam_qa proves it). The mask is the truth about which cells those are."},
           "visibility": {"file": L["vis_name"], "present_for": "straddle tiles",
                          "semantics": "landscape visibility weight: 255 = hole, 0 = visible; absent file = 0 for kept tiles and 255 for tiles_clipped/tiles_missing/padding",
                          "formula": "w = round(clamp(2/3 + d / (3 * px_m), 0, 1) * 255), d = signed metres into the clipped half-plane from clip.line (keep semantics of clip); the 2/3 iso-line is the clip line"},
           "weightmaps": {"files": L["weight_name"].replace("{band}", "{" + ",".join(bands) + "}"), "res": class_res, "row0": "north", "bands": bands,
                          "sum": f"{accept[0]}..{accept[1]} inside the clip, 0 outside", "alphamap_type": "Additive",
                          "importer_note": f"assemble the site mosaic (nx*{class_res} x ny*{class_res}, cell centres at odd metres) and resample once, "
                                           "cell-centre-aware bilinear, to the padded vertex grid; renormalise to 255"
                                           if class_res else "step 09 has not run: no weightmaps (weights null on every tile)"},
           "weight_sum_histogram": {"255": hist.get(255, 0), "254": hist.get(254, 0), "253": hist.get(253, 0), "252": hist.get(252, 0), "0": hist.get(0, 0)},
           "range_m": tm["range_m"], "elevation_units": tm.get("elevation_units", "metres"), "water_level": water_level,
           "pad_value_h16": pad_h16, "pad_visibility": "hidden",
           "ue_import_unpadded": {"actor_location_cm": [0, -100 * T * NY, 0], "actor_scale": [L["z_scale_cm"], L["z_scale_cm"], L["z_scale_cm"]],
                                  "verts": [NX * (RES - 1) + 1, NY * (RES - 1) + 1], "quads_per_tile": RES - 1,
                                  "tile_quad_origin": "x0 = tile_m*i, y0 = tile_m*(ny-1-j); heightmap row r, col c -> landscape vertex (x0+c, y0+r)",
                                  "padding_rule": "the importer pads to a valid component grid on the EAST and NORTH only and moves the actor by -100*pad_north in Y; these numbers are for the unpadded grid"},
           "clip": tclip, "tiles_clipped": tm.get("tiles_clipped", []), "clipped_cells_total": tm.get("clipped_cells_total", 0),
           "source_nodata": tm.get("nodata"), "clip_note": tm.get("clip_note"),
           "slope_qa": tm.get("slope_qa"), "tiles_missing": tm.get("tiles_missing", []),
           "water_tiles": cm.get("water_tiles", []) if cm else [],
           "tiles_without_ground_raster": [list(t) for t in no_ground],
           "seam_qa": seam_qa,
           "tiles_fabricated": invented, "empty_fill_m": empty_fill,
           "tiles_fabricated_note": ("every cell of these tiles was NoData in the source DTM: step 05 filled them from the "
                                     "nearest surveyed cell in the site mosaic (terrain_manifest tiles_fabricated, and "
                                     "fill_reach_max_m for how far that was). Nothing there was surveyed, and the clip mask "
                                     "marks them keep -- mask or water-fill them in the importer"),
           "weights_note": ("step 09 has not run: weights null on every tile; re-run the adapter after step 09" if cm is None else
                            "weights null only for tiles_without_ground_raster (coast tiles_without_dtm or no ground raster)"),
           "warnings": list(warnings),
           "tiles": tiles}
    _jdump(man, os.path.join(o, "landscape_manifest.json"))
    print(f"landscape : {n_hm} heightmaps, {n_hm} clip masks, {n_vis} visibility masks, {n_wt} tiles with weights, {n_null} without"
          f" (range {tm['range_m'][0]}..{tm['range_m'][1]} m, h16 window {man['heightmap']['window_m']})")
    return {"dir": "landscape", "manifest": "landscape/landscape_manifest.json", "files": n_hm * 2 + n_vis + n_wt * 4,
            "heightmaps": n_hm, "vis": n_vis, "weight_tiles": n_wt, "weights_null": n_null, "tiles_fabricated": n_invented,
            "tiles_clipped": len(tm.get("tiles_clipped", [])), "clipped_cells_total": tm.get("clipped_cells_total", 0)}


def _read_layer_records(d, prefix):
    """{(i, j): [records]} for networks/<prefix>_x{i}_y{j}.jsonl."""
    out = {}
    for path in sorted(glob.glob(os.path.join(d, f"{prefix}_x*_y*.jsonl"))):
        stem = os.path.basename(path)[len(prefix) + 2:-6]
        i, j = (int(v) for v in stem.split("_y"))
        out[(i, j)] = _read_jsonl(path)
    return out


def _read_jsonl(path):
    with open(path, encoding="utf-8") as fh:
        return [json.loads(l) for l in fh if l.strip()]


def _merge_dups(pts):
    """Consecutive identical [E, N] vertices (06 rounds to 2 dp) merged; the later attributes win."""
    out = [pts[0]]
    for p in pts[1:]:
        if p[0] == out[-1][0] and p[1] == out[-1][1]:
            out[-1] = p
        else:
            out.append(p)
    return out


class _Hash:
    """2-D bucket hash for 'is there a node within r of p' queries."""
    def __init__(self, r):
        self.r, self.cells = r, defaultdict(list)
    def add(self, p, payload=None):
        self.cells[(int(math.floor(p[0] / self.r)), int(math.floor(p[1] / self.r)))].append((p[0], p[1], payload))
    def near(self, p):
        cx, cy = int(math.floor(p[0] / self.r)), int(math.floor(p[1] / self.r))
        out = []
        for dx in (-1, 0, 1):
            for dy in (-1, 0, 1):
                for (x, y, pl) in self.cells.get((cx + dx, cy + dy), ()):
                    if math.hypot(x - p[0], y - p[1]) <= self.r:
                        out.append((x, y, pl))
        return out


def streetscape(cfg, adp, src, out, clip, profiles, warnings, strict=False):
    """Per-tile Streetscape documents streetscape/site_x{i}_y{j}.json + streetscape_manifest.json (13.4-13.9)."""
    S = adp["streetscape"]
    E0, N0, T = cfg["origin"]["E"], cfg["origin"]["N"], cfg["tile_m"]
    d = os.path.join(src, "networks")
    if not os.path.isdir(d):
        if strict:
            sys.exit(f"unreal adapter: --strict and no networks/ directory at {d} (step 06 has not run)")
        warnings.append("step 06 not run: no networks/ directory, no streetscape documents written")
        print("streetscape: none (step 06 not run)")
        return None
    nm = _jload(need(os.path.join(d, "networks_manifest.json"), "networks manifest"))
    lm = None
    lm_path = os.path.join(d, "linear_manifest.json")
    if os.path.exists(lm_path):
        lm = _jload(lm_path)
    elif glob.glob(os.path.join(d, "rail_x*_y*.jsonl")) or glob.glob(os.path.join(d, "barriers_x*_y*.jsonl")):
        sys.exit(f"unreal adapter: rail_*/barriers_* files exist in {d} but linear_manifest.json does not -- "
                 "a partial step-11 run; re-run step 11")
    elif strict:
        sys.exit(f"unreal adapter: --strict and no linear_manifest.json in {d} (step 11 has not run); "
                 "the rail and barrier layers would be absent")
    else:
        warnings.append("step 11 not run: no linear_manifest.json, rail and barrier layers absent")
    P = lib.paths(cfg)
    gpkg = need(P["gpkg"], "GeoPackage (step 01)")
    snap, tol_thin, tol_loc = S["junction_snap_m"], float(S["thin_tolerance_m"]), float(S["run_locate_tolerance_m"])
    passthrough = S["tags_passthrough"]

    # ---- read every network record, per layer and tile
    layers = {"roads": _read_layer_records(d, "roads")}
    if lm is not None:
        layers["rail"] = _read_layer_records(d, "rail")
        layers["barriers"] = _read_layer_records(d, "barriers")
    junctions_by_tile = defaultdict(list)
    runs_by_way = defaultdict(list)                  # (layer, osm_id) -> [(tile, rec)]
    points_in = 0
    for layer, per_tile in layers.items():
        for tile, recs in per_tile.items():
            for rec in recs:
                if layer == "roads" and rec.get("cls") == "_junction":
                    junctions_by_tile[tile].append(rec); continue
                points_in += len(rec["pts"])
                runs_by_way[(layer, str(rec["id"]))].append((tile, rec))
    needed = set(k[1] for k in runs_by_way)

    # ---- raw OSM geometry and tags from the GeoPackage
    raw = {}
    ds = ogr.Open(gpkg)
    lyr = ds.GetLayer("lines")
    lyr.SetAttributeFilter(None)
    for f in lyr:
        oid = f.GetField("osm_id")
        if oid is None or str(oid) not in needed: continue
        g = f.GetGeometryRef()
        if g is None or g.GetPointCount() < 2: continue
        raw[str(oid)] = ([(g.GetX(k), g.GetY(k)) for k in range(g.GetPointCount())], f.GetField("other_tags"))
    missing = sorted(needed - set(raw))
    if missing:
        sys.exit(f"unreal adapter: {len(missing)} way id(s) of the network files are not in {gpkg} lines (e.g. {missing[:5]}) -- "
                 "the GeoPackage and the network products come from different step-01 runs")

    # ---- nodes for thinning keep-sets and the way-join rule
    junc_hash = _Hash(snap)
    for tile, recs in junctions_by_tile.items():
        for k, rec in enumerate(recs):
            junc_hash.add((rec["pts"][0][0], rec["pts"][0][1]), (tile, k))
    end_hash = {layer: _Hash(snap) for layer in layers}
    for (layer, oid), items in runs_by_way.items():
        for tile, rec in items:
            for p in (rec["pts"][0], rec["pts"][-1]):
                end_hash[layer].add((p[0], p[1]), oid)

    # ---- one spline per run
    splines = {}                                     # id -> dict (schema record + private keys under _)
    docs = defaultdict(lambda: {"splines": [], "junctions": []})
    stats = Counter()
    by_layer, skipped_barriers, barriers_by_type, tags_cov = Counter(), Counter(), Counter(), Counter()
    thin_max, locate_max, quant_shift = 0.0, 0.0, 0.0
    used = {"road": set(), "edge": set(), "hedge": set()}
    way_ends = defaultdict(list)                     # (layer, round2 E, round2 N) -> [(spline id, 'start'|'end', osm_id)]
    for (layer, oid), items in sorted(runs_by_way.items()):
        raw_xy, other_tags = raw[oid]
        closed = len(raw_xy) > 2 and raw_xy[0] == raw_xy[-1]
        recs = [rec for _, rec in items]
        tiles = {id(rec): tile for tile, rec in items}
        ordered = order_runs(raw_xy, recs)
        for o_ in ordered:
            locate_max = max(locate_max, o_["dist_m"])
            if o_["dist_m"] > tol_loc:
                sys.exit(f"unreal adapter: {layer} way {oid}: a tile run starts {o_['dist_m']:.2f} m from the raw OSM way "
                         f"(> run_locate_tolerance_m {tol_loc}); the network product was not produced from this GeoPackage")
        kept_runs = []
        for o_ in ordered:
            pts = _merge_dups(o_["rec"]["pts"])
            stats["points_merged_duplicates"] += len(o_["rec"]["pts"]) - len(pts)
            if len(pts) < 2:
                stats["runs_degenerate"] += 1; continue
            kept_runs.append((o_, pts))
        if not kept_runs:
            continue
        relink_runs(kept_runs)                       # the drop above renumbers the way; see relink_runs
        # the whole way's step-06/11 chain, for overlay z
        chain = np.array([p for _, pts in kept_runs for p in pts], dtype=np.float64)
        pieces, n_drop = clip_polyline(raw_xy, cfg, clip)
        stats["overlay_vertices_dropped"] += n_drop
        if n_drop: stats["overlay_ways_clipped"] += 1
        tags = {}
        for key in passthrough:
            v = lib.tagval(other_tags, key)
            if v is not None: tags[key] = str(v)
        rec0 = kept_runs[0][0]["rec"]
        if layer == "rail":
            for key in ("gauge", "gauge_src", "tracks", "electrified", "service", "usage"):
                v = rec0.get(key)
                if v is not None: tags[key] = str(v)
        elif layer == "barriers":
            for key in ("h_src", "material", "fence_type", "wall"):
                v = rec0.get(key)
                if v is not None: tags[key] = str(v)
        for key in tags: tags_cov[key] += 1
        cls = rec0.get("cls")
        # profile ids, segments and flags are per way (every run of a way shares them)
        flags = {"bridge": bool(rec0.get("bridge", False)), "tunnel": bool(rec0.get("tunnel", False)), "z_gap": False,
                 "steps": layer == "roads" and cls == "steps", "disused": layer == "rail" and cls == "disused",
                 "gauge_unmapped": False, "closed_loop": closed, "tracks": None}
        segments = []
        if layer == "roads":
            pav = rec0.get("pav")
            pids = profile_ids_for(layer, cls, tags, S)
            # the pavement override goes to the side(s) that carry a kerb: 'both' when both (or none) do, else that side
            has_l, has_r = pids["edge_left"] is not None, pids["edge_right"] is not None
            side = "both" if has_l == has_r else ("left" if has_l else "right")
            seg = {"id": "adapter", "s0_m": 0.0, "s1_m": None, "side": side}
            if (has_l or has_r) and pav is not None and abs(float(pav) - float(profiles["edge"][S["edge_profile_default"]]["pavement_width_m"])) > 1e-9:
                seg["edge"] = {"pavement_width_m": float(pav)}
            if tags.get("lane_markings") == "no":
                seg["road"] = {"markings": []}
            if "edge" in seg or "road" in seg:
                segments.append(seg)
        elif layer == "rail":
            pids = profile_ids_for(layer, cls, tags, S)
            pid, unmapped = rail_profile_for(rec0.get("gauge"), S)
            pids["road"] = pid
            flags["gauge_unmapped"] = unmapped
            if unmapped: stats["gauge_unmapped"] += 1
            tr = rec0.get("tracks")
            flags["tracks"] = int(tr) if isinstance(tr, (int, float)) and not isinstance(tr, bool) and int(tr) >= 1 else None
        else:
            cb = classify_barrier(cls, rec0, S)
            if cb is None:
                skipped_barriers[cls] += 1
                continue
            btype, h, thick, material, hsrc = cb
            if hsrc == "adapter_default": stats["barrier_height_defaulted_by_adapter"] += 1
            if hsrc in ("adapter_default", "adapter_parsed"): tags["h_src"] = hsrc
            pids = profile_ids_for(layer, cls, tags, S)
            barriers_by_type[btype] += 1
            if btype == "kerb":
                segments.append({"id": "adapter", "s0_m": 0.0, "s1_m": None, "side": "left", "edge": {"pavement_width_m": 0.0}})
            elif btype == "hedge":
                width = float(S["barrier"]["default_thickness_m"]["hedge"])
                hedge = {"present": True, "width_m": width, "offset_m": -width / 2.0}
                if h is not None and h > 0: hedge["height_m"] = float(h)
                segments.append({"id": "adapter", "s0_m": 0.0, "s1_m": None, "side": "left", "hedge": hedge})
            else:
                bar = {"type": btype, "height_m": float(h), "thickness_m": float(thick), "material": material, "offset_m": -float(thick) / 2.0}
                pitch = S["barrier"]["default_post_pitch_m"].get(btype)
                if pitch is not None: bar["post_pitch_m"] = float(pitch)
                segments.append({"id": "adapter", "s0_m": 0.0, "s1_m": None, "side": "left", "edge": {"barrier": bar}})
        for kind, key in (("road", "road"), ("edge", "edge_left"), ("edge", "edge_right"), ("hedge", "hedge_left"), ("hedge", "hedge_right")):
            if pids[key] is not None:
                if pids[key] not in profiles[kind]:
                    sys.exit(f"unreal adapter: profile {kind}/{pids[key]!r} is not in profiles_dir")
                used[kind].add(pids[key])
        n_runs = len(kept_runs)
        way_ids = []
        for o_, pts in kept_runs:
            rec, tile = o_["rec"], tiles[id(o_["rec"])]
            sid = f"{layer}:{oid}:{o_['segment_index']}"
            way_ids.append(sid)
            # thinned in the LOCAL frame the document is written in, so thin_max_dev_m is measured on
            # the same numbers the file carries (point_quantum_max_shift_m below bounds the rounding)
            xy = np.array([[p[0] - E0, p[1] - N0] for p in pts], dtype=np.float64)
            keep = set()
            for k in range(1, len(pts) - 1):
                if junc_hash.near((pts[k][0], pts[k][1])) or end_hash[layer].near((pts[k][0], pts[k][1])):
                    keep.add(k)
            idx, dev = thin_against_interpolant(xy, tol_thin, keep)
            thin_max = max(thin_max, dev)
            points = []
            for n_, k in enumerate(idx):
                e, n, z = pts[k]
                x_l, y_l = round(e - E0, 2), round(n - N0, 2)
                quant_shift = max(quant_shift, abs(x_l - (e - E0)), abs(y_l - (n - N0)))
                pt = {"x": x_l, "y": y_l}
                if layer == "roads": pt["width_m"] = float(rec["w"])
                pt["_z_06"] = z
                if n_ == 0 and flags["steps"]: pt["tags"] = ["steps"]
                points.append(pt)
            stats["points_out"] += len(points)
            # overlay: the raw-way piece containing this run (by the run's u along the way)
            u0 = o_["u"]
            piece = None
            if pieces:
                inside = [pc for pc in pieces if pc[0][2] - 1e-6 <= u0 <= pc[-1][2] + 1e-6]
                piece = inside[0] if inside else min(pieces, key=lambda pc: min(abs(pc[0][2] - u0), abs(pc[-1][2] - u0)))
            overlay = None
            if piece is not None and len(piece) >= 2:
                opts, zs = [], []
                for (e, n, u, cross) in piece:
                    zs.append(None if cross else nearest_z((e, n), chain))
                for k in range(len(piece)):
                    if zs[k] is None:
                        prev = [zz for zz in zs[:k] if zz is not None]
                        nxt = [zz for zz in zs[k + 1:] if zz is not None]
                        zs[k] = prev[-1] if prev else (nxt[0] if nxt else float(chain[0, 2]))
                for (e, n, u, cross), z in zip(piece, zs):
                    opts.append([round(e - E0, 2), round(n - N0, 2), round(z, 2)])
                overlay = {"kind": "osm_way", "osm_id": oid, "pts": opts}
            else:
                stats["overlay_missing"] += 1
            sp = {"id": sid,
                  "source": {"layer": layer, "osm_id": oid, "name": rec.get("name"), "cls": cls, "tags": dict(tags),
                             "tile": [tile[0], tile[1]], "segment_index": o_["segment_index"], "segment_count": n_runs},
                  "profile_ids": dict(pids), "points": points, "segments": [json.loads(json.dumps(s)) for s in segments],
                  "drop_kerbs": [], "overlay": overlay,
                  "junction_start": None, "junction_end": None, "continues_from": None, "continues_to": None,
                  "continuation_kind": {"from": o_["from"], "to": o_["to"]},
                  "overrun_points": {"before": None, "after": None},
                  "flags": {**flags, "z_gap": bool(rec.get("z_gap", False))}}
            if overlay is None: del sp["overlay"]
            sp["_tile"] = tile
            splines[sid] = sp
            docs[tile]["splines"].append(sp)
            by_layer[layer] += 1
            if o_["from"] is None:
                way_ends[(layer, round(pts[0][0], 2), round(pts[0][1], 2))].append((sid, "start", oid))
            if o_["to"] is None:
                way_ends[(layer, round(pts[-1][0], 2), round(pts[-1][1], 2))].append((sid, "end", oid))
        # same-way continuations (seam / gap) and overrun points
        for (oa, _), (ob, _), sa, sb in zip(kept_runs, kept_runs[1:], way_ids, way_ids[1:]):
            A, B = splines[sa], splines[sb]
            A["continues_to"], B["continues_from"] = sb, sa
            kind = oa["to"]                          # measured above on these two runs' own end points
            A["continuation_kind"]["to"] = B["continuation_kind"]["from"] = kind
            A["overrun_points"]["after"] = _xyz(B["points"][1]) if len(B["points"]) > 1 else None
            B["overrun_points"]["before"] = _xyz(A["points"][-2]) if len(A["points"]) > 1 else None
        if any(o_["to"] == "gap" for o_, _ in kept_runs): stats["ways_with_gaps"] += 1
        if n_runs > 1: stats["ways_multi_run"] += 1
        if closed: stats["closed_loops"] += 1
        stats["ways"] += 1
        stats["seam_joins"] += sum(1 for o_, _ in kept_runs if o_["to"] == "seam")

    # ---- way joins: a run end shared with exactly one other way of the same layer, no junction disc near
    for (layer, e, n), ends in way_ends.items():
        if len(ends) != 2 or ends[0][2] == ends[1][2]: continue
        if junc_hash.near((e, n)): continue
        (sa, ea, _), (sb, eb, _) = ends
        A, B = splines[sa], splines[sb]
        for X, ex, Y, ey in ((A, ea, B, eb), (B, eb, A, ea)):
            other_adjacent = _xyz(Y["points"][1]) if ey == "start" else _xyz(Y["points"][-2])
            if ex == "end":
                X["continues_to"] = Y["id"]; X["continuation_kind"]["to"] = "way"; X["overrun_points"]["after"] = other_adjacent
            else:
                X["continues_from"] = Y["id"]; X["continuation_kind"]["from"] = "way"; X["overrun_points"]["before"] = other_adjacent
            if ex == ey:
                X.setdefault("_continuation_reversed", {})["to" if ex == "end" else "from"] = True
        stats["way_joins"] += 1

    # ---- junctions per document
    for tile, recs in junctions_by_tile.items():
        doc = docs[tile]
        ends_index = _Hash(snap)
        for sp in doc["splines"]:
            p0, p1 = sp["points"][0], sp["points"][-1]
            ends_index.add((p0["x"] + E0, p0["y"] + N0), (sp["id"], "start"))
            ends_index.add((p1["x"] + E0, p1["y"] + N0), (sp["id"], "end"))
        for k, rec in enumerate(recs):
            e, n, z = rec["pts"][0]
            jid = f"junction:{tile[0]}_{tile[1]}:{k}"
            ends = []
            for (_, _, (sid, which)) in ends_index.near((e, n)):
                ends.append({"spline_id": sid, "end": which})
                splines[sid]["junction_start" if which == "start" else "junction_end"] = jid
            doc["junctions"].append({"id": jid, "x": round(e - E0, 2), "y": round(n - N0, 2), "z": z, "radius_m": float(rec["r"]),
                                     "kind": "disc", "ends": ends})
            stats["junctions"] += 1

    # ---- write the documents
    o = os.path.join(out, "streetscape"); lib.mkdirs(o)
    _clear(o, "site_x*_y*.json")
    materials = _material_hints(S)
    if materials is None:
        warnings.append("materials hints not found (schema/examples/test_stretch.json); documents carry no materials block")
    sha = git_sha()
    generator = f"{GENERATOR_STEM}@{sha}"
    n_docs = 0
    for tile in sorted(docs):
        doc = docs[tile]
        if not doc["splines"] and not doc["junctions"]: continue
        i, j = tile
        pu = {"road": set(), "edge": set(), "hedge": set()}
        for sp in doc["splines"]:
            for kind, key in (("road", "road"), ("edge", "edge_left"), ("edge", "edge_right"), ("hedge", "hedge_left"), ("hedge", "hedge_right")):
                if sp["profile_ids"][key] is not None: pu[kind].add(sp["profile_ids"][key])
        body = {"schema_version": SCHEMA_VERSION, "site": cfg["site"], "crs": cfg["crs"], "origin": {"E": E0, "N": N0},
                "vertical_datum": cfg.get("vertical_datum"), "frame": FRAME, "generator": generator}
        if materials is not None: body["materials"] = materials
        body["profiles"] = {kind: {pid: profiles[kind][pid] for pid in sorted(pu[kind])} for kind in ("road", "edge", "hedge")}
        body["splines"] = [{k: v for k, v in sp.items() if k not in ("_tile",)} for sp in doc["splines"]]
        body["junctions"] = doc["junctions"]
        body["_tile"] = {"x": i, "y": j, "tile_m": T, "bounds_local": [i * T, j * T, (i + 1) * T, (j + 1) * T]}
        body["_profile_ids_used"] = {kind: sorted(pu[kind]) for kind in ("road", "edge", "hedge")}
        _jdump(body, os.path.join(o, f"site_x{i}_y{j}.json"), indent=None)
        n_docs += 1
    man = {"site": cfg["site"], "crs": cfg["crs"], "origin": {"E": E0, "N": N0}, "tile_m": T, "nx": cfg["nx"], "ny": cfg["ny"],
           "frame": FRAME, "frame_note": FRAME_NOTE, "schema_version": SCHEMA_VERSION, "generator": generator,
           "profiles_dir": S["profiles_dir"], "per_tile": True, "documents": n_docs,
           "splines_by_layer": {"roads": by_layer.get("roads", 0), "rail": by_layer.get("rail", 0), "barriers": by_layer.get("barriers", 0)},
           "points_in": points_in, "points_out": stats["points_out"], "points_merged_duplicates": stats["points_merged_duplicates"],
           "runs_degenerate": stats["runs_degenerate"],
           "thin_tolerance_m": tol_thin, "thin_max_dev_m": round(thin_max, 6),   # 6 dp: 0.1 must not stand for 0.10004
           "thin_interpolant_samples_per_segment": THIN_VERIFY_SAMPLES,
           "point_quantum_m": 0.01, "point_quantum_max_shift_m": round(quant_shift, 6),
           "run_locate_tolerance_m": tol_loc, "run_locate_max_m": round(locate_max, 3),
           "ways": stats["ways"], "ways_multi_run": stats["ways_multi_run"], "ways_with_gaps": stats["ways_with_gaps"],
           "closed_loops": stats["closed_loops"], "junctions": stats["junctions"], "seam_joins": stats["seam_joins"],
           "way_joins": stats["way_joins"],
           "skipped_barriers": dict(sorted(skipped_barriers.items())), "barriers_by_type": dict(sorted(barriers_by_type.items())),
           "barrier_height_defaulted_by_adapter": stats["barrier_height_defaulted_by_adapter"], "gauge_unmapped": stats["gauge_unmapped"],
           "overlay_vertices_dropped": stats["overlay_vertices_dropped"], "overlay_ways_clipped": stats["overlay_ways_clipped"],
           "overlay_missing": stats["overlay_missing"],
           "tags_coverage": dict(sorted(tags_cov.items())),
           "profile_ids_used": {kind: sorted(used[kind]) for kind in ("road", "edge", "hedge")},
           "sources": {"networks_manifest": "networks/networks_manifest.json", "linear_manifest": "networks/linear_manifest.json" if lm else None,
                       "gpkg": os.path.relpath(gpkg, os.path.dirname(src)).replace("\\", "/"),
                       "smoothing_06": nm.get("smoothing"), "junction_snap_m": snap},
           "notes": ["thin_max_dev_m is the largest distance of any step-06/11 vertex from the centripetal Catmull-Rom through the "
                     f"waypoints of its own spline, measured in this file's local frame on the interpolant sampled at "
                     f"{THIN_VERIFY_SAMPLES} points per segment (converged to ~1e-5 m; a coarser sampling reads ~0.3 mm low). "
                     "Waypoints are written rounded to point_quantum_m; point_quantum_max_shift_m is the largest shift that "
                     "rounding actually applied to any waypoint coordinate (0 when the origin is integral and step 06 already "
                     "emits centimetres), so the shipped curve is within thin_max_dev_m + that of every source vertex",
                     "points carry no z: the step-06/11 drape is _z_06 (informative) and overlay.pts[*][2]; heights come from the terrain source",
                     "tags: unreal.json tags_passthrough read from the GeoPackage other_tags; rail records add gauge (metres, parsed by step 11), "
                     "gauge_src, tracks, electrified, service, usage and barrier records add h_src, material, fence_type, wall -- all strings",
                     "the pavement segment is written only when the spline has an edge profile and pav differs from the edge profile's "
                     "pavement_width_m; lane_markings=no adds road.markings []",
                     "a closed loop's closure carries no continues_* (flags.closed_loop says so); _continuation_reversed marks a way join "
                     "whose neighbour runs the other way"],
           "warnings": list(warnings)}
    _jdump(man, os.path.join(o, "streetscape_manifest.json"))
    print(f"streetscape: {n_docs} documents, splines {dict(by_layer)}, points {points_in} -> {stats['points_out']} "
          f"(thin {tol_thin} m, max dev {thin_max:.3f} m), junctions {stats['junctions']}, seam {stats['seam_joins']}, "
          f"way joins {stats['way_joins']}, gaps {stats['ways_with_gaps']}, skipped barriers {dict(skipped_barriers)}")
    return {"dir": "streetscape", "manifest": "streetscape/streetscape_manifest.json", "files": n_docs, "documents": n_docs,
            "splines_by_layer": man["splines_by_layer"], "points_in": points_in, "points_out": stats["points_out"],
            "thin_max_dev_m": man["thin_max_dev_m"], "junctions": stats["junctions"]}


def _xyz(pt):
    return [pt["x"], pt["y"], pt.get("_z_06")]


def _material_hints(S):
    """unreal.json materials_hints: the materials block of schema/examples/test_stretch.json, beside profiles_dir."""
    pdir = S["profiles_dir"] if os.path.isabs(S["profiles_dir"]) else os.path.join(REPO, S["profiles_dir"])
    path = os.path.join(os.path.dirname(pdir), "examples", "test_stretch.json")
    if not os.path.exists(path): return None
    d = _jload(path)
    return d.get("materials")


def massing(cfg, adp, src, out, warnings, strict=False):
    """massing/buildings_x*_y*.jsonl: every step-07 field kept, rings in local metres (3 dp)."""
    E0, N0 = cfg["origin"]["E"], cfg["origin"]["N"]
    d = os.path.join(src, "massing")
    if not os.path.isdir(d):
        if strict:
            sys.exit(f"unreal adapter: --strict and no massing/ directory at {d} (step 07 has not run)")
        warnings.append("step 07 not run: no massing/ directory")
        print("massing   : none (step 07 not run)")
        return None
    man = _jload(need(os.path.join(d, "massing_manifest.json"), "massing manifest"))
    o = os.path.join(out, "massing"); lib.mkdirs(o)
    _clear(o, "buildings_x*_y*.jsonl")
    n = nf = 0
    for path in sorted(glob.glob(os.path.join(d, "buildings_x*_y*.jsonl"))):
        with open(os.path.join(o, os.path.basename(path)), "w", encoding="utf-8", newline="\n") as fh:
            for b in _read_jsonl(path):
                b["rings"] = [{"hole": r["hole"], "pts": [[round(e - E0, 3), round(nn - N0, 3)] for e, nn in r["pts"]]} for r in b["rings"]]
                fh.write(json.dumps(b, separators=(",", ":")) + "\n"); n += 1
        nf += 1
    _jdump({**man, "frame": FRAME, "frame_note": FRAME_NOTE, "coordinates": "rings in local metres, base_z/skirt ODN metres", "files": nf},
           os.path.join(o, "massing_manifest.json"))
    print(f"massing   : {n} buildings in {nf} files -> local metres")
    return {"dir": "massing", "manifest": "massing/massing_manifest.json", "files": nf, "buildings": n}


def furniture(cfg, adp, src, out, warnings, strict=False):
    """furniture/furniture_x*_y*.jsonl: local x/y, z kept, bearing kept, heading_deg added."""
    E0, N0 = cfg["origin"]["E"], cfg["origin"]["N"]
    d = os.path.join(src, "furniture")
    if not os.path.isdir(d):
        if strict:
            sys.exit(f"unreal adapter: --strict and no furniture/ directory at {d} (step 10 has not run)")
        warnings.append("step 10 not run: no furniture/ directory")
        print("furniture : none (step 10 not run)")
        return None
    qa_path = os.path.join(src, "qa_furniture.json")
    qa = _jload(qa_path) if os.path.exists(qa_path) else {}
    if not qa: warnings.append("qa_furniture.json missing: furniture manifest carries no placement counts")
    o = os.path.join(out, "furniture"); lib.mkdirs(o)
    _clear(o, "furniture_x*_y*.jsonl")
    n = nf = 0
    for path in sorted(glob.glob(os.path.join(d, "furniture_x*_y*.jsonl"))):
        with open(os.path.join(o, os.path.basename(path)), "w", encoding="utf-8", newline="\n") as fh:
            for r in _read_jsonl(path):
                rec = {"id": r["id"], "prop": r["prop"], "name": r.get("name"),
                       "x": round(r["e"] - E0, 2), "y": round(r["n"] - N0, 2), "z": r.get("z"),
                       "bearing": r["bearing"], "heading_deg": round(bearing_to_heading_deg(r["bearing"]), 2),
                       "src": r.get("src"), "d": r.get("d"), "cls": r.get("cls"), "nudged": r.get("nudged")}
                fh.write(json.dumps(rec, separators=(",", ":")) + "\n"); n += 1
        nf += 1
    _jdump({**qa, "frame": FRAME, "frame_note": FRAME_NOTE, "coordinates": "x, y local metres; z ODN metres or null (drape); bearing degrees cw from grid north",
            "heading_deg": "((90 - bearing + 180) mod 360) - 180, right-handed from +X (east) toward +Y (north)",
            "ue_yaw": "yaw_ue = bearing - 90 = -heading_deg (applied by the loader)", "files": nf, "records": n},
           os.path.join(o, "furniture_manifest.json"))
    print(f"furniture : {n} placements in {nf} files -> local metres, heading_deg")
    return {"dir": "furniture", "manifest": "furniture/furniture_manifest.json", "files": nf, "placed": n}


def write_root_manifest(cfg, adp, out, stats, src, warnings, only=None):
    """The site-level index. A --only run rebuilds SOME products; the others are still on disk and
    still current, so their entries are carried over from the manifest this run replaces instead of
    being nulled -- a null here would tell a consumer the product was never built."""
    path = os.path.join(out, "unreal_manifest.json")
    previous = _jload(path) if (only is not None and os.path.exists(path)) else None
    prev_products = (previous or {}).get("products", {}) or {}
    products, carried = {}, []
    for k in ("landscape", "streetscape", "massing", "furniture"):
        if k in stats:
            products[k] = stats[k]
        else:
            products[k] = prev_products.get(k)
            if products[k] is not None:
                carried.append(k)

    def jl(rel):
        p = os.path.join(src, rel)
        return _jload(p) if os.path.exists(p) else None
    tm, nm, lm = jl("terrain/terrain_manifest.json"), jl("networks/networks_manifest.json"), jl("networks/linear_manifest.json")
    cm, mm, qf = jl("coast/coast_manifest.json"), jl("massing/massing_manifest.json"), jl("qa_furniture.json")
    man = {"site": cfg["site"], "crs": cfg["crs"], "origin": {"E": cfg["origin"]["E"], "N": cfg["origin"]["N"]},
           "tile_m": cfg["tile_m"], "nx": cfg["nx"], "ny": cfg["ny"], "res": cfg["grid_res"], "vertical_datum": cfg.get("vertical_datum"),
           "frame": FRAME, "frame_note": FRAME_NOTE, "schema_version": SCHEMA_VERSION, "generator": f"{GENERATOR_STEM}@{git_sha()}",
           "clip": lib.clip_manifest(lib.parse_clip(cfg)),
           "adapter_settings": adp,
           "products": products,
           "sources": {"terrain": {"manifest": "terrain/terrain_manifest.json", "tiles": len(tm["tiles"]), "range_m": tm["range_m"],
                                   "slope_qa": tm.get("slope_qa"), "tiles_clipped": tm.get("tiles_clipped", [])} if tm else None,
                       "networks": {"manifest": "networks/networks_manifest.json", "segments": nm.get("segments"), "junctions": nm.get("junctions")} if nm else None,
                       "linear": {"manifest": "networks/linear_manifest.json",
                                  "rail_segments": lm.get("layers", {}).get("rail", {}).get("segments"),
                                  "barrier_segments": lm.get("layers", {}).get("barriers", {}).get("segments")} if lm else None,
                       "coast": {"manifest": "coast/coast_manifest.json", "tiles": len(glob.glob(os.path.join(src, "coast", "ground_x*_y*.tif"))),
                                 "water_tiles": cm.get("water_tiles")} if cm else None,
                       "massing": {"manifest": "massing/massing_manifest.json", "buildings": mm.get("buildings")} if mm else None,
                       "furniture": {"manifest": "qa_furniture.json", "placed": qf.get("placed")} if qf else None},
           "warnings": list(warnings)}
    if only is not None:
        man["partial_run"] = {"rebuilt": sorted(stats), "carried_over_from_previous_manifest": sorted(carried),
                              "note": "this manifest was written by a --only run: entries under carried_over_* were not "
                                      "rebuilt and describe the products already on disk; re-run without --only for a "
                                      "manifest every entry of which was written in one pass"}
    _jdump(man, os.path.join(out, "unreal_manifest.json"))
    return man


PRODUCTS = ("landscape", "streetscape", "massing", "furniture")


def main(argv=None):
    argv = list(sys.argv[1:] if argv is None else argv)
    only, strict = None, False
    while argv:
        a = argv.pop(0)
        if a == "--only" and argv:
            only = set(argv.pop(0).split(","))
            bad = sorted(only - set(PRODUCTS))
            if bad:
                sys.exit(f"unreal adapter: --only {','.join(bad)}: no such product; choose from {', '.join(PRODUCTS)}")
        elif a == "--strict":
            strict = True
        elif a in ("-h", "--help"):
            print(__doc__); return 0
        else:
            sys.exit(f"unreal adapter: unknown argument {a!r}")
    cfg = lib.load()
    P = lib.paths(cfg)
    adp = _jload(ADP_PATH)
    clip = lib.parse_clip(cfg)
    E0, N0 = cfg["origin"]["E"], cfg["origin"]["N"]
    pdir = adp["streetscape"]["profiles_dir"]
    pdir = pdir if os.path.isabs(pdir) else os.path.join(REPO, pdir)
    profiles = load_profiles(pdir)
    check_adapter_settings(adp, cfg.get("tuning", {}), profiles)
    src = P["out"]
    out = os.path.join(src, "unreal"); lib.mkdirs(out)
    print(f"unreal adapter: {cfg['site']}  ({cfg['crs']} -> Streetscape frame: local metres from E{E0} N{N0}, X east, Y north, Z up ODN; "
          f"clip {'none' if clip is None else clip.stamp()})")
    warnings, stats = [], {}
    if only is None or "landscape" in only:
        stats["landscape"] = landscape(cfg, adp, src, out, clip, warnings, strict)
    if only is None or "streetscape" in only:
        stats["streetscape"] = streetscape(cfg, adp, src, out, clip, profiles, warnings, strict)
    if only is None or "massing" in only:
        stats["massing"] = massing(cfg, adp, src, out, warnings, strict)
    if only is None or "furniture" in only:
        stats["furniture"] = furniture(cfg, adp, src, out, warnings, strict)
    write_root_manifest(cfg, adp, out, stats, src, warnings, only)
    for w in warnings:
        print(f"  WARNING: {w}")
    print(f"-> {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
