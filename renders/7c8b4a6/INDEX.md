# `renders/7c8b4a6` — what this snapshot shows

> **The 45 images of this snapshot were deleted on 2026-09-10 to keep the repository's LFS store
> from growing without bound.** This was the intermediate snapshot: `b1cd3e5` (roads buried) and
> `b6d3274` (roads and junctions present) bracket it and tell the same story. The analysis below and
> the camera transforms and per-image sha256 in `manifest.json` beside it are kept, so the numbers
> remain citable and the images themselves are recoverable from git history at commit `b6d3274` if
> anyone ever needs them.

45 frames, one per location in [`projects/one/Tools/ue/render_set.json`](../../projects/one/Tools/ue/render_set.json) (spec sha256 `584afbd7680113ae`), rendered at commit **7c8b4a6** — *The roads come out of the ground: conform against the surface the engine actually draws* — on 2026-09-10T11:15:34Z in 1088 s, on engine `5.8.2-56702186+++UE5+Release-5.8`, from `/Game/Thanet/Maps/Thanet` over `data/thanet/out/unreal/landscape_conformed`.

> The worktree held **one uncommitted change** when this was taken (`?? projects/one/Tools/compare_snapshots.py`, the measurement script used below; `manifest.json` records it). Every landscape, massing and streetscape asset in the level was built from commit `7c8b4a6` in this session — see *How this was built* at the end.

`manifest.json` beside this file holds, per image, the camera transform actually used, the sampled ground height, the streamed region, the file size, the sha256 **and — new in this snapshot — the landscape LOD properties read back off the resident proxies**. Compare snapshots through the manifest, never by eye alone.

## The one-line verdict

**The road network is now in the picture.** Of the 31 frames that stand on or look along a road, the carriageway is drawn in **30, against 15 at `b1cd3e5`**. Five of those 30 still lose part of the carriageway to ground breaking back through it — `north_foreland_lighthouse` badly, `canterbury_road_west_at_westgate` badly, `new_haine_road_at_haine` and `railway_bridge_over_minnis_road` at the edges, `marine_terrace_west_past_dreamland` in one small tongue — and every one of the five stands on a road the conform sank only 0.03 m. The one frame with no road surface is the Westwood Cross car park, where the aisle ribbons are drawn but there is no parking surface between them — the same defect 10 as before, not the road defect.

**Junctions still do not read as junctions.** Carriageways cross one another as independent ribbons, kerbs and footways run straight through the middle of the crossing, and the corners between arms are unfilled grass wedges. That is not a rendering accident: **nothing in the Unreal import path builds a junction.** See *Junctions* below — it is the largest single finding of this snapshot.

## What actually changed between `b1cd3e5` and this snapshot

Four things, and it is worth being exact about which of them did the work, because one whole track of this round is **not** visible here at all.

1. **The capture stopped forcing the landscape to its coarsest LOD.** `capture.landscape_lod0_screen_size` went 8.0 → `null`. `07_render_set.py:landscape_lod()` now reads the state back instead of assuming it, and every image in this manifest records `lod0_screen_size 0.5, lod0_distribution_setting 1.25, lod_distribution_setting 3.0` on 17 resident proxies — the level's own saved values. At `b1cd3e5` the whole set was drawn at the coarsest level and nothing in that manifest could show it.
2. **The conform was re-run with a per-station sink.** The corridor sink is now `clip(0.5 × the shallower side's own cover, 0.03, 0.15)` instead of a flat 0.03 m, and Renderer A's junction patch is burned into the ground as built surface. Over a 30-document sample (116.05 km of road) **59.2 % of road length sinks the full 0.15 m and 40.8 % keeps only the 0.03 m floor**, because the rule takes the *minimum* over the two sides and a road with a kerb on one side only gets the floor.
3. **The street is draped from the landscape's own triangulation.** `UStreetHeightfieldTerrain` now defaults to `LandscapeTriangulated`, and the import log says so: `sampling=landscape_triangulated` here against `sampling=bilinear` in `b1cd3e5`'s `full_import3.log`. Every station's height was resampled with the rule the engine actually rasterises, which moves a station by a measured 0.4 mm at the median, 13.4 mm at the p99 and 0.799 m at its worst (`Saved/Clearance/rules_v4.json`). It changes no count, only heights.
4. **Nothing else.** The streetscape *topology* in this level — actors, components, vertices, triangles, stations, marking strips, built length — is identical to `b1cd3e5`, which is what proves the junction work never reached it. See *Junctions*.

