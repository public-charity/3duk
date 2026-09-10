# `renders/b6d3274` — what this snapshot shows

45 frames, one per location in [`projects/one/Tools/ue/render_set.json`](../../projects/one/Tools/ue/render_set.json) (spec sha256 `584afbd7680113ae`), rendered at commit **b6d3274** — *Snapshot 7c8b4a6: the streets appear, and a verifier that refuses to call it finished* — on 2026-09-10T14:43:41Z in 1104 s, on engine `5.8.2-56702186+++UE5+Release-5.8`, from `/Game/Thanet/Maps/Thanet` over `data/thanet/out/unreal/landscape_conformed`.

> The worktree held **25 uncommitted changes** when this was taken — this round's junction wiring (`StreetJunctionBuild.*`, `StreetscapeEditorActors.cpp`, `03_import_streetscape.py`, …) and this round's clearance rule (`conform.py`, `terrain.py`, `conform_landscape.py`, `road_fusion_audit.py`, …). `manifest.json` lists all 25. **This snapshot is not commit `b6d3274`; it is `b6d3274` plus the two tracks built on top of it**, and that is the point of taking it.

`manifest.json` beside this file holds, per image, the camera transform actually used, the sampled ground height, the streamed region, the file size, the sha256 and the landscape LOD properties read back off the resident proxies. Compare snapshots through the manifest, never by eye alone.

## The one-line verdict

**The junctions are in the picture, and the roads that were sinking have come up.** Of the 31 frames that stand on or look along a road, the carriageway is drawn in **30** — the same 30 as at `7c8b4a6`, and the one frame with no road surface is still the Westwood Cross car park (defect 10, not the road defect). What is new is that the crossings now read as crossings: **1,642 junctions are in the level**, and in the seven frames listed below that look into one, the mouth is a continuous tarmac surface with kerbs and footways turning the corner on a radius, instead of a footway slab lying across the carriageway. **All three frames the verifier called worse than `b1cd3e5` have recovered**, one of them completely.

Mean over the 30 street-and-landmark frames, lower half of the frame: grass **0.4477 → 0.1482 → 0.1352**, tarmac **0.2586 → 0.5289 → 0.5705** (`b1cd3e5` → `7c8b4a6` → here).

## What changed since `7c8b4a6`

Three things, and only three. Every asset in the level was rebuilt from nothing in this session (`00_build_level.ps1 -Recreate`), so nothing here is left over from an earlier build.

1. **The junction layer reached the level.** At `7c8b4a6` the `StreetscapeEditor` module contained the string "Junction" zero times and the level held no junction at all. It now holds **1,642 built, 1,642 owned, 0 skipped**, counted in a reopened level with all 15,423 actors streamed in (`Saved/Tests/build_level_assert_loaded.json`, `problems: []`).
2. **The clearance rule became per-side.** The corridor sink is no longer one depth for the whole cross-section: each side gets what that side's own cover can hide, and the two are joined across the section with a 1.5 m flat margin and a 0.10 taper, capped at 0.15 m. The landscape product was re-burned (16,143,522 cells changed, against 12,877,749 before) and re-imported.
3. **Nothing else.** The spec, the capture settings, the map, the renderer and the driver are identical to `7c8b4a6`.

### The cameras did not move, and here is the proof

`projects/one/Saved/Rebuild/manifest_diff_7c8b4a6_b6d3274.json`, produced by comparing the two manifests block by block over all 45 frames:

| block | result |
|---|---|
| `spec.sha256` | `584afbd7680113ae…` in both — **identical**, so not one location, bearing or height was edited |
| `capture` | **no key differs**: width 1600, height 900, `source final_ldr`, `exposure_ev 0.0`, `landscape_lod0_screen_size null` |
| `landscape_dir`, `map`, `renderer`, `driver`, `engine_version`, `origin`, `schema_version`, `branch` | **all identical** |
| `counts` | 45 expected / 45 requested / 45 rendered / 0 missing / `partial false`, in both |
| `landscape_lod.in_force` | **identical in all 45 frames** — `lod0_screen_size 0.5`, `lod0_distribution_setting 1.25`, `lod_distribution_setting 3.0`, on the same proxy counts. The ground was drawn under the same LOD policy in both snapshots. |
| `camera_en`, `subject_en`, `camera_height_m`, `local_m`, `ground_source`, `bearing_deg`, `yaw_deg`, `pitch_deg`, `roll_deg`, `fov_deg`, `subject_distance_m` | **0 of 45 frames differ**, in every one of those eleven fields |
| `eye_ue_cm` X and Y | **0 of 45 frames differ** |
| `ground_z_m`, `eye_z_m`, `eye_ue_cm` **Z** | **7 frames differ**, and only these three fields |

