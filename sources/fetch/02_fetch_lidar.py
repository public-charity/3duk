#!/usr/bin/env python3.14
"""Fetch 1 m LIDAR DTM + first-return DSM per tile via WCS 2.0.1.

Half-pixel offset on the request window makes GDAL return exactly grid_res x grid_res
with pixel CENTRES on integer CRS metres -- so each terrain sample maps 1:1 to a LIDAR
sample, and adjacent tiles share an identical edge row rather than interpolating a seam.
Axis labels are E/N (using x/y returns HTTP 500).

The coverage URLs are per-site config: this happens to be the Environment Agency's
composite for England, but nothing here knows that.
"""
import json, os, sys, urllib.parse, urllib.request
from concurrent.futures import ThreadPoolExecutor

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import lib

CFG = lib.load()
P = lib.paths(CFG)
lib.mkdirs(P["lidar"])
E0, N0, T = CFG["origin"]["E"], CFG["origin"]["N"], CFG["tile_m"]
UA = f"3duk-pipeline/2.0 (site={CFG['site']})"

def fetch(args):
    kind, i, j = args
    path = os.path.join(P["lidar"], f"{kind}_x{i}_y{j}.tif")
    if os.path.exists(path) and os.path.getsize(path) > 100_000:
        return (kind, i, j, "cached", os.path.getsize(path))
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
        return (kind, i, j, "ok", len(data))
    except Exception as ex:
        return (kind, i, j, f"ERR {type(ex).__name__}", 0)

jobs = [(k, i, j) for k in ("dtm", "dsm") for i in range(CFG["nx"]) for j in range(CFG["ny"])]
print(f"fetching {len(jobs)} rasters for {CFG['site']} ({CFG['nx']}x{CFG['ny']} tiles x2)...", flush=True)
stats = {}
with ThreadPoolExecutor(max_workers=8) as ex:
    for k, i, j, st, sz in ex.map(fetch, jobs):
        key = st.split()[0]
        stats[key] = stats.get(key, 0) + 1
        if key not in ("ok", "cached"):
            print(f"  {k} x{i}_y{j}: {st}", flush=True)
print("summary:", stats)
