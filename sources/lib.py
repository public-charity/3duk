"""Shared helpers: site resolution, config, and raster geometry.

Every step imports this rather than hardcoding a site name, a CRS, a pixel size or
an output path. Adding a second site should mean adding one config file and setting
SITE -- never editing a step.
"""
import json, os, sys

SOURCES = os.path.dirname(os.path.abspath(__file__))
ROOT    = os.path.dirname(SOURCES)


def site_name():
    """SITE from the environment, or the only configured site if there is exactly one.

    Never guesses when there is more than one: silently defaulting to whichever site
    happens to sort first is how you spend an afternoon wondering why the heights are
    wrong for a town you are not building.
    """
    s = os.environ.get("SITE")
    if s:
        return s
    d = os.path.join(SOURCES, "config", "sites")
    names = sorted(f[:-5] for f in os.listdir(d) if f.endswith(".json"))
    if len(names) == 1:
        return names[0]
    sys.exit(f"set SITE=<name>  (configured: {', '.join(names) or 'none'})")


def load(site=None):
    """Site config + the cross-site tuning file, merged under distinct keys."""
    site = site or site_name()
    p = os.path.join(SOURCES, "config", "sites", f"{site}.json")
    if not os.path.exists(p):
        sys.exit(f"no config for site '{site}' at {p}")
    cfg = json.load(open(p, encoding="utf-8"))
    cfg["site"] = site
    cfg["tuning"] = json.load(open(os.path.join(SOURCES, "config", "tuning.json"), encoding="utf-8"))
    return cfg


def epsg(cfg):
    """Numeric EPSG code from the config's 'crs' string, e.g. 'EPSG:27700' -> 27700."""
    crs = cfg["crs"]
    if not str(crs).upper().startswith("EPSG:"):
        sys.exit(f"crs must be 'EPSG:<code>', got {crs!r}")
    return int(str(crs).split(":")[1])


def paths(cfg):
    """Per-site data directories, so two sites can coexist without colliding."""
    b = os.path.join(ROOT, "data", cfg["site"])
    d = {k: os.path.join(b, k) for k in ("raw", "interim", "derived", "out")}
    d["lidar"] = os.path.join(d["raw"], "lidar")
    d["gpkg"] = os.path.join(d["derived"], f"{cfg['site']}.gpkg")
    d["osm"] = os.path.join(d["raw"], f"{cfg['site']}.osm")
    return d


def mkdirs(*ds):
    for d in ds:
        os.makedirs(d, exist_ok=True)


# ---- raster geometry ----------------------------------------------------
# Nothing below may assume 1 m pixels. The EA composite is 1 m today; a 2 m or 50 cm
# source must not silently produce a model at the wrong scale.

def pixel_size(gt):
    """(width, height) of one pixel in CRS units, both positive."""
    return abs(gt[1]), abs(gt[5])


def tile_px(cfg, gt):
    """How many pixels span one tile edge. Fails loudly on a non-integer fit."""
    pw, ph = pixel_size(gt)
    T = cfg["tile_m"]
    nx, ny = T / pw, T / ph
    if abs(nx - round(nx)) > 1e-6 or abs(ny - round(ny)) > 1e-6:
        sys.exit(f"tile_m {T} is not a whole number of {pw}x{ph} pixels")
    return int(round(nx)), int(round(ny))