Those seven are the spec's own `camera_height_rule` — the eye is placed 1.7 m above the sampled ground every run — following ground that really did move under the new sink. Every one is **downward**: median −0.117 m, range −0.124 to −0.097 m.

| frame | `ground_z_m` `7c8b4a6` → now |
|---|---|
| `westgate-on-sea/canterbury_road_west_at_westgate` | 14.167 → 14.043 (−0.124) |
| `broadstairs/north_foreland_lighthouse` | 31.283 → 31.164 (−0.119) |
| `ramsgate/ramsgate_station_from_the_approach` | 42.619 → 42.501 (−0.118) |
| `cliftonville/eastern_esplanade_seafront_terrace` | 20.570 → 20.453 (−0.117) |
| `westwood/haine_road_past_westwood_cross` | 46.742 → 46.625 (−0.117) |
| `westwood/new_haine_road_at_haine` | 49.573 → 49.462 (−0.111) |
| `margate/marine_terrace_west_past_dreamland` | 5.838 → 5.741 (−0.097) |

Six of the seven are frames this round set out to fix. The other 38 cameras sat on ground the new rule did not move at all.

**No image is byte-identical to its `7c8b4a6` counterpart** (0 of 45), and that is expected — every actor in the level was rebuilt. The honest measure of how much a frame changed is pixels, not hashes. Over the twelve frames whose grass and tarmac fractions are unchanged to four decimals, the share of pixels that differ at all is: upper half (sky and cloud, which this renderer does not reproduce exactly between runs) min 0.07 %, median 1.29 %, max 21.59 %; lower half min 0.98 %, median 11.17 %, max 65.57 %. Two of them are real change rather than run-to-run noise: `ramsgate/ramsgate_sands_and_the_east_cliff` (52 % of the lower half differs by more than 8) and `westwood/westwood_cross_sheds_from_the_carpark` — both are frames of ribbon terraces standing proud of the ground, and the ground moved under them.

## Automated quality check

Every image decoded with the stdlib PNG decoder in `projects/one/Tools/qc_renders.py` (no PIL on this machine) and tested for: present, ≥ 50 KB, decodes, fully opaque, not a single flat colour, not more than 85 % one colour.

| check | `b6d3274` | `7c8b4a6` |
|---|---|---|
| images expected / rendered | 45 / 45 | 45 / 45 |
| under 50 KB | 0 (smallest 1,017,519 B) | 0 |
| failed to decode | 0 | 0 |
| not fully opaque | 0 | 0 |
| flat single colour | 0 | 0 |
| more than 85 % one colour | 0 (worst 39.4 %, `birchington/station_road_to_the_square`) | 0 (worst 39.2 %, same frame) |
| **failed any check** | **0** | **0** |

Edge fraction (share of pixels whose horizontal neighbour differs by more than 8 in luminance) runs 0.004–0.118, median **0.0124**, against 0.004–0.118 median 0.0123 before. Unchanged: this model still has no textures. Thirty-four frames carry the "very little detail" warning, the same warning the previous set carried.

All nine render batches returned raw exit `-1073741819` (`0xC0000005`) and were overridden to 0 by `run_ue_python.ps1`. In all nine the log carries `THANET_OK 07_render_set`, no crash marker, and all 45 images and 9 reports were written and then verified independently above. This is the teardown access violation of `docs/RESUME.md` §5; `manifest.batches` records it per batch rather than hiding it.

## What the pictures show

`projects/one/Tools/compare_snapshots.py` decodes the **lower half** of each frame and measures colour proxies calibrated against sampled pixels: grass at (109, 145, 46), tarmac at (104, 94, 80), paving at (188, 179, 162), the magenta overlay. Full output in `projects/one/Saved/Rebuild/compare_7c8b4a6_b6d3274.json`.

### The two fixes separate cleanly, and the paving column is what separates them

This was not designed as a test, and it is the strongest evidence in the snapshot. **Fourteen** of the 30 street-and-landmark frames gained more than a point of tarmac, and they fall into two disjoint groups.

**Group A — the junction fill: tarmac up, paving down by the same amount, grass unchanged.** New road surface where there was pale footway — exactly what happens when a junction mouth is filled and the footway that used to run across it is trimmed back and turned round a corner radius.

