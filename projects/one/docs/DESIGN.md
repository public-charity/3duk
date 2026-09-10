# Project One — architecture and decisions (design phase closed 2026-09-07)

This is the normative synthesis of the four subsystem designs in `docs/design/` (pipeline.md,
geometry.md, unreal.md, adapter_and_test_stretch.md) and their critiques. Where the designs disagreed,
the tie-break was: **BRIEF §4 first**; then the geometry design owns *schema names and semantics*
(its draft was the validated one), the adapter design owns *file formats and manifests*, the Unreal
design owns *engine facts* (all of which checked out). Every critique finding was either folded in
(marked ✔ in §20) or rejected with a reason (§19). Companion normative documents: SCHEMA.md,
UE_PLAN.md, PIPELINE_CHANGES.md, STAGES.md. Citations are `path:line` in the repo or under
`C:/Program Files/Epic Games/UE_5.8/Engine/Source` (alias `UE`), verified 2026-09-07/08.

---

## 1. Architecture in one picture

```
 EA WCS ──► 02 fetch ─► 03 mosaic ─► 05 terrain (clip → NoData) ─┐
 Overpass ► 01 gpkg  ─► 06 roads / 07 massing / 09 ground / 10 furniture / 11 rail+barriers (clip → drop+count)
                                                                   │  sources/derive/*  (EPSG:27700, engine-neutral)
                                                                   ▼
                                   sources/adapters/unreal.py  (Survey → Streetscape frame; no engine units)
                                                                   │
              data/<site>/out/unreal/ ─┬─ landscape/  hm_*.r16  clip_*.r8  vis_*.r8  weight_{band}_*.r8  landscape_manifest.json
                                       ├─ streetscape/ site_x{i}_y{j}.json  (schema 1.0.0, profiles inline)
                                       ├─ massing/  furniture/  (local metres)
                                       └─ unreal_manifest.json
                    ┌──────────────────────────────┴───────────────────────────────┐
   Tools/blender/streetscape (numpy core + bpy)                  Plugins/Streetscape (C++ mirror) + Tools/ue/*.py
   Heightfield.from_landscape_dir → Spline → road/edge/hedge      UStreetHeightfieldTerrain → UStreetSplineComponent → 3 renderers
   .npz + stats.json + GLB + PNG renders                           UStreetscapeLandscapeImporter → ALandscape (WP)  ;  AStreetscapeActor per spline
```

Three renderers only (BRIEF 1.1): **A** road surface (incl. rail as a kind), **B** edge extrusion
(kerb + pavement + drop kerbs + split materials + barriers + embankments), **C** volumetric hedge. All
three read one built `Spline`; variants are profiles and s-ranged segments, never new classes.

---

## 2. Frames — the three-frame table and every formula

| Frame | Axes / units | Applies to |
|---|---|---|
| **Survey** | EPSG:27700 E/N metres, Z = ODN metres, north-up rasters, `bearing` = deg clockwise from grid north | everything under `sources/derive/`, `data/<site>/out/` (unchanged) |
| **Streetscape JSON** | local metres from `origin (E0, N0)`, right-handed, X east, Y north, Z up (ODN, not re-based); doubles | `schema/streetscape.schema.json`, `data/<site>/out/unreal/**`, the numpy core, Blender (native frame) |
| **Unreal** | left-handed, Z-up, centimetres | only inside `FStreetscapeJson::ToUE` and `UStreetscapeLandscapeImporter` |

Formulas (all normative; a unit test in the adapter and an Automation test in UE assert them on the
same worked example):

- `x = E − E0`, `y = N − N0`, `z = z_ODN`. Thanet `E0 = 627680, N0 = 163080`.
- `X_ue = 100·x`, `Y_ue = −100·y`, `Z_ue = 100·z` (`GeoReferencingSystem.cpp:235` FlatPlanet does the same multiply).
- `heading_deg = ((90 − bearing + 180) mod 360) − 180 ∈ [−180, 180)` (right-handed angle from +X toward +Y, written by the adapter for furniture); `yaw_ue = bearing − 90 = −heading_deg` (mod 360; loader only). `bearing 270 → heading −180`, `bearing 131 → heading −41, yaw 41`.
- Worked example: survey `(635253.6, 171027.6, 17.2)` → local `(7573.6, 7947.6, 17.2)` → UE `(757360, −794760, 1720)`.
- Triangle winding: the Y mirror reverses handedness, so the UE converter emits `(a, c, b)` for every JSON triangle `(a, b, c)` and mirrors normals. The C++ geometry core runs in the **JSON frame** with left-positive `d`; nothing else knows about the flip (UE_PLAN.md 2.7).
- Heightmap: `h16 = round(z·128) + 32768` (uint16 LE), `z = (h16 − 32768)/128`, quantum 0.78125 cm, window −256.0 .. +255.99 m; `LANDSCAPE_ZSCALE = 1/128`, `MidValue 32768` (`UE/Runtime/Landscape/Public/LandscapeDataAccess.h:13, :27, :30-38`). Water level −0.6 m → 32691. With actor Z scale 100, engine cm = 100·z exactly (to the quantum).
- Row order: north row first, **no flip** — `Import` indexes `HeightData[Y·VertsX + X]` with Y = landscape +Y = UE +Y = south, so GeoTIFF row 0 (north) is the smallest Y.
- Tile → landscape quads (unpadded): tile `(i, j)`, heightmap row `r`, column `c` → landscape vertex `(512·i + c, 512·(ny − 1 − j) + r)`; landscape vertex `(qx, qy)` ↔ local `(qx, tile_m·ny − qy)` m; actor at `(0, −100·tile_m·ny − 100·padN, 0)` cm after padding `padN` rows to the north (§10).
- Clip line (BRIEF 4.1, OSTN15): `A = (628512, 169680)`, `B = (635496, 163609)`, `B − A = (6984, −6071)`, length 9253.8 m, bearing 131.0° A→B. Keep `P` iff `(P − A)·(6071, 6984) ≥ 0`. Unit normal toward the kept side `n̂ = (0.65605, 0.75471)`. Midpoint `M = (632004, 166644.5)` → local `(4324.0, 3564.5)`; probes `P± = M ± 2n̂` → local `(4325.31, 3566.01)` kept, `(4322.69, 3562.99)` cut. The Helmert pair `(628514, 169681 / 635498, 163610)` is 2.07 m off and must not appear anywhere.

---

## 3. The shared spline