def fill_nodata(a, bad, label="", empty_fill=0.0):
    """Nearest-valid fill for masked cells, in place. Returns the method used.

    The honest version of what this used to claim: scipy's distance transform gives a
    true nearest-valid fill. Without scipy we fall back to the median and say so out
    loud, because a median fill flattens real terrain and you should know it happened.

    `empty_fill` is the value used when the tile has NO valid cell at all and there is
    therefore nothing to interpolate from -- every cell of the result is fabricated. The
    caller passes the site's `water_level` where a tile beyond the survey's coverage is
    open sea, so the plate coincides with the water surface a consumer will draw instead
    of standing proud of it at 0 m ODN. It is shouted about for the same reason the median
    fallback is: the whole tile is invention, and a silent 0 m plate reads as real ground.
    """
    import numpy as np
    if not bad.any():
        return "none"
    good = ~bad
    if not good.any():
        a[bad] = empty_fill
        print(f"  WARNING{' ' + label if label else ''}: no valid cell at all -- the whole tile is "
              f"fabricated as a flat plate at {empty_fill:g} m. Nothing here was surveyed.", flush=True)
        return f"all-nodata -> {empty_fill:g}"
    try:
        from scipy import ndimage
        idx = ndimage.distance_transform_edt(bad, return_distances=False, return_indices=True)
        a[bad] = a[tuple(i[bad] for i in idx)]
        return "nearest"
    except ImportError:
        a[bad] = float(np.median(a[good]))
        print(f"  WARNING{' ' + label if label else ''}: scipy absent -- {bad.sum():,} nodata cells "
              f"filled with the median, which flattens real terrain. pip install scipy.", flush=True)
        return "median (degraded)"


def nodata_mask(a, nd):
    """Cells that are not real measurements. Explicit about the sentinel rather than
    guessing with a `<= nd/2` threshold, which breaks for any nodata >= 0."""
    import numpy as np
    bad = ~np.isfinite(a)
    if nd is not None:
        bad |= np.isclose(a, nd, rtol=0, atol=1e-6)
    bad |= a < -1e30
    return bad


# ---- clip region ------------------------------------------------------------
# An optional `clip` block in the site config restricts the model to a region inside the tile grid
# (Thanet: the half-plane north-east of the Minnis Bay -> Pegwell Bay line). Steps ask three questions
# -- is this point kept, what is this tile's state, which cells of this raster are kept -- through the
# module-level functions below and never look inside the clip object. With no clip block every
# function answers "kept", and no step writes a different byte.

class HalfPlaneClip:
    """Keep one side of the infinite line through A and B. keep 'left': keep P iff cross(B-A, P-A) >= 0.
    'right' negates the test. Points exactly on the line are kept."""
    type = "halfplane"

    def __init__(self, block):
        (ax, ay), (bx, by) = block["line"]
        self.a, self.b = (float(ax), float(ay)), (float(bx), float(by))
        self.line = [[ax, ay], [bx, by]]    # the config's own numbers, echoed verbatim by stamp()
        self.keep = block.get("keep", "left")
        if self.keep not in ("left", "right"):
            sys.exit(f"clip.keep must be 'left' or 'right', got {self.keep!r}")
        dx, dy = self.b[0] - self.a[0], self.b[1] - self.a[1]
        if dx == 0.0 and dy == 0.0:
            sys.exit("clip.line: the two endpoints coincide")
        s = 1.0 if self.keep == "left" else -1.0
        self.n = (-dy * s, dx * s)          # cross(B-A, P-A) == (P-A) . (-dy, dx)

    def stamp(self):
        """The block as every manifest records it. `line` carries the config's numbers unchanged (ints
        stay ints), so a consumer may compare its config against a manifest textually as well as
        numerically when deciding whether a product is stale."""
        return {"type": self.type, "line": [list(p) for p in self.line], "keep": self.keep}

    def keep_points(self, E, N):
        import numpy as np
        E = np.asarray(E, dtype=np.float64); N = np.asarray(N, dtype=np.float64)
        return (E - self.a[0]) * self.n[0] + (N - self.a[1]) * self.n[1] >= 0.0

    def signed_distance_out(self, E, N):
        """Metres INTO the clipped half-plane (positive = cut, negative = kept); used by the Unreal
        adapter for the landscape visibility weight."""
        import numpy as np, math
        E = np.asarray(E, dtype=np.float64); N = np.asarray(N, dtype=np.float64)
        return -((E - self.a[0]) * self.n[0] + (N - self.a[1]) * self.n[1]) / math.hypot(*self.n)

    def rect_state(self, e0, n0, e1, n1):
        k = self.keep_points([e0, e1, e0, e1], [n0, n0, n1, n1])
        return "inside" if k.all() else ("outside" if not k.any() else "straddle")

    def rect_polygon(self, e0, n0, e1, n1):
        poly = [(e0, n0), (e1, n0), (e1, n1), (e0, n1)]
        f = lambda p: (p[0] - self.a[0]) * self.n[0] + (p[1] - self.a[1]) * self.n[1]
        out = []
        for i in range(4):
            p, q = poly[i], poly[(i + 1) % 4]
            fp, fq = f(p), f(q)
            if fp >= 0.0: out.append(p)
            if (fp >= 0.0) != (fq >= 0.0):
                t = fp / (fp - fq)
                out.append((p[0] + (q[0] - p[0]) * t, p[1] + (q[1] - p[1]) * t))
        return out + [out[0]] if len(out) >= 3 else []