| frame | d_tarmac | d_paving | d_grass |
|---|---:|---:|---:|
| `ramsgate/military_road_at_the_royal_harbour` | +0.1715 | −0.1766 | +0.0051 |
| `birchington/station_road_to_the_square` | +0.1676 | −0.1742 | +0.0000 |
| `broadstairs/broadstairs_high_street` | +0.1401 | −0.1398 | +0.0032 |
| `margate/canterbury_road_east_at_garlinge` | +0.1399 | −0.1380 | −0.0053 |
| `cliftonville/northdown_road_east_through_the_shops` | +0.1282 | −0.1232 | −0.0022 |
| `manston/manston_high_street_by_the_green` | +0.0739 | −0.0972 | +0.0035 |

**Group B — the clearance rule: tarmac up, grass down by the same amount, paving unchanged.** Ground that was erupting through the carriageway no longer is.

| frame | d_tarmac | d_grass | d_paving |
|---|---:|---:|---:|
| `broadstairs/north_foreland_lighthouse` | +0.1186 | −0.1116 | −0.0020 |
| `westgate-on-sea/canterbury_road_west_at_westgate` | +0.0843 | −0.0721 | −0.0038 |
| `westwood/new_haine_road_at_haine` | +0.0584 | −0.0584 | +0.0004 |
| `birchington/railway_bridge_over_minnis_road` | +0.0547 | −0.0692 | +0.0011 |
| `westwood/haine_road_past_westwood_cross` | +0.0341 | −0.0337 | −0.0003 |
| `ramsgate/ramsgate_station_from_the_approach` | +0.0308 | −0.0172 | −0.0061 |

No frame is in both groups. Twelve frames are unchanged to four decimals in both proxies — aerials, seafronts, and rural streets with no junction in shot and no breakthrough (`acol/manston_road_west_towards_acol`, `acol/margate_hill_at_the_isle_edge`, `manston/preston_road_north_east_of_the_village`, …). That is the right answer for them.

### Do junctions read as junctions? Yes — opened and looked at

- **`birchington/station_road_to_the_square`** is the clearest before/after in the set. At `7c8b4a6` a broad pale footway slab ran diagonally straight across the carriageway a few metres in front of the camera, with a second slab behind it. Here the carriageway is unbroken to the bottom of the frame and the right-hand footway sweeps round the corner into the side street on a radius. Grass is 0.0000 in both, so this frame has nothing to do with the ground: it is the junction layer and only the junction layer.
- **`ramsgate/military_road_at_the_royal_harbour`**: the pale slab lying across the bottom-left of Military Road at `7c8b4a6` is gone; the carriageway runs continuously into the corner.
- **`margate/canterbury_road_east_at_garlinge`**: full-width A28 with centre dashes and both footways, and on the right the side road joins through a filled tarmac mouth with a kerb radius turning out of shot.
- **`westgate-on-sea/westgate_bay_avenue_east_to_the_town`**: a three-arm junction dead ahead-right — mouth filled, both corners radiused, no grass wedge between the arms.
- **`manston/manston_high_street_by_the_green`**: the footway turns a clean corner into the side road at bottom-right and the mouth is tarmac.
- **`cliftonville/northdown_road_east_through_the_shops`** and **`broadstairs/broadstairs_high_street`**: complete street canyons, carriageway and both footways, nothing crossing them.
- **`ramsgate/ramsgate_station_from_the_approach`** — the frame the last snapshot called "the clearest picture of the junction defect" — the green wedge between the two crossing carriageways is now road surface. At this range it is a subtle read; the close-ups the wiring agent took are far clearer than any camera in this fixed set. **If Alex wants junctions to be obvious in the standing set, the set needs a junction viewpoint; none of the 45 was chosen to frame one.**
- **`westwood/westwood_cross_and_the_retail_grid`** (aerial, 300 m up): the network reads as a continuous grey web, and the roundabouts read as filled discs rather than crossed ribbons.

What the junction layer does **not** fix, and it is visible: a **footway crossing a carriageway where there is no road-to-road junction record** is still drawn straight through. `broadstairs/st_peters_high_street` has one at mid-field on the right. There are 1,642 junction records and a footway/carriageway crossing is not one of them.

### Did the three regressed frames recover? Yes — two well, one completely

