# 3duk

Two things live here: a scanned street-furniture asset, and a pipeline that turns public
UK geodata into a tiled model of a place.

The pipeline output is **engine-neutral** — GeoTIFF rasters and JSONL in the site's own
CRS, elevation in real metres, north-up. Consumers convert; the survey stays honest.

```
assets/LitterBin/   Glasdon Jubilee 110 bin -- FBX + albedo, the Blender script that
                    builds it, and the provenance of the scan it came from
sources/
  lib.py            site resolution, config, raster geometry -- shared by every step
  config/
    sites/<site>.json   one file per place: CRS, tile grid, bbox, source coverages,
                        water level, height calibration, landmark overrides
    tuning.json         cross-site opinions: road widths, building priors, percentiles
  fetch/            01 Overpass extract, 02 1 m LIDAR DTM/DSM over WCS, reuse_tiles.py
                    (copy another site's tiles where the grids line up)
  derive/           03-11 mosaics, heights, terrain, roads, massing, ground cover,
                    street furniture, railway + barrier polylines
  adapters/         consumer-specific conversion; unity.py is the reference, unreal.py the
                    Streetscape-frame adapter for Unreal and Blender
  provenance/       what was actually fetched -- bbox, sha256, feature counts, the query
  tests/            dryrun.py fake-GDAL run of 05-11 + adapters on three synthetic sites;
                    regress_outputs.sh a site's products against a snapshot -- rasters byte
                    for byte, manifests structurally, and `selftest` to prove it can fail;
                    test_unreal_adapter.py
  run.sh            the driver
```

## Rebuilding

```bash
./sources/run.sh --list           # the steps
SITE=margate ./sources/run.sh     # 01 -> 11, each step resumable
./sources/run.sh --from 04        # resume
PATH=/c/<env>/Library/bin:$PATH PY=C:/<env>/python.exe SITE=thanet ./sources/run.sh --only 05
```

Needs a python that imports both `numpy` and `osgeo.gdal` — `run.sh` probes
`python3.14`, `python3.13`, `python3`, `python` on `PATH` for one and refuses to start
without it (a bare `python3` is often the Microsoft Store stub); `PY=` names one explicitly
and is checked the same way — plus the GDAL CLI on `PATH`. `scipy` is optional but wanted:
without it, terrain nodata is filled with a median instead of a true nearest-valid fill,
and step 05 says so loudly rather than quietly degrading. Step 01 must go through `run.sh`
so the datum guard applies (see Regression below).

Environment note: numpy's LAPACK calls (`polyfit`, `lstsq`, `svd` — step 07's height
regression uses one) exit **silently, with no output** in a conda environment unless its
`Library/bin` is on `PATH` — the OpenBLAS DLL is not found, and the process simply stops. On
this machine that means `PATH=/c/Users/Shadow/code/3duk-env/env/Library/bin:$PATH` in Git
Bash (the `/c/` form; a `C:/` entry is invisible to bash's `command -v` and to the DLL
search) with `PY=C:/Users/Shadow/code/3duk-env/env/python.exe`.

Output lands in `data/<site>/`, which is not tracked. `SITE` is required once more than
one site is configured — with exactly one, it resolves on its own.

## Sites

Three are configured: **margate** (the original — Thanet chalk coast, 13×7 tiles),
**whitby** (Yorkshire harbour town, shale cliffs both sides of the Esk, abbey headland,
6×5 tiles) and **thanet** (the whole isle, 26×19 tiles). Whitby's `water_level` and `coast`
thresholds are marked provisional in its config: they are properties of the survey, to be
read off the first DTM, not guessed.

**thanet** is Margate's grid grown to the isle: origin E 627680 N 163080, so Margate tile
`(i, j)` is Thanet tile `(i+10, j+10)` and `sources/fetch/reuse_tiles.py --from margate --to
thanet` copies the 182 already-fetched rasters into place (after checking each file's own
georeferencing tag lands where the new name says) instead of re-downloading them. It is the
first site with a **clip**: a straight line from Minnis Bay to Pegwell Bay along the old
Wantsum Channel cuts the isle from the mainland — step 02 does not fetch tiles wholly beyond
it, step 05 writes NoData there, steps 06–11 drop and count. Its `water_level`, `coast`,
`height_calib` fallback and `landmarks` are inherited from Margate (same chalk, same EA
survey) with a note saying so; the storey-height line is re-fitted by step 07 from Thanet's
own buildings.