_CLIP_TYPES = {"halfplane": HalfPlaneClip}


def parse_clip(cfg):
    blk = cfg.get("clip")
    if not blk: return None
    t = blk.get("type")
    if t not in _CLIP_TYPES:
        sys.exit(f"clip.type {t!r} not supported (known: {', '.join(sorted(_CLIP_TYPES))})")
    return _CLIP_TYPES[t](blk)


def keep_points(clip, E, N):
    import numpy as np
    if clip is None:
        return np.ones(np.broadcast(np.asarray(E), np.asarray(N)).shape, dtype=bool)
    return clip.keep_points(E, N)


def tile_state(clip, cfg, i, j):
    if clip is None: return "inside"
    E0, N0, T = cfg["origin"]["E"], cfg["origin"]["N"], cfg["tile_m"]
    return clip.rect_state(E0 + i * T, N0 + j * T, E0 + (i + 1) * T, N0 + (j + 1) * T)


def cell_mask(clip, gt, height, width, row0=0, col0=0):
    """(height, width) bool of KEPT cells for a north-up raster, evaluated at pixel CENTRES:
    E = gt[0] + (col + 0.5) * gt[1], N = gt[3] + (row + 0.5) * gt[5]."""
    import numpy as np
    if clip is None: return np.ones((height, width), dtype=bool)
    if gt[2] != 0.0 or gt[4] != 0.0:
        sys.exit("cell_mask: rotated geotransforms are not supported; rasters here are north-up")
    E = gt[0] + (col0 + np.arange(width) + 0.5) * gt[1]
    N = gt[3] + (row0 + np.arange(height) + 0.5) * gt[5]
    return clip.keep_points(E[None, :], N[:, None])


def clip_wkt(clip, bbox):
    e0, n0, e1, n1 = bbox
    ring = ([(e0, n0), (e1, n0), (e1, n1), (e0, n1), (e0, n0)] if clip is None
            else clip.rect_polygon(e0, n0, e1, n1))
    if not ring: return None
    return "POLYGON((" + ",".join(f"{x:.3f} {y:.3f}" for x, y in ring) + "))"


# ---- product completeness marker ------------------------------------------------
# A step that clears its whole product directory before it starts computing leaves the PREVIOUS
# run's manifest on disk for as long as the work takes. Abort in that window (a locked file, a
# full disk, Ctrl-C) and you get a half-empty directory beside a manifest that still lists every
# tile, with nothing in the product saying it is incomplete -- it happened during the 2026-09-08
# audit and cost 330 deleted ground rasters. One marker file closes it: written before the first
# delete, removed only after the manifest is written. Its presence means "do not trust this
# directory", and regress_outputs.sh reports it as an unexpected ADDED file.
INCOMPLETE = "_incomplete.json"


def begin_product(out_dir, step):
    import datetime
    mkdirs(out_dir)
    json.dump({"step": step, "started_utc": datetime.datetime.now(datetime.UTC).isoformat(timespec="seconds"),
               "note": "This product directory is being rebuilt. While this file exists the directory is "
                       "INCOMPLETE and its manifest describes a previous run. The step removes it once the "
                       "manifest has been written; if it is still here, re-run the step."},
              open(os.path.join(out_dir, INCOMPLETE), "w"), indent=1)


def end_product(out_dir):
    p = os.path.join(out_dir, INCOMPLETE)
    if os.path.exists(p):
        os.remove(p)