### The cameras did not move, and here is the proof

The spec's sha256 changed (`d8a8bc6702e77e3c` → `584afbd7680113ae`) and the reason is exactly two lines: `landscape_lod0_screen_size` and its explanatory note. `git diff 44f36bd 7c8b4a6 -- projects/one/Tools/ue/render_set.json` is 2 insertions and 2 deletions and touches no location.

Comparing the two manifests, camera block by camera block, over all 45 frames: `camera_en`, `subject_en`, `local_m`, `bearing_deg`, `yaw_deg`, `pitch_deg`, `roll_deg`, `fov_deg`, `camera_height_m`, `subject_distance_m` and the **X and Y** of `eye_ue_cm` are identical in every frame. Three fields differ, in 25 frames: `ground_z_m`, `eye_z_m` and the **Z** of `eye_ue_cm`. That is the spec's own `camera_height_rule` — the eye is placed 1.7 m above the sampled ground every run — following a ground that really did move. Median drop **0.119 m**, maximum **0.145 m**, always downward, which is the deeper conform sink and nothing else. No image is byte-identical to its `b1cd3e5` counterpart.

## Automated quality check

Every image was decoded with the same independent stdlib PNG decoder the previous snapshot used (`projects/one/Tools/qc_renders.py` — no PIL on this machine) and tested for: file present, ≥ 50 KB, decodes, fully opaque, not a single flat colour (luminance variance ≥ 25 and ≥ 200 distinct RGB triples), and not more than 85 % one colour.

| check | result | `b1cd3e5` |
|---|---|---|
| images expected / rendered | 45 / 45 | 45 / 45 |
| under 50 KB | 0 | 0 |
| failed to decode | 0 | 0 |
| not fully opaque | 0 | 0 |
| flat single colour | 0 | 0 |
| more than 85 % one colour | 0 (worst 39.2 %, `birchington/station_road_to_the_square`) | 0 (worst 36.3 %) |
| **failed any check** | **0** | **0** |

The *edge fraction* — the share of pixels whose horizontal neighbour differs by more than 8 in luminance — runs 0.004 to 0.118, median **0.0123**, against 0.004–0.109 median about 0.010 before. It is a shade higher because the ground is no longer a smooth coarse-LOD sheet, and it is still very low: this model has no textures.

## The road defect, measured

`projects/one/Tools/compare_snapshots.py` (written for this snapshot) decodes the **lower half** of each frame — the half a street camera fills with the ground it is standing on — and measures three colour proxies with thresholds calibrated against sampled pixels rather than guessed: grass at (109, 145, 46), tarmac at (104, 94, 80), the magenta overlay. Over the 30 street-and-landmark frames:

| | `b1cd3e5` | `7c8b4a6` |
|---|---:|---:|
| mean grass fraction, lower half | 0.4477 | **0.1482** |
| mean tarmac fraction, lower half | 0.2586 | **0.5289** |

Frame by frame, the sixteen frames that had no carriageway at `b1cd3e5`:

| frame | tarmac before → after | verdict |
|---|---:|---|
| `margate/canterbury_road_east_at_garlinge` | 0.0012 → 0.5649 | **recovered** — full carriageway, both footways, a side road joining on the right |
| `broadstairs/st_peters_high_street` | 0.0057 → 0.4799 | **recovered** |
| `ramsgate/high_street_down_to_the_harbour` | 0.0153 → 0.5326 | **recovered** — a complete street canyon, carriageway and both footways |
| `ramsgate/ramsgate_station_from_the_approach` | 0.0098 → 0.5731 | **recovered** — and it is the clearest picture of the junction defect in the set |
| `birchington/canterbury_road_a28` | 0.0015 → 0.7429 | **recovered** — the emptiest frame in the previous set is now a full A28 with centre dashes |
| `birchington/station_road_to_the_square` | 0.0063 → 0.2992 | **recovered** — and a side street's footway runs straight across the carriageway |
| `birchington/railway_bridge_over_minnis_road` | 0.0139 → 0.2793 | **recovered, partly** — Minnis Road is drawn but the ground still cuts across it |
| `westwood/new_haine_road_at_haine` | 0.1149 → 0.6947 | **recovered, partly** — the carriageway is drawn, the ground eats large lobes out of both edges |
| `manston/spitfire_way_along_the_airfield` | 0.0030 → 0.6741 | **recovered** |
| `manston/manston_high_street_by_the_green` | 0.0012 → 0.3650 | **recovered** — clean, no breakthrough |
| `manston/manston_hangars_and_control_tower` | 0.0025 → 0.4765 | **recovered** — two carriageways, and a footway running diagonally across both |
| `acol/manston_road_west_towards_acol` | 0.0009 → 0.6668 | **recovered** |
| `acol/shottendane_road_between_the_fields` | 0.0018 → 0.5770 | **recovered** |
| `acol/margate_hill_at_the_isle_edge` | 0.0050 → 0.6080 | **recovered** |
| `acol/cheesemans_farm_from_manston_road` | 0.0064 → 0.5195 | **recovered** |
| `westwood/westwood_cross_sheds_from_the_carpark` | 0.0586 → 0.0611 | **not recovered** — the aisle ribbons are drawn and float above the grass exactly as before; there is still no car park surface (defect 10) |