| frame | grass `b1cd3e5` / `7c8b4a6` / now | tarmac `b1cd3e5` / `7c8b4a6` / now | read |
|---|---|---|---|
| `broadstairs/north_foreland_lighthouse` | 0.1653 / 0.3416 / **0.2300** | 0.3952 / 0.2685 / **0.3871** | **most of the way back.** The mosaic of green wedges across the whole width is gone; what is left is a handful of small isolated patches in the middle of the carriageway and a ragged left edge. Tarmac is back to within 0.008 of `b1cd3e5`. |
| `westgate-on-sea/canterbury_road_west_at_westgate` | 0.0786 / 0.1305 / **0.0584** | 0.6959 / 0.6413 / **0.7256** | **completely.** Every green blade that cut across the tarmac is gone; carriageway, both footways and the side road joining on the right are unbroken. Better than `b1cd3e5` on both proxies. |
| `westwood/haine_road_past_westwood_cross` | 0.1263 / 0.1515 / **0.1178** | 0.7288 / 0.7020 / **0.7361** | **carriageway completely, edges partly.** The running surface is clean; two green tongues remain in the near-left footway strip and the right-hand verge still takes bites at mid-distance. Better than `b1cd3e5` on both proxies. |

`b1cd3e5` is not a fair target and it is worth saying so: that whole snapshot was rendered with every landscape component pinned to its coarsest LOD by mistake, so its numbers describe a different ground. `7c8b4a6` is the honest baseline, and against it all three improved.

The clearance agent predicted these three frames from the geometry alone, before any picture existed (`Saved/Clearance/frame_clearance_after.json`): screen-weighted cut fraction 0.0764 → 0.0348, 0.0480 → 0.0273, 0.0441 → 0.0216. The pictures agree in direction and roughly in magnitude on all three.

### Where the ground still breaks through

Four road frames still show it, all of it beyond the near field:

- **`birchington/railway_bridge_over_minnis_road`** — the worst remaining. The carriageway is drawn but a scatter of green wedges cuts into it through the middle distance. Grass 0.4852 → 0.4160, tarmac 0.2793 → 0.3340: better, and still visibly broken. This is a road in a cutting with steep sides, the hardest case for any single sink depth.
- **`broadstairs/north_foreland_lighthouse`** — small isolated patches, described above.
- **`westwood/new_haine_road_at_haine`** — the running surface is clean; the left verge and the ribbons on the right still take green bites.
- **`westwood/haine_road_past_westwood_cross`** — edges only.

The other 26 road frames that draw a carriageway draw it unbroken.

## What the level holds, counted in a reopened level

`07_assert_level.py --census-only`: a fresh commandlet that re-opens the saved map and streams the whole world in (`Saved/Tests/build_level_assert_loaded.json`, `problems: []`, peak RSS 21.0 GB).

| | `b1cd3e5` | `7c8b4a6` | **`b6d3274`** |
|---|---:|---:|---:|
| streetscape actors | 15,422 | 15,423 | **15,423** |
| landscape components / proxies | 2,067 / 140 | 2,067 / 140 | **2,067 / 140** |
| massing actors / buildings | 216 / 20,121 | 216 / 20,121 | **216 / 20,121** |
| **junctions built** | 0 | 0 | **1,642** |
| **junctions owned / skipped** | — | — | **1,642 / 0** |
| junction patch verts / tris | 0 | 0 | **87,969 / 86,327** |
| junction corners / corner tris | 0 | 0 | **3,451 / 498,830** |
| trimmed ends / splines trimmed | 0 | 0 | **5,168 / 4,087** |
| trim total | 0 m | 0 m | **25,808.929493541713 m** |
| vertices | 19,705,600 | 19,711,962 | **19,699,912** |
| triangles | 29,006,476 | 29,015,722 | **28,842,149** |
| renderer components | 30,624 | 30,628 | **31,317** |
| marking strips | 20,700 | 20,731 | **19,320** |
| stations | 745,642 | 745,758 | **750,086** |
| spline length | 1,072,441.99 m | 1,072,613.40 m | **1,072,613.40 m** |

Read the last six rows together, because they are the arithmetic signature of a junction layer that is really there:

- vertices fell by 12,050 and triangles by 173,573 **even though junctions added 461,446 vertices and 585,157 triangles** — because the trims removed 25,808.9 m of carriageway and kerb at 5,168 spline ends;
- **marking strips fell by 1,411**: you do not paint a centre line through a junction, and now the model does not;
- **stations rose by 4,328**: both trim stations are added to the mandatory station set, so every renderer carries the trim in its list exactly;
- **spline length is unchanged to the last digit**, because trimming masks arc length rather than redefining the spline.

