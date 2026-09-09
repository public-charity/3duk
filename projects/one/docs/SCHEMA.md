# Streetscape interchange schema 1.0.0 — normative prose

Project One. This document and `projects/one/schema/streetscape.schema.json` are the contract between
`sources/adapters/unreal.py` (writer), the numpy/Blender core `projects/one/Tools/blender/streetscape/`
(reader) and the Unreal plugin `projects/one/Plugins/Streetscape` (reader and writer). Field names below
are the JSON keys exactly; the C++ property names are their PascalCase (`kerb_width_m` → `KerbWidthM`)
and are converted back mechanically (UE_PLAN.md 2.11). Where this document and the JSON Schema file
disagree, the JSON Schema file wins and this document has a bug.

Companion documents: DESIGN.md (why), UE_PLAN.md (C++ mirror), PIPELINE_CHANGES.md (adapter that
writes these files). Source designs: `docs/design/geometry.md` (the schema's origin) and
`docs/design/streetscape.schema.draft.json`, promoted here with the changes listed in §11.

---

## 1. Files

| File | Content | Written by | Read by |
|---|---|---|---|
| `projects/one/schema/streetscape.schema.json` | JSON Schema draft 2020-12 of a site document; `$defs/ProfileFile` for the library files | synthesis (this round) | validators, tests |
| `projects/one/schema/profiles/<id>.json` | one library profile: `{"kind": "road"\|"edge"\|"hedge", "id": "<id>", "profile": {...}}`, `id` == file name | synthesis; geometry task maintains | adapter (inlines the referenced ones), UE bootstrap (`ImportProfiles`), numpy `io_json.load_profile_file` |
| `projects/one/schema/examples/test_stretch.json` | the first-deliverable stretch (Trinity Square, Margate, Thanet frame) | synthesis | Blender build, UE `03_import_streetscape.py`, both test suites |
| `projects/one/schema/examples/synthetic_straight.json` | the `straight_100` numeric fixture | synthesis | `Tools/blender/tests/make_fixtures.py`, C++ Automation tests |
| `data/<site>/out/unreal/streetscape/site_x{i}_y{j}.json` | one site document per pipeline tile | adapter | UE `LoadSite(dir)`, Blender `build_all` |

The 20 library profiles: `road_trunk, road_primary, road_secondary, road_tertiary, road_residential,
road_unclassified, road_living_street, road_service, road_pedestrian, path_footway, path_cycleway,
path_track, rail_standard, edge_uk_kerb, edge_uk_half_grass, edge_barrier_only, edge_wall_brick,
edge_chain_link, edge_railing, hedge_privet`. Every id the adapter's class map can produce is in this
list (PIPELINE_CHANGES.md 13.6); the adapter refuses to run otherwise.

---

## 2. Conventions (normative)

1. **Frame.** `frame` is the const string `"local-metres, X east, Y north, Z up"`; a reader refuses
   any other value. `x = E − origin.E`, `y = N − origin.N`, `z` = ODN metres unchanged. Doubles.
   Nothing in a document is in Unreal units; the Unreal loader applies `(100x, −100y, 100z)` cm and
   reverses triangle winding once (BRIEF 4.2; UE_PLAN.md 2.11).
2. **Direction of travel** = increasing arc length `s`, from `points[0]` to `points[-1]`.
3. **Left / right.** With the unit horizontal tangent `t_h = (tx, ty, 0)`, the LEFT normal is
   `n_flat = Z × t_h = (−ty, tx, 0)`. The signed lateral offset `d` is **positive to the left**.
   `side = +1` is left, `−1` right; an outward per-side distance `o ≥ 0` maps to `d = side·o`.
   UK vehicles keep left, so the nearside kerb of the forward lane is at `d = +w/2`. Marking
   `offset_m` with `anchor: centre` is signed the same way; `roll_deg` is + when the left side is up.
4. **Arc length `s`** is measured along the resampled centreline (chord sum of the dense Catmull-Rom
   evaluation, §3.1). Every `s0_m`, `s1_m`, `s_m` means this `s`. `s1_m: null` means "to the end
   (`L`)". Any `s > L + 0.01` is a validation warning and is clamped to `L`.
5. **Heights.** `z_ref(s)` is the smoothed terrain height at the centreline and is the road crown.
   The road surface at lateral `d` is `z_ref + camber(d, w(s))`; the **road-edge level**
   `z_edge(s, side) = z_ref + camber(±edge_offset(side))` is the height reference `h = 0` of every
   Renderer B/C section on that side.
6. **Materials are names** (lower snake case, §7). Ids are per-buffer integers assigned in first-use
   order; engines map names to slots.
7. **UVs are metres**: `u = s`, `v =` metres across the section. Texture repeat is a material
   property (`materials.<name>.texture_repeat_m`), never baked into UVs.
8. **Determinism.** No randomness except the integer-hash noise of DESIGN.md 3.9, seeded from the
   profile. Same document + same heightfield → bit-identical buffers in numpy and in C++.
9. **Strictness.** Every object is `additionalProperties: false` except that keys beginning with
   `_` are notes and allowed everywhere. Readers reject unknown non-underscore keys (a typo must not
   become a default). C++ reads with `bStrictMode = true` equivalent (UE_PLAN.md 2.11).
10. **Ids** match `^[A-Za-z0-9_.:-]+$`. Spline ids are unique within a site. Adapter ids are
    `"<layer>:<osm_id>:<segment_index>"` (`roads:30253079:0`); junction ids `"junction:<i>_<j>:<k>"`;
    hand-authored splines use `"authored:<name>"`.
11. **Versioning.** `schema_version` is semver `1.x.y`. Readers accept any 1.x and ignore unknown
    *optional* fields only under `_`-prefixed keys. Adding an optional field bumps the minor version
    and updates the schema file in the same commit; renaming or re-meaning a field is 2.0.0.

---

## 3. The shared spline — how a document becomes stations (normative summary)

The full algorithm is DESIGN.md 3; the C++ port mirrors it function for function (UE_PLAN.md 2.5.4).
This section fixes what a schema reader must do with the numbers.

### 3.1 Curve

Centripetal Catmull-Rom (alpha 0.5, Barry–Goldman pyramid, knot spacing `|P_{i+1} − P_i|^0.5`,
phantom end points `P_{−1} = 2P_0 − P_1`, `P_K = 2P_{K−1} − P_{K−2}`), each segment evaluated at
`max(8, ceil(chord/0.1)) + 1` parameters; cumulative chord → `s`. **Before building**, consecutive
points with `|ΔP| < 1e-6 m` are merged (later point's `z`, `roll_deg`, `width_m`, `tags` win; tags
are unioned); the count goes to `Spline.warnings` / `stats.json:points_merged`. At least two distinct
points must remain, else a structural error. Two distinct points give a straight line. Step 06 rounds
vertices to 2 dp and writes the seam vertex twice per run (`sources/derive/06_build_networks.py:195`),
so adapter output contains such duplicates whenever thinning is off.

### 3.2 Stations

`κ_d = |dT/ds|` from consecutive unit tangents of the dense curve;
`step(κ) = clip(step_m / (1 + curvature_gain·κ), min_step_m, step_m)`;
march `s = 0; while s + step(κ(s)) < L − min_step_m: s += step(κ(s))`, then append `L`.

**Mandatory stations** (union, clamped to `(0, L)`): every waypoint's `s`; every `s0, s1, s0−ramp,
s1+ramp` of every scalar override; every `s0, s1` of every painted interval (barriers, embankments,
hedges, markings, profile switches); every drop kerb's `s−ramp, s, s+len, s+len+ramp`;
`sampling.extra_stations_m`. **Merge**: drop an adaptive station within `min_step_m/2` of a mandatory
one; union; sort.

Guarantees: `s[0] = 0`, `s[−1] = L`, strictly increasing; every mandatory station present as the exact
float given; no adaptive–adaptive gap below `min_step_m` or above `step_m`; the final gap before `L`
lies in `[min_step_m, step_m + min_step_m)` (the one place a gap may exceed `step_m`). A gap between a
mandatory station and an adjacent adaptive station may be as small as `min_step_m/2` (e.g. 71.83 →
72.0 on `straight_100`). Marking dash ends are **not** stations (§3.7).

### 3.3 Width and edge offset

`w(s) = interp(s, s_knots, w_knots)` (every point is a knot; missing `width_m` = profile `width_m`;
constant beyond the ends), then each `Segment.road.width_m` applies `apply_ramped_override` in file
order. `extra_left/right(s)` likewise from 0 via `edge_extra_left_m / edge_extra_right_m`.

**`edge_offset(side) = w/2 + extra(side)`** — the only definition of the kerb line. The road ribbon's
surface edge rows sit at `d = ±edge_offset(side)` (so a parking bay from `edge_extra_*` is carriageway
surface), its skirt rows at `±(edge_offset + overlap_m)`, and the kerb face at `edge_offset`. Both
renderers read the same array; no other code may compute `width/2`.

`apply_ramped_override(s, base, s0, s1, ramp, v)`: `[s0−ramp, s0]` lerp `base → v`; `[s0, s1]` = `v`;
`[s1, s1+ramp]` lerp `v → base`; ramps are clamped to `[0, L]`.

### 3.4 Roll

`roll_pl(s) = interp(s, s_knots[has_roll], roll[has_roll])`, mask `m(s) = interp(s, s_knots,
has_roll)` (1 at points that set `roll_deg`, 0 elsewhere). `roll_deg: null` counts as not set.

### 3.5 Heights

`z_raw = terrain.sample(x, y)` (NaN where none) → `fill_nan_along` (carry nearest valid forward then
backward; all-NaN → 0 + warning) → `moving_average_arclength(s, z, W, passes)` with
`hw_i = min(W/2, s_i − s_0, s_N − s_i)` (window shrinks symmetrically to zero at the ends, so end
heights are the raw terrain and two splines meeting at a node agree bit-for-bit) → `apply_pins`:
for each point with `z` set, `z += (z_pin − z_s(s_k))·max(0, 1 − |s − s_k|/pin_blend_m)`.

### 3.6 Bank

`h_probe = max(w/2, bank_probe_min_half_width_m)`; `β_raw = atan2(z(+h_probe·n_flat) − z(−h_probe·n_flat), 2h_probe)`
in degrees, NaN → 0; `β_t = clip(MA(β_raw, W, 1), ±bank_max_deg)`; `β = (1 − m)·β_t + m·roll_pl`;
then the **rate limit**: forward pass `β_i = clip(β_i, β_{i−1} ± r·Δs_i)`, backward pass
`β_i = clip(β_i, β_{i+1} ± r·Δs_{i+1})` with `r = bank_rate_max_deg_per_m`. Frames:
`n = n_flat·cos β + Z·sin β`, `b = t_h × n`. Every vertex is `p + d·n + h·b`.

### 3.7 Markings and the lift

Markings are strips swept over `spline.frames.insert(dash-end stations)` — interpolated frames, not a
re-sample — at `h = surface_h(c ± w_m/2) + lift_m`. At an **interpolated** station the strip vertex
height is evaluated on the actual road triangle pair under it (barycentric on the quad
`(V_{i,k}, V_{i+1,k}, V_{i+1,k+1}, V_{i,k+1})` split on the `V_{i,k}–V_{i+1,k+1}` diagonal), so every
marking vertex is exactly `lift_m` above the road mesh. Between vertices the road may bulge above a
straight marking edge by at most `|T|/4` where `T` is the quad twist, `|T| ≈ (row spacing)·sin(Δβ)`.
With `lateral_station_spacing_m 1.0`, `step_m 2.0` and `bank_rate_max_deg_per_m 0.25` the bank
changes ≤ 0.5° per station → `|T|/4 ≤ 2.2 mm`; the parabola sagitta over a 1 m chord is ≤ 1.04 mm
(`w = 6`); worst case 3.2 mm < `lift_m` 0.004 → clearance ≥ 0.8 mm; typical clearance is the full 4 mm.
This is why `lift_m` defaults to 0.004 and why the rate limit exists (DESIGN.md 4.1, 18).

---

## 4. Field by field

Column key — *W*: who writes it (A = adapter always, A? = adapter when known, H = hand-authored /
tests, U = UE `SaveSite` round-trips it). Everything is read by both the numpy core and the UE loader
unless the row says otherwise. Defaults apply when the key is absent.

### 4.1 Document header

| field | type / unit | range | default | W | meaning |
|---|---|---|---|---|---|
| `schema_version` | string | `^1\.\d+\.\d+$` | required | A H U | `"1.0.0"` |
| `site` | string | ≥ 1 char | required | A H U | `thanet`, `margate`, or a fixture name |
| `crs` | string | `^EPSG:\d+$` | required | A H U | `EPSG:27700` |
| `origin` | `{E, N}` numbers | — | required | A H U | grid SW corner, CRS metres; UE refuses a mismatch with the site actor |
| `vertical_datum` | string | — | required | A H U | `ODN` |
| `frame` | const string | — | required | A H U | `"local-metres, X east, Y north, Z up"` |
| `generator` | string | — | required | A H U | `sources/adapters/unreal.py@<sha>` / `hand-authored (...)` / `Plugins/Streetscape SaveSite@0.1` |
| `materials` | `{name: MaterialHint}` | — | `{}` | H A? | preview hints only |
| `profiles` | `{road:{}, edge:{}, hedge:{}}` | all three maps required | required | A H U | every profile referenced by the document's splines, inline |
| `splines` | `Spline[]` | — | required | A H U | |
| `junctions` | `Junction[]` | — | `[]` | A H U | the document's surfaced junctions; §4.18 |

Per-tile adapter documents additionally carry `_tile: {x, y, tile_m, bounds_local: [x0, y0, x1, y1]}`
and `_profile_ids_used: {road: [], edge: [], hedge: []}` as notes.

### 4.2 `MaterialHint`

| field | type | range | default |
|---|---|---|---|
| `base_color` | `[r, g, b]` linear | 0..1 | — |
| `roughness` | number | 0..1 | — |
| `two_sided` | boolean | — | false |
| `texture_repeat_m` | m > 0 | — | — |

### 4.3 `Sampling` (all optional; precedence `spline.sampling` > `RoadProfile.sampling_defaults` > built-in)

| field | unit | range | road default | rail default | meaning |
|---|---|---|---|---|---|
| `step_m` | m | > 0 | 2.0 | 1.0 | straight-line station spacing; chord sagitta at R = 200 m is 2.1 mm (road), 0.3 mm at R = 300 m (rail) |
| `min_step_m` | m | > 0 | 0.25 | 0.25 | adaptive floor and merge tolerance (`/2`) |
| `curvature_gain` | m | ≥ 0 | 20 | 60 | R = 20 m road → 1.0 m; R = 300 m rail → 0.83 m |
| `smoothing_window_m` | m | ≥ 0 | 20 | 40 | full width W of the arc-length moving average; bias on a vertical curve is `W²/(24 R_v)` = 2.6 cm at R_v = 650 m |
| `smoothing_passes` | int | 0..4 | 1 | 2 | 2 = triangular kernel |
| `width_ramp_m` | m | > 0 | 5.0 | 5.0 | default ramp of scalar segment overrides (1:5 build-out) |
| `bank_max_deg` | deg | 0..30 | 4.0 | 6.0 | 4° ≈ 7 % max superelevation; rail 150 mm cant ≈ 5.7° |
| `bank_probe_min_half_width_m` | m | > 0 | 1.5 | 1.5 | probe outside a 1 m DTM pixel |
| `bank_rate_max_deg_per_m` | deg/m | ≥ 0 | 0.25 | 0.25 | twist limit, §3.7; 4° develops over 16 m |
| `pin_blend_m` | m | > 0 | 10.0 | 10.0 | pin blend half-width |
| `extra_stations_m` | m[] | ≥ 0 | `[]` | `[]` | extra mandatory stations |

### 4.4 `RoadProfile`

| field | type / unit | range | default | meaning |
|---|---|---|---|---|
| `kind` | `road` \| `rail` | — | required | `rail` requires `rail` |
| `lanes` | int | ≥ 0 | — | informational |
| `lane_widths_m` | m[] | > 0 | — | informational; warning if sum > `width_m` |
| `width_m` | m | ≥ 0 | required | base of `w(s)`; rail: ballast top width |
| `surface_material` | name | — | required | |
| `camber` | `Camber` | — | required | §4.5 |
| `overlap_m` | m | 0.03..0.10 | 0.04 | skirt past the kerb line; schema floor 0.03 |
| `skirt_drop_m` | m | 0..0.03 | 0.02 | skirt drop over `overlap_m`; must be < `EdgeProfile.tuck_depth_m` |
| `lateral_station_spacing_m` | m | > 0 | 1.0 | `n_int = max(7, 2·ceil(w_max/(2·this)) + 1)`, `w_max = max_s(edge_offset_L + edge_offset_R)` |
| `markings` | `Marking[]` | — | required (may be `[]`) | |
| `rail` | `RailSpec` | — | required iff `kind = rail` | §4.7 |
| `sampling_defaults` | `Sampling` | — | — | rail profiles set the rail column of §4.3 |

### 4.5 `Camber`

| field | type | range | default | meaning |
|---|---|---|---|---|
| `kind` | `parabolic` \| `planar` \| `none` | — | required | parabolic `h(d) = −c(2d/w)²`; planar `h(d) = −(crossfall/100)·|d|`; none 0 |
| `crossfall_pct` | % | 0..10 | — | parabolic: `c = crossfall/100 · w/4` (edge slope = crossfall) |
| `camber_m` | m | ≥ 0 | — | explicit crown; overrides `crossfall_pct` |

`w = 6`, 2.5 %: `c = 0.0375 m`; planar edge drop 0.075 m.

### 4.6 `Marking`

| field | type / unit | range | default | meaning |
|---|---|---|---|---|
| `id` | Id | — | — | mesh group `marking:<id>` |
| `anchor` | `centre` \| `edge_left` \| `edge_right` | — | `centre` | centre: `offset_m` signed (+ left). edge_*: `offset_m ≥ 0` inward from that edge |
| `offset_m` | m | — | required | strip centre (double: pair centre) |
| `width_m` | m | > 0 | required | one line |
| `pattern` | `solid` \| `dashed` \| `double` \| `none` | — | required | |
| `dash_m`, `gap_m` | m | > 0 | required for dashed | dash k = `[phase + k(dash+gap), … + dash]` |
| `phase_m` | m | — | 0 | global along `s` |
| `double_gap_m` | m | > 0 | required for double | clear gap between the two lines |
| `material` | name | — | required | |
| `lift_m` | m | 0..0.02 | 0.004 | §3.7 |
| `s0_m`, `s1_m` | m / null | ≥ 0 | whole spline | optional range |

Effective centre per station: `centre → offset_m`; `edge_left → +edge_offset_L(s) − offset_m`;
`edge_right → −edge_offset_R(s) + offset_m`. Reference snippets (`centre_1004`, `warning_1004_1` and
`edge_left_1012_1` / `edge_right_1012_1` are carried by `profiles/road_*.json`; `dyl_left_1018_1` by the two
examples; `lane_1005` and `syl_left_1017` are canonical parameterisations for hand-authored profiles):

```
centre_1004      centre     0.00  0.10 dashed 4.0/2.0  white_paint
warning_1004_1   centre     0.00  0.10 dashed 6.0/3.0  white_paint
lane_1005        centre     3.65  0.10 dashed 2.0/7.0  white_paint
edge_left_1012_1 edge_left  0.20  0.15 solid           white_paint
dyl_left_1018_1  edge_left  0.25  0.10 double gap 0.10 yellow_paint
syl_left_1017    edge_left  0.25  0.10 solid           yellow_paint
```

### 4.7 `RailSpec`

| field | type / unit | default | meaning |
|---|---|---|---|
| `gauge_m` | m > 0 | required (1.435) | inner faces of the rail heads; rail centrelines at `±(gauge_m/2 + head_width_m/2)` = ±0.75243 |
| `pad_m` | m ≥ 0 | 0.005 | rail foot above sleeper top |
| `rail` | `RailSection` | required | `profile_id?`, `height_m 0.15875`, `head_width_m 0.06985`, `foot_width_m 0.1397`, `web_thickness_m 0.020`, `head_depth_m 0.045`, `foot_thickness_m 0.011`, `material` |
| `sleeper` | `Sleeper` | required | `length_m 2.5`, `width_m 0.25`, `height_m 0.15`, `pitch_m 0.65`, `phase_m 0`, `embed_m 0.10`, `mode instances\|merged`, `material` |
| `ballast` | `Ballast` | required | `shoulder_slope 1.5` (horizontal per 1 vertical), `depth_m 0.45`, `material`. **The ballast top width is `RoadProfile.width_m`** (3.4); the draft's `top_width_m` was removed as a duplicate |

### 4.8 `EdgeProfile` (side-agnostic)

| field | type / unit | range | default | meaning |
|---|---|---|---|---|
| `kerb_width_m` | m | ≥ 0 | required | 0 = no kerb block |
| `kerb_height_m` | m | ≥ 0 | required | upstand above the road edge |
| `lip` | `Lip` | — | radius 0.02, 3 pts | `{kind: radius\|chamfer\|none, size_m, arc_points 1..8}`; scales with the drop factor |
| `pavement_width_m` | m | ≥ 0 | required | 0 = no pavement |
| `pavement_crossfall_pct` | % | 0..10 | 2.5 | rises away from the kerb |
| `pavement_max_crossfall_pct` | % | 0..20 | 8.0 | back-edge dip limit at drop kerbs |
| `tuck_depth_m` | m | ≥ 0 | 0.03 | kerb block starts this far below the road edge |
| `tuck_in_m` | m | ≥ 0 | 0.02 | underside reaches this far under the road |
| `skirt_m` | m | ≥ 0 | 0.30 | back face down to −0.30 |
| `materials` | `{kerb, pavement}` | — | required | |
| `split_material` | `SplitMaterial` | — | disabled | `{enabled, inner, outer, boundary_frac 0.5}`; flush by construction |
| `drop_kerbs` | `DropKerb[]` | — | `[]` | baseline list |
| `barriers` | `BarrierSegment[]` | — | `[]` | baseline list |
| `embankments` | `Embankment[]` | — | `[]` | baseline list |

Library profiles keep the three lists empty except `edge_wall_brick`, `edge_chain_link` and
`edge_railing`, which carry one whole-length barrier (`s0_m 0, s1_m null`). `edge_barrier_only` has no
kerb, no pavement and an empty list: the spline's `Segment.edge.barrier` supplies the barrier.

### 4.9 `DropKerb` and `SplineDropKerb`

| field | unit | range | default | meaning |
|---|---|---|---|---|
| `side` (spline-level only) | `left`\|`right`\|`both` | — | required | |
| `s_m` | m | ≥ 0 | required | **start of the flat run**; down-ramp `[s_m − ramp_m, s_m]`, up-ramp `[s_m + length_m, s_m + length_m + ramp_m]` |
| `length_m` | m | ≥ 0 | 1.83 | flat run (two 915 mm units) |
| `ramp_m` | m | > 0 | 0.915 | each ramp; `smoothstep(t) = t²(3 − 2t)` |
| `target_height_m` | m | 0..0.2 | 0.006 | upstand in the flat run (0.006 pedestrian, 0.025 vehicle, 0 flush) |

Drop factor `f = max_k f_k(s)`; `hk = kh(1 − f) + target·f`; lip size scales `hk/kh`; back edge
`hk_back = min(kh + pw·cf, hk + pw·max_cf)`. Defaults: ramp midpoint `hk = 0.0655`, flat run 0.006,
back edge dips to 0.150 (from 0.170) with `pw = 1.8`.

### 4.10 `BarrierSegment` / `BarrierInline` and `BarrierType`

`type ∈ brick_wall | stone_wall | concrete_wall | retaining_wall | chain_link | wood_fence | railing |
guard_rail | none`.

| field | unit | default | applies to | meaning |
|---|---|---|---|---|
| `s0_m`, `s1_m` | m / null | required on `BarrierSegment` (profile list) only; `BarrierInline` takes them from the enclosing `Segment` | all | |
| `height_m` | m > 0 | required unless none | all | top above the base |
| `thickness_m` | m > 0 | required unless none | all | wall thickness; fences: panel plane at `thickness_m/2` |
| `material` | name | required unless none | all | never a raw OSM value |
| `coping_material` | name | `coping_concrete` | walls | |
| `coping_overhang_m` | m | 0.025 | walls | |
| `coping_height_m` | m | 0.05 | walls | |
| `post_pitch_m` | m > 0 | required | chain_link, wood_fence, railing, guard_rail | `n = floor(Δ/p) + 1 + [frac(Δ/p) > 0.5]` posts: `s0 + j·p` for `j < n − 1`, the last at `s1` (so a fence always ends on a post). `[45, 100]`, pitch 3 → 19 posts at 45, 48, …, 96, 100 |
| `post_size_m` | m | 0.06 | fences/railings | round diameter (chain_link, wood_fence) or square side (railing, guard_rail) |
| `post_material` | name | `post_steel` | fences/railings | |
| `rails_m` | m[] | railing `[H − 0.02, 0.5H, 0.10]`; guard_rail `[0.75, 0.55]` | railing, guard_rail | horizontal rail heights |
| `rail_size_m` | m | 0.04 | railing, guard_rail | square rail side |
| `offset_m` | m | 0 | all | inner face from the base line (pavement back edge), outward + |
| `skirt_m` | m | 0.30 | walls | extension below the base |

Base line: `o_b = edge_offset + kerb_width_m + pavement_width_m + offset_m`; base height: pavement
back edge (`h0 + hk_back`; `h0 + hk` if `pw = 0`; `h0` if `kw = pw = 0`). Geometry per type is
DESIGN.md 4.2.

### 4.11 `Embankment` / `EmbankmentInline`

`s0_m`, `s1_m` (m / null, required on `Embankment` — the profile list — only; `EmbankmentInline` takes
them from the enclosing `Segment`), `side ∈ left|right|both|downhill|uphill|auto` (required),
`kind ∈ batter|retaining_wall|auto` (required), `slope_ratio 1.5`, `wall_thickness_m 0.30`,
`wall_coping_m 0.10`, `threshold_m 0.35`, `toe_extra_m 0.30`, `material` (required).
`dz = z_back_edge − terrain(back edge)`; batter where `dz > threshold`, retaining wall where
`dz < −threshold`.

### 4.12 `HedgeProfile`, `HedgeSegment`, `Foliage`

| field | unit | default | meaning |
|---|---|---|---|
| `width_m`, `height_m` | m | required (0.8, 1.5 privet) | volume `W × (H + base_sink_m)` |
| `top_profile` | `flat`\|`rounded`\|`domed` | required | |
| `corner_radius_m` / `corner_points` | m / int 1..8 | 0.15 / 4 | |
| `noise_amplitude_m` / `noise_scale_m` / `noise_seed` | m / m / int | 0.06 / 0.6 / 1 | value-noise displacement, DESIGN.md 3.9 |
| `base_sink_m` | m | 0.10 | below the pavement back-edge level |
| `material` | name | required | |
| `foliage` | `{mode none\|cards\|instances, density_per_m2 12, card_size_m 0.25, material, mesh_id, seed 1}` | required | |
| `segments` | `HedgeSegment[]` `{s0_m, s1_m, offset_m 0.1, height_override_m?, width_override_m?}` | required (`[]` in the library) | a hedge exists only where a HedgeSegment or a `Segment.hedge.present: true` covers `s` |

`offset_m` is the gap between the **barrier line** (outer face of the barrier in force at `s`, else the
pavement back edge) and the hedge's inner face — this is how a hedge stacks beside a wall without
knowing its geometry.

### 4.13 `Spline`

| field | type | default | W | meaning |
|---|---|---|---|---|
| `id` | Id | required | A H U | |
| `source` | `Source` | required | A H U | §4.15 |
| `profile_ids` | `ProfileIds` | required | A H U | **all five keys required**: `road, edge_left, edge_right, hedge_left, hedge_right`, each Id or null |
| `points` | `Point[]` ≥ 2 | required | A H U | §4.14 |
| `sampling` | `Sampling` | inherit | A? H U | adapter writes it only for the test-stretch style overrides; normally absent |
| `segments` | `Segment[]` | `[]` | A H U | §4.16 |
| `drop_kerbs` | `SplineDropKerb[]` | `[]` | H U | adapter emits none this round |
| `overlay` | `Overlay` | — | A H U | required in practice when `source.layer ≠ authored` (semantic warning) |
| `junction_start`, `junction_end` | Id / null | null | A H U | normative: that end is trimmed back to the junction's trim radius, §4.18 |
| `continues_from`, `continues_to` | Id / null | null | A U | seam / way / gap neighbour |
| `continuation_kind` | `Continuation` = `{from, to}` each `seam`\|`way`\|`gap`\|null | — | A U | seam: same way continues in the adjacent tile; way: another way starts/ends at this node with no junction disc; gap: same way continues after an off-grid / off-clip excursion |
| `overrun_points` | `OverrunPoints` = `{before, after}` each `XYZ` `[x,y,z]`\|null | — | A U | neighbour's second point, so end tangents match without loading the neighbour's document |
| `flags` | `Flags` | all false / null | A U | `bridge, tunnel, z_gap, steps, disused, gauge_unmapped, closed_loop, tracks` |

`profile_ids.road = null` → no carriageway: `w(s) = 0`, `edge_offset = extras only`, camber none (OSM
barrier ways). `edge_<side> = null` → nothing on that side.

### 4.14 `Point`

| field | type / unit | range | default | meaning |
|---|---|---|---|---|
| `x`, `y` | m | — | required | local metres |
| `z` | m / null | — | absent | **pin** (forces the smoothed height, blended over `pin_blend_m`). The adapter never sets it this round; the step-06 drape goes into `_z_06` and `overlay.pts[*][2]` |
| `roll_deg` | deg / null | −30..30 | absent | bank override, + = left up; not clamped by `bank_max_deg` |
| `width_m` | m | ≥ 0 | profile `width_m` | width knot |
| `tags` | string[] | — | `[]` | `junction:<id>` only convention |

### 4.15 `Source`

`layer ∈ roads|rail|barriers|authored` (required); `osm_id` string|null; `osm_ids` string[] (hand-authored
merges); `name`; `cls`; `tags` `{key: string}` (strings only, absent tags omitted); `tile [i, j]`;
`segment_index` (0 = the run containing the way's first vertex); `segment_count`.

### 4.16 `Segment`, `SegmentRoad`, `SegmentEdge`, `SegmentHedge`

| field | type | default | meaning |
|---|---|---|---|
| `id` | Id | — | |
| `s0_m`, `s1_m` | m / null | required | |
| `side` | `left`\|`right`\|`both`\|`centre` | required | `centre` reads only `road` |
| `ramp_m` | m ≥ 0 | `sampling.width_ramp_m` | scalar ramps |
| `road` | `{width_m?, profile_id?, edge_extra_left_m?, edge_extra_right_m?, markings?, markings_add?}` | — | `markings` replaces, `markings_add` appends |
| `edge` | `{profile_id?, kerb_width_m?, kerb_height_m?, pavement_width_m?, pavement_crossfall_pct?, split_material?, barrier?: BarrierInline\|null, embankment?: EmbankmentInline\|null}` | — | `null` block paints "none" |
| `hedge` | `{present (required), profile_id?, offset_m?, height_m?, width_m?}` | — | |

Resolution rules are §5.

### 4.17 `Overlay`

`kind ∈ osm_way|step06_smoothed|other`; `pts` `[[x, y(, z)], …]` ≥ 2 (raw OSM vertices, clipped to
the grid and the clip half-plane by the adapter, PIPELINE_CHANGES.md 13.9); `osm_id`. Both engines
re-drape the overlay on their terrain source and lift it **0.3 m** (DESIGN.md 5.5); the file's `z` is
informative.

### 4.18 `Junction`

`{id, x, y, z: number|null, radius_m, trim_radius_m: number|null, kind: disc|none,
ends: [{spline_id, end: start|end}]}`. Step 06 `_junction` records map to `kind: disc`,
`radius_m = r`; `ends` lists the splines of the same document whose first/last point is within
`junction_snap_m` = 0.3 m (measured maximum on Thanet: 0.257 m over 5,185 ends).

**`kind`** is the switch. `disc`: the junction is SURFACED — the shared spline layer trims every arm
in `ends`, Renderer A fills the hole with one tarmac patch and Renderer B turns the kerb corner
between adjacent arms. `none`: a plain node — nothing is trimmed and nothing is filled. A junction
with fewer than three surviving arms is treated as `none` (two splines meeting end to end already
share their end point; there is nothing to fill).

**One field was added and it is an override, not a stored derivation.** `trim_radius_m` is null in
every adapter document and should stay null: everything a renderer needs beyond the fields above is
DERIVED from the arms themselves, so it cannot go stale when a profile width changes. What is derived,
and how:

| derived | from |
|---|---|
| which arms, and in what order | `ends`, ordered by the bearing of each arm's outward tangent at its trim station |
| the arm's half-extent `e` | `max(edge_offset(left), edge_offset(right)) + overlap_m` at the trim station — the outer edge of the ribbon's skirt row, i.e. where the carriageway actually ends in plan |
| the trim radius `d` | below |
| the arm's trim station | the first arc length, scanning inward from that end, at which the centreline reaches plan distance `d` from `(x, y)` |
| the patch boundary | each arm's own ribbon end row, joined by the corner fillets |
| the patch's material and apex height | the arms' own `surface_material` and `z_ref` |
| the kerb corner radius | the fillet tangent to both kerb lines at the two trim ends (no stored radius) |

**The trim radius.** Order the arms by `phi_i`, the bearing of the arm's TRIM POINT about the node
(not of its tangent: on a spline that curves near its end the tangent swings far faster than the node
direction, and solving on it makes the fixed point oscillate). At radius `d` an arm of half-extent `e`
subtends an angular half-width of about `atan(e / d)` there — measured exactly, as the larger deviation
of the arm's two skirt corners from `phi_i`. Requiring each arm to take at most half of each of its two
adjacent gaps makes neighbouring arms disjoint in bearing, which is what stops a wide road leaving a
notch across a narrow one. With `D_i` the smaller of arm *i*'s two adjacent gaps and
`clearance_deg = 2°` (an arm already inside its share of both gaps asks for no change at all):

```
requirement_i = e_i / tan((D_i - clearance) / 2)         (0 when the gap is >= 180 deg)
d             = clamp(max over arms of requirement_i, radius_m, max_trim_radius_m = 20 m)
d_i           = min(d, max(radius_m, max_trim_frac_of_length * L_i))
```

The maximum is taken over the arms, not per arm, because a junction has one size: a 12 m trunk
crossing a 4 m lane makes a big junction for both of them. Two escapes stop that being destructive.
An arm whose requirement exceeds `max_trim_radius_m` is **unseparable** — two OSM ways can leave the
same node 2° apart, and separating those would need `e / tan(1°)` ≈ 340 m of trim to fix an overlap
that exists along the whole length of both arms anyway — so it is dropped from the maximum and
recorded rather than driving it. And no arm gives up more than `max_trim_frac_of_length` = 0.5 of its
own spline to one junction. Because `e` is read at the trim station and the trim station depends on
`d`, the solve is a fixed-point iteration from `d = radius_m`, run to convergence (a change below
1e-9 m) within `JunctionPlan.ITERS` = 8 passes; it converges in one pass wherever the width is
constant near the end.

**The trim is a mask on `s`, never a re-basing.** `s` is the document's own coordinate — every
`Segment.s0_m/s1_m`, marking interval, drop kerb, barrier run and hedge run is expressed in it — so
re-basing would silently move every authored `s`, would have to be mirrored in the adapter and in the
C++ port, and would make `length_m` mean something different from the document. Masking changes only
which stations are *emitted*: `length_m` and the station array are unchanged, and **both trim stations
are added to the mandatory set** (§3.2) so they exist exactly and every renderer sees the same extent.
A spline trimmed at both ends keeps at least `min_remaining_m` = 1 m; when the two trims would leave
less, both are scaled by one common factor so it shortens symmetrically instead of vanishing or
inverting, and the arms are re-derived at the scaled trims so the patch still meets the ribbon exactly.
A spline shorter than `min_remaining_m` is not trimmed at all.

**Geometry-core defaults** (`schema.JUNCTION_DEFAULTS`; not document fields, and the C++ port carries
the same numbers): `snap_m` 0.3, `clearance_deg` 2.0, `max_trim_radius_m` 20.0, `min_remaining_m` 1.0,
`max_trim_frac_of_length` 0.5, `corner_step_deg` 10.0, `corner_handle_frac` 0.45.

**What the renderers do with it.** Renderer A stops the ribbon at the trim and, in the SAME buffer with
the SAME material, emits the patch as a fan from the node to a boundary made of each arm's own ribbon
end row plus the corner fillets offset outward by `overlap_m` and dropped by `skirt_drop_m`; the apex
sits at the highest arm crown, so the patch is a surface that meets each arm at that arm's level rather
than a disc at one z. Renderer B stops the kerb at the same trim and sweeps the same kerb section along
the same fillet, so the road overhangs the corner kerb by the same `overlap_m` it does along a
straight. Group names: `junction:<id>` on the road buffer, `corner_kerb:<id>:<k>` and
`corner_pavement:<id>:<k>` on the edge buffer. Those prefixes are excluded from every `(s, d, h)`
measurement (`mesh.NON_STATION_PREFIXES`) because they are not swept along the spline.

### 4.19 `ProfileFile`

`{kind: road|edge|hedge, id, profile}`; `profile` is validated as `RoadProfile` / `EdgeProfile` /
`HedgeProfile` by `kind`. A `rail_standard` file is `kind: "road"` with `profile.kind: "rail"`.

---

## 5. Resolution rules (profiles + segments → per-side timelines)

Computed **before** sampling (they contribute mandatory stations) by `schema.resolve_road(spline, site)
→ RoadTimeline` and `schema.resolve_side(spline, side, site) → SideTimeline`; C++
`FStreetRoadTimeline::Resolve`, `FStreetSideTimeline::Resolve` (UE_PLAN.md 2.5.6).

1. Start from `profile_ids.<slot>` (null → an empty profile with every width 0).
2. **Scalars** (`kerb_width_m`, `kerb_height_m`, `pavement_width_m`, `pavement_crossfall_pct`, road
   `width_m`, `edge_extra_*`, hedge `height/width/offset`) are functions of `s`: baseline = profile
   value (road width: the point-knot function); each applicable segment, in file order, applies
   `apply_ramped_override` over `[s0−ramp, s1+ramp]`. Later segments win.
3. **Profile switches** (`edge.profile_id`, `road.profile_id`) replace the lists and materials inside
   `[s0, s1]` exactly at the stations and act as ramped scalar overrides for the scalar fields.
   Camber kind and `overlap_m`, `skirt_drop_m`, `surface_material`, `lateral_station_spacing_m` are
   taken from the road profile in force **per station** (camber kind switches exactly at `s0/s1`;
   `crossfall_pct` / `camber_m` ramp like scalars). **`kind` must be identical across all road profiles
   painted on one spline** (validation error otherwise): a spline is either a road or a rail.
4. **Lists** (`barriers`, `embankments`, hedge `segments`, `markings`) are resolved by interval painting:
   breakpoints `{0, L} ∪ all s0/s1`; the value in force on each interval is the last layer covering it,
   layers ordered profile list (file order) then spline segments (file order). `"barrier": null` paints
   "none". `markings` replaces, `markings_add` appends.
5. **Drop kerbs**: union of the profile's `drop_kerbs[]` and the spline's `drop_kerbs[]` filtered by
   side (`both` → both). Overlapping drop kerbs combine by `max` of their factors.
6. `s1_m: null` → `L`; `s > L + 0.01` warns and clamps.

The same `SideTimeline` evaluated on the stations (`SideSpec`) is handed to Renderer B **and**
Renderer C — that is how the hedge "reads the same segment list as B".

---

## 6. Adapter conventions for real sites

- One document per pipeline tile: `data/<site>/out/unreal/streetscape/site_x{i}_y{j}.json`, with
  `profiles` inlined (only referenced ids), `_tile`, `_profile_ids_used`.
- `id = "<layer>:<osm_id>:<segment_index>"`; `source.layer ∈ roads|rail|barriers`; `source.tags` from
  `unreal.json streetscape.tags_passthrough`, stringified, absent omitted.
- Roads: `profile_ids.road` from `road_profile_by_class[cls]`; `edge_left/right` = `edge_uk_kerb` per
  the sidewalk rule (PIPELINE_CHANGES.md 13.6) or null; one whole-spline `Segment {s0_m 0, s1_m null,
  side both, edge {pavement_width_m: pav}}` when `pav ≠ 1.8`; `road {markings: []}` in the same segment
  when `lane_markings = no`.
- Barriers: `profile_ids.edge_left = edge_barrier_only`, everything else null, one `Segment {side left,
  edge {barrier {type, height_m: h, thickness_m, material, post_pitch_m, offset_m: −thickness_m/2}}}`.
  Hedges: `hedge_left = hedge_privet`, `Segment {side left, hedge {present true, height_m: h, width_m,
  offset_m: −width_m/2}}` — centred on the OSM way.
- Points: `{x, y, width_m (roads only), _z_06}` — never `z`, never `roll_deg`.
- `overlay {kind osm_way, osm_id, pts}` clipped to grid and clip; `continues_*`, `continuation_kind`,
  `overrun_points`, `flags` filled; `junctions` from `_junction` records.

---

## 7. Material names (normative set)

`tarmac, white_paint, yellow_paint, concrete_kerb, paving_slab, grass, gravel, brick_red,
coping_concrete, chain_link, post_steel, steel_painted_black, wood_fence, privet_leaf, ballast,
sleeper_concrete, rail_steel, stone_flint, concrete_wall, massing_grey`. The UE bootstrap creates one
`MaterialInstanceConstant` per name and `DT_StreetMaterials` keys are exactly these strings
(UE_PLAN.md 5.4); a name outside the set is a validation warning ("unhinted") and resolves to the
magenta fallback in UE. Adapter barrier types map to materials: brick_wall → `brick_red`,
stone_wall → `stone_flint`, concrete_wall / retaining_wall → `concrete_wall`, chain_link → `chain_link`,
wood_fence → `wood_fence`, railing / guard_rail → `steel_painted_black`.

---

## 8. Validation

*Structural* (`io_json.validate_structure`, `FStreetscapeJson::ValidateStructure`, no geometry):
required keys, types, enums, ranges as in the schema file; `frame` const; `schema_version` 1.x;
every `profile_ids.*` and `Segment.*.profile_id` resolves inside the document; `s0_m < s1_m` when
`s1_m` is not null; `boundary_frac ∈ [0, 1]`; dashed markings carry `dash_m, gap_m`; doubles carry
`double_gap_m`; rail profiles carry `rail`; barrier requirements per type; every material name in §7
(else warning "unhinted"). A test loads `examples/test_stretch.json`, `examples/synthetic_straight.json`
and the adapter fixture output through the same validator (numpy: `test_io_json.py`; C++:
`Streetscape.Json.SchemaFixtures`).

*Semantic* (after building): `s ≤ L + 0.01` (warn + clamp); `sum(lane_widths_m) ≤ width_m` (warn);
overlapping same-side segments (info); `overlap_m ≥ 0.03` and `tuck_depth_m > skirt_drop_m` (error);
one road `kind` per spline (error); `overlay` missing on a non-authored spline (warn); points merged
(warn, count).

---

## 9. Worked examples

### 9.1 `examples/test_stretch.json` — Trinity Square, Margate (abridged)

Thanet frame (`origin E 627680 N 163080`); Margate-origin local = these − 5120 in x and y; UE start
`(809998, −817112, 2056)` cm. One spline `authored:trinity_square`, 15 points (the adapter design's
13 Douglas-Peucker points plus the two taper knots), east → west, left = south (the square).

```json
"profile_ids": {"road": "road_trinity", "edge_left": "edge_uk_kerb", "edge_right": "edge_uk_kerb", "hedge_left": null, "hedge_right": "hedge_privet"},
"points": [{"x": 8099.98, "y": 8171.12, "width_m": 6.0, "tags": ["junction:j_trinity_east"]}, …,
           {"x": 7961.63, "y": 8158.53, "width_m": 6.0}, {"x": 7956.86, "y": 8158.91, "width_m": 6.479},
           {"x": 7951.68, "y": 8159.48, "width_m": 7.0}, …, {"x": 7930.69, "y": 8162.25, "width_m": 7.0}],
"sampling": {"step_m": 2.0, "min_step_m": 0.25, "curvature_gain": 20.0, "smoothing_window_m": 15.0, "smoothing_passes": 1, "width_ramp_m": 5.0, "bank_max_deg": 4.0, "bank_probe_min_half_width_m": 1.5, "pin_blend_m": 10.0, "bank_rate_max_deg_per_m": 0.25},
"segments": [
  {"id": "pavement_1p5",    "s0_m": 0.0,  "s1_m": null,  "side": "both",  "edge": {"pavement_width_m": 1.5}},
  {"id": "half_grass_left", "s0_m": 0.0,  "s1_m": 95.9,  "side": "left",  "edge": {"profile_id": "edge_uk_half_grass"}},
  {"id": "wall_right",      "s0_m": 0.0,  "s1_m": 45.0,  "side": "right", "edge": {"barrier": {"type": "brick_wall", "height_m": 1.2, "thickness_m": 0.215, "material": "brick_red", "coping_material": "coping_concrete", "coping_overhang_m": 0.025, "coping_height_m": 0.05, "offset_m": 0.0}}},
  {"id": "fence_right",     "s0_m": 45.0, "s1_m": 95.0,  "side": "right", "edge": {"barrier": {"type": "chain_link", "height_m": 1.2, "thickness_m": 0.05, "material": "chain_link", "post_pitch_m": 3.0, "post_size_m": 0.06, "post_material": "post_steel", "offset_m": 0.0}}},
  {"id": "hedge_right",     "s0_m": 55.0, "s1_m": 90.0,  "side": "right", "hedge": {"present": true, "offset_m": 0.4}},
  {"id": "railing_right",   "s0_m": 95.0, "s1_m": 140.0, "side": "right", "edge": {"barrier": {"type": "railing", "height_m": 1.0, "thickness_m": 0.05, "material": "steel_painted_black", "post_pitch_m": 2.0, "post_size_m": 0.05, "post_material": "steel_painted_black", "rails_m": [0.98, 0.5, 0.10], "rail_size_m": 0.04, "offset_m": 0.0}}}],
"drop_kerbs": [{"side": "right", "s_m": 38.8, "length_m": 3.0, "ramp_m": 0.9, "target_height_m": 0.0},
               {"side": "left",  "s_m": 75.0, "length_m": 1.83, "ramp_m": 0.915, "target_height_m": 0.006}],
"overlay": {"kind": "osm_way", "osm_id": "30253079", "pts": [[8099.98, 8171.12, 20.56], …, [7930.69, 8162.25, 18.09]]}
```

Profile `road_trinity` = `road_residential` + markings `centre_1004` (whole length) and
`dyl_left_1018_1` with `s0_m 0, s1_m 60`. Item by item of BRIEF 1.1 "first deliverable": width
6 → 7 m over `s` 140.2–150.2 (knots at 140.2 / 145.0 / 150.2; the kerb on both sides re-samples
`edge_offset` 3.0 → 3.5); TSRGD 1004 centre dashes; double yellows on the left for `s` 0–60 following
the edge; vehicle drop kerb on the right (flat 38.8–41.8, ramps 37.9–38.8 / 41.8–42.7, target 0)
through a standard kerb, and a pedestrian drop kerb on the left (flat 75.0–76.83) through the
half-grass kerb so both split materials ramp down; half-grass / half-tarmac kerb on the left for
0–95.9 with the flush boundary at `boundary_frac 0.5`; brick wall → chain-link → railing on the right
at 45 / 95 / 140 behind a 1.5 m pavement (base line `edge_offset + 0.125 + 1.5` = 4.625 m on the 6 m
section, 5.125 m after the taper); privet hedge 0.4 m behind the fence for 55–90 (inner face at
back edge + 0.05 + 0.4); heights from the Margate/Thanet DTM tile (15, 15) smoothed with W = 15 m
(expected profile: the `dtm_ma15_s_z` table of `docs/design/adapter_and_test_stretch.md` B6, e.g.
`z_ref(10) = 20.47`, `z_ref(100) = 19.35`, `z_ref(160) = 18.24` ± 0.02 m); the 11 raw OSM vertices
as overlay. Length `L = 171.40 ± 0.05 m` (the 06 polyline measures 171.39 m; the Catmull-Rom through
the 15 knots 171.41 m).

### 9.2 Rail example (the draft's worked example 2, restated)

```json
"profiles": {"road": {"rail_standard": <profiles/rail_standard.json .profile>}, "edge": {}, "hedge": {}},
"splines": [{"id": "authored:rail_example",
  "source": {"layer": "rail", "osm_id": "0", "name": "Chatham Main Line (example)", "cls": "rail", "tags": {"gauge": "1435", "electrified": "rail"}},
  "profile_ids": {"road": "rail_standard", "edge_left": null, "edge_right": null, "hedge_left": null, "hedge_right": null},
  "points": [{"x": 4000.0, "y": 5000.0}, {"x": 4060.0, "y": 5002.0}, {"x": 4120.0, "y": 5012.0}, {"x": 4175.0, "y": 5035.0}, {"x": 4220.0, "y": 5070.0}, {"x": 4255.0, "y": 5115.0}],
  "overlay": {"kind": "osm_way", "osm_id": "0", "pts": [[4000.0, 5000.0], [4120.0, 5012.0], [4255.0, 5115.0]]}}]
```

Nothing else is needed: rails, sleepers and ballast come out of `road.build_road` because the profile's
kind is `rail`; the ballast top is `width_m` 3.4 m, the shoulders reach `3.4 + 2·0.45·1.5 = 4.75 m`
at the toe; rail head inner faces are 1.435 m apart, rail centres 1.50485 m; rail top is
`(0.15 − 0.10) + 0.005 + 0.15875 = 0.21375 m` above the ballast top; sleepers at `floor(L/0.65) + 1`
stations; stations 1.0 m on straights and `1/(1 + 60/300) = 0.83 m` on an R = 300 m bend.

### 9.3 `examples/synthetic_straight.json` — the numbers every implementation must reproduce

Flat terrain `z = 10`; points `(0,0) w 6, (40,0) w 6, (50,0) w 8, (100,0) w 8`; `edge_uk_kerb` both
sides; left drop kerb `s_m 70` (defaults); markings `centre_1004` + `dyl_left_1018_1`; sampling
`2.0 / 0.25 / 20 / 20 / 1 / 5.0 / 4.0 / 1.5 / 10.0 / 0.25`.

| quantity | expected |
|---|---|
| stations `N` | **54** = 51 adaptive (0, 2, …, 100) + 3 drop-kerb stations not on the 2 m grid (69.085, 71.83, 72.745); 70, 40, 50 coincide with adaptive stations |
| gaps | min 0.17 (71.83 → 72.0, mandatory–adaptive), max 2.0; every adaptive–adaptive gap 2.0 |
| `w(45)` | 7.0 ± 1e-9; `w(40) = 6`, `w(50) = 8`; `w_max = 8` |
| ribbon rows | `n_int = max(7, 2·ceil(8/2) + 1) = 9` interior + 2 skirt = **11** rows |
| ribbon vertices / triangles (groups `road`, `skirt_*` only) | 11·54 = **594** / 2·10·53 = **1060** |
| overlap (`measure_lateral_overlap`) | min = max = **0.040** at all 54 stations, both sides |
| coincident distinct positions (`coincident_xy_pairs`, dedup 1e-9) in `[o0, o0 + 0.04]` | **2 per station** (road-edge row vs kerb rows B and C at `o = 0`) → 108 per side; 0 in `(o0 + 1e-6, o0 + 0.04]` |
| kerb rows | D, S, E flush (`max|Δz| < 1e-12`); B at `−0.03`; A at `o = −0.02` |
| drop kerb (left) | `hk(70.915) = 0.006 ± 1e-6` (flat-run centre); `hk(69.5425) = hk(72.2875) = 0.0655 ± 1e-6` (ramp midpoints); back edge F at 0.150 in the flat run |
| centre dashes | 17 dashes `[0,4] [6,10] … [96,100]`, ends within 1e-9; strip `vd ∈ {−0.05, +0.05}` |
| double yellow (left) | pair centre `o0 − 0.25`; line centres `o0 − 0.35`, `o0 − 0.15`; at `s = 45` (`w = 7`) every yellow vertex is 0.5 m further out than at `s = 40` |
| marking lift | every marking vertex `0.004 ± 1e-9` above the road mesh at the same `(s, d)` |
| height coherence | `road_edge_row.z − (z_ref + h0)` and kerb row B `+ 0.03` both `< 1e-9` |
| smoothing test (2 % grade + `0.1·√3·unit_noise(i, 7)`, W = 20, 51 stations) | interior (`s ∈ [10, 90]`) RMS factor **≥ 2.5** (measured 2.837); interior `max|err| ≤ 0.08` (0.0635); ends pinned; grade `0.0196 ± 0.002`; W = 10 factor ≥ 1.7 (1.942); two passes W = 20 ≥ 3.0 (3.308); 8 m ripple `0.1·sin(2πs/8)` RMS 0.0700 → ≤ 0.010 (0.0065) |
| `unit_noise(0..4, 7)` | `−0.33847302, 0.94551079, −0.62749659, 0.96820159, 0.64059920` (±1e-8) |
| `lowbias32` | `lowbias32(0) = 0`, `lowbias32(1) = 0x688990c0`, `lowbias32(2) = 0xd1132181`, `lowbias32(0xdeadbeef) = 0xe628c683` |

The other fixtures (`sine_5_50`, `curve_R20_200`, `rail_R300_600`) and their numbers are DESIGN.md 3.10;
`Tools/blender/tests/make_fixtures.py` writes all of them to `Tools/blender/tests/fixtures/` with
`expected.json`, which both test suites read.

### 9.4 The six junction fixtures — the numbers every implementation must reproduce

`synthetic.JUNCTION_BUILDERS` builds six documents, each one straight 60 m arm per bearing meeting at
one node with `radius_m = 4.0`, `road_test_marked` carriageways and `edge_uk_kerb` both sides on flat
`z = 10` terrain (`junction_slope` on a 6 % east / 3 % north grade). Frozen in
`fixtures/expected.json:junction`; asserted by `tests/test_junction.py:TestFrozenCounts`.

| fixture | bearings ° | widths m | `trim_radius_m` | boundary | patch v / t | corners | corner t | total v / t |
|---|---|---|---|---|---|---|---|---|
| `junction_crossroads` | 0 90 180 270 | 6 | **4.000000** | 70 | 71 / 70 | 4 | 760 | 5357 / 7838 |
| `junction_tee` | 0 90 180 | 6 | **4.000000** | 44 | 45 / 44 | 3 | 400 | 3899 / 5700 |
| `junction_five_arm` | 0 72 144 216 288 | 6 | **4.341570** | 95 | 96 / 95 | 5 | 1100 | 7197 / 10343 |
| `junction_skew` | 0 30 180 210 | 6 | **12.192774** | 70 | 71 / 70 | 4 | 760 | 4717 / 6870 |
| `junction_slope` | 0 90 180 270 | 6 | **4.000000** | 70 | 71 / 70 | 4 | 760 | 5357 / 7838 |
| `junction_widths` | 0 90 180 270 | 12 4 12 6 | **6.254603** | 82 | 83 / 82 | 4 | 760 | 5549 / 8258 |

Patch plan areas: 61.1172, 54.8786, 68.4125, 256.3222, 61.0966, 149.4264 m². `patch_verts` is
`boundary + 1` (the apex) and `patch_tris` is `boundary` — one fan triangle per boundary edge.

Where the radii come from (§4.18): crossroads / tee / slope ask for less than the record's own 4.0 m,
so the floor wins. `five_arm`: 72° gaps, `e = 3.04`, `3.04 / tan(35°) = 4.341570`. `skew`: 30° gaps,
`3.04 / tan(14°) = 12.192774` — the acute pair drives it, and it is inside the 20 m cap so the pair is
separated rather than declared unseparable. `widths`: the 12 m trunk, `e = 6.04`, at 90° gaps,
`6.04 / tan(44°) = 6.254603`, and the 4 m lanes are pushed back to the same radius because a junction
has one size.

Measured on all six: worst patch-to-ribbon gap **0.0 m**, worst kerb-to-corner gap **0.0 m**,
double-covered patch area **< 1e-11 m²**, road-over-kerb overlap **0.040 m** at every corner sample,
skirt drop **0.020 m**, and the corner deviates from the true circular fillet by less than
`2.7e-4 · r` (0.27 mm on the crossroads' 1.0 m corner) — the known error of the `(4/3)·tan(τ/4)` cubic
handle, two orders of magnitude inside the 40 mm overlap it sits in.

### 9.5 The whole isle — the acceptance command and what it last printed

The six fixtures freeze the arithmetic; this is the run that proves it survives real OSM. It builds
every one of the 246 adapter documents with its junctions and measures the finished buffers:

```sh
cd projects/one/Tools/blender
export PATH="/c/Users/Shadow/code/3duk-env/env/Library/bin:$PATH"
C:/Users/Shadow/code/3duk-env/env/python.exe -m streetscape.build \
    --junction-audit  ../../../../data/thanet/out/unreal/streetscape \
    --terrain         ../../../../data/thanet/out/unreal/landscape \
    --clearance-landscape ../../../../data/thanet/out/unreal/landscape_conformed \
    --out ../../Saved/Diag/junction_isle.json
```

`--terrain` is the **unconformed** landscape, because that is the ground the road drapes on
(`Tools/conform_landscape.py` header); `--clearance-landscape` is the **conformed** one, because that
is the ground the engine draws. Last run 2026-09-09 (`Saved/Diag/junction_isle.json`,
`Saved/Logs/junction_isle.log`), **409.7 s** wall clock:

| | |
|---|---|
| documents / junctions / patches built | 246 / 1,642 / **1,642** (none skipped: `junctions_skipped_kind` 0, `junctions_skipped_arms` 0, `arms_dropped` 0) |
| arms | 5,185 (3.16 per junction) |
| splines trimmed / ends trimmed | 4,087 / 5,168; **25,808.9 m** of carriageway removed, worst single end **20.484 m** |
| degraded rather than vanished | 234 splines had both trims scaled by one common factor to keep `min_remaining_m`; 15 were shorter than 1 m and were not trimmed at all; **0 inverted, 0 vanished** |
| **worst patch-to-ribbon gap** | **0.0 m** — exactly zero, over all 5,185 arm end rings |
| **worst kerb-to-corner gap** | **6.1e-12 m** (float noise on a 10,869 m coordinate) |
| kerb corners | 3,451 built, 1,734 skipped because neither arm carries a kerb (two paths meeting), **0 skipped as incompatible** |
| patch mesh | 87,969 vertices, 86,327 triangles, 137,840.2 m² of new tarmac; corners add 498,830 triangles |
| fan double cover | 3,377.3 m² of 137,840.2 (**2.45 %**), worst junction 46.2 m²; 322 of 1,642 boundaries non-monotone; 139 arms unseparable (two ways leaving one node inside `clearance_deg`) |
| patch above the **conformed** ground | 814 of 87,969 vertices (0.93 %) below it, worst −2.890 m — the wedges `conform.py` does not yet burn (`road.junction_surface`) |

Regressions to watch: `worst_patch_gap_m` must stay 0, `corners_skipped_incompatible` must stay 0,
and `splines_untrimmable` + `splines_degenerate` must stay small — a jump in either means the trim
radius has grown and is eating short links. The CLI itself is covered by
`tests/test_junction.py:TestAuditCLI`, which runs the module as a script on a one-document directory.

---

## 10. Reading the schema from C++ and numpy

- numpy: `schema.py` dataclasses named as the `$defs` (`RoadProfile`, `EdgeProfile`, …), field names =
  keys; `io_json.validate_structure` hand-mirrors §8.
- C++: `USTRUCT`s `FStreet<Def>` with PascalCase members (`SM`, `LengthM`, `RampM`, `TargetHeightM`,
  `S0M`, `S1M`, `OffsetM`, …); `PascalToSnakeKeys`/`SnakeToPascalKeys` convert keys **and** enum
  string values (`EdgeLeft ↔ edge_left`, `BrickWall ↔ brick_wall`, `None ↔ none`). Nullable numbers
  (`z`, `roll_deg`, `s1_m`) are `TOptional<double>` serialised as null when unset. UE_PLAN.md 2.11.

---

## 11. Changes from `docs/design/streetscape.schema.draft.json`

1. `BarrierType` enum extended with `concrete_wall`, `wood_fence`, `guard_rail`; `post_material` added;
   guard_rail default rails `[0.75, 0.55]`. (Adapter needed them; `kerb_only` is not a barrier and is
   expressed as `edge_uk_kerb` with `pavement_width_m 0`.)
2. `Ballast.top_width_m` removed (duplicate of `RoadProfile.width_m`).
3. `Sampling.bank_rate_max_deg_per_m` added (default 0.25); `Marking.lift_m` default 0.003 → 0.004.
4. `ProfileIds`: all five keys required. `Point.roll_deg` accepts null.
5. `Spline`: optional `continues_from`, `continues_to`, `continuation_kind`, `overrun_points`, `flags`;
   `Source`: optional `osm_ids`, `segment_index`, `segment_count`; `tags` values strings only.
6. `$defs/ProfileFile` added for the library files; `HedgeProfile.segments` documented as empty in the
   library (presence comes from spline segments).
7. `Marking.anchor` `edge_left/edge_right` + `offset_m` (the adapter's `inset_m` is renamed).
8. Draft worked example 1 (Noble Gardens) is superseded by `examples/test_stretch.json`; example 2 is
   §9.2.
