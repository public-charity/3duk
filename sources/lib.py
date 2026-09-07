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


def fill_nodata(a, bad, label=""):
    """Nearest-valid fill for masked cells, in place. Returns the method used.

    The honest version of what this used to claim: scipy's distance transform gives a
    true nearest-valid fill. Without scipy we fall back to the median and say so out
    loud, because a median fill flattens real terrain and you should know it happened.
    """
    import numpy as np
    if not bad.any():
        return "none"
    good = ~bad
    if not good.any():
        a[bad] = 0.0
        return "all-nodata -> 0"
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


# ---- TIFF header, without GDAL -------------------------------------------
# Step 02 runs before any GDAL step and must be able to tell a real tile from a truncated
# download, an HTML error page or a server-side resample. A size heuristic cannot; the
# header can. Reads only the first IFD.

def tiff_info(path):
    """{'width','height','dtype','nodata'} of a classic TIFF's first image, or None if the
    file is not a TIFF. dtype is e.g. 'float32'."""
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
        fmt = {1: "uint", 2: "int", 3: "float"}.get(vals.get(339, 1), "uint")
        return {"width": vals.get(256), "height": vals.get(257),
                "dtype": f"{fmt}{vals.get(258)}", "nodata": vals.get("nodata")}
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