The trim total, `25,808.929493541713 m`, is the C++ figure summed over 12 import slices; the numpy isle-wide audit gives `25,808.929493541782 m`. They differ in the last three digits of a sum over 5,168 terms.

## How this was built

Every command ran headless through `Tools/ue/run_ue_python.ps1`; no GUI editor was launched and none was running.

1. `Tools/build.ps1` — `Result: Succeeded`, 2.15 s: the binaries already matched the working tree, so this snapshot is drawn by the code that is on disk.
2. `Tools/ue/00_build_level.ps1 -Recreate` — the map deleted and rebuilt from nothing: bootstrap, then the landscape from `landscape_conformed` (2,067 components, 140 proxies, 435 s; shared tile edges 0 of 378,081 samples disagreeing, heightfield-vs-landscape grid max 0.000586 m, cliff and clip gates green), then the authored test stretch, 216 massing actors, and the isle in 12 streetscape slices.
3. **The run failed at slice 11 and was resumed, not restarted.** `roads:132194822:0` in `site_x7_y7.json` sampled no terrain at any station and the default `-AllowNoTerrain 0` refused it. It is an 18 cm stub of road whose five points sit 1.2–18.6 cm on the kept side of the Wantsum clip line, over ground the model holes out; it failed the same way at the `7c8b4a6` build and at the junction-wiring build, both of which were re-run with `--allow-no-terrain 1`. Slices 11 and 12 were re-run with the same allowance (`ACCEPTED … (limit 1): roads:132194822:0`). Slices 1–10 had already saved; the failing commandlet exited before its save, so nothing partial was left behind.
4. The two assertion passes, then `Tools/render_set.ps1 -PerTown`, nine commandlets, 1104 s.

Junction totals accumulated over the 12 import slices: 246 documents, 1,642 junctions in the documents, 1,642 planned, 1,642 built, 1,642 owned, 0 skipped, 5,168 trimmed ends, 4,087 splines trimmed — the same figures the reopened level then reported back.

## Every frame

Columns: file size, edge fraction, magenta fraction (lower half), and the grass and tarmac fractions `7c8b4a6` → now.

### margate (5 images, 7.8 MB)
| image | kind | bytes | edge | magenta | grass 7c8b4a6 -> now | tarmac 7c8b4a6 -> now |
|---|---|---:|---:|---:|---|---|
| [`margate_bay_from_the_north_west.png`](margate/margate_bay_from_the_north_west.png) | aerial | 1,913,686 | 0.092 | 0.004 | 0.0789 -> 0.0776 | 0.1125 -> 0.1137 |
| [`marine_terrace_west_past_dreamland.png`](margate/marine_terrace_west_past_dreamland.png) | street | 1,535,783 | 0.014 | 0.027 | 0.0339 -> 0.0308 | 0.7564 -> 0.7721 |
| [`canterbury_road_east_at_garlinge.png`](margate/canterbury_road_east_at_garlinge.png) | street | 1,510,731 | 0.013 | 0.024 | 0.1410 -> 0.1357 | 0.5649 -> 0.7048 |
| [`turner_contemporary_from_the_sands.png`](margate/turner_contemporary_from_the_sands.png) | seafront | 1,463,107 | 0.009 | 0.005 | 0.0051 -> 0.0022 | 0.0130 -> 0.0131 |
| [`millmead_road_east_up_the_hill.png`](margate/millmead_road_east_up_the_hill.png) | street | 1,346,127 | 0.009 | 0.023 | 0.0813 -> 0.0770 | 0.6507 -> 0.6507 |