The first full Thanet run (2026-09-08; 05–11 in 96 s on the fetched data): step 02 reports
`cached: 782, skipped_clip: 206` (the 103 positions beyond the line had been fetched before
the clip existed and stay on disk, unread); step 05 writes **391** terrain tiles — 103
positions beyond the line not exported, 31 straddling it with **3,861,822** cells written as
NoData after the fill — elevation −3.08..59.62 m, steepest cell **86.3°** with 0.201 % of
cells over 45°, and 14.6 M offshore source gaps filled nearest and counted as such (a
coverage gap, distinct from a clipped cell). Step 06: 14,468 road segments across 246 tiles,
1,841 junctions, 119,825 smoothed vertices and 162 junctions dropped beyond the line, none
without DTM. Step 07: 20,121 buildings (3,278 beyond the line, 60 off the grid), the storey
line **re-fitted as 1.385 + 2.646 × levels** (n = 2,948, 176 rejected, rmse 1.21 m,
`excluded_off_clip` 78) against Margate's 1.337 + 2.807 (n = 1,457, rmse 1.4): the intercept
holds to 5 cm and the per-storey figure drops 16 cm, which is what adding Ramsgate's,
Broadstairs' and Birchington's inter-war semis and bungalows to Margate's high-ceilinged
Victorian seafront terraces should do — a 2 ½ storey house moves by under 30 cm, inside the
fit's own rmse. The fit regresses over the buildings the model **emits**, not over every
footprint in the extract: 78 mainland buildings that only have LIDAR because this machine
still holds all 494 raw tile positions are excluded and counted, so a clean re-fetch of the
391 in-clip positions produces the same line. Both Margate landmark overrides still apply
(Arlington House 57 m, checked against the DSM: 61.3 m max / 58.4 m p90 over 672 cells; the
Jubilee Clock Tower's inherited 24 m was **wrong by 9 m** and is now 15.0 — DSM max 21.45 −
DTM p50 6.49 = 14.96 m over its 22 cells, nDSM p90 14.49, and the way's own `height` tag 14).
North Foreland lighthouse is the other height the first run got wrong: OSM `height=57` on a
seamark is the *light's* elevation above MHWS, so step 07 now prefers
`seamark:landmark:height` (26 m, and the LIDAR says 25.75) and reports `src: seamark_height`. Step 09: 103 positions beyond the line get no raster and 961,665 class cells are
zeroed on the straddling tiles. Step 10: 52 placements, 3 nodes beyond the line.

**Step 11's first real output**: 282 rail segments across 45 tiles, **49.8 km of emitted
centreline** (49.6 km of it `rail`, 0.15 km `miniature`; `linear_manifest.layers.rail.length_km`
is 80.7, which counts whole ways including the parts beyond the grid and the line, as its
`by_class_note` says) — 171 `rail` ways and 2 `miniature` (Chatham Main Line (Ramsgate Branch), Ashford
to Ramsgate Line, depot roads at Ramsgate), the Birchington–Margate–Broadstairs–Ramsgate
line continuous from tile x 2 to x 22; 275 runs carry `gauge=1435` from OSM and 7 took the
default (`gauge_defaulted` 7); `abandoned` 20, `razed` 16, `platform` 7 skipped and counted;
46 of the 219 track ways read lie wholly beyond the grid or the line (the Ashford line south
of Pegwell Bay). Barriers: 2,354 segments across 145 tiles, 134 km of ways read — fence 1,253,
wall 837, hedge 180, retaining_wall 56, kerb 26, guard_rail 2 segments; 2,111 of the 2,191
ways read carry no `height` tag and took the tuning default (`h_src: default`); gate 40,
bollard 30, `yes` 5, block 3, rope 3 skipped; 21 barrier areas in `multipolygons` not read.
On Margate the same step emits 504 barrier segments and no rail, and says why (the extract
predates `way["railway"]`).

One thing the first run found that Margate and Whitby could not show: the EA composite runs
out far offshore. 35 sea-edge positions (`coast_manifest.tiles_without_dtm` — the north row
`j=18` for `i=0..16`, `j=17` for `i=2..8`, and the eastern edge off Ramsgate) have under 1 %
DTM coverage, and their neighbours bottom out at −3.0..−1.6 m ODN, the surveyed sea surface.
`coast.missing_tiles_are_water` is therefore set true **from measurement** (the config note
records the evidence), and step 09 lists 192 tiles needing a water surface — it writes no
raster for a position with no DTM, so the count is 356 ground rasters, not 391. The
inherited `water_level` −0.6 holds as the upper bound of the water band; the deep-water
surface at −3..−2.7 m is caught by the below-water-level rule.

28 of those 35 positions have **no valid cell at all**, so step 05 has nothing to
interpolate from and exports 7,368,732 fabricated cells — 7.2 % of the model. They are
filled at the site's `water_level` (`fill: "all-nodata -> -0.6"`, listed as
`tiles_fabricated` with `empty_fill_m` in the terrain manifest) rather than at 0 m ODN,
which stood 0.6 m proud of the water plane a consumer draws, and step 05 now prints a
WARNING naming every one of them — nothing about a whole fabricated tile should be quiet.
The plate still sits about 2 m above the deep water its neighbours carry; that residual is a
property of the inherited `water_level`, and fixing it properly needs an offshore water
surface measured for this site, not another fabricated constant.