Normative algorithm: SCHEMA.md 3; numpy `Tools/blender/streetscape/spline.py`; C++
`FStreetSplineMath` + `UStreetSplineComponent::Resample()` (UE_PLAN.md 2.5.4). Decisions and reasons:

1. **Centripetal Catmull-Rom through the waypoints** (alpha 0.5), not a B-spline (must pass through
   OSM-snapped nodes so two splines meeting at a node agree; and a closed-form curve keeps the core pure
   numpy without LAPACK, which ports to C++ verbatim — geometry.md App. B) and not `USplineComponent`'s Hermite (`UE/Runtime/Engine/Classes/Components/SplineComponent.h:214`;
   different `s`). Consecutive points < 1e-6 m apart are merged first (step 06 duplicates seam vertices,
   `06_build_networks.py:195`); 789 of Margate's 4,417 road records contain such a pair.
2. **Curvature-adaptive stations** `step = clip(step_m/(1 + gain·κ), min_step_m, step_m)`, road
   2.0/0.25/20 (R = 20 m → 1.0 m), rail 1.0/0.25/60 (R = 300 m → 0.83 m). Mandatory stations at every
   waypoint, segment boundary and ramp end, painted-interval boundary and drop-kerb break, so width
   changes and material switches fall exactly on stations and **both renderers see identical stations
   by construction** (asserted, §6 rule 2). The design's `straight_100` count is **54**, not 55 (70 is
   already an adaptive station).
3. **Heights**: sample the terrain at every station (never lerp between waypoints — BRIEF 1.1 rail
   rule), fill gaps along `s`, centred arc-length moving average W = 20 m (rail 40, two passes) with the
   window shrinking to zero at the ends so junction nodes keep the raw height and meeting splines agree
   bit-for-bit; `points[].z` is a **pin** blended over 10 m — the adapter never writes it (it would pin
   the road to the raw 1 m drape, which BRIEF 1.1 forbids).
4. **Bank**: terrain cross slope from probes at `±max(w/2, 1.5 m)`, averaged with the same W, clamped
   ±4° (rail ±6°), blended with `roll_deg` overrides via a mask, then **rate-limited to
   0.25°/m** (new; bounds quad twist so lifted markings clear the road, SCHEMA.md 3.7).
5. **Frames**: `n = n_flat cos β + Z sin β`, `b = t_h × n`; every vertex `p + d·n + h·b`. Sections
   are vertical planes perpendicular to the horizontal travel direction, rotated by the bank.
6. **The edge contract**: `edge_offset(side) = w/2 + extra(side)` and `edge_height(side)` are the only
   kerb-line functions; `road.py`/`edge.py`/`hedge.py` may not compute `width/2` (a test greps for it).
   The ribbon's surface edge rows are at `±edge_offset` (a parking bay from `edge_extra_*` is
   carriageway surface), skirts at `±(edge_offset + overlap_m)`.

3.7 **Measured fixtures** (design prototype, env python; the frozen expectations are SCHEMA.md 9.3):
`straight_100` N = 54, exact 2.0 m spacing away from the drop kerb; `sine_5_50` (y = 5 sin(2πx/50),
points every 5 m) L = 109.2 ± 0.1, N = 101 ± 3, crest spacing ≤ 0.85 (0.817), inflection ≥ 1.5 (1.601),
ratio ≥ 1.8 (1.96); `curve_R20_200` (60 m straight, 90° arc R = 20, straight to L = 200) N = 117 ± 2, arc
1.00 ± 0.03, straights 1.99 ± 0.02, ratio 2.0 ± 0.1; `rail_R300_600` straight 1.00 ± 0.02, bend
0.83 ± 0.03.