### cliftonville (5 images, 7.6 MB)
| image | kind | bytes | edge | magenta | grass 7c8b4a6 -> now | tarmac 7c8b4a6 -> now |
|---|---|---:|---:|---:|---|---|
| [`cliftonville_from_over_walpole_bay.png`](cliftonville/cliftonville_from_over_walpole_bay.png) | aerial | 2,146,661 | 0.118 | 0.004 | 0.4031 -> 0.4019 | 0.1646 -> 0.1652 |
| [`northdown_road_east_through_the_shops.png`](cliftonville/northdown_road_east_through_the_shops.png) | street | 1,088,585 | 0.016 | 0.017 | 0.0086 -> 0.0064 | 0.5625 -> 0.6907 |
| [`eastern_esplanade_seafront_terrace.png`](cliftonville/eastern_esplanade_seafront_terrace.png) | street | 1,423,304 | 0.014 | 0.029 | 0.1468 -> 0.1276 | 0.6638 -> 0.6871 |
| [`walpole_bay_chalk_cliff_from_the_sands.png`](cliftonville/walpole_bay_chalk_cliff_from_the_sands.png) | seafront | 1,452,002 | 0.004 | 0.004 | 0.0054 -> 0.0057 | 0.0030 -> 0.0010 |
| [`princess_margaret_avenue_at_northdown.png`](cliftonville/princess_margaret_avenue_at_northdown.png) | street | 1,443,686 | 0.009 | 0.024 | 0.1357 -> 0.1323 | 0.6516 -> 0.6525 |

### broadstairs (5 images, 7.9 MB)
| image | kind | bytes | edge | magenta | grass 7c8b4a6 -> now | tarmac 7c8b4a6 -> now |
|---|---|---:|---:|---:|---|---|
| [`the_town_and_viking_bay_from_the_sea.png`](broadstairs/the_town_and_viking_bay_from_the_sea.png) | aerial | 2,177,611 | 0.069 | 0.002 | 0.0786 -> 0.0784 | 0.0524 -> 0.0531 |
| [`broadstairs_high_street.png`](broadstairs/broadstairs_high_street.png) | street | 1,132,448 | 0.017 | 0.016 | 0.0125 -> 0.0157 | 0.6021 -> 0.7422 |
| [`st_peters_high_street.png`](broadstairs/st_peters_high_street.png) | street | 1,521,802 | 0.012 | 0.044 | 0.2235 -> 0.2204 | 0.4799 -> 0.4804 |
| [`viking_bay_sands_and_the_cliff_town.png`](broadstairs/viking_bay_sands_and_the_cliff_town.png) | seafront | 1,409,067 | 0.011 | 0.004 | 0.0003 -> 0.0003 | 0.0078 -> 0.0078 |
| [`north_foreland_lighthouse.png`](broadstairs/north_foreland_lighthouse.png) | landmark | 1,614,185 | 0.014 | 0.017 | 0.3416 -> 0.2300 | 0.2685 -> 0.3871 |

### ramsgate (5 images, 7.3 MB)
| image | kind | bytes | edge | magenta | grass 7c8b4a6 -> now | tarmac 7c8b4a6 -> now |
|---|---|---:|---:|---:|---|---|
| [`royal_harbour_and_town_from_the_sea.png`](ramsgate/royal_harbour_and_town_from_the_sea.png) | aerial | 1,958,744 | 0.072 | 0.002 | 0.1045 -> 0.1042 | 0.0571 -> 0.0577 |
| [`military_road_at_the_royal_harbour.png`](ramsgate/military_road_at_the_royal_harbour.png) | street | 1,428,638 | 0.009 | 0.019 | 0.0383 -> 0.0434 | 0.4593 -> 0.6308 |
| [`high_street_down_to_the_harbour.png`](ramsgate/high_street_down_to_the_harbour.png) | street | 1,017,519 | 0.021 | 0.021 | 0.0065 -> 0.0039 | 0.5326 -> 0.5334 |
| [`ramsgate_station_from_the_approach.png`](ramsgate/ramsgate_station_from_the_approach.png) | landmark | 1,425,846 | 0.009 | 0.056 | 0.1456 -> 0.1284 | 0.5731 -> 0.6039 |
| [`ramsgate_sands_and_the_east_cliff.png`](ramsgate/ramsgate_sands_and_the_east_cliff.png) | seafront | 1,508,735 | 0.024 | 0.002 | 0.0003 -> 0.0002 | 0.0043 -> 0.0041 |