The two frames that got **worse**, both confirmed by opening them:

- `broadstairs/north_foreland_lighthouse` — grass 0.1653 → 0.3416, tarmac 0.3952 → 0.2685. Large jagged green wedges erupt through North Foreland Road across most of its width. The road under that camera is `roads:1028594193:1`, secondary, kerbed on **one** side only, so its per-station sink is the 0.030 m floor at every one of its 112 stations.
- `westgate-on-sea/canterbury_road_west_at_westgate` — grass 0.0786 → 0.1305. The road is drawn but green blades cut across it near the camera. `roads:607951329:1`, trunk, sink 0.030 m.

That is the residual mechanism in one sentence: **where the sink is 0.15 m the carriageway is clean, and where it is 0.03 m the drawn ground can still win.** Checked at nine cameras: the five frames that still lose carriageway all stand on 0.030 m roads; `princess_margaret_avenue_at_northdown` and `manston_high_street_by_the_green`, both 0.150 m, are clean. `Saved/Clearance/rules_v4.json` predicts exactly this — 0 % of corridor points have ground above the road at the landscape's LOD 0, but 0.034 % at LOD 1 and 1.93 % at LOD 2, and 0.03 m is the floor that buys the least.

## Junctions

`ramsgate/ramsgate_station_from_the_approach`, `manston/manston_hangars_and_control_tower` and `birchington/station_road_to_the_square` are the three frames to look at. In all three the carriageways of a junction simply overlap: the kerb and footway of each arm run through the crossing, one arm's pavement crosses another arm's tarmac, and the corners between arms are unfilled grass or black gaps.

**Why**: the junction layer is complete in the geometry core and in the C++ port, and it is not called by anything that builds the level.

```
$ grep -rnE "FStreetJunctionPlan|BuildJunctionPatch|BuildJunctionCorners" \
      projects/one/Plugins/Streetscape/Source --include=*.cpp --include=*.h \
    | grep -viE "StreetJunctions|StreetRenderers|Tests/"
    StreetSplineMath.cpp:706   # a comment
    StreetSplineMath.cpp:770   # a comment
    StreetSplineMath.h:79,136,144   # three comments
    (no call site)

$ grep -rn "Junction" projects/one/Plugins/Streetscape/Source/StreetscapeEditor
    (nothing at all)
```

`UStreetSplineComponent::Build` calls `FStreetSplineMath::Build(Def, Profiles, Terrain, *S, &Err)` — five arguments, no `Trim` — and `AStreetscapeActor::RebuildAllChecked` calls `BuildRoad`/`BuildEdge` with no junction patch and no corners. The whole `StreetscapeEditor` module, which is what `03_import_streetscape.py` drives, contains the string "Junction" zero times. The level's own per-actor stats agree: `Saved/Rebuild/census_reopen.json` reports `"trimmed": false, "trim_m": [0, 0]`.

The census proves the consequence arithmetically. Whole world, re-opened in a fresh commandlet and streamed in at a 20 km radius:

| | `b1cd3e5` (`full_import3.log`) | `7c8b4a6` | delta |
|---|---:|---:|---:|
| streetscape actors | 15,422 | 15,423 | +1 |
| vertices | 19,705,600 | 19,711,962 | +6,362 |
| triangles | 29,006,476 | 29,015,722 | +9,246 |
| renderer components | 30,624 | 30,628 | +4 |
| marking strips | 20,700 | 20,731 | +31 |
| stations | 745,642 | 745,758 | +116 |
| built length | 1,072,441.99 m | 1,072,613.40 m | +171.41 m |