## Adding a site

Add `sources/config/sites/<name>.json` and set `SITE=<name>`. No step should need
editing. If one does, that is a bug in the step, not a missing feature — the constant it
wants belongs in the site config or in `tuning.json`. The dry run below builds three
synthetic sites with different origins, pixel sizes, grid sizes and calibration modes for
exactly this reason: if a constant leaks, one of them breaks.

A clip is the one feature that is legitimately a step-wide change — opt-in via the site
config's `clip` block, implemented once in `lib.py` (`parse_clip`, `keep_points`,
`tile_state`, `cell_mask`), recorded in every manifest it touches — with `wkt`, the kept
region as a polygon in CRS metres, so no consumer has to re-derive the cut outline from the
line and the grid bbox — and byte-identical output without it (proved by
`sources/tests/regress_outputs.sh`, below).

Steps 05 and 09 clear their whole product directory before they compute anything, which
leaves the previous run's manifest describing a directory that no longer matches it for the
20–25 s the work takes. They therefore write `_incomplete.json` before the first delete and
remove it only after the manifest is written: **if that file is in a product directory, the
product is not to be trusted** — `regress_outputs.sh` reports it as an unexpected addition,
and a successful run never leaves one. This is not hypothetical; an aborted run on
2026-09-08 left 26 of 356 ground rasters beside a manifest still claiming all 356.

Storey height is regressed per site from its own buildings (`height_calib.mode: auto`),
so a town of Victorian terraces and one of post-war flats each get their own line; the
manifest records which line was used and how well it fit. The regression population is the
population the site **emits**: footprints the grid or the clip drops are held out and
counted in `height_calib_fit.excluded_off_grid` / `excluded_off_clip`, so the fitted line
does not depend on which raw tiles happen to be sitting on the machine.

## Checked against real data

Steps 01 (fetch) and 02 ran for real on Whitby on 2026-09-07 — the only two that need no
GDAL. The 60 EA tiles are 513×513 float32, georeferenced by `ModelTransformation` with pixel
centres on integer metres, nodata `-3.4e38`, and 100% valid **including open sea**: the
composite carries the surveyed water surface as a flat plane, which is where Whitby's
`water_level` of −2.4 m comes from and why step 09 has a water band. Elevation runs
−2.9..68.8 m; the shale cliffs measure a 53° median face. The Overpass extract holds 3,330
buildings (2 with `building:levels`), a cliff way, 4 beach polygons, 1,432 highways, 8 bins
— and needed the retry logic: all three public mirrors returned 504 on the first pass.

