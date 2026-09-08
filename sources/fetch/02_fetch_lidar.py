#!/usr/bin/env python3.14
"""Fetch 1 m LIDAR DTM + first-return DSM per tile via WCS 2.0.1.

Half-pixel offset on the request window makes the server return exactly grid_res x
grid_res with pixel CENTRES on integer CRS metres -- so each terrain sample maps 1:1 to a
LIDAR sample, and adjacent tiles share an identical edge row rather than interpolating a
seam. Axis labels are E/N (using x/y returns HTTP 500). Verified on live tiles: 513x513
float32, georeferenced by ModelTransformation at (E-0.5, N+T+0.5), EPSG in the GeoKeys.

The coverage URLs are per-site config: this happens to be the Environment Agency's
composite for England, but nothing here knows that.

Two guards against the cache lying:
  * a tile counts as cached only if its TIFF header says grid_res x grid_res float32 --
    a truncated download, an HTML error page or a server-side resample is deleted and
    fetched again, instead of living forever behind a size heuristic;
  * the directory is stamped with the grid it was fetched for. Tiles are named by index,
    so a changed origin or tile size would otherwise serve the old grid under new names.
"""
import json, os, sys, urllib.parse, urllib.request
from concurrent.futures import ThreadPoolExecutor

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import lib

CFG = lib.load()
P = lib.paths(CFG)
CLIP = lib.parse_clip(CFG)
lib.mkdirs(P["lidar"])
E0, N0, T, RES = CFG["origin"]["E"], CFG["origin"]["N"], CFG["tile_m"], CFG["grid_res"]
UA = f"3duk-pipeline/2.0 (site={CFG['site']})"

# The stamp is the four raster-defining keys only. A clip never changes a tile's bytes, so adding
# or moving one must not invalidate a fetched directory; the clip is recorded in _fetch_clip.json.
GRID = lib.grid_stamp(CFG)
stamp = os.path.join(P["lidar"], "_grid.json")
if os.path.exists(stamp):
    old = json.load(open(stamp))
    if old != GRID:
        sys.exit(f"02: FATAL -- {P['lidar']} holds tiles fetched for a different grid.\n"
                 f"  cached: {old}\n  config: {GRID}\n  Delete the directory to refetch.")
else:
    json.dump(GRID, open(stamp, "w"), indent=1)


def valid_tile(path):
    if not os.path.exists(path):
        return False
    info = lib.tiff_info(path)
    return bool(info) and info["width"] == RES and info["height"] == RES and info["dtype"] == "float32"


def fetch(args):
    kind, i, j = args
    path = os.path.join(P["lidar"], f"{kind}_x{i}_y{j}.tif")
    if valid_tile(path):
        return (kind, i, j, "cached", os.path.getsize(path))
    if os.path.exists(path):
        os.remove(path)                              # present but wrong: refetch
    e, n = E0 + i * T, N0 + j * T
    w = CFG["wcs"][kind]
    q = (f"?service=WCS&version=2.0.1&request=GetCoverage"
         f"&CoverageId={urllib.parse.quote(w['coverage'])}&format=image/tiff"
         f"&subset=E({e - 0.5},{e + T + 0.5})&subset=N({n - 0.5},{n + T + 0.5})")
    try:
        req = urllib.request.Request(w["url"] + q, headers={"User-Agent": UA})
        with urllib.request.urlopen(req, timeout=180) as r:
            data = r.read()
        if len(data) < 5000 or data[:4] not in (b"II*\x00", b"MM\x00*"):
            return (kind, i, j, "EMPTY", len(data))
        open(path, "wb").write(data)
        if not valid_tile(path):
            info = lib.tiff_info(path)
            os.remove(path)
            return (kind, i, j, f"BAD {info}", len(data))
        return (kind, i, j, "ok", len(data))
    except Exception as ex:
        return (kind, i, j, f"ERR {type(ex).__name__}", 0)


positions = [(i, j) for i in range(CFG["nx"]) for j in range(CFG["ny"])]
# A tile position whose 512 m square lies wholly outside the site's clip is not fetched at all.
# One already on disk there (fetched before the clip existed) is left alone: steps 05 and 09
# skip it from the config, so it is harmless, and it is listed below so nobody wonders.
skipped = [(i, j) for (i, j) in positions if lib.tile_state(CLIP, CFG, i, j) == "outside"]
jobs = [(k, i, j) for k in ("dtm", "dsm") for (i, j) in positions if (i, j) not in set(skipped)]
print(f"fetching {len(jobs)} rasters for {CFG['site']} ({len(positions) - len(skipped)} of {CFG['nx'] * CFG['ny']} "
      f"tile positions x2, {RES}x{RES} each)...", flush=True)
if skipped:
    print(f"clip: skipping {len(skipped)} tile positions ({2 * len(skipped)} rasters) wholly outside the clip line", flush=True)
if CLIP is not None:
    on_disk = [[i, j] for (i, j) in skipped
               if any(os.path.exists(os.path.join(P["lidar"], f"{k}_x{i}_y{j}.tif")) for k in ("dtm", "dsm"))]
    json.dump({"clip": lib.clip_manifest(CLIP),
               "skipped_positions": [[i, j] for (i, j) in skipped],
               "skipped_positions_on_disk": on_disk,
               "note": "skipped_positions are wholly outside the clip and were not requested this run; "
                       "skipped_clip in the run summary counts them x2 (dtm + dsm) whether or not a raster "
                       "exists on disk for them. skipped_positions_on_disk lists those that do (fetched "
                       "before the clip was configured); they are neither read nor deleted."},
              open(os.path.join(P["lidar"], "_fetch_clip.json"), "w"), indent=1)
stats, problems = {}, []
with ThreadPoolExecutor(max_workers=8) as ex:
    for k, i, j, st, sz in ex.map(fetch, jobs):
        key = st.split()[0]
        stats[key] = stats.get(key, 0) + 1
        if key not in ("ok", "cached"):
            problems.append((k, i, j, st))
            print(f"  {k} x{i}_y{j}: {st}", flush=True)
if CLIP is not None:
    stats["skipped_clip"] = 2 * len(skipped)
print("summary:", stats)

# EMPTY is legal -- open sea or ground beyond the source's coverage -- and steps 05 and 09
# record which tiles are missing. BAD and ERR are not legal: stop here rather than let a
# half-fetched grid flow downstream and surface as a flat tile three steps later.
hard = [p for p in problems if not p[3].startswith("EMPTY")]
if hard:
    sys.exit(f"02: FATAL -- {len(hard)} tile(s) failed or came back malformed; re-run to retry them.")