Every one of those deltas is the authored `authored:trinity_square` test stretch, which this build imports and the `b1cd3e5` census did not: 6,362 vertices (1794 + 1508 + 2696 + 364), 9,246 triangles, 4 components, 31 marking strips, 116 stations, and 171.4054835 m of length against the fixture's 171.405484. **The isle's own 15,422 actors have exactly the topology they had at `b1cd3e5`** — their station heights moved, because the drape rule changed (item 3 above), but not one vertex was added or removed. The junction work — which by the geometry core's own isle-wide measurement should add 87,969 patch vertices and 86,327 patch triangles, and remove 25,808.9 m of carriageway at 5,168 trims — is in none of it.

The ground, on the other hand, *has* been conformed to those junctions: 1,634 of 1,642 junction patches were burned into the landscape over 232,464 cells. So the middle of a crossroads is now a shallow dish shaped like the tarmac that is not there.

## Other defects across the whole set

| # | defect at `b1cd3e5` | now |
|---|---|---|
| 1 | Magenta OSM debug overlay drawn over everything, depth-test free | **unchanged** — in all 45; mean overlay fraction in the lower half rose 0.0195 → 0.0272 only because more of the road it lies on is now visible |
| 2 | No textures anywhere | **unchanged** |
| 3 | No ambient or sky light on shaded faces; façades render solid black | **unchanged** |
| 4 | Corridor ribbons stand proud of the ground with unlit vertical faces, black wedge gaps | **worse** — the deeper sink puts up to 0.15 m of daylight under a kerbed ribbon instead of 0.03 m. Clearest in `minnis_bay_where_the_model_ends`, `westwood_cross_sheds_from_the_carpark`, `canterbury_road_a28` and `manston_high_street_by_the_green` |
| 5 | The model ends in a hard vertical cut into dark blue | **unchanged** |
| 6 | Beach-level cameras look across a flat plane with no beach | **unchanged** |
| 7 | Cliffs are not cliffs — smoothed into sand ramps | **better** — `walpole_bay_chalk_cliff_from_the_sands` now shows a stepped vertical face rather than a ramp, because the landscape is no longer decimated. It is terraced and still the wrong colour, but it is a cliff |
| 8 | The railway leaves the ground at bridges and arcs into the air | **better, with a new artefact** — in `railway_bridge_over_minnis_road` the line now runs in a cutting under a deck instead of arcing overhead, but the conform's earthwork around it has built a canyon of green cliffs either side, and Minnis Road in the foreground is cut by ground breakthrough |
| 9 | Manston's runway and aprons not modelled | **unchanged** — the aerial still shows field where 2.7 km of concrete should be, though the taxi and apron roads around it are now drawn |
| 10 | Car park surfaces missing, only aisle ribbons | **unchanged** — `westwood_cross_sheds_from_the_carpark` is the single road-bearing frame still without a surface |
| 11 | Lane markings inconsistent | **unchanged** — present on `canterbury_road_a28`, `canterbury_road_west_at_westgate`, `marine_terrace`; absent on `haine_road`, `preston_road` |
| — | *new* | **junction overlaps are now visible**, because the roads that overlap are now drawn. At `b1cd3e5` most of them were under the ground |

The nine aerials also improved and it is worth recording, because they were never counted in the 31: mean tarmac fraction 0.0776 → 0.1013 and grass 0.4163 → 0.3890. In `margate_bay_from_the_north_west` and `westwood_cross_and_the_retail_grid` the inland street grid is now continuous grey ribbon where it was thin magenta on unbroken green.

## Every image

`dom` is the largest share of the frame taken by one colour after quantising to 16 levels per channel (fail above 0.85); `edge` is the detail measure above; `grass` and `tarmac` are the lower-half fractions described under *The road defect, measured*, shown as `b1cd3e5 → 7c8b4a6`.

### margate (5 images, 7.8 MB)

