# Thanet open geodata

The frame the photos hang on. Where [`images/`](../images/README.md) collects pictures to
reconstruct *from*, this collects what the buildings are, which are protected, where the
aerial surveys flew, and which national datasets cover the isle.

Fetched by [`sources/fetch/geo.py`](../sources/fetch/geo.py). Everything here is Open
Government Licence v3.0 or ODbL, and everything is re-fetchable, so `geo/` is not committed —
same rule as `data/`.

```bash
python sources/fetch/geo.py fetch                    # all layers
python sources/fetch/geo.py fetch --layer nhle_listed --layer ea_oblique
python sources/fetch/geo.py list
```

Every file carries a `_provenance` block naming its source, licence and required attribution.
**Read it before you redistribute anything derived from that layer** — the table below is a
summary, the `_provenance` block is the record.

## Layers

| File | What it is | Licence |
|---|---|---|
| `osm/places.geojson` | Place nodes (town/suburb/village/hamlet). The anchors in `sources/config/thanet_towns.json` were read from here. | ODbL |
| `osm/buildings_named.geojson` | Named buildings, plus any carrying `height` or `building:levels`. The ones with enough identity to be worth a reconstruction target. | ODbL |
| `osm/admin.geojson` | County / district / civil-parish boundaries. | ODbL |
| `osm/heritage.geojson` | OSM's own `historic=*`, `heritage=*`, attractions, lighthouses, churches. | ODbL |
| `heritage/nhle_listed.geojson` | **Historic England's National Heritage List** — every listed building with grade and list entry number. | OGL v3 |
| `heritage/conservation_areas.geojson` | Historic England conservation-area polygons. | OGL v3 |
| `ea/oblique_photography_index.geojson` | **EA oblique aerial photo index** — one record per frame, with camera easting, northing, heading and view angle. | OGL v3 |
| `ea/vertical_photography_index.geojson` | EA vertical (ortho) photo index, 10–25 cm. | OGL v3 |
| `ea/lidar_pointcloud_index.geojson` | EA classified LAZ point cloud index, median 0.85 m spacing. | OGL v3 |
| `ea/lidar_nlp_index.geojson` | National LIDAR Programme index. | OGL v3 |
| `os/opendata_products.json` | OS OpenData catalogue with live download URLs (keyless). | OGL v3 |

## What each is actually for

**`nhle_listed` is the target list.** Thanet's listed-building stock is dense and it is exactly
the set worth spending reconstruction effort on. Grade I and II\* first. Join it to the photo
manifests on position to see which listed buildings already have imagery and which are gaps:

```bash
python - <<'PY'
import json, glob, math
listed = json.load(open("geo/heritage/nhle_listed.geojson", encoding="utf-8"))["features"]
photos = [json.loads(l) for f in glob.glob("images/*/MANIFEST.jsonl") for l in open(f, encoding="utf-8")]
def near(lat, lon, r=60):
    return sum(1 for p in photos
               if abs(p["lat"]-lat) < r/111320 and abs(p["lon"]-lon) < r/69400)
for f in listed:
    g = f.get("geometry") or {}
    if g.get("type") != "Point": continue
    lon, lat = g["coordinates"][:2]
    p = f["properties"]
    print(f'{near(lat,lon):4d}  {p.get("Grade","?"):4s} {p.get("Name","")[:70]}')
PY
```

**The three `ea_*` indexes are indexes, not imagery.** They tell you precisely which survey
files exist over Thanet and where they were flown. See [`ea/README.md`](ea/README.md), which
`geo.py` writes with the Thanet shortlist, for how to order the files themselves.

**`ea/lidar_pointcloud_index` is the georeferencing shortcut.** RealityScan accepts a point
cloud as control, and that is the cheapest way to land a photogrammetric mesh in real
OSGB36 / ODN coordinates instead of an arbitrary frame. Match the CRS the rest of this repo
works in: `EPSG:27700`, elevations in metres above Ordnance Datum Newlyn
(`sources/config/sites/thanet.json`).

Density is *not* the reason to reach for it, despite what you might assume: over Thanet the
spacing is **median 0.85 m**, comparable to the 1 m composite the pipeline already uses. Only
the 2006 (0.21 m) and 2017 (0.35 m) surveys are meaningfully finer — pick by year, and ignore
the mean, which one 253 m outlier tile drags to 2.25 m. What you actually gain is that these
are raw **classified** returns (ground / building / vegetation, multiple returns) rather than
one resampled surface. `ea/README.md` carries the per-year table.

**`os/opendata_products.json` resolves live download URLs.** The products are national, not
Thanet-shaped. The useful ones: `OpenBuiltUpAreas` (settlement polygons — a truer town
boundary than the anchor discs in `thanet_towns.json`), `OpenNames` (gazetteer),
`OpenUPRN` (a point per addressable property), `OpenRoads`, `Terrain50`, and `OpenZoomstack`
(a whole-GB vector basemap in one GeoPackage).

## Relationship to `data/`

Nothing here feeds the terrain pipeline. `sources/run.sh` remains the only thing that writes
`data/<site>/`, and it fetches its own OSM extract and LIDAR from the endpoints recorded in
`sources/config/sites/thanet.json`. This directory is reference and planning material for the
photogrammetry work, deliberately kept out of that path so it cannot change a pipeline output.

One consequence worth knowing: `geo/osm/*` is a *fresh* Overpass fetch, while
`data/thanet/raw/thanet.osm` is the extract the pipeline froze. They will drift. If you need
them to agree, re-run `sources/run.sh --only 01`.

## Attribution

- OpenStreetMap layers: © OpenStreetMap contributors, ODbL 1.0.
- Historic England layers: Contains Historic England data © Historic England, OGL v3.0.
- Environment Agency layers: © Environment Agency copyright and/or database right 2026.
  All rights reserved. OGL v3.0.
- Ordnance Survey: Contains OS data © Crown copyright and database right 2026. OGL v3.0.