def site_bbox(cfg):
    """(e0, n0, e1, n1) of the whole tile grid in CRS metres."""
    E0, N0, T = cfg["origin"]["E"], cfg["origin"]["N"], cfg["tile_m"]
    return (E0, N0, E0 + cfg["nx"] * T, N0 + cfg["ny"] * T)


def clip_manifest(clip, cfg=None):
    """The clip block every manifest records. With `cfg`, it also carries `wkt`: the KEPT region as a
    polygon in CRS metres, the grid rectangle cut by the half-plane. Without it a consumer that wants
    the cut outline has to reconstruct it from `line` plus the grid bbox, which is how two consumers
    end up with two slightly different outlines."""
    if clip is None: return None
    m = {**clip.stamp(),
         "semantics": "keep P iff cross(B-A, P-A) >= 0 for keep 'left' (<= 0 for 'right'); line = [A, B] in CRS "
                      "metres; points on the line are kept. Raster cells are tested at their centres; features at "
                      "their vertices (06, 11), footprint envelope centre (07) or node (10)."}
    if cfg is not None:
        m["wkt"] = clip_wkt(clip, site_bbox(cfg))
        m["wkt_note"] = ("The KEPT region: the site's tile-grid rectangle cut by the half-plane, in CRS metres. "
                         "Machine-readable form of `line` + `keep`; null if the grid keeps nothing.")
    return m


def grid_stamp(cfg, clip=None):
    """The _grid.json stamp step 02 and reuse_tiles.py agree on: the four raster-defining keys. The clip
    does not change a tile's bytes, so it is NOT part of the stamp (02 records it in _fetch_clip.json)."""
    return {"crs": cfg["crs"], "origin": cfg["origin"], "tile_m": cfg["tile_m"], "grid_res": cfg["grid_res"]}


# ---- line geometry -------------------------------------------------------------
# Densify + Chaikin + bilinear drape + per-tile split, exactly as step 06 does it. Step 06 keeps its own
# copies (BRIEF 4.4 "06 stays untouched"); the dry run proves equivalence (check C11 'rail on a road's
# polyline gives identical pts'); the follow-up commit "refactor-06-onto-lib.drape_runs" is gated by
# sources/tests/regress_outputs.sh compare margate before == 0 changed.

def tagval(ot, key):                        # == 06_build_networks.py:72-78
    if not ot: return None
    tok = '"' + key + '"=>"'
    i = ot.find(tok)
    if i < 0: return None
    j = ot.find('"', i + len(tok))
    return ot[i + len(tok):j]


