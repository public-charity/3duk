#!/usr/bin/env python3.14
"""Fetch EA 1m LIDAR DTM + first-return DSM per 512m tile via WCS 2.0.1.

Half-pixel offset on the request window makes GDAL return exactly 513x513
with pixel CENTRES on integer BNG metres -- so each Unity heightmap node
maps 1:1 to a LIDAR sample, and adjacent tiles share an identical edge row.
Axis labels are E/N (using x/y returns HTTP 500).
"""
import json, os, sys, urllib.parse, urllib.request
from concurrent.futures import ThreadPoolExecutor

ROOT = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
CFG  = json.load(open(f"{ROOT}/sources/config/margate.json"))
OUT  = f"{ROOT}/data/raw/lidar"
os.makedirs(OUT, exist_ok=True)
E0, N0, T = CFG["origin"]["E"], CFG["origin"]["N"], CFG["tile_m"]

def fetch(args):
    kind, i, j = args
    path = f"{OUT}/{kind}_x{i}_y{j}.tif"
    if os.path.exists(path) and os.path.getsize(path) > 100_000:
        return (kind, i, j, "cached", os.path.getsize(path))
    e, n = E0 + i * T, N0 + j * T
    w = CFG["wcs"][kind]
    q = (f"?service=WCS&version=2.0.1&request=GetCoverage"
         f"&CoverageId={urllib.parse.quote(w['coverage'])}&format=image/tiff"
         f"&subset=E({e - 0.5},{e + T + 0.5})&subset=N({n - 0.5},{n + T + 0.5})")
    try:
        req = urllib.request.Request(w["url"] + q, headers={"User-Agent": "virtual-margate/1.0"})
        with urllib.request.urlopen(req, timeout=180) as r:
            data = r.read()
        if len(data) < 5000 or data[:4] not in (b"II*\x00", b"MM\x00*"):
            return (kind, i, j, "EMPTY", len(data))
        open(path, "wb").write(data)
        return (kind, i, j, "ok", len(data))
    except Exception as ex:
        return (kind, i, j, f"ERR {type(ex).__name__}", 0)

jobs = [(k, i, j) for k in ("dtm", "dsm") for i in range(CFG["nx"]) for j in range(CFG["ny"])]
print(f"fetching {len(jobs)} rasters ({CFG['nx']}x{CFG['ny']} tiles x2)...", flush=True)
stats = {}
with ThreadPoolExecutor(max_workers=8) as ex:
    for k, i, j, st, sz in ex.map(fetch, jobs):
        key = st.split()[0]
        stats[key] = stats.get(key, 0) + 1
        if key not in ("ok", "cached"):
            print(f"  {k} x{i}_y{j}: {st}", flush=True)
print("summary:", stats)