| image | kind | bytes | dom | edge | grass | tarmac |
|---|---|---:|---:|---:|---|---|
| [`margate_bay_from_the_north_west.png`](margate/margate_bay_from_the_north_west.png) | aerial | 1,911,025 | 0.071 | 0.093 | 0.0885 → 0.0789 | 0.1044 → 0.1125 |
| [`marine_terrace_west_past_dreamland.png`](margate/marine_terrace_west_past_dreamland.png) | street | 1,539,080 | 0.085 | 0.015 | 0.0030 → 0.0339 | 0.7594 → 0.7564 |
| [`canterbury_road_east_at_garlinge.png`](margate/canterbury_road_east_at_garlinge.png) | street | 1,529,688 | 0.059 | 0.014 | 0.9895 → 0.1410 | 0.0012 → 0.5649 |
| [`turner_contemporary_from_the_sands.png`](margate/turner_contemporary_from_the_sands.png) | seafront | 1,471,061 | 0.157 | 0.009 | 0.0078 → 0.0051 | 0.0166 → 0.0130 |
| [`millmead_road_east_up_the_hill.png`](margate/millmead_road_east_up_the_hill.png) | street | 1,348,198 | 0.081 | 0.009 | 0.1614 → 0.0813 | 0.6061 → 0.6507 |

### cliftonville (5 images, 7.6 MB)

| image | kind | bytes | dom | edge | grass | tarmac |
|---|---|---:|---:|---:|---|---|
| [`cliftonville_from_over_walpole_bay.png`](cliftonville/cliftonville_from_over_walpole_bay.png) | aerial | 2,139,781 | 0.061 | 0.118 | 0.4387 → 0.4031 | 0.1420 → 0.1646 |
| [`northdown_road_east_through_the_shops.png`](cliftonville/northdown_road_east_through_the_shops.png) | street | 1,120,868 | 0.305 | 0.017 | 0.0008 → 0.0086 | 0.5594 → 0.5625 |
| [`eastern_esplanade_seafront_terrace.png`](cliftonville/eastern_esplanade_seafront_terrace.png) | street | 1,429,313 | 0.087 | 0.014 | 0.0930 → 0.1468 | 0.6662 → 0.6638 |
| [`walpole_bay_chalk_cliff_from_the_sands.png`](cliftonville/walpole_bay_chalk_cliff_from_the_sands.png) | seafront | 1,463,069 | 0.127 | 0.004 | 0.0427 → 0.0054 | 0.0122 → 0.0030 |
| [`princess_margaret_avenue_at_northdown.png`](cliftonville/princess_margaret_avenue_at_northdown.png) | street | 1,442,745 | 0.087 | 0.009 | 0.2033 → 0.1357 | 0.5745 → 0.6516 |

### broadstairs (5 images, 7.9 MB)

| image | kind | bytes | dom | edge | grass | tarmac |
|---|---|---:|---:|---:|---|---|
| [`the_town_and_viking_bay_from_the_sea.png`](broadstairs/the_town_and_viking_bay_from_the_sea.png) | aerial | 2,169,997 | 0.039 | 0.069 | 0.0918 → 0.0786 | 0.0423 → 0.0524 |
| [`broadstairs_high_street.png`](broadstairs/broadstairs_high_street.png) | street | 1,148,975 | 0.263 | 0.017 | 0.2911 → 0.0125 | 0.3879 → 0.6021 |
| [`st_peters_high_street.png`](broadstairs/st_peters_high_street.png) | street | 1,520,359 | 0.050 | 0.012 | 0.9802 → 0.2235 | 0.0057 → 0.4799 |
| [`viking_bay_sands_and_the_cliff_town.png`](broadstairs/viking_bay_sands_and_the_cliff_town.png) | seafront | 1,405,198 | 0.166 | 0.011 | 0.0012 → 0.0003 | 0.0061 → 0.0078 |
| [`north_foreland_lighthouse.png`](broadstairs/north_foreland_lighthouse.png) | landmark | 1,639,559 | 0.072 | 0.015 | 0.1653 → 0.3416 | 0.3952 → 0.2685 |

### ramsgate (5 images, 7.3 MB)

| image | kind | bytes | dom | edge | grass | tarmac |
|---|---|---:|---:|---:|---|---|
| [`royal_harbour_and_town_from_the_sea.png`](ramsgate/royal_harbour_and_town_from_the_sea.png) | aerial | 1,953,111 | 0.075 | 0.072 | 0.1257 → 0.1045 | 0.0460 → 0.0571 |
| [`military_road_at_the_royal_harbour.png`](ramsgate/military_road_at_the_royal_harbour.png) | street | 1,445,116 | 0.080 | 0.010 | 0.0104 → 0.0383 | 0.4635 → 0.4593 |
| [`high_street_down_to_the_harbour.png`](ramsgate/high_street_down_to_the_harbour.png) | street | 1,018,883 | 0.329 | 0.021 | 0.7018 → 0.0065 | 0.0153 → 0.5326 |
| [`ramsgate_station_from_the_approach.png`](ramsgate/ramsgate_station_from_the_approach.png) | landmark | 1,433,403 | 0.087 | 0.009 | 0.3642 → 0.1456 | 0.0098 → 0.5731 |
| [`ramsgate_sands_and_the_east_cliff.png`](ramsgate/ramsgate_sands_and_the_east_cliff.png) | seafront | 1,463,420 | 0.226 | 0.019 | 0.0246 → 0.0003 | 0.0047 → 0.0043 |