def densify(pts, step):                     # == 06_build_networks.py:81-92
    import math
    out = [pts[0]]
    for i in range(1, len(pts)):
        ax, ay = out[-1]; bx, by = pts[i]
        d = math.hypot(bx - ax, by - ay)
        if d > step:
            n = int(d // step)
            for k in range(1, n + 1):
                t = k * step / d
                if t < 1.0: out.append((ax + (bx - ax) * t, ay + (by - ay) * t))
        out.append(pts[i])
    return out


def chaikin(pts, iters):                    # == 06_build_networks.py:95-106
    for _ in range(iters):
        if len(pts) < 3: break
        new = [pts[0]]
        for i in range(len(pts) - 1):
            ax, ay = pts[i]; bx, by = pts[i + 1]
            new.append((ax * 0.75 + bx * 0.25, ay * 0.75 + by * 0.25))
            new.append((ax * 0.25 + bx * 0.75, ay * 0.25 + by * 0.75))
        new.append(pts[-1])
        pts = new
    return pts


class DtmSampler:
    """06_build_networks.py:54-69 as an object: bilinear sample of a north-up array whose gaps are NaN."""
    def __init__(self, arr, gt):
        self.a, self.gt = arr, gt
        self.H, self.W = arr.shape

    def __call__(self, e, n):
        import math, numpy as np
        gt, W, H, DTM = self.gt, self.W, self.H, self.a
        fx = (e - gt[0]) / gt[1] - 0.5
        fy = (n - gt[3]) / gt[5] - 0.5
        if not (0.0 <= fx <= W - 1 and 0.0 <= fy <= H - 1): return (0.0, False)
        x0, y0 = int(math.floor(fx)), int(math.floor(fy))
        x0 = min(x0, W - 2); y0 = min(y0, H - 2)
        tx, ty = fx - x0, fy - y0
        a = DTM[y0, x0]; b = DTM[y0, x0+1]; c = DTM[y0+1, x0]; d = DTM[y0+1, x0+1]
        v = (a*(1-tx) + b*tx)*(1-ty) + (c*(1-tx) + d*tx)*ty
        return (float(v), True) if np.isfinite(v) else (0.0, False)


def tile_of(cfg, e, n):                     # == 06_build_networks.py:152-157, cfg passed in
    E0, N0, T = cfg["origin"]["E"], cfg["origin"]["N"], cfg["tile_m"]
    i, j = int((e - E0) // T), int((n - N0) // T)
    return (i, j) if 0 <= i < cfg["nx"] and 0 <= j < cfg["ny"] else None


def drape_runs(pts, cfg, sample, clip, counters):
    """06_build_networks.py:163-201 as a function. Returns [(tile, [[E, N, z], ...], z_gap)] per tile run,
    seam vertex duplicated on both sides. An off-grid vertex and an off-clip vertex both close the run.
    counters: 'outside_grid', 'outside_clip', 'without_dtm' (kept vertices only)."""
    keep = keep_points(clip, [p[0] for p in pts], [p[1] for p in pts]) if clip is not None else None
    samp = []
    for k, (e, n) in enumerate(pts):
        tile = tile_of(cfg, e, n)
        if tile is None:
            counters["outside_grid"] = counters.get("outside_grid", 0) + 1
            samp.append((e, n, None, None)); continue
        if keep is not None and not keep[k]:
            counters["outside_clip"] = counters.get("outside_clip", 0) + 1
            samp.append((e, n, None, None)); continue
        z, ok = sample(e, n)
        samp.append((e, n, z if ok else None, tile))
    zs = [s[2] for s in samp]
    counters["without_dtm"] = counters.get("without_dtm", 0) + sum(1 for (_, _, z, t) in samp if z is None and t is not None)
    last = None
    for idx in range(len(zs)):
        if zs[idx] is not None: last = zs[idx]
        elif last is not None and samp[idx][3] is not None: zs[idx] = last
    nxt = None
    for idx in range(len(zs) - 1, -1, -1):
        if zs[idx] is not None: nxt = zs[idx]
        elif nxt is not None and samp[idx][3] is not None: zs[idx] = nxt
    runs, run, cur, run_gap = [], [], None, False
    def flush():
        if cur is not None and len(run) >= 2: runs.append((cur, run, run_gap))
    for (e, n, z_raw, tile), z in zip(samp, zs):
        filled = z_raw is None
        if tile is None:
            flush(); run, cur, run_gap = [], None, False
            continue
        if z is None: z = 0.0
        if cur is None: cur = tile
        v = [round(e, 2), round(n, 2), round(z, 2)]
        if tile != cur:
            run.append(v); run_gap |= filled
            flush()
            run = [run[-1]]; cur = tile; run_gap = filled
        run.append(v); run_gap |= filled
    flush()
    return runs


# ---- TIFF header, without GDAL -------------------------------------------
# Step 02 runs before any GDAL step and must be able to tell a real tile from a truncated
# download, an HTML error page or a server-side resample. A size heuristic cannot; the
# header can. Reads only the first IFD.

def tiff_info(path):
    """{'width','height','dtype','nodata','georef_origin'} of a classic TIFF's first image, or None
    if the file is not a TIFF. dtype is e.g. 'float32'. georef_origin is the (E, N) of the raster's
    top-left corner from ModelTransformationTag 34264 (raw EA WCS tiles) or, failing that, the
    ModelTiepointTag 33922 tiepoint at raster (0, 0) (GDAL-written tiles); None when neither is
    present. reuse_tiles.py uses it to prove a renamed tile lands where its new name says."""
    import struct
    try:
        with open(path, "rb") as f:
            head = f.read(8)
            if len(head) < 8 or head[:2] not in (b"II", b"MM"):
                return None
            bo = "<" if head[:2] == b"II" else ">"
            if struct.unpack(bo + "H", head[2:4])[0] != 42:
                return None                      # BigTIFF or garbage
            off = struct.unpack(bo + "I", head[4:8])[0]
            f.seek(off)
            n = struct.unpack(bo + "H", f.read(2))[0]
            entries = f.read(12 * n)
            if len(entries) < 12 * n:
                return None
            sizes = {1: 1, 2: 1, 3: 2, 4: 4, 5: 8, 6: 1, 7: 1, 8: 2, 9: 4, 10: 8, 11: 4, 12: 8}
            vals = {}
            for k in range(n):
                tag, typ, cnt = struct.unpack(bo + "HHI", entries[12 * k:12 * k + 8])
                raw = entries[12 * k + 8:12 * k + 12]
                sz = sizes.get(typ, 1) * cnt
                if sz > 4:
                    p = struct.unpack(bo + "I", raw)[0]
                    f.seek(p); data = f.read(sz)
                else:
                    data = raw[:sz]
                if tag in (256, 257, 258, 339):
                    unit = sizes.get(typ, 1)
                    vals[tag] = struct.unpack(bo + {2: "H", 4: "I"}.get(unit, "H"), data[:unit])[0]
                elif tag == 42113:
                    try:
                        vals["nodata"] = float(data.decode("latin1").rstrip("\x00"))
                    except ValueError:
                        pass
                elif tag == 34264 and typ == 12 and cnt >= 16:
                    # ModelTransformationTag: 4x4 row-major matrix; the origin (corner of pixel 0,0)
                    # is the translation column of rows 0 and 1. Raw EA WCS tiles carry this tag.
                    m = struct.unpack(bo + "16d", data[:128])
                    vals["_mt_origin"] = (m[3], m[7])
                elif tag == 33922 and typ == 12 and cnt >= 6:
                    # ModelTiepointTag: (I, J, K, X, Y, Z) tuples; the one at raster (0, 0) is the
                    # origin. GDAL-written tiles carry this together with 33550 (pixel scale).
                    tp = struct.unpack(bo + f"{cnt}d", data[:8 * cnt])
                    for k in range(0, cnt - 5, 6):
                        if tp[k] == 0.0 and tp[k + 1] == 0.0:
                            vals["_tp_origin"] = (tp[k + 3], tp[k + 4]); break
        fmt = {1: "uint", 2: "int", 3: "float"}.get(vals.get(339, 1), "uint")
        return {"width": vals.get(256), "height": vals.get(257),
                "dtype": f"{fmt}{vals.get(258)}", "nodata": vals.get("nodata"),
                "georef_origin": vals.get("_mt_origin", vals.get("_tp_origin"))}
    except (OSError, struct.error):
        return None


# ---- shell bridge -------------------------------------------------------
# `eval "$(python3 sources/lib.py env)"` gives the .sh steps the same resolved site,
# CRS and paths the .py steps get, so there is one source of truth and no shell-side
# copy of a default to drift out of sync.
def _sh(key, value):
    """One `KEY='value'` line, single-quoted so spaces in a path cannot split the
    assignment, and with separators normalised to forward slashes so the same output
    works whether the caller is bash on Linux or bash on Windows."""
    v = str(value).replace("\\", "/")
    return f"{key}='" + v.replace("'", "'\\''") + "'"


if __name__ == "__main__":
    if len(sys.argv) > 1 and sys.argv[1] == "env":
        c = load()
        p = paths(c)
        out = [("SITE", c["site"]), ("CRS", c["crs"]), ("EPSG", epsg(c)),
               ("BBOX", ",".join(str(v) for v in c["bbox_wgs84"])),
               ("NX", c["nx"]), ("NY", c["ny"])]
        out += [(f"DIR_{k.upper()}", p[k]) for k in ("raw", "interim", "derived", "out", "lidar")]
        out += [("OSM", p["osm"]), ("GPKG", p["gpkg"])]
        for k, v in out:
            print(_sh(k, v))
    else:
        sys.exit("usage: lib.py env")