**The whole pipeline, 01–10 plus the Unity adapter, then ran end to end on Whitby** with a
conda-forge GDAL 3.13 (11 s for the data layer). It found two things the dry run could not:
the EA first-return DSM has flight-strip gaps over 187 ha of land where the DTM is complete
(630 buildings — step 04 now samples ground and height independently so they keep their real
ground), and the sea surface is not one plane but a −2.3 ± 0.3 m spread (the water rule now
takes anything below the water level, plus a tolerance band). Also caught for real: a GDAL
Python lifetime bug in the adapter that the fake could not see. The adapter's heightmaps
round-trip the neutral tiles exactly.

A GDAL environment for this: `micromamba create -p <dir> -c conda-forge python=3.13 gdal
numpy scipy`, then `PATH=<dir>/Library/bin:$PATH PY=<dir>/python.exe` — `run.sh` finds
`GDAL_DATA` and `PROJ_DATA` beside the binaries itself.

## Regression against the original model

The refactored pipeline was run on Margate and diffed, building by building and vertex by
vertex, against the model committed at `1fdb6dc`. **It reproduces it to the centimetre**:
7,486 LIDAR-height buildings identical in every height field, 100% of footprint coordinates
exact, 196k road vertices exact in plan (99.9% in height, max 0.04 m), terrain min/max
identical on all 91 tiles, the same 23 water tiles, the same 83 QA outliers. Every remaining
difference is a deliberate change and is listed in that commit.

It did not reproduce on the first attempt. Everything OSM-derived came out **1.79 m east
and 0.81 m north** of the original, and the LIDAR proved the original right: 92.0% of roof
under the old footprints, 87.0% under the new, and shifting the new ones back restored
92.0% exactly. The cause was PROJ lacking the OSTN15 grid and silently falling back to a
2 m-class Helmert transformation. Step 01 now checks the operation PROJ will use, enables
`PROJ_NETWORK` to fetch the grid, refuses to build on a degraded transformation, and records
the operation in provenance. That bug depended on which machine you ran on, and nothing in
the output would ever have told you.

That standard is now a script. `sources/tests/regress_outputs.sh snapshot margate before`
hashes every file under `data/margate/out/` (795 files on 2026-09-08, also kept by hand as
`data/margate/regress/baseline_2026-09-08.sha256`); after an edit, `SITE=margate
./sources/run.sh --from 05` re-runs 05–11 on the existing interim data and
`regress_outputs.sh compare margate <label>` must print `0 problems`. The only files a later
step may add are step 11's `networks/barriers_*`, `rail_*`, `linear_manifest.json` and the
Unreal adapter's `unreal/**`. The clip work landed this way: 795 identical, 46 added,
0 changed, and no clipless manifest gained a clip key.

**Rasters byte for byte, manifests structurally.** A gate that compares one hash per file
has a failure mode that eventually kills it: a manifest gains a key, or `generator` records
a new commit sha, and from then on *every* comparison is red, so nothing can be caught. That
is exactly what happened here — by 2026-09-09 the gate failed under all four snapshots on
disk. It now classifies instead of counting:

