#!/usr/bin/env python3
"""OSM railway and barrier ways -> per-tile draped polylines, beside the roads of step 06.

Two layers from the GeoPackage's `lines`, each densified, smoothed, draped on the DTM and
split per tile exactly as step 06 does it -- through lib.drape_runs, so a railway drawn
along a road's polyline gets the road's vertices to the centimetre (dryrun.py proves it).

  networks/rail_x{i}_y{j}.jsonl      railway=rail/light_rail/tram/narrow_gauge/miniature/disused
                                     with gauge (metres), tracks, electrified, service, usage,
                                     bridge/tunnel flags
  networks/barriers_x{i}_y{j}.jsonl  barrier=wall/fence/hedge/retaining_wall/kerb/guard_rail/
                                     handrail/city_wall with a height in metres
  networks/linear_manifest.json      this step's manifest (networks_manifest.json stays 06's)

What is an opinion and what is a measurement is written into every record: `gauge_src` and
`h_src` say `osm` when the tag was read and `default` when tuning.json's number was used.
Which railway/barrier values were seen but not emitted is counted in the manifest rather
than dropped silently. No width is emitted for either layer; the Streetscape profiles own
that. Barrier AREAS (closed outlines in `multipolygons`) are counted and not read.

Coordinates are [easting, northing, elevation] in CRS metres, as roads. Elevation is the
draped ground: bridges and tunnels are flagged, never lifted or sunk.
"""
import glob, json, math, os, re, sys
from collections import Counter, defaultdict
import numpy as np
from osgeo import gdal, ogr
gdal.UseExceptions(); ogr.UseExceptions()

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
import lib

CFG = lib.load()
P = lib.paths(CFG)
CLIP = lib.parse_clip(CFG)
OUT = os.path.join(P["out"], "networks")
lib.mkdirs(OUT)
RAIL, BAR = CFG["tuning"]["rail"], CFG["tuning"]["barriers"]
for c in BAR["classes"]:
    if c not in BAR["default_height_m"]:
        sys.exit(f"11: FATAL -- tuning.barriers.classes emits '{c}' but default_height_m has no entry for it")

dtm_ds = gdal.Open(os.path.join(P["interim"], "dtm.vrt"))
band = dtm_ds.GetRasterBand(1)
DTM = band.ReadAsArray().astype(np.float32)
# Nodata by the band's declared sentinel, so a -9999 reads as a gap and not as 9 km underground.
DTM[lib.nodata_mask(DTM, band.GetNoDataValue())] = np.nan
sample = lib.DtmSampler(DTM, dtm_ds.GetGeoTransform())

_NUM = re.compile(r"^\s*([-+]?\d+(?:\.\d+)?)\s*(m|cm|mm|ft|')?\s*$", re.I)


def parse_gauge(s):
    """OSM `gauge` is millimetres ("1435"), a list ("1435;1000" -> first) or "standard".
    -> (metres, "osm"), or the tuning default when absent or unparseable (a value outside
    0.1..5 m after conversion counts as unparseable: someone tagged metres, not mm)."""
    if s:
        tok = s.split(";")[0].strip().lower()
        if tok == "standard":
            return 1.435, "osm"
        try:
            g = float(tok.split()[0]) / 1000.0
            if 0.1 <= g <= 5.0:
                return round(g, 4), "osm"
        except (ValueError, IndexError):
            pass
    return RAIL["default_gauge_m"], "default"


def parse_height(s, cls):
    """OSM `height`: first token, unit suffix m (default) / cm / mm / ft or ' -> (metres, "osm");
    absent, unparseable or non-positive -> (tuning default for the class, "default")."""
    if s:
        m = _NUM.match(s.split(";")[0])
        if m:
            v = float(m.group(1)) * {"m": 1.0, "cm": 0.01, "mm": 0.001, "ft": 0.3048, "'": 0.3048}[(m.group(2) or "m").lower()]
            if v > 0:
                return round(v, 3), "osm"
    return BAR["default_height_m"][cls], "default"


def as_int(s):
    try:
        return int(float(str(s).split(";")[0]))
    except (TypeError, ValueError):
        return None


def build_record(layer, f, cls, ot):
    """The per-way fields of OUTPUT.md's step-11 tables, minus z_gap/pts (per run).
    Returns (record, defaulted) where defaulted says the gauge/height came from tuning."""
    base = {"id": f.GetField("osm_id"), "cls": cls}
    if layer == "rail":
        g, gs = parse_gauge(lib.tagval(ot, "gauge"))
        return ({**base, "gauge": g, "gauge_src": gs, "tracks": as_int(lib.tagval(ot, "tracks")),
                 "electrified": lib.tagval(ot, "electrified"), "service": lib.tagval(ot, "service"),
                 "usage": lib.tagval(ot, "usage"),
                 "bridge": bool(lib.tagval(ot, "bridge")), "tunnel": bool(lib.tagval(ot, "tunnel")),   # tag presence, as 06
                 "name": f.GetField("name")}, gs == "default")
    h, hs = parse_height(lib.tagval(ot, "height"), cls)
    return ({**base, "h": h, "h_src": hs, "material": lib.tagval(ot, "material"),
             "fence_type": lib.tagval(ot, "fence_type"), "wall": lib.tagval(ot, "wall"),
             "name": f.GetField("name")}, hs == "default")


LAYERS = {"rail": dict(column="railway", classes=set(RAIL["classes"]), tun=RAIL, prefix="rail"),
          "barriers": dict(column="barrier", classes=set(BAR["classes"]), tun=BAR, prefix="barriers")}