### westgate-on-sea (5 images, 7.9 MB)

| image | kind | bytes | dom | edge | grass | tarmac |
|---|---|---:|---:|---:|---|---|
| [`westgate_from_over_st_mildreds_bay.png`](westgate-on-sea/westgate_from_over_st_mildreds_bay.png) | aerial | 1,998,947 | 0.079 | 0.077 | 0.3342 → 0.3143 | 0.1239 → 0.1387 |
| [`westgate_bay_avenue_east_to_the_town.png`](westgate-on-sea/westgate_bay_avenue_east_to_the_town.png) | street | 1,506,347 | 0.061 | 0.011 | 0.1263 → 0.1667 | 0.5609 → 0.5840 |
| [`canterbury_road_west_at_westgate.png`](westgate-on-sea/canterbury_road_west_at_westgate.png) | street | 1,497,490 | 0.082 | 0.013 | 0.0786 → 0.1305 | 0.6959 → 0.6413 |
| [`st_mildreds_bay_from_the_sands.png`](westgate-on-sea/st_mildreds_bay_from_the_sands.png) | seafront | 1,738,667 | 0.038 | 0.007 | 0.0425 → 0.0040 | 0.1555 → 0.1427 |
| [`westgate_station_from_station_road.png`](westgate-on-sea/westgate_station_from_station_road.png) | landmark | 1,160,318 | 0.361 | 0.017 | 0.0518 → 0.0140 | 0.2563 → 0.3003 |

### birchington (5 images, 7.4 MB)

| image | kind | bytes | dom | edge | grass | tarmac |
|---|---|---:|---:|---:|---|---|
| [`birchington_and_the_wantsum_edge.png`](birchington/birchington_and_the_wantsum_edge.png) | aerial | 1,868,518 | 0.071 | 0.080 | 0.5023 → 0.4495 | 0.0895 → 0.1316 |
| [`canterbury_road_a28.png`](birchington/canterbury_road_a28.png) | street | 1,477,236 | 0.084 | 0.011 | 0.9940 → 0.1105 | 0.0015 → 0.7429 |
| [`station_road_to_the_square.png`](birchington/station_road_to_the_square.png) | street | 1,041,551 | 0.392 | 0.012 | 0.4181 → 0.0000 | 0.0063 → 0.2992 |
| [`minnis_bay_where_the_model_ends.png`](birchington/minnis_bay_where_the_model_ends.png) | seafront | 1,511,703 | 0.073 | 0.010 | 0.0242 → 0.0523 | 0.5090 → 0.5166 |
| [`railway_bridge_over_minnis_road.png`](birchington/railway_bridge_over_minnis_road.png) | landmark | 1,518,701 | 0.050 | 0.010 | 0.8969 → 0.4852 | 0.0139 → 0.2793 |

### westwood (5 images, 7.9 MB)

| image | kind | bytes | dom | edge | grass | tarmac |
|---|---|---:|---:|---:|---|---|
| [`westwood_cross_and_the_retail_grid.png`](westwood/westwood_cross_and_the_retail_grid.png) | aerial | 1,993,451 | 0.079 | 0.081 | 0.5478 → 0.5075 | 0.1128 → 0.1700 |
| [`haine_road_past_westwood_cross.png`](westwood/haine_road_past_westwood_cross.png) | street | 1,449,081 | 0.091 | 0.021 | 0.1263 → 0.1515 | 0.7288 → 0.7020 |
| [`new_haine_road_at_haine.png`](westwood/new_haine_road_at_haine.png) | street | 1,520,892 | 0.080 | 0.013 | 0.7923 → 0.2013 | 0.1149 → 0.6947 |
| [`westwood_cross_sheds_from_the_carpark.png`](westwood/westwood_cross_sheds_from_the_carpark.png) | landmark | 1,435,024 | 0.163 | 0.011 | 0.4144 → 0.3781 | 0.0586 → 0.0611 |
| [`manston_court_road_and_the_farmland.png`](westwood/manston_court_road_and_the_farmland.png) | street | 1,504,057 | 0.080 | 0.012 | 0.1653 → 0.1588 | 0.4114 → 0.4415 |