### westgate-on-sea (5 images, 7.9 MB)
| image | kind | bytes | edge | magenta | grass 7c8b4a6 -> now | tarmac 7c8b4a6 -> now |
|---|---|---:|---:|---:|---|---|
| [`westgate_from_over_st_mildreds_bay.png`](westgate-on-sea/westgate_from_over_st_mildreds_bay.png) | aerial | 2,000,683 | 0.076 | 0.004 | 0.3143 -> 0.3133 | 0.1387 -> 0.1387 |
| [`westgate_bay_avenue_east_to_the_town.png`](westgate-on-sea/westgate_bay_avenue_east_to_the_town.png) | street | 1,503,222 | 0.011 | 0.021 | 0.1667 -> 0.1602 | 0.5840 -> 0.5872 |
| [`canterbury_road_west_at_westgate.png`](westgate-on-sea/canterbury_road_west_at_westgate.png) | street | 1,466,750 | 0.011 | 0.043 | 0.1305 -> 0.0584 | 0.6413 -> 0.7256 |
| [`st_mildreds_bay_from_the_sands.png`](westgate-on-sea/st_mildreds_bay_from_the_sands.png) | seafront | 1,735,593 | 0.007 | 0.005 | 0.0040 -> 0.0021 | 0.1427 -> 0.1432 |
| [`westgate_station_from_station_road.png`](westgate-on-sea/westgate_station_from_station_road.png) | landmark | 1,160,153 | 0.017 | 0.018 | 0.0140 -> 0.0138 | 0.3003 -> 0.3004 |

### birchington (5 images, 7.4 MB)
| image | kind | bytes | edge | magenta | grass 7c8b4a6 -> now | tarmac 7c8b4a6 -> now |
|---|---|---:|---:|---:|---|---|
| [`birchington_and_the_wantsum_edge.png`](birchington/birchington_and_the_wantsum_edge.png) | aerial | 1,876,392 | 0.080 | 0.004 | 0.4495 -> 0.4482 | 0.1316 -> 0.1317 |
| [`canterbury_road_a28.png`](birchington/canterbury_road_a28.png) | street | 1,477,621 | 0.011 | 0.027 | 0.1105 -> 0.1095 | 0.7429 -> 0.7431 |
| [`station_road_to_the_square.png`](birchington/station_road_to_the_square.png) | street | 1,048,033 | 0.012 | 0.044 | 0.0000 -> 0.0000 | 0.2992 -> 0.4668 |
| [`minnis_bay_where_the_model_ends.png`](birchington/minnis_bay_where_the_model_ends.png) | seafront | 1,518,706 | 0.011 | 0.030 | 0.0523 -> 0.0451 | 0.5166 -> 0.5368 |
| [`railway_bridge_over_minnis_road.png`](birchington/railway_bridge_over_minnis_road.png) | landmark | 1,516,956 | 0.010 | 0.013 | 0.4852 -> 0.4160 | 0.2793 -> 0.3340 |

### westwood (5 images, 7.9 MB)
| image | kind | bytes | edge | magenta | grass 7c8b4a6 -> now | tarmac 7c8b4a6 -> now |
|---|---|---:|---:|---:|---|---|
| [`westwood_cross_and_the_retail_grid.png`](westwood/westwood_cross_and_the_retail_grid.png) | aerial | 1,990,669 | 0.081 | 0.006 | 0.5075 -> 0.5069 | 0.1700 -> 0.1721 |
| [`haine_road_past_westwood_cross.png`](westwood/haine_road_past_westwood_cross.png) | street | 1,438,419 | 0.020 | 0.050 | 0.1515 -> 0.1178 | 0.7020 -> 0.7361 |
| [`new_haine_road_at_haine.png`](westwood/new_haine_road_at_haine.png) | street | 1,502,839 | 0.013 | 0.045 | 0.2013 -> 0.1429 | 0.6947 -> 0.7531 |
| [`westwood_cross_sheds_from_the_carpark.png`](westwood/westwood_cross_sheds_from_the_carpark.png) | landmark | 1,425,900 | 0.011 | 0.053 | 0.3781 -> 0.3788 | 0.0611 -> 0.0610 |
| [`manston_court_road_and_the_farmland.png`](westwood/manston_court_road_and_the_farmland.png) | street | 1,509,078 | 0.012 | 0.014 | 0.1588 -> 0.1631 | 0.4415 -> 0.4416 |