| verdict | what it means |
|---|---|
| `CHANGED` / `REMOVED` / `ADDED-UNEXPECTED` | a **problem**. Any raster, `.jsonl`, `.png` or other non-JSON file that differs by one byte lands here with no allowance of any kind. |
| `PROVENANCE` | a JSON product that differs **only** in its `generator` string (the code's git sha). Allowed, printed, counted. |
| `EXTENDED` | a JSON product that differs **only** by gaining a key named in the script's `ALLOW_ADDED` table, with the commit that added it. Allowed, printed with the key. |

Both allowances are proved by hash, not asserted: the current file is parsed, the declared
new keys deleted and the provenance string put back, and the result must re-serialise to the
snapshot's bytes exactly. One recorded number moving by one digit fails. Adding a row to
`ALLOW_ADDED` is a deliberate act and needs the reason written beside it.

`regress_outputs.sh selftest margate` proves the gate can still fail: it copies four real
products into a scratch site, breaks one thing at a time — a flipped bit in a GeoTIFF, an
edited `.jsonl` record, a changed manifest number, an undeclared new key, a removed key, a
1 cm move of one spline point, a deleted file, an unexpected file — and requires the exact
verdict and exit code for each. 12 cases, 0 failed on 2026-09-09.

Against the pre-edit baselines the products of this round are clean:
`compare margate baseline_2026-09-08` → `794 identical, 1 extended (allowed), 788 added
(allowed), 0 problems` and `compare margate terrain_fix_before` → `1582 identical, 1 extended
(allowed), 0 problems`. The one extended file is `terrain/terrain_manifest.json`, which
gained `shared_edges` when step 05's per-tile NoData fill became one fill over the mosaic;
deleting those 677 bytes reproduces the baseline hash exactly, and all 91 Margate terrain
rasters are byte-identical to 2026-09-08. The two mid-round labels `before` and
`fixer_before` are **superseded and still red on purpose**: 64 files differ only in
provenance and 2 only gained keys, but 18 streetscape documents and 2 adapter manifests
really did change when `3e26561` added centimetre quantisation of point coordinates and took
`thin_max_dev_m` from 4 decimal places to 6. Those are product changes and the gate is right
to say so.

## Cliffs

The EA DTM holds cliff faces at 65–80° — measured at Cliftonville, 5 m wide for a 10 m
drop. If a consumer shows them as ~45° ramps, the consumer did it: a resampled heightmap
or terrain LOD decimation. Step 05 records the steepness that went in (`slope_qa` in the
terrain manifest) so the faces can be proved to have come out the other side.

Read the notes in the config before reusing another site's numbers. `height_calib`,
`coast.foreshore_max_odn` and `coast.rock_slope_deg` are measurements of one town and one
survey flight, not universal constants, and `tuning.json`'s `type_priors_m` records which
site it was measured at. Step 07 warns when more than 5% of buildings fall back to those
priors, because that means the model is being described by another place's vernacular.

## The photo warchest

Separate from the terrain pipeline and not part of `run.sh`: a corpus of open-licensed
photography and reference geodata for reconstructing individual Thanet buildings
photogrammetrically (RealityScan, headless Blender) and dropping the meshes into the Unreal
map. Two fetchers, both stdlib-only and resumable:

```bash
python sources/fetch/photos.py catalogue     # what exists, per town per source (JSON, no image bytes)
python sources/fetch/photos.py clusters      # which photo groups are dense enough to reconstruct
python sources/fetch/photos.py download --town margate --source panoramax
python sources/fetch/geo.py fetch            # OSM, Historic England, EA survey indexes, OS OpenData
```

Output lands in `images/<town>/<source>/` and `geo/`, neither of which is committed — like
`data/`, all of it is re-fetchable. **[images/README.md](images/README.md)** covers the photo
sources, how to feed them to RealityScan, and the attribution obligations that come with
CC-BY-SA; **[geo/README.md](geo/README.md)** covers the geodata layers.

Towns come from [sources/config/thanet_towns.json](sources/config/thanet_towns.json), which
files each photo under the nearest OSM place anchor.

Two things worth knowing before trusting a catalogue: most of these APIs cap a result set
silently rather than paging, so Panoramax and Commons are enumerated with an adaptive
quadtree that subdivides any cell coming back at the cap; and roughly half of Wikimedia
Commons over Thanet is Geograph re-uploaded, deduplicated on the Geograph id in the filename.

## Sources and licensing

| | |
|---|---|
| Buildings, highways, amenities | OpenStreetMap via Overpass API — **ODbL** |
| Terrain and surface heights | Environment Agency LIDAR Composite 1 m DTM + first-return DSM — **OGL v3** |
| Warchest photography | Panoramax **CC-BY-SA-4.0**, Geograph **CC-BY-SA-2.0**, Wikimedia Commons **mixed CC/PD** |
| Warchest geodata | Historic England **OGL v3**, EA survey indexes **OGL v3**, OS OpenData **OGL v3** |

OSM is live data: re-running `01` later will not reproduce the earlier model, because
footprints get added, retagged and split. `sources/provenance/<site>.osm.json` records the
bbox, byte count and sha256 of the extract actually used, so a later build can tell whether
it is comparing like with like. It also records the Overpass **query** — `query_sha256` and
the sorted selectors (`way["railway"]`, `way["barrier"]`, …) — because what an extract
contains depends on what was asked for: Margate's and Whitby's extracts were fetched before
`way["railway"]` was in the query (`query_sha256: null`, and step 11 says so when it finds
no railway ways), Thanet's after.

## Output

| Step | Product |
|---|---|
| 05 | `terrain/dtm_x*_y*.tif` — Float32 GeoTIFF, real metres, north-up, CRS-tagged; NoData beyond a site's clip |
| 06 | `networks/roads_x*_y*.jsonl` — centrelines as `[easting, northing, elevation]`, width, class, bridge/tunnel flags |
| 07 | `massing/buildings_x*_y*.jsonl` — per-building height, ridge, eaves, roof form, rings in CRS metres, and `src` naming which evidence produced the height |
| 09 | `coast/ground_x*_y*.tif` — 4-band grass/sand/rock/water fractions, north-up, plus water tile list |
| 10 | `furniture/furniture_x*_y*.jsonl` — prop key, position, `bearing` degrees clockwise from grid north |
| 11 | `networks/rail_x*_y*.jsonl`, `networks/barriers_x*_y*.jsonl` — railway ways with gauge/tracks/electrification, barrier ways with a height, draped like roads; `linear_manifest.json` |

Every step writes a manifest beside its output recording the CRS, the origin and the
parameters it ran under. **[sources/OUTPUT.md](sources/OUTPUT.md) is the contract** — every
field, its units, what `null` means, and which values are measurements versus opinions.

## Checking it without GDAL

```bash
C:/Users/Shadow/code/3duk-env/env/python.exe sources/tests/dryrun.py
```

Runs steps 05–11 and the adapters against three synthetic sites through a fake in-memory
GDAL — one coastal at 1 m with a cliff, a beach, a DTM hole and an auto-fitted height
calibration; one inland at 2 m with a different origin, grid size and a pinned calibration;
the third has a clip line crossing the grid diagonally and rail/barrier ways, and runs step
11 and the Unreal adapter (its checks are counted as skipped, never passed, while that
adapter is absent). Needs numpy only. It proves the wiring, the schemas in `OUTPUT.md`, that
no site constant leaks between sites, and the fidelity guarantees (nodata by declared
sentinel, honest bridge elevation, buildings without LIDAR emitted rather than dropped, 87°
synthetic cliff surviving into `slope_qa`, north-up rasters, adapter refusing to clip
terrain, NoData beyond the clip written after the fill and never on a clipless site, a rail
on a road's polyline draped to the same centimetre). It does not exercise GDAL itself or
steps 01–04.

### Consumers

`sources/adapters/unity.py` converts all of it to Unity's conventions — local metres from
the grid origin, Y-up, 16-bit RAW heightmaps, south-first alphamaps, yaw — and holds the
things that are properly Unity's and not the survey's: road draw-order lift, and the
invented bridge and tunnel offsets. It refuses to encode terrain that does not fit its
height window rather than silently flattening it.

Write a sibling adapter for any other consumer. Nothing in `sources/derive/` should ever
learn about one.

## The bin

`assets/LitterBin/` — photogrammetry scan of a real Thanet District Council bin, rebuilt
as parametric geometry and snapped to the manufacturer's published 1158 × 598 × 553 mm.
Three LODs, one 1024×512 albedo. `.fbx` and `.png` are tracked with git-lfs. The README in
that folder has the full method and the caveats worth reading before scanning another.