### manston (5 images, 7.5 MB)

| image | kind | bytes | dom | edge | grass | tarmac |
|---|---|---:|---:|---:|---|---|
| [`manston_airfield_from_the_east.png`](manston/manston_airfield_from_the_east.png) | aerial | 1,667,216 | 0.086 | 0.035 | 0.6321 → 0.6092 | 0.0337 → 0.0585 |
| [`spitfire_way_along_the_airfield.png`](manston/spitfire_way_along_the_airfield.png) | street | 1,505,928 | 0.080 | 0.011 | 0.8895 → 0.1293 | 0.0030 → 0.6741 |
| [`manston_high_street_by_the_green.png`](manston/manston_high_street_by_the_green.png) | street | 1,466,997 | 0.061 | 0.012 | 0.7932 → 0.2490 | 0.0012 → 0.3650 |
| [`manston_hangars_and_control_tower.png`](manston/manston_hangars_and_control_tower.png) | landmark | 1,558,752 | 0.049 | 0.014 | 0.4295 → 0.1535 | 0.0025 → 0.4765 |
| [`preston_road_north_east_of_the_village.png`](manston/preston_road_north_east_of_the_village.png) | street | 1,324,914 | 0.207 | 0.009 | 0.0656 → 0.0490 | 0.4430 → 0.4698 |

### acol (5 images, 7.4 MB)

| image | kind | bytes | dom | edge | grass | tarmac |
|---|---|---:|---:|---:|---|---|
| [`acol_fields_and_the_isle_edge.png`](acol/acol_fields_and_the_isle_edge.png) | aerial | 1,405,245 | 0.187 | 0.007 | 0.9855 → 0.9557 | 0.0040 → 0.0259 |
| [`manston_road_west_towards_acol.png`](acol/manston_road_west_towards_acol.png) | street | 1,556,452 | 0.071 | 0.008 | 0.4889 → 0.0882 | 0.0009 → 0.6668 |
| [`shottendane_road_between_the_fields.png`](acol/shottendane_road_between_the_fields.png) | street | 1,482,092 | 0.086 | 0.008 | 0.9612 → 0.2028 | 0.0018 → 0.5770 |
| [`margate_hill_at_the_isle_edge.png`](acol/margate_hill_at_the_isle_edge.png) | street | 1,507,127 | 0.078 | 0.009 | 0.9607 → 0.1966 | 0.0050 → 0.6080 |
| [`cheesemans_farm_from_manston_road.png`](acol/cheesemans_farm_from_manston_road.png) | street | 1,475,822 | 0.063 | 0.009 | 0.8139 → 0.2672 | 0.0064 → 0.5195 |

Totals: **45 images, 68,765,377 bytes (68.8 MB)**, 1088 s wall clock. Acol's own anchor is still outside the clip (`render_set.json:known_soft_spot`); those five frames are of Acol's surroundings.

## Which of these 45 I opened

Eighteen of them, with my own eyes, and every description above that says what a frame *looks* like comes from one of these: `margate/margate_bay_from_the_north_west`, `margate/marine_terrace_west_past_dreamland`, `margate/canterbury_road_east_at_garlinge`, `cliftonville/walpole_bay_chalk_cliff_from_the_sands`, `cliftonville/princess_margaret_avenue_at_northdown`, `broadstairs/north_foreland_lighthouse`, `ramsgate/high_street_down_to_the_harbour`, `ramsgate/ramsgate_station_from_the_approach`, `westgate-on-sea/canterbury_road_west_at_westgate`, `birchington/canterbury_road_a28`, `birchington/station_road_to_the_square`, `birchington/minnis_bay_where_the_model_ends`, `birchington/railway_bridge_over_minnis_road`, `westwood/westwood_cross_and_the_retail_grid`, `westwood/new_haine_road_at_haine`, `westwood/westwood_cross_sheds_from_the_carpark`, `manston/manston_high_street_by_the_green`, `manston/manston_hangars_and_control_tower` — plus nine of the `b1cd3e5` originals for comparison. Everything else in the tables is measurement, not impression.

## How this was built