3.8 **Noise / determinism.** `lowbias32(x): x ^= x>>16; x *= 0x7feb352d; x ^= x>>15; x *= 0x846ca68b;
x ^= x>>16` (uint32). `unit_noise(i, seed) = lowbias32(uint32(i)·0x9E3779B1 ^ lowbias32(uint32(seed)))
/ 2^32 · 2 − 1 ∈ [−1, 1)`; `[0, 1)` where needed is `(unit_noise + 1)/2`.
`lattice(ix, iy, iz, seed) = lowbias32(ix·0x9E3779B1 ^ lowbias32(iy·0x85EBCA77 ^ lowbias32(iz·0xC2B2AE3D ^ seed)))/2^32·2 − 1`;
`value_noise3` = trilinear smoothstep interpolation of lattice values; `fbm3(q) = (v(q) + 0.5·v(2q + 17.3))/1.5
∈ [−1, 1]` (normalised; the design's "±1.37" was the unnormalised sum; no clip needed). Known answers:
`lowbias32(1) = 0x688990c0`, `lowbias32(2) = 0xd1132181`, `lowbias32(0xdeadbeef) = 0xe628c683`;
`unit_noise(0..4, 7) = −0.33847302, 0.94551079, −0.62749659, 0.96820159, 0.64059920`. The smoothing test
uses this sequence (portable to C++ bit-for-bit); its re-frozen factors are SCHEMA.md 9.3
(W = 20: 2.837, not the design's 4.01 which came from an unspecified sequence).

3.9 **Hedge noise** uses `fbm3` with `noise_seed` from the profile; leaf cards from the same hash
sequence. No simplex, no actor-id seeds (a re-import must give the same mesh).

3.10 The synthetic fixtures live as schema documents in `Tools/blender/tests/fixtures/` written by
`Tools/blender/tests/make_fixtures.py` (geometry task) from `schema/examples/synthetic_straight.json`
plus programmatic `sine_5_50`, `curve_R20_200`, `rail_R300_600`, with `fixtures/expected.json` holding
every number of SCHEMA.md 9.3 and this section. Both test suites read that one file.

---

## 4. Renderers and their topology

One cross-section sweep serves everything (**closes BRIEF 6 Q4**): numpy
`sweep.sweep(buf, section, frames, side, lateral, height, point_o, point_h, mask, cap_start, cap_end,
cap_mat, group)`, C++ `FStreetSweep::Sweep(FDynamicMesh3&, const FStreetSection&, const FStreetFrames&,
const FStreetSweepParams&)`. A `Section` is a list of `(o, h, material, v, smooth)` points, open or
closed (closed listed clockwise in the `(o, h)` plane; open sections list the exposed surface on the
left of the walk). Rows: smooth points share a vertex row, hard interior points are emitted twice
(`R = P + #hard_interior`, closed all-hard `2P`). Quads split on the `V_{i,k}–V_{i+1,k+1}` diagonal;
**winding is decided geometrically** (exposed normal = left perpendicular of the section edge mapped
to world; flip if the emitted normal opposes it) so one routine is correct for both sides. Caps close
every mask run with the ring's own vertices (watertight). UV `u = s`, `v` = metres across. Posts,
sleepers and leaf cards are instance lists, not sweeps. Degenerate triangles (< 1e-10 m²) are skipped.

### 4.1 Renderer A — road (`road.py`, `UStreetRoadRenderer`)

- Ribbon: interior rows at fractions `f_k = −½ + k/(n_int − 1)` of the surface width
  `edge_offset_L + edge_offset_R` (rows at `d = −edge_offset_R … +edge_offset_L`), `n_int = max(7,
  2·ceil(w_max/(2·lateral_station_spacing_m)) + 1)` with `w_max` the maximum surface width over the
  stations; plus two skirt rows at `±(edge_offset + overlap_m)`, `h = surface_h(edge) − skirt_drop_m`.
  One sweep call, all points smooth. For `w ≤ 6` that is 7 + 2 = 9 rows; `straight_100` (w_max 8) has
  11 rows → 594 vertices / 1060 triangles.
- Camber (parabolic default): `h(d) = −c(2d/w)²`, `c = crossfall/100·w/4` (w = 6, 2.5 % → 3.75 cm);
  planar `−crossfall/100·|d|`; none. Camber kind switches at profile-switch stations; crossfall ramps.
- **Markings — BRIEF 6 Q5 closed once, for both toolchains: lifted strips.** `lift_m` default
  **0.004 m**, separate material-id triangles in the *same* buffer and build pass, swept over the shared
  frames plus interpolated dash-end frames (never extra spline stations). Dash ends are evaluated on the
  actual road triangles (SCHEMA.md 3.7). Reasons: physically right (thermoplastic is proud of the
  surface); same-plane material splits would make ribbon topology depend on the marking layout (rows at
  every marking edge, moving with width-anchored offsets) and, for dashes, force every dash edge into
  the shared station set — changing the kerb tessellation whenever paint changes. The clearance is
  guaranteed by the bank rate limit: worst case 2.2 mm twist + 1.0 mm sagitta < 4 mm. Parameterisation:
  `pattern solid|dashed|double|none`, `dash_m`, `gap_m`, `phase_m` (global), `double_gap_m`, `anchor
  centre|edge_left|edge_right` + `offset_m`, optional `s0_m/s1_m`. The UE renderer builds exactly this
  (UE_PLAN.md 2.6) — its earlier "same-plane split" is withdrawn.
- Width change: nothing special — rows use the per-station `edge_offset`; both renderers derive the
  kerb line from the same array, so the road-edge row and the kerb face coincide in (x, y) to float
  precision across the ramp.

### 4.2 Renderer B — edge (`edge.py`, `UStreetEdgeRenderer`)

Section outward `o` from the kerb line, `h` from the road-edge level, per station `kw, kh, pw, cf`
from the resolved `SideSpec`, drop factor `f`, `hk = kh(1 − f) + target·f`, lip `r = lip·hk/kh`:

```
A (−tuck_in, −tuck_depth) hard  B (0, −tuck_depth) hard  C (0, hk − r) smooth  L_j lip arc (arc_points)  D (r, hk) smooth
S (kw·boundary_frac, hk) smooth [split only]  E (kw, hk) smooth  F (kw + pw, hk_back) hard  G (kw + pw, −skirt)
```

Materials: inner face + top to D (or S) = `materials.kerb` (`split.inner`); S→E top, pavement and back
face = `split.outer` when split, else `materials.pavement`. D, S, E share one height → **flush by
construction**, no step. `kw = 0` removes A–E, `pw = 0` removes F; `kw = pw = 0` (barrier-only) emits
only barriers/embankments. Caps at mask-run ends.

- **Drop kerbs**: `f_k = smoothstep((s − (s_d − ramp))/ramp)` up to 1 on `[s_d, s_d + len]` and down
  again; `f = max_k f_k`. `hk` follows, the lip collapses to the 6 mm arris, the back edge dips only as
  far as `pavement_max_crossfall_pct` requires (1.8 m pavement: 0.170 → 0.150). Both split materials
  ride the same rows down (BRIEF 1.1 §B last bullet).
- **Barriers** (types SCHEMA.md 4.10) at base `o_b = edge_offset + kw + pw + offset_m`, height
  `h0 + hk_back`: walls (brick/stone/concrete/retaining) = closed CW box with coping `(0,−skirt) (0,H)
  (−ov,H) (−ov,H+ch) (t+ov,H+ch) (t+ov,H) (t,H) (t,−skirt)`, caps at run ends; chain_link / wood_fence =
  round posts (instances) + a two-sided panel `(t/2, 0.05) → (t/2, H)` (wood_fence opaque material,
  otherwise identical); railing / guard_rail = square posts + closed 4-point rails at `rails_m`
  (guard_rail default `[0.75, 0.55]`). Post rule: `n = floor(Δ/pitch) + 1 + [frac(Δ/pitch) > 0.5]`,
  posts at `s0 + j·pitch` for `j < n − 1`, last at `s1` — `[45, 100]`/3 → 19 posts.
- **Embankments**: `auto` selects batter (open 2-point) where `dz > 0.35` and retaining
  wall (closed box) where `dz < −0.35`, using the actual banked world edge. Explicit
  retaining walls support either direction. Batters solve the toe's terrain contact;
  walls remain world-vertical with buried footings. Missing/unreachable required toes
  fail the build. Side/kind gating and contact limits are defined in SCHEMA.md 4.11.

### 4.3 Renderer C — hedge (`hedge.py`, `UStreetHedgeRenderer`) — **closes BRIEF 6 Q6**

Swept closed rounded-rectangle volume (flat / rounded / domed top, `corner_radius_m 0.15`,
`corner_points 4`), inner face at `o_h = edge_offset + kw + pw + [barrier.offset_m + thickness if a
barrier is in force] + hedge.offset_m`, base `h0 + hk_back − base_sink_m`; per-vertex displacement
along the section-space outward normal by `noise_amplitude_m · fbm3(V/noise_scale_m, seed)` (base row
`h ≤ 0.05` undisplaced; volume stays closed); leaf cards `floor(area·density + frac)` per surface
triangle as an instance list (`mode cards`), or engine meshes (`mode instances`). Not Niagara/PCG for
the volume: it must exist identically in Blender and in the numpy tests; PCG may later *consume* the
instance list. Density knobs: `foliage.density_per_m2 12`, `card_size_m 0.25`, `noise_amplitude_m
0.06`, `noise_scale_m 0.6`, `corner_radius_m`, `corner_points`, `top_profile`. Because
`barrier_timeline` and `hedge_timeline` come from one `SideTimeline`, the hedge steps out by exactly
the wall thickness where the wall is — "stacks cleanly beside walls/fences".

---

## 5. Seam and overlap rule (BRIEF 1.1, "critical") — the numbers

`o0 = edge_offset(side)`, `ov = overlap_m = 0.04` (schema floor 0.03), `sd = skirt_drop_m = 0.02`,
`td = tuck_depth_m = 0.03`, `ti = tuck_in_m = 0.02`.

1. **Lateral overlap** `measure_lateral_overlap(road, edge, side).per_station[i] == 0.040` to 1e-9 at
   every station, including inside width ramps (both rows come from `o0[i]`).
2. **Identical stations**: `np.array_equal(np.unique(road.vs[grp ∉ marking:*]), spline.s)` and the same
   for every edge/hedge buffer (marking groups excluded — their vertices sit on interpolated dash-end
   frames by design).
3. **Road owns the seam**: the skirt row at `d = side·(o0 + ov)`, `h = h0 − sd` lies strictly inside the
   kerb block `[0, kw] × [−td, hk]`: `0 < 0.04 < 0.125` and `−0.03 < −0.02 < hk` for every `hk ≥ 0.006`;
   the kerb underside row A reaches `o = −0.02` under the skirt.
4. **Coincident verticals**: `coincident_xy_pairs` counts **distinct positions** (vertices deduplicated
   at 1e-9 first); exactly 2 per station in `[o0, o0 + ov]` (road-edge row against kerb rows B and C at
   `o = 0`) and 0 in `(o0 + 1e-6, o0 + ov]`.
5. **Height coherence**: `|road_edge_row.z − (z_ref + h0)| < 1e-9`; kerb row B is exactly `td` below.
6. **Width change invisible at the seam**: on the 6 → 8 m ramp rules 1 and 5 hold at every station and
   kerb-face `(x, y)` equals road-edge `(x, y)` to 1e-9.

5.5 **Overlay**: both engines re-drape the OSM overlay polyline on their terrain source and lift it
**0.3 m** (one constant; the adapter's `z` in the file is informative).

---

## 6. Rail as a road-profile kind (BRIEF 4.4, stage 7)

`RoadProfile.kind = "rail"`: the ribbon is the ballast top (`width_m` 3.4), camber none; the ballast
section `(−(w/2 + depth·k), −depth) → (−w/2, 0) → (w/2, 0) → (w/2 + depth·k, −depth)` (`k = 1.5`,
`depth = 0.45`, toe width 4.75 m); sleepers as instances at `phase + j·pitch` (0.65 m; `floor(L/0.65) + 1`),
box `2.5 × 0.25 × 0.15` spanning `h ∈ [−0.10, 0.05]`; two rails as a closed 12-point BS113A section
swept at `lateral = ±(gauge/2 + head_width/2) = ±0.75243 m`, `height = 0.05 + 0.005`. Inner faces are
exactly 1.435 m apart (test tolerance ±1 mm), rail top 0.21375 m above the ballast. Tighter sampling
comes from `sampling_defaults` (1.0 / 0.25 / 60 / 40 / 2 / 6°); the spline may override. The UE
renderer sweeps the same sections (its earlier `±Gauge/2` placement and 0.30 ballast depth are
withdrawn). `edge_offset` still exists (3.4/2 = 1.7 m at the shoulder) for future lineside fences.

---

## 7. Interchange: one schema, three writers/readers

- The schema is `schema/streetscape.schema.json` 1.0.0 (SCHEMA.md). The adapter writes it verbatim
  (per-tile documents, profiles inlined, ids `roads:<osm>:<k>`, points without `z`); the UE loader
  reads it verbatim (`frame` const, five `profile_ids` keys, `segments[]`, `overlay{}`, enums in lower
  snake case, `bStrictMode` on unknown keys); the numpy core reads it verbatim. No `profile_overrides`,
  `overlay_points`, `units`, `edges{left,right}` or `p:[x,y,z]` anywhere.
- Profile library `schema/profiles/*.json` (20 files, SCHEMA.md 1) is the single source: the adapter
  inlines from it, the UE bootstrap creates DataAssets from it (`{kind, id, profile}` shape), the numpy
  tests load it. The adapter's `edge_uk_kerb_grass` is renamed `edge_uk_half_grass` in `unreal.json`;
  `kerb_only` and `hedge` are not barrier types.
- Material names are one list (SCHEMA.md 7); the UE bootstrap creates exactly those instances.
- Q7 junctions: reserved as `junctions[] {id, x, y, z, radius_m, kind, ends[{spline_id, end}]}` +
  `Spline.junction_start/junction_end` + point tag `junction:<id>`; step 06 discs map 1:1; no renderer
  reads them this round; spline ends are not trimmed. **Closes BRIEF 6 Q7.**

---

## 8. Terrain products and the heightfield the core samples

The adapter writes (PIPELINE_CHANGES.md 13.3):

| file | dtype / shape | meaning |
|---|---|---|
| `landscape/hm_x{i}_y{j}.r16` | uint16 LE, 513×513, north row first | `h16` of step 05's filled DTM; clipped cells filled nearest-valid (the mask carries the truth) |
| `landscape/clip_x{i}_y{j}.r8` | uint8, 513×513 | 255 keep / 0 clipped-or-nodata, from step 05's declared NoData |
| `landscape/vis_x{i}_y{j}.r8` | uint8, 513×513, straddle tiles only | landscape visibility weight, `clamp(2/3 + d/(3·px_m), 0, 1)·255`, `d` = signed distance into the clipped half-plane from `clip.line` (§16) |
| `landscape/weight_{grass,sand,rock,water}_x{i}_y{j}.r8` | uint8, 256×256 | step 09 bands as-is |
| `landscape/landscape_manifest.json` | — | everything the importer and the samplers read |

**There is no float32 heightfield product.** The numpy core's `Heightfield.from_landscape_dir(path)`
reads `landscape_manifest.json` + `hm_*.r16` + `clip_*.r8`: `z = (h16 − 32768)/128`, NaN where
`clip == 0`, tiles listed in `tiles_missing`/`tiles_clipped` absent → NaN. The UE
`UStreetHeightfieldTerrain` reads the identical bytes with the identical bilinear rule (pixel centres on
integer metres, inward clamp at the last row/column, NaN if any of the four samples is clipped), so
Blender and Unreal sample bit-identical data. The 0.78 cm quantum is below the DTM's own step-to-step
noise (RMS 2.1 cm on the test stretch). `Heightfield.from_step05_dir` (GDAL) remains a convenience for
the env python. **Closes BRIEF 6 Q3**: the plugin samples an `IStreetTerrainSource`; the heightfield
implementation is primary and the one used for every numeric comparison; `UStreetLandscapeTerrain`
(`ALandscapeProxy::GetHeightAtLocation`, `LandscapeProxy.h:1101`, converting `FVector(100x, −100y, 0)`
in and `/100` out) is an in-editor convenience with a stated tolerance of 1 cm at vertices.

---

## 9. Landscape import plan and numbers — closes BRIEF 6 Q1 and Q2

- Heightfield W = 26·512 + 1 = **13313** columns, H = 19·512 + 1 = **9729** rows (BRIEF 6's "12801" is
  a typo, 25·512 + 1). No valid component size divides 13312 (2¹⁰·13) or 9728 (2⁹·19): quads per
  component are `ss·ns`, `ss ∈ {7,15,31,63,127,255}`, `ns ∈ {1,2}` (`UE/Runtime/Landscape/Private/LandscapeConfigHelper.cpp:24-25`).
- **Component size: 127 quads/section × 2 sections = 254 quads**, 256² textures, **53 × 39 = 2067
  components**, padded to **13463 × 9907**, padding **150 columns east and 178 rows north**, fill
  `h16 = 32691` (water level), visibility 255 (hole), weights water 255. `ChooseBestComponentSizeForImport`
  (`UE/Editor/LandscapeEditor/Public/LandscapeImportHelper.h:140`) would pick 255×2 (27 × 20, ≤ 32 rule,
  `LandscapeImportHelper.cpp:469-492`); we override for finer LOD/culling and log its answer.
- Padding placement: **north and east only**, so the site origin stays at UE (0, 0) and landscape
  vertex (0, 0) is the padded NW corner. Actor at `FVector(0, −100·(9728 + 178), 0) = (0, −990600, 0)`
  cm, scale (100, 100, 100). Data row `r` → padded row `r + 178`; columns unchanged. Extent
  `(0, 0, 13462, 9906)`. The importer never uses `ExpandCentered` (the `TransformHeightmapImportData`
  default, `LandscapeImportHelper.h:138`, enum `:49-58`) — it assembles the padded arrays itself.
- **World Partition grid size 4** → 1016 m proxies, **14 × 10 = 140 streaming proxies** via
  `ULandscapeSubsystem::ChangeGridSize` (`UE/Runtime/Landscape/Public/LandscapeSubsystem.h:153`).
- **Import granularity (D1, now "unverified; gated")**: Epic's own New Landscape flow never calls a
  single `Import` above a 16 × 16-component region in a WP world (`bNeedsLandscapeRegions`,
  `UE/Editor/LandscapeEditor/Private/LandscapeEditorDetailCustomization_NewLandscape.cpp:1163-1166`;
  initial region clamp `:1182-1186`; remaining regions added per 16×16 block with `AddComponents` `:1058`,
  `ImportHeightData`/`ImportWeightData(..., Subregion)` `:1338, :1346`, `ForceLayersFullUpdate` `:1352`,
  `SaveLandscapeProxies` `:1353`). Plan: **(a)** prove the path on a 2×2-tile Margate cutout
  (1025×1025 → 4×4 components), **(b)** prove a 16×16-component (4065-quad) import, **(c)** attempt the
  single 2067-component `Import` with memory recorded per step (peak estimate 4.5 GB CPU); **(d)** if (c)
  fails or exceeds 20 GB / 30 min, use the region fallback: initial `Import` of the first ≤16×16 region,
  then for each remaining 16×16 region `ULandscapeSubsystem::FindOrAddLandscapeProxy(Info, SectionBase)`
  (`LandscapeSubsystem.h:154`) → add components → `FLandscapeEditDataInterface(Info).SetHeightData(...)`
  and `SetAlphaData(...)` for that rect (the calls `Import` itself makes, `LandscapeEdit.cpp:3784, :3795`)
  → `Info->ForceLayersFullUpdate()` → save the new proxies → unload them before the next region.
  Every step records components, proxies, RSS and wall time in the report JSON (UE_PLAN.md 3.6).
- **Visibility and weightmaps in the same `Import` call (Q2)**: `FLandscapeImportLayerInfo` entries
  for `grass, sand, rock, water` (layer infos created by `UE::Landscape::CreateTargetLayerInfo`,
  `UE/Runtime/Landscape/Public/LandscapeUtils.h:330`) plus one for `ALandscapeProxy::VisibilityLayer`
  (`LandscapeProxy.h:1002`) keyed by the empty GUID, alphamap type `Additive` (`LandscapeProxy.h:178`).
  Visibility semantics: material `LandscapeVisibilityMask` = `1 − weight`
  (`UE/Runtime/Landscape/Private/Materials/MaterialExpressionLandscapeVisibilityMask.cpp:20, :45-46`),
  so weight 255 = hole; render edge where the bilinearly sampled weight crosses 2/3
  (`LandscapeDataAccess.h:19`); collision removes a quad whose dominant layer is the visibility layer
  (`UE/Runtime/Landscape/Private/LandscapeCollision.cpp:1276-1279`, hole index → triangle skipped
  `:644-654`); the marching-squares cut at `LandscapeEdit.cpp:4411` is the Nanite/static-mesh export path
  only. Weightmaps: the importer assembles the site mosaic of 09 cells (`nx·256 × ny·256`, cell centres
  at odd metres) and resamples **once**, cell-centre-aware bilinear, to the padded vertex grid, then
  renormalises the four ground layers to 255 (residue to the largest); no per-tile resample (that would
  seam every 512 m). Cells outside the clip (all-zero bands) stay zero so the visibility layer is
  dominant there.

---

## 10. Actor granularity, streaming, saving — closes BRIEF 6 Q8

- **One `AStreetscapeActor` per Streetscape-JSON spline** (= one per step-06/11 tile run), components
  `Spline` (root), `Road`, `EdgeLeft`, `EdgeRight`, optional `HedgeLeft/Right`, `Overlay`;
  `bIsSpatiallyLoaded = true`, main grid. Thanet estimate: 391 kept tiles / 91 Margate tiles = 4.3× →
  ≈ 21.5k road actors + ≈ 2.5k barrier/rail ≈ **24k actors** (the design's 27k/30k scaled by the full
  494-tile grid). Within WP's design range; the per-tile alternative gives the same component count
  with coarser streaming.
- Meshes are **not serialised**: `bRebuildOnLoad`; `PreSave` (`UE/Runtime/CoreUObject/Public/UObject/Object.h:278`)
  stashes the mesh and `Reset()`s the `UDynamicMesh` (`UE/Runtime/GeometryFramework/Public/UDynamicMesh.h:132`);
  the owning actor's `PostSaveRoot` (`UE/Runtime/Engine/Classes/GameFramework/Actor.h:2380`, each OFPA
  actor is its own package root) restores the stashed mesh, so a save in the same session leaves the
  road walkable and visible (the design's save-then-blank bug is fixed); `OnRegister`
  (`UE/Runtime/Engine/Classes/Components/ActorComponent.h:830`) rebuilds when the mesh is empty.
  Rebuild-on-load requires `data/<site>/out/unreal/landscape` on disk at the manifest path (resolved from
  a `UStreetscapeSettings` developer setting, project-relative default `../../data/<site>/out/unreal`);
  **packaged builds are out of scope this round**. Materials are pre-resolved in
  `AStreetscapeSiteActor::PostLoad`. A `Streetscape.Perf.Tile` test logs ms per actor.
- Collision: complex-as-simple per component; DynamicMesh has no Nanite path in 5.8 — HLOD/Nanite is
  a later static-mesh bake.
- Overlay batch id: `FCrc::StrCrc32(*StreetId)` forced non-zero (`UE/Runtime/Core/Public/Misc/Crc.h:43`),
  stored as a `UPROPERTY`; `GetActorGuid()` is editor-only (`Actor.h:1147, :1180`) and would not compile
  for the Game target.
- Save behaviour of the landscape: 140 proxy packages under `Content/__ExternalActors__`, regenerated,
  never committed.

---

## 11. Explorer — closes BRIEF 6 Q9

`AThanetExplorerPawn : ACharacter` (`UE/Runtime/Engine/Classes/GameFramework/Character.h:338`), camera at
eye height 1.6 m, walk 300 cm/s (sprint ×2.5), fly 1500 cm/s (sprint 6000) via
`SetMovementMode(MOVE_Flying)` (`CharacterMovementComponent.h:1276`), step height 45 cm, Enhanced Input
assets **built in C++ at runtime** (`UInputMappingContext::MapKey`, `EI/InputMappingContext.h:228`): WASD
move, mouse look, Space jump/ascend, LeftCtrl descend, LeftShift sprint, F fly toggle, O overlay toggle.
`AThanetGameMode` sets it as default pawn; `03_import_streetscape.py --player-start` places a
`PlayerStart` 2 m above the first waypoint of the test stretch with yaw = bearing − 90. Minimap later.

---

## 12. UnrealMCP plugin — closes BRIEF 6 Q10

Source-only copy of `C:/UnrealProjects/unreal-mcp/MCPGameProject/Plugins/UnrealMCP` (`UnrealMCP.uplugin`,
`Source/`; no `Binaries/`, `Intermediate/`) into `projects/one/Plugins/UnrealMCP/`. Changes: a
`UUnrealMCPSettings : UDeveloperSettings` (`Port` default 55557, `bStartInEditor`, `bStartInCommandlets
= false`, env override `UNREAL_MCP_PORT`); Thanet's `DefaultEngine.ini` sets `Port=55558`; the server is
not started in commandlets; **`SetReuseAddr(true)` removed** so a genuine conflict fails at `Bind` with
the existing error log and the editor continues (with it, Windows lets a second socket bind
`127.0.0.1:55557` and steal Alex's connections). Verification: Thanet's Output Log shows port 55558
while `C:/UnrealProjects/test_bridge.py` still answers on 55557.

---

## 13. Headless first

Every editor step runs via `UnrealEditor-Cmd.exe Thanet.uproject -run=pythonscript -script=…`
(`Tools/ue/run_ue_python.ps1`); landscape import, probes and screenshots add `-AllowCommandletRendering`
because the edit-layer merge requires `FApp::CanEverRender()` (`UE/Runtime/Landscape/Private/LandscapeEditLayers.cpp:7051`).
The MCP bridge is a convenience on top. Scripts print `THANET_OK <script> <json>` / `THANET_FAIL`.

---

## 14. Blender prototype and parity with C++

The numpy core (`Tools/blender/streetscape/`, pure numpy, no LAPACK calls — `np.polyfit/lstsq/solve/svd`
exit silently in the env python unless `3duk-env/env/Library/bin` is on `PATH`, BRIEF §8; the rule is kept
for C++ portability, and pipeline tests must not treat LAPACK as forbidden) is the reference implementation; the C++ port mirrors
its modules function for function (UE_PLAN.md 2.14 table) and must reproduce `stats.json` keys:
`length_m, n_samples, step_min/max/mean, z_raw_nan_count, bank_min/max, per-buffer {verts, tris,
per_material}`, `overlap_min/max` per side, marking strip count, instance counts. **Parity is defined
on those measurable quantities and on vertex/triangle counts of the ribbon and kerb buffers**, which
match because both implement the same row rule. `Streetscape.Json.SchemaFixtures` loads
`examples/test_stretch.json` unchanged; `Streetscape.Json.RoundTrip` makes the C++ save byte-equal after
canonical ordering. Blender renders (`BLENDER_EEVEE`, three fixed cameras — Workbench is not selectable under
`-b` on this machine, BRIEF §8) go to `Tools/blender/renders/`
via LFS; `Tools/blender/out/` is ignored (`.gitignore:34`).

---

## 15. Massing placeholder (BRIEF stage 8)

`UStreetscapeEditorLibrary::ImportMassing(dir)` (UE_PLAN.md 2.12) builds one `AStreetscapeMassingActor`
per `massing/buildings_x{i}_y{j}.jsonl` tile with a single `UDynamicMeshComponent`: each footprint's
rings extruded from `base_z` (skirt below) to `base_z + h`, ear-clipped caps, material `massing_grey`,
`bIsSpatiallyLoaded`. Furniture is **out of scope** this round (the adapter still converts it).

---

## 16. The clip, end to end (BRIEF 4.1 binding)

| stage | what happens | where recorded |
|---|---|---|
| config | `thanet.json clip {type halfplane, line [[628512, 169680], [635496, 163609]], keep left}` — OSTN15 endpoints; config, not code | `sources/config/sites/thanet.json` |
| lib | `lib.parse_clip / keep_points / tile_state / cell_mask / clip_wkt / clip_manifest` (PIPELINE_CHANGES.md 2); with no clip every function answers "kept" and no step writes a different byte | `sources/lib.py` |
| 02 | tiles whose 512 m square is wholly outside (`tile_state == outside`, 103 positions) are not fetched: 391 positions, 782 rasters; `_grid.json` keeps its four keys; `_fetch_clip.json` records the skip list | stdout summary `skipped_clip: 206` |
| 05 | inside tiles unchanged; straddle tiles (31) get cells with centre outside the line set to NoData −9999 **after** the gap fill (3,861,822 cells of 8,158,239 tested); NoData declared on every tile of a clipped site; `range_m`/`slope_qa` over kept cells | `terrain_manifest.json: nodata, clip, tiles_clipped, clipped_cells_total, tiles[].clip_state/clipped_cells` |
| 06/07/09/10/11 | vertices / envelope centres / class cells / nodes outside are dropped and counted; an off-clip vertex closes a run like an off-grid one; 09 writes all-zero bands (sum 0) outside | each manifest: `clip`, `*_outside_clip`, `tiles_clipped`, `clipped_cells`, `bands_note` |
| adapter | `clip_*.r8` from the NoData mask (verification, count must equal `clipped_cells`), `vis_*.r8` from the **line** (the cut), `weight_*` zeros outside; roads/rail/barriers already clipped; overlays clipped to the half-plane with the crossing point inserted | `landscape_manifest.json: clip, tiles_clipped, clipped_cells_total, visibility` |
| UE | visibility layer fed from `vis_*.r8` (absent → 0 visible; missing/excluded tiles and padding → 255): render edge exactly on the line, collision edge within one cell | import report: components, probes `P±` |
| streetscape | ways end at their last kept vertex, ≤ 12 m short of the line; **no spline is extended to the line this round** | `networks_manifest.vertices_outside_clip` |

Semantics consistency: every stage tests `(P − A)·(6071, 6984) ≥ 0`; rasters at cell centres (integer
metres, which are also the landscape vertex positions), vectors at vertices, footprints at their
envelope centre (07 uses the envelope centre, not the centroid), nodes at their position.

---

## 17. Pipeline decisions carried (details PIPELINE_CHANGES.md)

- Step 11 emits `rail_*` and `barriers_*` with the record schemas of PIPELINE_CHANGES.md 4; `lib.py`
  holds `tagval/densify/chaikin/DtmSampler/tile_of/drape_runs` as copies of 06's arithmetic; **06 is not
  refactored this round** (BRIEF 4.4's two sentences conflict; the "untouched" one protects the
  centimetre regression) — the follow-up commit "refactor-06-onto-lib.drape_runs" is accepted only when
  `regress_outputs.sh compare margate before` reports 0 changed; the dry-run check `C11 rail on a road's
  polyline gives identical pts` is the drift guard meanwhile.
- `fetch_osm.sh` adds `way["railway"]` only; the query is recorded in provenance.
- Step 09's bands sum to **252–255** inside the clip (per-band uint8 truncation; measured on Margate:
  87 of 91 tiles have cells summing to 252–254) and to 0 outside; the adapter accepts exactly that.
- `run.sh` probes a usable `PY` and exports it; `reuse_tiles.py` copies Margate's 182 rasters to
  `(i+10, j+10)` after checking each file's georeferencing.
- Margate byte identity is proven by `sources/tests/regress_outputs.sh` (sha256sum output normalised
  to `hash␠␠path`).

---

## 18. Design-parameter decisions with reasons (quick reference)

| parameter | value | reason |
|---|---|---|
| `overlap_m` | 0.04 (floor 0.03) | BRIEF "a few centimetres"; hides the width-change error under the lip |
| `skirt_drop_m` / `tuck_depth_m` / `tuck_in_m` | 0.02 / 0.03 / 0.02 | skirt strictly inside the kerb block |
| kerb 125 × 125 mm, lip r 20 mm | UK HB2/BN units | geometry.md 4.2 |
| drop kerb `length_m` 1.83 / `ramp_m` 0.915 / `target_height_m` 0.006 m (0.025 m vehicle) | DL1/DL2 915 mm units, ≤ 6 mm pedestrian upstand | |
| pavement 1.8 m, 2.5 %, max 8 % at drops | Inclusive Mobility; 1:40 crossfall | class value via segment override |
| markings 100 mm; 1004 4/2; 1005 2/7; 1018.1 100/100 at 250 mm; 1012.1 150 mm | Traffic Signs Manual Ch. 5 | |
| `lift_m` 0.004 | clears 2.2 mm twist + 1.0 mm sagitta | §4.1 |
| `bank_rate_max_deg_per_m` 0.25 | 0.5°/station at 2 m → twist ≤ 8.7 mm | §4.1 |
| smoothing W 20 m (rail 40, 2 passes) | 4× noise attenuation class; 2.6 cm bias on a 30 mph crest | test stretch uses 15 to match its measured table |
| bank clamp 4° (rail 6°) | 7 % superelevation; 150 mm cant | |
| brick wall 0.215 m | one UK brick length | adapter default 0.23 replaced |
| chain link 1.8 m / posts 3.0 m / thickness 0.05 m | domestic spec; panel at post centre | |
| railing 1.1 m / posts 2.0 m / rails at 1.08, 0.55, 0.10 m | BS 7818 class | |
| privet 0.8 × 1.5 m, noise 0.06 m @ 0.6 m, 12 cards/m² | trimmed garden privet | |
| rail 1.435 m gauge, BS113A, sleepers 2.5 × 0.25 × 0.15 m @ 0.65 m, ballast 3.4 m top / 1:1.5 / 0.45 m deep | standard gauge; NR practice | |
| landscape 127×2, WP grid 4, pad N+E, fill 32691 | §9 | |
| overlay lift 0.3 m | one shared constant | §5.5 |

---

## 19. Rejected critique

| finding | why rejected |
|---|---|
| pipeline.md §12 minor — add a third layer `networks/road_tags.jsonl` (sidewalk/lanes/… tags) | The adapter already opens `derived/<site>.gpkg` for the raw overlay geometry and reads `other_tags` with `lib.tagval`; a third pipeline layer would duplicate step-01 data. OUTPUT.md gains one sentence saying the Unreal adapter reads the GeoPackage for raw geometry and tags (PIPELINE_CHANGES.md 10.1). |
| pipeline.md §2.3 minor, option (b) — make 06 import `tagval/densify/chaikin` from `lib` this round | BRIEF 4.4 "06 stays untouched except for clip support" protects the centimetre regression; duplication is bounded (~70 lines) and guarded by the C11 equivalence check; the refactor is the named follow-up commit gated on `regress_outputs.sh` (§17). |
| adapter A4.5 — implement interpolant-aware thinning as the only option | Adopted in the form (a) with tolerance 0.10 m measured against the Catmull-Rom (keeps 15 of 115 points on the test stretch); the 5 cm figure is *not* claimed. Not rejected, but the tolerance is 0.10 m rather than 0.05 m (0.05 keeps 19 points for no visible gain). |
| unreal.md region-fallback proposal "two or four independent ALandscape actors" | Replaced by the engine's own region flow (§9 d); independent actors would break material blending at the seams. |
| adapter B5 — rail Overpass regex + `node["railway"="station"]` + route relation | Class filtering belongs in `tuning.rail.classes` (config, not the query); stations are not needed by any consumer this round; relations carry no geometry. Recorded so it is not re-raised. |
| geometry §2 — add `points[].profile_ids` for a literal "profile id per waypoint" | Per-waypoint profile ids are deliberately expressed as s-ranged `segments[]` (a waypoint profile id is a segment from that knot to the next with no ramp); STAGES.md words stage 3 accordingly. |
| adapter — `sampling.height_source`, `z_note`, `terrain_hint` as schema keys | Not needed: heights always come from terrain unless `z` pins; the tile is `source.tile`; the heightfield directory is a site-level fact (`landscape_manifest.json`). |
| unreal.md — Nanite/HLOD for DynamicMesh | No Nanite path for `UDynamicMeshComponent` in 5.8; deferred to a static-mesh bake, not designed here. |

Everything else in the critiques was accepted; the resulting changes are listed in §20 and in
SCHEMA.md 11, UE_PLAN.md 0, PIPELINE_CHANGES.md 0.

---

## 20. Deviations from the source designs (accepted critique, summarised)

pipeline.md: OSTN15 clip line everywhere; 3,861,822 clipped cells; `grid_stamp` unchanged (four keys),
`_fetch_clip.json` instead; `regress_outputs.sh` sha256sum `*` normalisation; bands 252–255; "envelope
centre" wording; budget_note reworded and pinned by a dry-run check; 02 banner corrected.
geometry.md: heightfield read from r16 + clip (no f32); 20 profiles (adapter ids added, `edge_uk_half_grass`
kept); barrier enum extended; `straight_100` N = 54, 11 rows, 594/1060, coincident positions deduped
(2·N); post rule closed form; rule 2 excludes marking groups; marking clearance re-derived with a bank
rate limit and `lift_m` 0.004; ribbon edge rows at `edge_offset`; duplicate-point merge; C++ frame
statement (JSON frame, flip at Commit); `unit_noise` written out and factors re-frozen; `fbm3`
normalised; `ballast.top_width_m` dropped; per-station camber/scalar rule and single `kind`;
`ProfileIds` all required; `FLandscapeTerrainSource` conversion stated; citations fixed
(`.gitignore:34`, `margate.json:7/10/13`, `06:175-182`); §10.4 replaced by the Trinity Square stretch.
unreal.md: USTRUCTs renamed to the schema; enums lower snake; resampler = geometry's; lateral sign
left-positive; lifted markings; adapter manifest and file names adopted; D1 gated + region fallback;
OSTN15 probes; PreSave/PostSaveRoot; overlay batch id; `TPL` template paths; 24k actors;
collision citations; hedge segment reduced; `EditInlineNew` terrain sources; rebuild-on-load
prerequisites; massing importer; material names; segments/timelines in C++; parity redefined;
fixtures owned by the geometry task; 1004 = 4/2 m.
adapter: bands 252–255 with histogram; schema shape verbatim (ids `roads:`, five profile keys,
`segments[]`, `overlay{}`, junction shape, tags strings, no `z`/`roll_deg`); `chain_segments` ordered by
the raw way with gaps and loops; overlay clipped; thinning against the interpolant (0.10 m); `ue_import`
renamed `ue_import_unpadded` with the padding rule; drop kerb 38.8 + a second pedestrian drop through the
half-grass kerb; manifest skeletons; heading range `[−180, 180)`; h16 example 32817/35673; visibility
mechanisms cited; single mosaic weight resample; service roads keep a kerb (`pavement_width_m 0`), barrier
splines centred with `offset_m = −thickness/2`; B1 counts corrected (1,067 residential+tertiary, 43
`sidewalk=no`, chord deviation 11.1 m). Cross: header/spline/points/resampler/manifest/profile
set/heightfield/payload/lateral sign/enum casing/drop kerb/barrier enum/Q5/materials/segments in
C++/parity/fixtures/massing/noise/schema extensions/clip exactness/padding/smoothing window/overlay
lift/ownership/clipped ends/rail selectors — all applied as recommended.

---

## 21. Ownership for the implementation phase

| owner | files |
|---|---|
| pipeline | `sources/lib.py`, `sources/run.sh`, `sources/fetch/{fetch_osm.sh, 01_fetch_osm.sh, 02_fetch_lidar.py, reuse_tiles.py}`, `sources/derive/{05,06,07,09,10}_*.py` (clip edits), `sources/derive/11_linear_features.py`, `sources/config/sites/thanet.json`, `sources/config/tuning.json`, `sources/tests/{dryrun.py, regress_outputs.sh}`, `sources/OUTPUT.md`, `README.md`, root `.gitignore` |
| adapter | `sources/adapters/unreal.py`, `sources/adapters/unreal.json`, `sources/tests/test_unreal_adapter.py` |
| geometry | `projects/one/schema/**` (maintenance), `projects/one/Tools/blender/**` incl. `tests/make_fixtures.py`, `tests/fixtures/` |
| unreal | `projects/one/Thanet.uproject`, `Source/**`, `Config/**`, `Plugins/Streetscape/**`, `Plugins/UnrealMCP/**`, `Tools/ue/**`, `Tools/build.ps1`, `Tools/build.sh` |
| integration | `projects/one/README.md`, `docs/STAGES.md` status column, commits per phase |