src = ogr.Open(P["gpkg"])
lyr = src.GetLayer("lines")
have = {L["column"]: lyr.GetLayerDefn().GetFieldIndex(L["column"]) >= 0 for L in LAYERS.values()}
summary, skipped_all = {}, {}
for name, L in LAYERS.items():
    buckets, skipped, counters = defaultdict(list), Counter(), {}
    by_class, length, n_default, n_read, n_dropped = Counter(), 0.0, 0, 0, 0
    if have[L["column"]]:
        lyr.SetAttributeFilter(f"{L['column']} IS NOT NULL")
        for f in lyr:
            cls = f.GetField(L["column"])
            if cls not in L["classes"]:
                skipped[cls] += 1
                continue
            g = f.GetGeometryRef()
            if g is None or g.GetPointCount() < 2:
                continue
            n_read += 1
            raw = [(g.GetX(k), g.GetY(k)) for k in range(g.GetPointCount())]
            rec, defaulted = build_record(name, f, cls, f.GetField("other_tags"))
            n_default += int(defaulted)
            pts = lib.chaikin(lib.densify(raw, L["tun"]["densify_step_m"]), L["tun"]["chaikin_iters"])
            runs = lib.drape_runs(pts, CFG, sample, CLIP, counters)
            for tile, run, gap in runs:
                buckets[tile].append({**rec, "z_gap": gap, "pts": run})
            if runs: by_class[cls] += 1
            else: n_dropped += 1
            for a, b in zip(pts, pts[1:]):
                length += math.hypot(b[0] - a[0], b[1] - a[1])
    else:
        print(f"11: NOTE -- the lines layer has no '{L['column']}' column; nothing to read for {name}")

    # Clear this layer's previous files only (06's roads_* and the other layer's are not ours).
    for old in glob.glob(os.path.join(OUT, f"{L['prefix']}_x*_y*.jsonl")):
        os.remove(old)
    n = 0
    for (i, j), items in sorted(buckets.items()):
        with open(os.path.join(OUT, f"{L['prefix']}_x{i}_y{j}.jsonl"), "w") as fh:
            for it in items:
                fh.write(json.dumps(it, separators=(",", ":")) + "\n"); n += 1

    ent = {"files": f"{L['prefix']}_x{{i}}_y{{j}}.jsonl", "column": L["column"],
           "classes_emitted": list(L["tun"]["classes"]),
           "segments": n, "tiles": len(buckets), "length_km": round(length / 1000, 2),
           "by_class": dict(by_class), "ways_read": n_read, "ways_dropped": n_dropped,
           "smoothing": {"densify_step_m": L["tun"]["densify_step_m"], "chaikin_iters": L["tun"]["chaikin_iters"]}}
    if name == "rail":
        ent.update({"default_gauge_m": RAIL["default_gauge_m"], "gauge_defaulted": n_default})
    else:
        ent.update({"default_height_m": dict(BAR["default_height_m"]), "height_defaulted": n_default})
    ent.update({"vertices_without_dtm": counters.get("without_dtm", 0),
                "vertices_outside_grid": counters.get("outside_grid", 0)})
    if CLIP is not None:
        ent["vertices_outside_clip"] = counters.get("outside_clip", 0)
    summary[name] = ent
    skipped_all[L["column"]] = dict(skipped)
    print(f"{name}: {n} segments across {len(buckets)} tiles, {length / 1000:.1f} km; by class {dict(by_class)}; "
          f"defaulted {n_default}; skipped {dict(skipped)}; dropped (no kept vertex on the grid) {n_dropped}")

# Barrier areas (closed outlines that OSM promoted to multipolygons) are counted, not read.
n_areas = 0
mp = src.GetLayer("multipolygons")
if mp.GetLayerDefn().GetFieldIndex("barrier") >= 0:
    mp.SetAttributeFilter("barrier IS NOT NULL")
    n_areas = mp.GetFeatureCount()

json.dump({"site": CFG["site"], "crs": CFG["crs"],
           "coordinates": "[easting, northing, elevation] in CRS metres",
           "origin": CFG["origin"], "tile_m": CFG["tile_m"],
           "source_layer": "lines (GeoPackage from step 01); barrier areas in multipolygons are not read",
           "by_class_note": "ways of an emitted class that produced at least one tile run; ways_dropped had no "
                            "kept vertex on the grid. length_km sums the smoothed polylines of every way read, "
                            "including parts beyond the grid or clip, as networks_manifest.length_km does.",
           "layers": summary,
           "ways_skipped_by_class": skipped_all,
           "barrier_areas_skipped": n_areas,
           **({} if CLIP is None else {"clip": lib.clip_manifest(CLIP, CFG)})},
          open(os.path.join(OUT, "linear_manifest.json"), "w"), indent=1)

print(f"wrote {summary['rail']['segments']} rail + {summary['barriers']['segments']} barrier segments -> {OUT}; "
      f"{n_areas} barrier areas in multipolygons not read")
if CLIP is not None:
    print(f"clip: {summary['rail'].get('vertices_outside_clip', 0):,} rail and "
          f"{summary['barriers'].get('vertices_outside_clip', 0):,} barrier vertices outside the clip line, dropped")

# Zero railway ways is not an error, but it is worth a word: the extract may simply predate
# the way["railway"] selector in fetch_osm.sh (Margate, Whitby). The provenance says.
if summary["rail"]["ways_read"] == 0 and not skipped_all.get("railway"):
    prov = os.path.join(lib.SOURCES, "provenance", f"{CFG['site']}.osm.json")
    qsha = json.load(open(prov, encoding="utf-8")).get("query_sha256") if os.path.exists(prov) else None
    if qsha is None:
        print('11: NOTE -- no railway ways in the extract; the Overpass query must include way["railway"] '
              "(fetch_osm.sh) and the extract must be re-fetched")
    else:
        print('11: NOTE -- no railway ways in the extract although the recorded query included way["railway"]; '
              "the area has none")