Every step ran headless, in the background, with its own log under `projects/one/Saved/Logs/`, and every claim was read back out of the output rather than out of an exit code.

```bash
# 1. adapter products, from the committed code (246 documents, 15,422 splines, 1,642 junctions)
SITE=thanet C:/Users/Shadow/code/3duk-env/env/python.exe sources/adapters/unreal.py

# 2. the conform, re-run at HEAD (13,097 splines, 12,877,749 cells changed, 1,634 junction patches burned)
python projects/one/Tools/conform_landscape.py \
    --landscape data/thanet/out/unreal/landscape \
    --streetscape data/thanet/out/unreal/streetscape \
    --out data/thanet/out/unreal/landscape_conformed

# 3. the gate: 0 of 660,835 stations penetrated (before the conform, 564,241)
python projects/one/Tools/road_fusion_audit.py --landscape data/thanet/out/unreal/landscape_conformed \
    --gate-m 0.005 --float-gate-m 0.125 --float-max-frac 0.08 --slope --rules

# 4. the level, from nothing
powershell -File projects/one/Tools/ue/00_build_level.ps1 -Recreate

# 5. the snapshot (nine editor batches)
powershell -File projects/one/Tools/render_set.ps1 -PerTown

# 6. the checks
python projects/one/Tools/qc_renders.py renders/7c8b4a6
python projects/one/Tools/compare_snapshots.py renders/b1cd3e5 renders/7c8b4a6
```

`00_build_level.ps1 -Recreate` **failed on its own defaults**, at streetscape slice 11: `roads:132194822:0` in `site_x7_y7.json` is a 0.18 m cycleway that sits on a clipped-out cell — the numpy heightfield returns NaN at its own two points and a real height 3 m away — so it builds flat at z = 0, and `-AllowNoTerrain 0` rejects it. Slices 11 and 12 were re-run with `--allow-no-terrain 1`, the value the `b1cd3e5` build used. It is exactly one spline isle-wide: slices 1–10 passed with the limit at 0.

The level was then asserted twice, the second time in a fresh commandlet that streamed the whole world: **15,423 streetscape actors, 216 massing actors / 20,121 buildings, 140 landscape proxies, 2,067 landscape components, extent [0, 0, 13462, 9906], `PlayerStart` and game mode set, `problems: []`**; and re-opened a third time for the census in the table above (peak RSS 23,045 MB, 218 s to stream 15,423 actors).

Wall clock, per commandlet: bootstrap 85.7 s, landscape 434.1 s (2,067 components at `--max-components 256`, grid probe max \|dz\| 0.000645 m, cliff 84.65° against the tile's 81.7°, clip 20 kept / 20 cut), test stretch 105.4 s, massing 87.7 s, twelve streetscape slices 37.8–92.6 s each, assert 13.9 s, assert-with-streaming 418.2 s, reopen census 258 s. About 43 minutes of editor time end to end, plus 410 s for the adapter, 947 s for the conform and 201 s for the two fusion audits.

All nine render batches ended with the engine's raw exit code `-1073741819` (0xC0000005) *after* `LogExit`, which `run_ue_python.ps1` rewrites to 0 and `render_set.ps1` records per batch in `manifest.json → batches`. Every batch logged its `THANET_OK`, wrote its report and produced all five images, so this is the known teardown crash of `docs/RESUME.md` §5 and not a lost render.

## What the next round should pick up

1. **Wire the junction layer into the Unreal import path.** It is written, ported, tested and parity-proved on six frozen fixtures, and it reaches nothing. `UStreetSplineComponent::Build` needs the `Trim` from a per-document `FStreetJunctionPlan`, and `AStreetscapeActor` needs to call `BuildJunctionPatch` and `BuildJunctionCorners` for the junctions its spline owns.
2. **The sink is set by the shallower side.** 40.8 % of road length (30-document sample, 116 km) keeps only the 0.03 m floor because one side of the road has no kerb, and every frame in this set that still loses carriageway is on such a road. Either take the sink from the side that *has* cover, or raise the floor.
3. **`render_set.json`'s `honesty` block still carries the disproved claim** that the carriageway renders cleanly "only because the capture pins the landscape at LOD 0". The `capture` block beside it has been corrected; the prose has not. I do not own that file.
4. Defect 4 (black wedge gaps under every ribbon) is now the most conspicuous thing in a street frame, and it got worse for a good reason. A skirt that reaches the ground, or an ambient term so the vertical faces are not black, would repay itself across the whole set.