### manston (5 images, 7.5 MB)
| image | kind | bytes | edge | magenta | grass 7c8b4a6 -> now | tarmac 7c8b4a6 -> now |
|---|---|---:|---:|---:|---|---|
| [`manston_airfield_from_the_east.png`](manston/manston_airfield_from_the_east.png) | aerial | 1,666,303 | 0.035 | 0.003 | 0.6092 -> 0.6089 | 0.0585 -> 0.0588 |
| [`spitfire_way_along_the_airfield.png`](manston/spitfire_way_along_the_airfield.png) | street | 1,505,660 | 0.011 | 0.019 | 0.1293 -> 0.1255 | 0.6741 -> 0.6742 |
| [`manston_high_street_by_the_green.png`](manston/manston_high_street_by_the_green.png) | street | 1,464,752 | 0.013 | 0.023 | 0.2490 -> 0.2525 | 0.3650 -> 0.4389 |
| [`manston_hangars_and_control_tower.png`](manston/manston_hangars_and_control_tower.png) | landmark | 1,557,829 | 0.014 | 0.039 | 0.1535 -> 0.1557 | 0.4765 -> 0.4765 |
| [`preston_road_north_east_of_the_village.png`](manston/preston_road_north_east_of_the_village.png) | street | 1,324,799 | 0.009 | 0.036 | 0.0490 -> 0.0490 | 0.4698 -> 0.4698 |

### acol (5 images, 7.4 MB)
| image | kind | bytes | edge | magenta | grass 7c8b4a6 -> now | tarmac 7c8b4a6 -> now |
|---|---|---:|---:|---:|---|---|
| [`acol_fields_and_the_isle_edge.png`](acol/acol_fields_and_the_isle_edge.png) | aerial | 1,406,588 | 0.007 | 0.001 | 0.9557 -> 0.9554 | 0.0259 -> 0.0261 |
| [`manston_road_west_towards_acol.png`](acol/manston_road_west_towards_acol.png) | street | 1,556,081 | 0.008 | 0.015 | 0.0882 -> 0.0882 | 0.6668 -> 0.6668 |
| [`shottendane_road_between_the_fields.png`](acol/shottendane_road_between_the_fields.png) | street | 1,494,031 | 0.008 | 0.014 | 0.2028 -> 0.2105 | 0.5770 -> 0.5770 |
| [`margate_hill_at_the_isle_edge.png`](acol/margate_hill_at_the_isle_edge.png) | street | 1,508,026 | 0.009 | 0.015 | 0.1966 -> 0.1966 | 0.6080 -> 0.6080 |
| [`cheesemans_farm_from_manston_road.png`](acol/cheesemans_farm_from_manston_road.png) | street | 1,475,906 | 0.009 | 0.016 | 0.2672 -> 0.2672 | 0.5195 -> 0.5195 |

## Other defects across the whole set

| # | defect | now |
|---|---|---|
| 1 | Magenta OSM debug overlay drawn over everything, depth-test free | **unchanged** — in all 45 frames; mean overlay fraction in the lower half of the road frames 0.0272 → 0.0274 |
| 2 | No textures anywhere | **unchanged** |
| 3 | Building facades unlit, reading as solid black | **unchanged** — clearest in `broadstairs/broadstairs_high_street` and `ramsgate/ramsgate_station_from_the_approach` |
| 6 | Beach-level cameras look across a flat plane with no beach under them | **unchanged** |
| 9 | Chalk cliffs smoothed away by the 1 m DTM; clifftop paths float as a stack of ribbon terraces with unlit black sides | **unchanged in kind, changed in detail** — `ramsgate/ramsgate_sands_and_the_east_cliff` and `cliftonville/walpole_bay_chalk_cliff_from_the_sands` still show the staircase; the treads are larger and more consolidated than at `7c8b4a6` because the ground came up closer to them |
| 10 | Car park: aisle ribbons drawn, no parking surface between them | **unchanged** — `westwood/westwood_cross_sheds_from_the_carpark`, tarmac 0.0611 → 0.0610. This is the one frame of the 31 with no road surface, and it is not the road defect |
| new | A footway crossing a carriageway where there is no junction record is still drawn straight across it | `broadstairs/st_peters_high_street`, mid-field right |

## What is still open after this snapshot

- The float gate is red by 0.06 points: `road_fusion_audit.py --float-max-frac 0.08` measures 0.080621 of stations with more than 0.125 m of daylight under the outer face. The clearance agent's own account (`Saved/Clearance/RESULT_v5.json`, `the_float_it_cost`) is that this is the fix and not a side effect — a road kerbed on one side now sinks its whole shoulder 0.15 m, and a footway drawn as a separate ribbon 2–6 m away is still draped on the survey. It is visible in this set as the black wedges under kerbs and paths, most obviously at `cliftonville/eastern_esplanade_seafront_terrace` and on the East Cliff.
- Ground still cuts into four road frames at range, worst at `birchington/railway_bridge_over_minnis_road`.
- The fixed viewpoint set has no camera chosen to frame a junction. That was the right set for the road defect; it is the wrong set for showing off the junction layer.
