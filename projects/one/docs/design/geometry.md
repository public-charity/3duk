# Streetscape geometry core and shared spline + profile schema — design

Project One, design phase. Author: geometry-core design agent, 2026-09-07. Companion file:
`projects/one/docs/design/streetscape.schema.draft.json` (JSON Schema draft 2020-12, with the two
worked examples of §3.8/§3.9 embedded under `examples`; validated in this session, see Appendix A).

This document is written to be implemented from without asking questions. Where a number comes
from a standard I name it; where it comes from memory or trade practice I say "(memory)". Every
repo fact is cited as `path:line`; every Unreal API as a header path under
`C:/Program Files/Epic Games/UE_5.8/Engine/...` with a line number that was grepped in this session.

Sections 4 and 7 of `projects/one/docs/BRIEF.md` are binding and are not re-opened here. The one
place this design deliberately departs from the wording of the task brief (the rail-gauge test,
§7.8) states its reason.

---

## 0. Scope

Owned by this design (implementation phase files):

| Path | What |
|---|---|
| `projects/one/schema/streetscape.schema.json` | promoted from the draft next to this document |
| `projects/one/schema/profiles/*.json` | the ten UK default profiles of §4 |
| `projects/one/Tools/blender/streetscape/` | pure-numpy geometry core + thin bpy layer (§5) |
| `projects/one/Tools/blender/tests/` | pure-numpy tests, env python (§7) |

Not owned: the Unreal plugin classes (UE_PLAN.md; §8 gives the mirror table they must follow), the
adapter that writes the JSON (PIPELINE_CHANGES.md; §10 lists what this design assumes of it), the
landscape import.

---

## 1. Conventions (normative for everything below)

1. **Frame.** Local metres from the site origin, right-handed, X east, Y north, Z up, ODN metres
   (BRIEF.md:230). JSON numbers are doubles; numpy is `float64` throughout; `float32` appears only at
   the bpy/glTF boundary. Nothing in the core knows about Unreal's cm or Y flip (BRIEF.md:231).
2. **Direction of travel** = increasing arc length `s`, from `points[0]` to `points[-1]`.
3. **Left/right.** With unit horizontal tangent `t_h = (tx, ty, 0)`, the **left** normal is
   `n_flat = Z × t_h = (-ty, tx, 0)`. Signed lateral offset `d` is positive to the LEFT of travel.
   `side = +1` means left, `side = -1` right; a per-side outward distance `o >= 0` maps to
   `d = side * o`. UK vehicles keep left, so the nearside kerb of the forward lane is at `d = +w/2`.
4. **Arc length `s`** is measured along the resampled centreline (the chord sum of the dense
   Catmull-Rom evaluation, §5.4.1). Every `s0_m`, `s1_m`, `s_m` in the JSON means this `s`.
   `s1_m: null` means "to the end of the spline".
5. **Heights.** `z_ref(s)` is the smoothed terrain height at the centreline and is the road crown.
   The road surface at lateral `d` is `z_ref(s) + camber(d, w(s))` with `camber(0) = 0` and
   `camber(±w/2) = -c` (§5.7). The **road-edge level** `z_edge(s, side) = z_ref + camber(edge)` is the
   height reference (`h = 0`) of every Renderer B/C cross-section on that side.
6. **Vertex placement.** Every vertex is `V = p_i + d * n_i + h * b_i` where `p_i` is the sample
   position (with `z_ref`), `n_i` the *banked* left normal and `b_i = t_h × n_i` the banked up vector
   (§5.4.7). Sections live in vertical planes perpendicular to the horizontal direction of travel,
   rotated about `t_h` by the bank angle. This is what "project along the banked normal" means here.
7. **Materials are names** (strings) in JSON and in every `MeshBuffer`; ids are per-buffer integers
   assigned in first-use order (`MeshBuffer.material_id(name)`). Engines map names to slots.
8. **UVs are metres**: `u = s`, `v = metres across the section` (§5.5.4). Texture repeat is a material
   property (`materials.<name>.texture_repeat_m`), never baked into UVs.
9. **Determinism.** No randomness anywhere except the integer-hash noise of §5.10, seeded from the
   profile; the same JSON + heightfield gives bit-identical buffers on every run and platform.
10. **No LAPACK.** In the env python every LAPACK-backed `numpy.linalg` routine (`polyfit`, `lstsq`,
    `solve`, `svd`) kills the interpreter silently with exit code 127 (Appendix B). The core and the
    tests use only element-wise numpy, `np.cross`, `np.linalg.norm`, `np.interp`, `np.cumsum`,
    `np.searchsorted`. This is a rule, not a preference.

---

## 2. Requirement map: BRIEF §1.1 → this design

Every bullet of the verbatim spec (BRIEF.md:33-134) maps to a field or a function.

| Spec requirement (BRIEF.md line) | Where it lands |
|---|---|
| One shared spline is the source of truth; renderers read it (45) | `spline.Spline` object built once per JSON spline; Renderers A/B/C receive the *same instance*; they may locate the road edge only through `Spline.edge_offset(side)` and `Spline.edge_height(side)` (§5.4.9) |
| Variants are profiles + per-segment overrides (45) | `profiles.{road,edge,hedge}` + `splines[].segments[]` (§3.6); zero renderer code per variant |
| Single schema both engines read/write (49) | `streetscape.schema.draft.json`; `io_json.py` (§5.11); C++ `FStreetscapeJson` (§8) |
| Waypoints: position, optional width, bank, profile id, segment tags (54) | `Point {x, y, z?, roll_deg?, width_m?, tags[]}`, `profile_ids`, `segments[]` (§3.5) |
| Renderer A: flat/cambered/banked carriageway (64) | `road.build_road` (§5.7): ribbon sweep, `Camber {kind, crossfall_pct | camber_m}`, bank from §5.4.6 |
| A: lane count, per-lane widths, total width per segment, material, camber (65) | `RoadProfile {lanes, lane_widths_m, width_m, surface_material, camber}`; `Point.width_m`, `Segment.road.width_m` |
| A: markings are a list on the profile: offset, width, pattern, material (66-67) | `RoadProfile.markings[] : Marking {anchor, offset_m, width_m, pattern, dash_m, gap_m, phase_m, double_gap_m, material, lift_m}` |
| A: double yellow, single yellow, centre dashes as data (67) | §4.3 marking snippets; worked example 1 |
| A: markings in the same mesh pass as sub-meshes; no second spline (68) | `road.build_road` emits marking triangles into the *same* `MeshBuffer` with their own material ids, from the same `Frames` (§5.7.4). There is no marking renderer and no marking spline object anywhere in the package |
| B: vertical extrusion with a top lip (71) | kerb section §5.8.1 (face, lip arc, top, back) via `sweep.sweep` |
| B: samples the road's current edge offset at each point (72) | `Spline.edge_offset(side)` — the only source; asserted identical (§6 rule 2) |
| B: kerb width NOT fixed, kerb height, pavement width, drop-kerb list (73) | `EdgeProfile {kerb_width_m, kerb_height_m, pavement_width_m, drop_kerbs[]}` + `Segment.edge.*` ramped overrides + `splines[].drop_kerbs[]` |
| B: drop kerbs punch the lip and ramp height over a run; logic lives here (74) | `edge.drop_factor` (§5.8.2) scales kerb height and lip radius; nothing in `road.py` knows about drop kerbs |
| B: pavement here, not in A; shares seam and drop-kerb handling (75) | pavement is points E-F-G of the *same* kerb section (§5.8.1), so it shares the sweep, the seam and `drop_factor` by construction |
| B: walls/fences/railings are profile types with s-ranges (76) | `Barrier {s0_m, s1_m, type ∈ brick_wall|stone_wall|retaining_wall|chain_link|railing|none, height_m, thickness_m, material, post_pitch_m, offset_m}`; `edge.build_barriers` (§5.8.3) |
| B: half-grass/half-tarmac split material, flush top, ramps carry both (77) | `SplitMaterial {enabled, inner, outer, boundary_frac}`; split point S is a vertex on the top polyline at the same `h` as D and E → flush by construction (§5.8.1); drop factor applies to the whole section |
| C: a volume with foliage, not an extrusion (80) | `hedge.build_hedge` (§5.9): closed rounded-rectangle sweep + noise displacement + leaf-card instances |
| C: reads the same spline and same segment list as B (81) | `hedge.build_hedge(spline, side, side_spec, ...)` takes the `SideSpec` produced by `schema.resolve_side` — the identical object `edge.build_edge` consumed — and stacks behind `SideSpec.barrier_timeline` (§5.9.1) |
| Seam: never a 0-width join; top surface owns the seam; road extends past the kerb line; kerb tucks under (85-88) | `RoadProfile.overlap_m` (≥ 0.03, default 0.04) + `skirt_drop_m`; `EdgeProfile.tuck_depth_m/tuck_in_m`; rules §6 |
| Seam: both renderers re-sample the same edge offset on width change (89) | width is a function on the shared `Spline`; mandatory stations at every width knot (§5.4.3) |
| LIDAR: sample at each sample point; smooth; road and kerb inherit (92-94) | `Spline.build` steps 7-8 (§5.4.5); `z_ref` is on the shared object |
| LIDAR: tilt/bank to local terrain cross slope (95) | `spline.terrain_bank_deg` (§5.4.6), clamp `bank_max_deg` |
| LIDAR: tessellate tighter on curvature; sample height at each tessellated point (96) | `adaptive_stations` (§5.4.2); heights sampled at *every* station, never lerped between waypoints |
| LIDAR: cutting/embankment as extra profile entry on B (97) | `Embankment {s0_m, s1_m, side, kind, slope_ratio, material}`; `edge.build_embankments` (§5.8.4) |
| Rail: same architecture; hug LIDAR; sampling problem (100-102) | `RoadProfile.kind = "rail"` + `RailSpec`; `rail.build_rail` (§5.7.5); `sampling_defaults` step 1.0 / gain 60 / two smoothing passes |
| Data model Spline/RoadProfile/EdgeProfile/HedgeProfile (105-122) | §3 uses those names and adds only what the spec left implicit |
| First deliverable list (133) | worked example 1 (§3.8) exercises every item |

**WHAT NOT TO DO (BRIEF.md:124-130) → made structurally impossible**

| Prohibition | Why it cannot happen in this design |
|---|---|
| One renderer per marking / fence / kerb width | There are exactly three build functions (`road.build_road`, `edge.build_edge`, `hedge.build_hedge`) and no registry, factory or subclass hook. Marking, barrier and kerb variation are *data* consumed inside those functions; a fourth renderer would need a new file and a new schema section, both of which §7 tests would fail (`test_examples.py` checks the package exports exactly three builders). |
| Independent road-paint splines | `Marking` has no geometry of its own — no points, no sampling. Markings are emitted from the road's `Frames` object; the schema has no place to attach a spline to a marking. |
| Pavement in the road renderer | `RoadProfile` has no pavement field; `road.py` never imports `edge.py`; the pavement is a section polyline segment inside `edge.py`. |
| Hedges in the edge renderer | `EdgeProfile` has no hedge field; `edge.py` emits no closed volumes except walls; `hedge.py` is the only importer of `noise.py`. |
| Final meshes from OSM polygons | The schema holds OSM only as `Spline.overlay` (a debug polyline) and `Spline.source` (ids/tags). No renderer reads `overlay`. |
| Waiting for buildings/seafront | Nothing here references massing; the test stretch (BRIEF.md:332-339) runs on Margate data already on disk. |

---

## 3. The schema

Full machine-readable form: `streetscape.schema.draft.json`. This section is the normative prose;
field names below are exactly the JSON keys.

### 3.1 Top level

```
{
  "schema_version": "1.0.0",            semver; readers accept 1.x
  "site": "thanet",                     as sources/config/sites/<site>.json
  "crs": "EPSG:27700",
  "origin": {"E": 627680, "N": 163080}, local_x = E - origin.E ; local_y = N - origin.N
  "vertical_datum": "ODN",
  "frame": "local-metres, X east, Y north, Z up",   const; refuse anything else
  "generator": "sources/adapters/unreal.py@<sha>",
  "materials": { "<name>": MaterialHint, ... },     optional preview hints (base_color, roughness, two_sided, texture_repeat_m)
  "profiles": { "road": {id: RoadProfile}, "edge": {id: EdgeProfile}, "hedge": {id: HedgeProfile} },
  "splines": [ Spline, ... ],
  "junctions": [ Junction, ... ]                    placeholder, §3.7
}
```

Keys starting with `_` are notes and are allowed everywhere (the repo's configs use `_note`).
Unknown other keys are rejected (`additionalProperties: false`) so a typo cannot silently become
a default.

### 3.2 RoadProfile

| field | type / unit | default | meaning |
|---|---|---|---|
| `kind` | `road` \| `rail` | required | `rail`: the ribbon is the ballast bed, `rail` block required, tighter `sampling_defaults` |
| `lanes` | int | — | informational |
| `lane_widths_m` | number[] | — | informational; validation warns if the sum exceeds `width_m` |
| `width_m` | m ≥ 0 | required | base of the width function `w(s)`; rail: ballast top width |
| `surface_material` | name | required | |
| `camber` | `{kind: parabolic\|planar\|none, crossfall_pct?, camber_m?}` | required | §5.7.2 |
| `overlap_m` | m, 0.03..0.10 | 0.04 | road skirt past the kerb line (seam rule); schema floor 0.03 |
| `skirt_drop_m` | m, 0..0.03 | 0.02 | skirt drops this over `overlap_m` so it hides inside the kerb block |
| `lateral_station_spacing_m` | m | 1.0 | max spacing of the ribbon's lateral vertex rows |
| `markings[]` | Marking | required (may be `[]`) | §3.2.1 |
| `rail` | RailSpec | required iff kind = rail | §3.2.2 |
| `sampling_defaults` | Sampling | — | profile-level sampling defaults (rail sets them) |

#### 3.2.1 Marking

| field | type | default | meaning |
|---|---|---|---|
| `id` | string | — | for tests / stats |
| `anchor` | `centre` \| `edge_left` \| `edge_right` | `centre` | **`centre`: `offset_m` is signed, + = left of travel.** `edge_left`/`edge_right`: `offset_m ≥ 0` measured *inward* from that road edge, so the line follows width changes (yellow lines hug the kerb) |
| `offset_m` | m | required | strip centre (for `double`: centre of the pair) |
| `width_m` | m > 0 | required | width of ONE line |
| `pattern` | `solid` \| `dashed` \| `double` \| `none` | required | |
| `dash_m`, `gap_m` | m | required for dashed | dash k covers `s ∈ [phase + k(dash+gap), phase + k(dash+gap) + dash]` |
| `phase_m` | m | 0 | global along the spline → dashes continuous across segment boundaries |
| `double_gap_m` | m | required for double | clear gap between the two lines |
| `material` | name | required | |
| `lift_m` | m, 0..0.02 | 0.003 | strip above the carriageway (real thermoplastic 1.5-3 mm, memory) |
| `s0_m`, `s1_m` | m / null | whole spline | optional range |

Effective centre offset per sample: `centre → offset_m`; `edge_left → +edge_offset_L(s) − offset_m`;
`edge_right → −edge_offset_R(s) + offset_m`.

#### 3.2.2 RailSpec

`gauge_m` (inner faces of the rail heads, 1.435), `pad_m` (0.005), `rail {profile_id, height_m,
head_width_m, foot_width_m, web_thickness_m, head_depth_m, foot_thickness_m, material}`,
`sleeper {length_m, width_m, height_m, pitch_m, phase_m, embed_m (0.10), mode: instances|merged,
material}`, `ballast {top_width_m, shoulder_slope (horizontal per 1 vertical), depth_m, material}`.
Rail centrelines are at `d = ±(gauge_m/2 + head_width_m/2)` (§5.7.5).

### 3.3 EdgeProfile (side-agnostic; applied per side by the spline)

| field | type | default | meaning |
|---|---|---|---|
| `kerb_width_m` | m ≥ 0 | required | 0 = no kerb block (barrier-only or pavement-only edge) |
| `kerb_height_m` | m ≥ 0 | required | upstand above the road edge |
| `lip` | `{kind: radius\|chamfer\|none, size_m, arc_points}` | radius 0.02, 3 | scales with the drop factor |
| `pavement_width_m` | m ≥ 0 | required | 0 = no pavement |
| `pavement_crossfall_pct` | % | 2.5 | pavement rises away from the kerb |
| `pavement_max_crossfall_pct` | % | 8.0 | at drop kerbs the back edge is lowered only as far as needed to keep the crossfall under this |
| `tuck_depth_m` | m | 0.03 | kerb block starts this far below the road edge |
| `tuck_in_m` | m | 0.02 | kerb underside reaches this far under the road |
| `skirt_m` | m | 0.30 | back face extends this far below the road edge |
| `materials` | `{kerb, pavement}` | required | |
| `split_material` | `{enabled, inner, outer, boundary_frac}` | disabled | §5.8.1 |
| `drop_kerbs[]` | DropKerb | `[]` | `{s_m (start of flat run), length_m 1.83, ramp_m 0.915, target_height_m 0.006}` |
| `barriers[]` | Barrier | `[]` | `{s0_m, s1_m, type, height_m, thickness_m, material, coping_material, coping_overhang_m 0.025, coping_height_m 0.05, post_pitch_m, post_size_m 0.06, rails_m[], rail_size_m 0.04, offset_m 0, skirt_m 0.30}` |
| `embankments[]` | Embankment | `[]` | `{s0_m, s1_m, side: left\|right\|both\|downhill\|uphill\|auto, kind: batter\|retaining_wall\|auto, slope_ratio 1.5, wall_thickness_m 0.30, wall_coping_m 0.10, threshold_m 0.35, toe_extra_m 0.30, material}` |

The three lists inside a profile are the *baseline* for every spline that uses the profile. A
reusable library profile keeps them empty; a spline-specific inline profile (the test stretch) may
fill them. Spline-level `segments[]` and `drop_kerbs[]` layer on top (§3.6).

### 3.4 HedgeProfile

`width_m`, `height_m`, `top_profile: flat|rounded|domed`, `corner_radius_m` (0.15), `corner_points`
(4), `noise_amplitude_m` (0.06), `noise_scale_m` (0.6), `noise_seed` (1), `base_sink_m` (0.10),
`material`, `foliage {mode: none|cards|instances, density_per_m2 12, card_size_m 0.25, material,
mesh_id, seed}`, `segments[] {s0_m, s1_m, offset_m 0.1, height_override_m?, width_override_m?}`.
`offset_m` is the gap between the **barrier line** (outer face of the barrier in force in that
s-range, else the pavement back edge) and the hedge's inner face — so a hedge stacks beside a wall
or a fence without either knowing the other's geometry (§5.9.1).

### 3.5 Spline

```
{
  "id": "w4590626",
  "source": {"layer": "roads|rail|barriers|authored", "osm_id", "name", "cls", "tags": {...}, "tile": [i, j]},
  "profile_ids": {"road": id|null, "edge_left": id|null, "edge_right": id|null, "hedge_left": id|null, "hedge_right": id|null},
  "points": [ {"x", "y", "z"?: number|null, "roll_deg"?, "width_m"?, "tags": []}, ... ],   >= 2
  "sampling": Sampling (all optional),
  "segments": [ Segment, ... ],
  "drop_kerbs": [ {"side": left|right|both, "s_m", "length_m"?, "ramp_m"?, "target_height_m"?}, ... ],
  "overlay": {"kind": "osm_way", "pts": [[x, y(, z)], ...], "osm_id"},
  "junction_start": id|null, "junction_end": id|null
}
```

- `profile_ids.road = null` → no carriageway: `w(s) = 0`, `edge_offset = extras only`, camber none.
  This is how an OSM `barrier=wall` way becomes a spline: `edge_left = edge_wall_brick`, everything
  else null. `edge_right = null` → no kerb/pavement/barrier on the right at all.
- `points[].z`: a **pin** (forces the smoothed height there, blended over `pin_blend_m`). Omit it for
  heights from terrain — the adapter omits it for ordinary roads and sets it only for bridges/tunnels
  it chooses to raise (its decision, its number).
- `points[].width_m`: every point is a width knot (value = `width_m` if given else the road
  profile's `width_m`); `w(s)` is piecewise linear in `s` between knots and constant beyond the
  ends. A single override at one mid point therefore ramps to it from the neighbours and back.
- `points[].roll_deg`: bank override, + = left side up; §5.4.6 blends it with terrain bank.
- `points[].tags`: free strings; `junction:<id>` is the only convention this round.
- `sampling`: `step_m, min_step_m, curvature_gain, smoothing_window_m, smoothing_passes,
  width_ramp_m, bank_max_deg, bank_probe_min_half_width_m, pin_blend_m, extra_stations_m[]`.
  Precedence: `spline.sampling` > `road profile.sampling_defaults` > built-in (§4.1).

### 3.6 Left/right and per-side overrides — the resolution rule

Decision: **an `EdgeProfile` describes a kerb/pavement/barrier *type* and is side-agnostic; the
spline decides which profile applies to which side and layers s-ranged overrides per side.** The
brief's data model puts `dropKerbs[]` and `barrierSegments[]` on the profile (BRIEF.md:114-118); they
stay there as the baseline so that the spec's shape is honoured and a one-file test stretch can inline
a fully specified profile, but Thanet-scale variation is authored on the spline:

```
Segment {
  "s0_m", "s1_m" (null = end), "side": left|right|both|centre, "ramp_m"? (default sampling.width_ramp_m = 5.0),
  "road":  {"width_m"?, "profile_id"?, "edge_extra_left_m"?, "edge_extra_right_m"?, "markings"? (replaces), "markings_add"? (appends)},
  "edge":  {"profile_id"?, "kerb_width_m"?, "kerb_height_m"?, "pavement_width_m"?, "pavement_crossfall_pct"?, "split_material"?,
            "barrier"?: BarrierInline|null, "embankment"?: EmbankmentInline|null},
  "hedge": {"present", "profile_id"?, "offset_m"?, "height_m"?, "width_m"?}
}
```

Resolution (`schema.resolve_side(spline_def, side, profiles) -> SideTimeline`, `schema.resolve_road(...)
-> RoadTimeline`; both pure data, computed *before* sampling so they can contribute mandatory stations):

1. Start from `profile_ids.edge_<side>` (may be null → an empty profile with all widths 0).
2. **Scalars** (`kerb_width_m`, `kerb_height_m`, `pavement_width_m`, `pavement_crossfall_pct`,
   road `width_m`, `edge_extra_*`, hedge `height/width/offset`) are functions of `s`: baseline =
   profile value (or the point-knot function for road width); each applicable segment, in file order,
   applies `apply_ramped_override` (§5.4.4) over `[s0−ramp, s1+ramp]`. Later segments win.
3. **Profile switches** (`edge.profile_id`, `road.profile_id`) replace the whole baseline inside
   `[s0, s1]` for the *lists and materials* and are treated as a scalar override (with ramp) for the
   scalar fields — so switching `edge_uk_kerb → edge_uk_half_grass` at s = 60 changes materials
   exactly at the s = 60 station and ramps nothing (same dimensions).
4. **Lists** (`barriers`, `embankments`, hedge `segments`, `markings`) are resolved by *interval
   painting*: breakpoints = {0, L} ∪ all `s0/s1`; the value in force on each interval is the last
   layer that covers it, layers in the order: profile list (file order), then spline segments (file
   order). A segment block set to `null` (`"barrier": null`) paints "none". `markings` replaces,
   `markings_add` appends to the list in force.
5. **Drop kerbs**: union of the profile's `drop_kerbs[]` and the spline's `drop_kerbs[]` filtered by
   side (`both` → both sides). Overlapping drop kerbs combine by `max` of their drop factors (§5.8.2).
6. Everything with `s1_m: null` is clamped to `L`; any `s > L + 0.01` is a validation *warning* and is
   clamped (a way split at a tile seam may carry s from the parent).

The **same `SideTimeline`** is evaluated on the sample stations to a `SideSpec` (arrays over
samples) and handed to *both* `edge.build_edge` and `hedge.build_hedge`. That is the mechanism by which
Renderer C "reads the same segment list as Renderer B".

### 3.7 Junctions (placeholder, BRIEF §6 Q7)

```
Junction {"id", "x", "y", "z": number|null, "radius_m", "kind": disc|none,
          "ends": [{"spline_id", "end": start|end}, ...]}
```
plus `Spline.junction_start/junction_end` and the `junction:<id>` point tag. Step 06's `_junction`
records (`sources/OUTPUT.md:61-62`: one point, radius `r`) map to `kind: disc`, `radius_m = r`. In this
round no renderer reads junctions and spline ends are not trimmed; the schema simply reserves the
place, so adding junction geometry later is a new consumer of existing data, not a schema change.

### 3.8 Worked example 1 — residential road (Noble Gardens, Margate, OSM way 4590626)

Condensed; the full JSON is `examples[0]` in the draft schema. Real Margate coordinates
(`data/margate/out/networks/roads_x0_y2.jsonl`, way `4590626`, first/last vertices
E 633310.19 N 169735.05 → E 633309.79 N 169661.06, minus origin E 632800 N 168200).

```json
"profiles": {
  "road": { "road_residential_marked": {
    "kind": "road", "lanes": 2, "lane_widths_m": [3.0, 3.0], "width_m": 6.0, "surface_material": "tarmac",
    "camber": {"kind": "parabolic", "crossfall_pct": 2.5}, "overlap_m": 0.04, "skirt_drop_m": 0.02,
    "markings": [
      {"id": "centre_1004", "anchor": "centre", "offset_m": 0.0, "width_m": 0.10, "pattern": "dashed",
       "dash_m": 4.0, "gap_m": 2.0, "phase_m": 0.0, "material": "white_paint", "lift_m": 0.003},
      {"id": "dyl_left_1018_1", "anchor": "edge_left", "offset_m": 0.25, "width_m": 0.10, "pattern": "double",
       "double_gap_m": 0.10, "material": "yellow_paint", "lift_m": 0.003} ] } },
  "edge": { "edge_uk_kerb": {...§4.2...}, "edge_uk_half_grass": {...split inner tarmac / outer grass, boundary_frac 0.5...} },
  "hedge": { "hedge_privet": {...§4.2...} }
},
"splines": [{
  "id": "w4590626",
  "source": {"layer": "roads", "osm_id": "4590626", "name": "Noble Gardens", "cls": "residential", "tags": {"sidewalk": "both"}, "tile": [0, 2]},
  "profile_ids": {"road": "road_residential_marked", "edge_left": "edge_uk_kerb", "edge_right": "edge_uk_kerb",
                  "hedge_left": "hedge_privet", "hedge_right": null},
  "points": [ {"x": 510.19, "y": 1535.05}, {"x": 510.05, "y": 1495.05, "width_m": 6.0},
              {"x": 510.00, "y": 1485.05, "width_m": 7.0}, {"x": 509.79, "y": 1461.06, "tags": ["junction:j_noble_dentdelion"]} ],
  "sampling": {"step_m": 2.0, "min_step_m": 0.25, "curvature_gain": 20.0, "smoothing_window_m": 20.0, "smoothing_passes": 1,
               "width_ramp_m": 5.0, "bank_max_deg": 4.0},
  "segments": [
    {"id": "half_grass_right", "s0_m": 0.0, "s1_m": 60.0, "side": "right", "edge": {"profile_id": "edge_uk_half_grass"}},
    {"id": "wall_left", "s0_m": 0.0, "s1_m": 45.0, "side": "left",
     "edge": {"barrier": {"type": "brick_wall", "height_m": 1.2, "thickness_m": 0.215, "material": "brick_red", "coping_material": "coping_concrete", "offset_m": 0.0}},
     "hedge": {"present": true, "offset_m": 0.1}},
    {"id": "fence_left", "s0_m": 45.0, "s1_m": null, "side": "left",
     "edge": {"barrier": {"type": "chain_link", "height_m": 1.8, "thickness_m": 0.005, "material": "chain_link", "post_pitch_m": 3.0, "post_size_m": 0.06, "offset_m": 0.0}},
     "hedge": {"present": false}} ],
  "drop_kerbs": [ {"side": "left", "s_m": 70.0, "length_m": 1.83, "ramp_m": 0.915, "target_height_m": 0.006} ],
  "overlay": {"kind": "osm_way", "osm_id": "4590626", "pts": [[510.19, 1535.05], [510.02, 1490.10], [509.79, 1461.06]]},
  "junction_start": null, "junction_end": "j_noble_dentdelion"
}]
```

What it exercises, item by item of BRIEF.md:133: width 6 → 7 m between the knots at s ≈ 40 and
s ≈ 50 (points 2 and 3), double yellows on the left following that width change (`anchor:
edge_left`), TSRGD 1004 centre dashes, one pedestrian dropped kerb (left, s = 70), half-grass /
half-tarmac kerb on the right for s ∈ [0, 60], a brick wall switching to chain-link at s = 45 on the
left with a privet hedge behind the wall only, heights from the Margate DTM smoothed with W = 20 m,
the raw OSM way as overlay.

### 3.9 Worked example 2 — rail line

`examples[1]` in the draft. Profile `rail_standard` (§4.2) with `kind: rail`, `width_m 3.4` (=
ballast top), `camber none`, `rail {gauge 1.435, BS113A section, sleeper 2.5×0.25×0.15 at 0.65 m,
ballast 3.4 top / 1:1.5 shoulders / 0.45 deep}` and `sampling_defaults {step 1.0, min 0.25, gain 60,
window 40, passes 2, bank_max 6}`. The spline has six points through a gentle curve, no edge or hedge
profiles (all `null`), and its overlay. Nothing else is needed: rails, sleepers and ballast come out of
`road.build_road` because the profile's kind is `rail`.

### 3.10 Validation (two stages)

*Structural* (`io_json.validate_structure`, no geometry needed): required keys, types, enums,
ranges as in the draft schema; every `profile_ids.*` and `Segment.*.profile_id` resolves; `frame`
const; `schema_version` 1.x; `s0_m < s1_m` (when `s1_m` not null); `boundary_frac ∈ [0,1]`; dashed
markings have `dash_m, gap_m`; doubles have `double_gap_m`; rail profiles have `rail`; every material
name used is either in `materials` or is reported as "unhinted" (warning, not error).
*Semantic* (`schema.validate_site` after `Spline.build`): `s` values ≤ L + 0.01 (warn+clamp);
`sum(lane_widths_m) ≤ width_m` (warn); overlapping segments on the same side reported (info);
`overlap_m ≥ 0.03` and `tuck_depth_m > skirt_drop_m` (error — the seam rule would break).

### 3.11 Versioning

`schema_version` is semver. 1.x readers ignore unknown *optional* fields under a `_`-prefixed key
only; any other unknown key is an error, so additive changes bump the minor version and update the
schema file in the same commit. Renaming or re-meaning a field is 2.0.

---

## 4. UK defaults and the ten default profiles

### 4.1 Sampling defaults (built-in)

| | road | rail | why |
|---|---|---|---|
| `step_m` | 2.0 | 1.0 | chord sagitta at R = 200 m with the road step (after gain, 1.82 m) is 2.1 mm; rail at R = 300 m (0.83 m step) 0.3 mm |
| `min_step_m` | 0.25 | 0.25 | floor so a kink cannot explode the sample count |
| `curvature_gain` | 20 | 60 | `step = step_m / (1 + gain·κ)`: road R = 20 m → 1.0 m (measured 0.995, App. A); rail R = 300 m → 0.83 m, R = 100 m → 0.63 m |
| `smoothing_window_m` | 20 | 40 | 11 samples at 2 m: attenuates σ = 0.1 m sample noise by ≥ 3.5× (measured 4.0×, App. A); bias on a vertical curve of radius R_v is W²/(24 R_v): 2.6 cm at R_v = 650 m (a 30 mph crest, DMRB K ≈ 6.5, memory); rail is straighter vertically so 40 m is safe and hides ballast-shoulder noise |
| `smoothing_passes` | 1 | 2 | second pass gives a triangular kernel (measured 4.2× at W = 20) |
| `width_ramp_m` | 5.0 | 5.0 | a 1 m width change over 5 m is a 1:5 build-out taper; kerb build-outs are typically 1:5–1:10 (memory); per-segment `ramp_m` overrides |
| `bank_max_deg` | 4.0 | 6.0 | 4° ≈ 7% = DMRB CD 109 maximum superelevation (memory); rail 150 mm maximum cant over 1.505 m centres = 5.7° (memory) |
| `bank_probe_min_half_width_m` | 1.5 | 1.5 | probe at ≥ 1.5 m so a 1.8 m footway does not sample within one DTM pixel |
| `pin_blend_m` | 10.0 | 10.0 | |

### 4.2 Dimensions and their sources

| quantity | default | source / justification |
|---|---|---|
| Kerb width | 0.125 m | HB2 half-batter kerb 125 × 255 mm and BN bull-nosed 125 × 150 mm are the common UK precast units (BS 7263 profiles, now BS EN 1340) — memory; 150 mm (HB1) is the alternative |
| Kerb upstand | 0.125 m | typical UK design upstand 100–125 mm (memory); `tuning.json → furniture.kerb_m 0.12` is the pipeline's own prior for pavement-top height above the carriageway (`sources/config/tuning.json`, furniture block) |
| Kerb lip | radius 0.02 m | bull-nose/half-batter arris ~15–25 mm (memory) |
| Drop kerb | flat 1.83 m, ramps 0.915 m, upstand 6 mm | dropper kerbs (DL1/DL2) are 915 mm units; a pedestrian dropped crossing has ≤ 6 mm upstand (DfT *Inclusive Mobility* / tactile paving guidance, memory); 25 mm for vehicle crossings |
| Pavement width | 1.8 m | *Inclusive Mobility*: 2.0 m preferred, 1.5 m minimum (memory); `tuning.json → roads.widths_m` gives 1.5–2.0 per class (`sources/config/tuning.json:4-22`) and the adapter should pass the class value through a segment override |
| Pavement crossfall | 2.5 % (max 8 % at drops) | 1 in 40 footway crossfall; dropped-kerb ramps ≤ 1:12 (memory) |
| Carriageway crossfall | 2.5 % | DMRB CD 109 normal crossfall 2.5 % (memory) |
| Centre line (TSRGD diagram 1004) | 100 mm, 4 m mark / 2 m gap | Traffic Signs Manual Ch. 5: 1004 at ≤ 40 mph (memory) |
| Warning line (1004.1) | 100 mm, 6 m / 3 m | Ch. 5 (memory) |
| Lane line (1005) | 100 mm, 2 m / 7 m | Ch. 5, ≤ 40 mph (memory) |
| Edge line (1012.1) | 150 mm solid | Ch. 5 (100/150/200 mm variants; memory) |
| Double yellow (1018.1) | two 100 mm lines, 100 mm apart, 250 mm from the kerb | Ch. 5; the narrow variant is 50 mm lines 50 mm apart in conservation areas (memory) |
| Single yellow (1017) | one 100 mm line, 250 mm from the kerb | memory |
| Marking lift | 3 mm | thermoplastic screed markings are laid 1.5–3 mm thick (memory); §9 Q5 |
| Rail gauge | 1.435 m | standard gauge, definitional |
| Rail section BS113A (56E1) | height 158.75, head 69.85, foot 139.7, web 20 mm | 6¼ in, 2¾ in, 5½ in — memory, internally consistent |
| Sleeper | 2.5 × 0.25 × 0.15 m at 0.65 m pitch, embedded 0.10 m | task brief; Network Rail concrete sleeper spacing 650–700 mm (memory) |
| Ballast | top 3.4 m (2.5 + 2 × 0.45 shoulder), 1:1.5 shoulders, 0.45 m to formation | shoulder 0.3–0.5 m beyond sleeper ends, ≥ 0.3 m under the sleeper (memory) |
| Brick wall | thickness 0.215 m, coping 50 mm × 25 mm overhang | one UK brick length 215 mm (215 × 102.5 × 65 mm, definitional) |
| Chain link | 1.8 m high, posts every 3.0 m, 60 mm posts | common domestic/industrial spec (memory) |
| Pedestrian railing | 1.1 m high, posts every 2.0 m, rails at 1.08 / 0.55 / 0.10 m | BS 7818 guardrail ~1.0–1.1 m (memory) |
| Privet hedge | 0.8 m wide, 1.5 m high | trimmed garden privet 0.6–1.2 wide, 1.2–2.0 high (memory) |

### 4.3 Marking snippets (copy into `RoadProfile.markings` / `Segment.road.markings_add`)

```json
{"id": "centre_1004",      "anchor": "centre",     "offset_m": 0.0,  "width_m": 0.10, "pattern": "dashed", "dash_m": 4.0, "gap_m": 2.0, "phase_m": 0.0, "material": "white_paint", "lift_m": 0.003}
{"id": "warning_1004_1",   "anchor": "centre",     "offset_m": 0.0,  "width_m": 0.10, "pattern": "dashed", "dash_m": 6.0, "gap_m": 3.0, "phase_m": 0.0, "material": "white_paint", "lift_m": 0.003}
{"id": "lane_1005",        "anchor": "centre",     "offset_m": 3.65, "width_m": 0.10, "pattern": "dashed", "dash_m": 2.0, "gap_m": 7.0, "phase_m": 0.0, "material": "white_paint", "lift_m": 0.003}
{"id": "edge_left_1012_1", "anchor": "edge_left",  "offset_m": 0.20, "width_m": 0.15, "pattern": "solid",  "material": "white_paint", "lift_m": 0.003}
{"id": "dyl_left_1018_1",  "anchor": "edge_left",  "offset_m": 0.25, "width_m": 0.10, "pattern": "double", "double_gap_m": 0.10, "material": "yellow_paint", "lift_m": 0.003}
{"id": "dyl_right_1018_1", "anchor": "edge_right", "offset_m": 0.25, "width_m": 0.10, "pattern": "double", "double_gap_m": 0.10, "material": "yellow_paint", "lift_m": 0.003}
{"id": "syl_left_1017",    "anchor": "edge_left",  "offset_m": 0.25, "width_m": 0.10, "pattern": "solid",  "material": "yellow_paint", "lift_m": 0.003}
{"id": "dyl_left_narrow",  "anchor": "edge_left",  "offset_m": 0.25, "width_m": 0.05, "pattern": "double", "double_gap_m": 0.05, "material": "yellow_paint", "lift_m": 0.003}
```
"Double yellow on one side + centre dashes" = `centre_1004` + `dyl_left_1018_1`; "single yellow
both sides" = `syl_left_1017` + its `edge_right` twin. No code.

### 4.4 The ten default profiles (`projects/one/schema/profiles/<id>.json`)

Each file is `{"kind": "road"|"edge"|"hedge", "id": "...", "profile": {...}}` so the UE bootstrap can
create the DataAsset from the file name alone. Contents:

```json
road_residential: {"kind": "road", "lanes": 2, "lane_widths_m": [3.0, 3.0], "width_m": 6.0, "surface_material": "tarmac",
  "camber": {"kind": "parabolic", "crossfall_pct": 2.5}, "overlap_m": 0.04, "skirt_drop_m": 0.02, "lateral_station_spacing_m": 1.0, "markings": []}
road_primary:     {"kind": "road", "lanes": 2, "lane_widths_m": [3.65, 3.65], "width_m": 10.0, "surface_material": "tarmac",
  "camber": {"kind": "parabolic", "crossfall_pct": 2.5}, "overlap_m": 0.04, "skirt_drop_m": 0.02, "lateral_station_spacing_m": 1.0,
  "markings": [ centre_1004 ]}
road_service:     {"kind": "road", "lanes": 1, "lane_widths_m": [3.5], "width_m": 3.5, "surface_material": "tarmac",
  "camber": {"kind": "planar", "crossfall_pct": 2.5}, "overlap_m": 0.04, "skirt_drop_m": 0.02, "markings": []}
rail_standard:    {"kind": "rail", "lanes": 1, "width_m": 3.4, "surface_material": "ballast", "camber": {"kind": "none"},
  "overlap_m": 0.04, "skirt_drop_m": 0.0, "markings": [],
  "rail": {"gauge_m": 1.435, "pad_m": 0.005,
           "rail": {"profile_id": "BS113A", "height_m": 0.15875, "head_width_m": 0.06985, "foot_width_m": 0.1397, "web_thickness_m": 0.020, "head_depth_m": 0.045, "foot_thickness_m": 0.011, "material": "rail_steel"},
           "sleeper": {"length_m": 2.5, "width_m": 0.25, "height_m": 0.15, "pitch_m": 0.65, "phase_m": 0.0, "embed_m": 0.10, "mode": "instances", "material": "sleeper_concrete"},
           "ballast": {"top_width_m": 3.4, "shoulder_slope": 1.5, "depth_m": 0.45, "material": "ballast"}},
  "sampling_defaults": {"step_m": 1.0, "min_step_m": 0.25, "curvature_gain": 60.0, "smoothing_window_m": 40.0, "smoothing_passes": 2, "bank_max_deg": 6.0}}
edge_uk_kerb:     {"kerb_width_m": 0.125, "kerb_height_m": 0.125, "lip": {"kind": "radius", "size_m": 0.02, "arc_points": 3},
  "pavement_width_m": 1.8, "pavement_crossfall_pct": 2.5, "pavement_max_crossfall_pct": 8.0,
  "tuck_depth_m": 0.03, "tuck_in_m": 0.02, "skirt_m": 0.30,
  "materials": {"kerb": "concrete_kerb", "pavement": "paving_slab"}, "split_material": {"enabled": false}, "drop_kerbs": [], "barriers": [], "embankments": []}
edge_uk_half_grass: {same as edge_uk_kerb but "materials": {"kerb": "concrete_kerb", "pavement": "grass"},
  "split_material": {"enabled": true, "inner": "tarmac", "outer": "grass", "boundary_frac": 0.5}}
edge_wall_brick:  {"kerb_width_m": 0.0, "kerb_height_m": 0.0, "lip": {"kind": "none"}, "pavement_width_m": 0.0,
  "materials": {"kerb": "concrete_kerb", "pavement": "grass"}, "split_material": {"enabled": false}, "drop_kerbs": [], "embankments": [],
  "barriers": [{"s0_m": 0.0, "s1_m": null, "type": "brick_wall", "height_m": 1.8, "thickness_m": 0.215, "material": "brick_red", "coping_material": "coping_concrete", "coping_overhang_m": 0.025, "coping_height_m": 0.05, "offset_m": 0.0, "skirt_m": 0.30}]}
edge_chain_link:  {...as edge_wall_brick with "barriers": [{"s0_m": 0.0, "s1_m": null, "type": "chain_link", "height_m": 1.8, "thickness_m": 0.005, "material": "chain_link", "post_pitch_m": 3.0, "post_size_m": 0.06, "offset_m": 0.0}]}
edge_railing:     {...as edge_wall_brick with "barriers": [{"s0_m": 0.0, "s1_m": null, "type": "railing", "height_m": 1.1, "thickness_m": 0.05, "material": "steel_painted_black", "post_pitch_m": 2.0, "post_size_m": 0.05, "rails_m": [1.08, 0.55, 0.10], "rail_size_m": 0.04, "offset_m": 0.0}]}
hedge_privet:     {"width_m": 0.8, "height_m": 1.5, "top_profile": "flat", "corner_radius_m": 0.15, "corner_points": 4,
  "noise_amplitude_m": 0.06, "noise_scale_m": 0.6, "noise_seed": 1, "base_sink_m": 0.10, "material": "privet_leaf",
  "foliage": {"mode": "cards", "density_per_m2": 12, "card_size_m": 0.25, "material": "privet_leaf", "seed": 1},
  "segments": [{"s0_m": 0.0, "s1_m": null, "offset_m": 0.1}]}
```

The barrier-only edge profiles (`edge_wall_brick`, `edge_chain_link`, `edge_railing`) have zero kerb
and pavement so Renderer B emits only the barrier sweep; they are what the adapter assigns to OSM
`barrier=*` ways (467 in Margate, BRIEF.md:200), with `profile_ids.road = null`.

Material names used by the defaults: `tarmac, white_paint, yellow_paint, concrete_kerb,
paving_slab, grass, brick_red, coping_concrete, chain_link, post_steel, steel_painted_black,
privet_leaf, ballast, sleeper_concrete, rail_steel, stone_flint, concrete_wall`.

---

## 5. The geometry core — `projects/one/Tools/blender/streetscape/`

### 5.1 Package layout

```
streetscape/
  __init__.py       __version__, re-exports: load_site, build_spline, MeshBuffer
  schema.py         dataclasses for every JSON object + resolve_road/resolve_side + validate_site
  io_json.py        load/save/validate_structure (stdlib json only)
  terrain.py        Heightfield (bilinear, NaN off-coverage) — matches 06_build_networks.ground()
  spline.py         Spline: Catmull-Rom, adaptive stations, width/roll functions, heights, bank, Frames
  sweep.py          Section / SectionPoint / sweep()  — THE one cross-section sweep routine
  mesh.py           MeshBuffer + triangulate_polygon_2d + measurements for tests
  noise.py          lowbias32, unit_noise, value_noise3, fbm3 (shared by hedge.py and tests)
  road.py           Renderer A: build_road (dispatches to rail.build_rail for kind == rail)
  rail.py           ballast / sleepers / rails (called only from road.py)
  edge.py           Renderer B: build_edge (kerb + pavement + drop kerbs + split + barriers + embankments)
  hedge.py          Renderer C: build_hedge (volume + noise + leaf-card instances)
  build.py          build_spline(site, spline_id, terrain) -> BuildResult; CLI writes .npz + stats.json (no bpy)
  bpy_bridge.py     MeshBuffer -> bpy mesh/object/collection; instances; glTF export  (imports bpy lazily)
  render.py         Workbench renders from 3 fixed cameras (bpy)
  blender_main.py   `blender.exe -b --python blender_main.py -- --site X.json --terrain DIR --out DIR [--gltf] [--render]`
```

`rail.py` is a separate *file* but not a separate renderer: it has no public entry point other than
`build_rail`, which is called only by `road.build_road` when `profile.kind == "rail"` (BRIEF.md:293).

Dependency rule (checked by `test_examples.py` via `sys.modules` inspection after import): `road.py`,
`edge.py`, `hedge.py` import `spline`, `sweep`, `mesh`, `schema` (and `noise` for hedge, `rail` for
road) and never each other.

### 5.2 `schema.py`

One `@dataclass(frozen=True)` per JSON object, field names = JSON keys, with `from_dict(d)` /
`to_dict()` and defaults exactly as in the draft schema: `MaterialHint, Sampling, Camber, Marking,
RailSection, Sleeper, Ballast, RailSpec, RoadProfile, Lip, SplitMaterial, DropKerb, Barrier,
Embankment, EdgeProfile, Foliage, HedgeSegment, HedgeProfile, Point, SegmentRoad, SegmentEdge,
SegmentHedge, Segment, SplineDropKerb, Source, Overlay, ProfileIds, SplineDef, Junction, Site`.

Resolution (pure data, §3.6):

```python
def resolve_sampling(spline: SplineDef, road: RoadProfile | None) -> Sampling
def resolve_road(spline: SplineDef, site: Site) -> RoadTimeline
    # .profile_intervals: list[(s0, s1, RoadProfile)]        painted
    # .width_knots: (K,2) [s_k, w_k] from points (s_k filled in by Spline after the dense curve exists)
    # .width_overrides: list[(s0, s1, ramp, w)]              from segments, file order
    # .extra_overrides[side]: list[(s0, s1, ramp, value)]
    # .markings: list[(s0, s1, list[Marking])]               painted (replace / add)
    # .camber: Camber ; .overlap_m ; .skirt_drop_m ; .kind
def resolve_side(spline: SplineDef, side: int, site: Site) -> SideTimeline
    # .scalar_overrides: dict[name -> list[(s0, s1, ramp, value)]]   baseline value first
    # .material_intervals: list[(s0, s1, materials, split)]          painted
    # .barriers / .embankments / .hedges: list[(s0, s1, spec|None)]  painted
    # .drop_kerbs: list[DropKerb]
    # .mandatory_stations() -> sorted list of s to force into the sample set
def paint_intervals(L: float, layers: list[tuple[float, float | None, Any]]) -> list[tuple[float, float, Any]]
def apply_ramped_override(s: np.ndarray, base: np.ndarray, s0: float, s1: float, ramp: float, value: float) -> np.ndarray
    # base copy; s in [s0-ramp, s0]: lerp(base, value, (s-(s0-ramp))/ramp); [s0,s1]: value; [s1, s1+ramp]: lerp(value, base, (s-s1)/ramp)
def validate_site(site: Site, built: dict[str, "Spline"]) -> list[str]     # semantic warnings/errors (§3.10)
```

`SideTimeline.evaluate(s: np.ndarray) -> SideSpec` produces arrays over the N stations:
`kerb_width, kerb_height, pavement_width, crossfall, lip_size (N,)`, `present (N,) bool`,
`mat_kerb, mat_pavement, mat_inner, mat_outer (N,) object`, `split_frac (N,) or None`,
`drop_factor (N,)` (§5.8.2), `barrier_timeline, embankment_timeline, hedge_timeline` (lists of
`(s0, s1, spec)` with `spec` possibly `None`), `tuck_depth, tuck_in, skirt, max_crossfall` scalars.

### 5.3 `terrain.py`

```python
class Heightfield:
    """Tiled north-up float grid. Pixel centres at (x_west + c*px, y_north - r*px). NaN = no data."""
    origin_xy: tuple[float, float]     # local metres of the site origin (always (0,0) in the JSON frame)
    tile_m: float; res: int; px_m: float
    tiles: dict[tuple[int, int], np.ndarray]     # (res, res) float32, row 0 = north, NaN where nodata/clipped
    @classmethod
    def from_adapter_dir(cls, path: str) -> "Heightfield"      # heightfield_manifest.json + hf_x{i}_y{j}.f32 (np.fromfile('<f4'))
    @classmethod
    def from_step05_dir(cls, path: str) -> "Heightfield"       # optional: GDAL present (env python) -> reads terrain/dtm_x*_y*.tif
    @classmethod
    def from_function(cls, fn, extent_m: tuple[float, float], px_m: float = 1.0, tile_m: float = 512.0) -> "Heightfield"   # tests
    def sample(self, x: np.ndarray, y: np.ndarray) -> np.ndarray   # (N,) float64, NaN off coverage or on nodata
```

`sample` reproduces `ground()` in `sources/derive/06_build_networks.py:54-69` exactly. That function
computes `fx = (e − gt[0])/gt[1] − 0.5`, `fy = (n − gt[3])/gt[5] − 0.5` on the interim VRT mosaic and
bilinearly interpolates between pixel *centres*, clamping the last row/column inward
(`x0 = min(x0, W−2)`), returning "no value" when the result is not finite or the point is outside
`[0, W−1] × [0, H−1]`. The Margate tiles have `gt = (E_west − 0.5, 1.0, 0, N_north + 0.5, 0, −1.0)`
(measured this session on `data/margate/raw/lidar/dtm_x0_y0.tif`: `(632799.5, 1.0, 0.0, 168712.5,
0.0, −1.0)`, nodata −3.4028e38; `data/margate/out/terrain/dtm_x0_y0.tif` identical transform, nodata
None), so `fx = e − E_west` and `fy = N_north − n` — pixel-centre coordinates are integer metres.
Hence, per query point:

```
i = floor(x / tile_m) ; j = floor(y / tile_m)                      tile index (local metres, origin (0,0))
if (i, j) not in tiles: NaN
cx = (x - i*tile_m) / px_m ;  ry = ((j+1)*tile_m - y) / px_m       pixel-centre coordinates in [0, res-1]
x0 = min(floor(cx), res-2) ; y0 = min(floor(ry), res-2) ; tx = cx - x0 ; ty = ry - y0
v = (a(1-tx) + b tx)(1-ty) + (c(1-tx) + d tx) ty   with a=T[y0,x0], b=T[y0,x0+1], c=T[y0+1,x0], d=T[y0+1,x0+1]
NaN if any of a,b,c,d is NaN
```

Because adjacent tiles share their edge row/column (`sources/OUTPUT.md:25-27`, verified this
session: column 512 of `dtm_x0_y0` equals column 0 of `dtm_x1_y0`), a point exactly on a tile
boundary gives the same value from either tile, and the per-tile sampler equals the mosaic sampler
everywhere. The one intended difference from step 06: step 06 samples the *raw* mosaic and carries
gaps forward; the adapter's heightfield is step 05's *filled* terrain (`sources/derive/05_export_terrain.py:45`)
with Thanet's clipped cells as NaN (BRIEF.md:222). Vectorised with `np.floor`, fancy indexing per tile
group (`np.unique` on tile ids) — no Python loop per point.

### 5.4 `spline.py`

```python
@dataclass
class Frames:
    s: np.ndarray      # (N,)
    p: np.ndarray      # (N,3) position incl. z_ref
    t_h: np.ndarray    # (N,3) unit horizontal tangent
    n_flat: np.ndarray # (N,3) Z x t_h  (horizontal left normal)
    n: np.ndarray      # (N,3) banked left normal
    b: np.ndarray      # (N,3) t_h x n  (banked up)
    def at(self, s_query: np.ndarray) -> "Frames"          # linear interp of p; n, b interpolated and renormalised (b = t_h x n)
    def insert(self, s_extra: np.ndarray) -> "Frames"      # union of stations, sorted, duplicates within 1e-9 dropped

class Spline:
    def __init__(self, sdef: schema.SplineDef, site: schema.Site, terrain: terrain.Heightfield): ...   # builds everything
    # results
    sampling: schema.Sampling ; length: float
    s: (N,) ; xy: (N,2) ; kappa: (N,) signed (+ = turning left) ; mandatory: (N,) bool
    width: (N,) ; extra_left, extra_right: (N,)
    z_raw: (N,) (NaN kept for stats) ; z_ref: (N,) ; bank_deg: (N,)
    frames: Frames
    road: RoadTimeline ; camber: schema.Camber ; kind: str
    side_spec: dict[int, SideSpec]        # {+1: left, -1: right}
    # the ONLY edge-location API renderers may use:
    def edge_offset(self, side: int) -> np.ndarray     # (N,) = width/2 + extra(side)            (>= 0)
    def edge_height(self, side: int) -> np.ndarray     # (N,) = surface_h(side * edge_offset)     (<= 0, relative to z_ref)
    def surface_h(self, d: np.ndarray) -> np.ndarray   # (N,) camber height at signed lateral d per sample (§5.7.2)
```

Build order (each step a module-level function so tests can call them alone):

**5.4.1 Curve** — `catmull_rom_dense(P: (K,2), alpha=0.5, max_chord_m=0.1) -> (s_d: (D,), xy_d: (D,2), s_knots: (K,))`.
Centripetal Catmull-Rom (Barry–Goldman pyramid with knot spacing `t_{i+1} − t_i = |P_{i+1} − P_i|^0.5`,
phantom end points `P_{-1} = 2P_0 − P_1`, `P_K = 2P_{K−1} − P_{K−2}`), each segment evaluated at
`max(8, ceil(chord/0.1))` + 1 parameters, cumulative chord length → `s_d`. `s_knots[k]` is the `s_d`
at which waypoint k is hit exactly. Two-point splines are straight lines.

*Why centripetal Catmull-Rom and not a cubic B-spline.* The waypoints are OSM-snapped positions
(and, from the adapter, step 06's Chaikin-smoothed 2 dp vertices, `06_build_networks.py:161,195`): the
curve must pass *through* them so that (a) junction endpoints are hit exactly and two splines meeting
at a node agree to the centimetre, (b) the width knots and pins authored on points apply where the
author put them. A uniform cubic B-spline approximates its control points (it misses a corner by up
to a sixth of the neighbouring chord) and would need control-point solving (LAPACK, §1.10) to
interpolate. Catmull-Rom is C1, which is all the frames need (curvature is only used for the step
size), and the centripetal parameterisation is the one that provably has no cusps or
self-intersections within a segment (Yuksel, Schaefer & Keyser 2011). Unreal's `USplineComponent`
(`Engine/Source/Runtime/Engine/Classes/Components/SplineComponent.h:214`) uses Hermite segments with
its own tangent rule; the C++ port implements this Catmull-Rom itself (`FStreetSplineMath::CatmullRom`)
so both sides produce the same `s` (§8).

**5.4.2 Adaptive stations** — `adaptive_stations(s_d, kappa_d, sampling, mandatory: (M,)) -> s: (N,)`:

```
κ_d      = |Δθ/Δs| from consecutive unit tangents of the dense curve (np.gradient of the tangent, no atan2 wrap issues: use |dT/ds|)
step(κ)  = clip(step_m / (1 + curvature_gain * κ), min_step_m, step_m)
march:   s = 0; while s + step(κ(s)) < L − min_step_m: s += step(κ(s)); append   → append L last
merge:   drop adaptive stations within min_step_m/2 of any mandatory station (mandatory wins), union, sort
```
Guarantees: `s[0] = 0`, `s[-1] = L`, strictly increasing, every mandatory station present as the
*exact* float it was given (so `np.searchsorted(s, s0) ` hits), final gap ∈ `[min_step, step + min_step)`,
no adaptive gap below `min_step_m`, no gap above `step_m`. Mandatory stations (from
`RoadTimeline` and both `SideTimeline`s, §3.6): all waypoint `s_knots`; every `s0, s1, s0−ramp,
s1+ramp` of every segment scalar override; every `s0, s1` of every painted interval (barriers,
embankments, hedges, markings, profile switches); every drop kerb's `s−ramp, s, s+len, s+len+ramp`;
`sampling.extra_stations_m`. All clamped to `(0, L)`. Because the *same* station set is used for
every renderer, "both renderers use identical s-samples" holds by construction and is still asserted
(§6 rule 2). Measured behaviour: straight 100 m → 51 stations at exactly 2.0 m; a 20 m-radius bend →
mean spacing 0.995 m vs 1.991 m on the straights (ratio 2.00); a 5 m-amplitude 50 m-period sine →
0.82 m at the crests vs 1.60 m at the inflections (App. A).

**5.4.3 Width and extras** — `w(s)`: `np.interp(s, s_knots, w_knots)` (constant beyond the ends),
then `apply_ramped_override` for each `Segment.road.width_m` in file order; `extra_left/right(s)`
likewise from 0. `edge_offset(side) = w/2 + extra(side)`. Mandatory stations at every knot and
every ramp end mean `w(s)` is exactly piecewise linear *between samples*, so both renderers see the
same kerb-line offset at every station and linear interpolation between stations is exact.

**5.4.4 Roll** — `roll_pl(s) = np.interp(s, s_knots[has_roll], roll[has_roll])` and a mask
`m(s) = np.interp(s, s_knots, has_roll.astype(float))` (1 at points that set `roll_deg`, 0 elsewhere,
linear between). Used in 5.4.6.

**5.4.5 Heights** —
```
z_raw  = terrain.sample(x, y)                                        (N,), NaN where none
z_fill = fill_nan_along(z_raw)      carry nearest valid forward then backward along s (as 06_build_networks.py:176-182); all-NaN → 0 and Spline.warnings += [...]
z_s    = moving_average_arclength(s, z_fill, W, passes)
z_ref  = apply_pins(z_s, s, pins, pin_blend_m)
```
`moving_average_arclength(s, z, W, passes)`: for each i, `hw_i = min(W/2, s_i − s_0, s_N − s_i)`;
`z'_i = mean(z_j : |s_j − s_i| ≤ hw_i + 1e-9)`; uniform sample weights (denser samples on bends weigh
more; acceptable because W ≫ step); repeat `passes` times. Vectorised with `np.searchsorted` on
`s ± hw` and a cumulative sum. **Edge handling: the window shrinks symmetrically to zero at the
ends**, so `z'_0 = z_0` and `z'_N = z_N` exactly — two splines meeting at a junction node both keep
the raw terrain height there and agree bit-for-bit; the first W/2 metres are progressively less
smoothed (accepted; the junction round will replace the endpoint rule). `apply_pins`: for each pinned
point k: `z += (z_pin − z_s(s_k)) · max(0, 1 − |s − s_k| / pin_blend_m)`.

**5.4.6 Bank** —
```
h_probe  = max(w/2, bank_probe_min_half_width_m)                                 per sample
zl, zr   = terrain.sample(xy + h_probe·n_flat.xy), terrain.sample(xy − h_probe·n_flat.xy)
β_raw    = degrees(atan2(zl − zr, 2 h_probe)) ; NaN → 0
β_t      = clip(moving_average_arclength(s, β_raw, W, 1), −bank_max_deg, +bank_max_deg)
β        = (1 − m(s))·β_t + m(s)·roll_pl(s)                                      roll overrides are NOT clamped
```
Positive β = left side up (the road leans with a hillside rising to the left). A terrain plane
`z = 0.1·y` under a road along +x gives β_raw = atan(0.1) = 5.71°, clamped to 4.0° (test §7.2).

**5.4.7 Frames** — `t_h = normalize(dx, dy, 0)` from the dense curve; `n_flat = (−t_y, t_x, 0)`;
`n = n_flat·cos β + Z·sin β` (rotation about `t_h`, since `t_h × n_flat = Z`); `b = t_h × n =
−n_flat·sin β + Z·cos β`. Sections are therefore vertical planes perpendicular to the horizontal
direction of travel, rotated by the bank — kerb faces are vertical on an unbanked road regardless
of grade, and every vertex is `p + d·n + h·b` (§1.6). Height differences along the path live in `p.z`.

**5.4.8 Curvature at stations** — `np.interp(s, s_d, κ_signed_d)`; sign from the z-component of
`t_h[i] × t_h[i+1]`. Stored for stats and for the rail tessellation test.

**5.4.9 The shared-edge contract** — `edge_offset(side)` and `edge_height(side)` are the *only*
functions in the package that know where the kerb line is. `road.py` uses them to place the skirt,
`edge.py` to place the kerb, `hedge.py` indirectly through `SideSpec` (which stores the back-edge
offset computed from `edge_offset`). A grep for `width / 2` outside `spline.py` must return nothing
(`test_examples.py` greps the package source for `width` arithmetic outside `spline.py` and fails if
found).

### 5.5 `sweep.py` — the one cross-section sweep

```python
@dataclass(frozen=True)
class SectionPoint:
    o: float          # lateral coordinate in section space (m). Side sweeps: outward from the kerb line, >= 0 away from the carriageway. Centre sweeps: signed d.
    h: float          # height above the section reference (m)
    mat: str          # material of the EDGE leaving this point toward the next point (ignored on the last point of an open section)
    v: float          # UV v (metres across the section)
    smooth: bool = False   # False = hard crease at this point: the vertex is duplicated so the two edges get separate normals

@dataclass(frozen=True)
class Section:
    points: tuple[SectionPoint, ...]
    closed: bool
    # Orientation rule: walking the polyline in listed order in the (o, h) plane (o to the right, h up),
    # the EXPOSED side is on the LEFT. Open sections list the visible surface so; closed sections are listed CLOCKWISE.

@dataclass
class SweepResult:
    vidx: np.ndarray        # (N, R) vertex ids per station and section ROW (R = P + number of hard interior points; -1 where masked)
    tri_range: tuple[int, int]
    group_id: int

def sweep(buf: MeshBuffer, section: Section, frames: Frames, *,
          side: int = +1,                          # +1 left, -1 right, for centre sweeps +1 with signed o
          lateral: np.ndarray | float = 0.0,       # (N,) outward offset of the section origin from the centreline (edge_offset for kerbs; 0 for the road)
          height: np.ndarray | float = 0.0,        # (N,) height of the section origin above z_ref (edge_height for kerbs; 0 for the road)
          point_o: np.ndarray | None = None,       # (N, P) per-station override of every point's o (road stations, lip shrink, split boundary)
          point_h: np.ndarray | None = None,       # (N, P) per-station override of every point's h (camber, drop kerbs)
          mask: np.ndarray | None = None,          # (N,) bool: section exists at this station; quads need both ends True
          cap_start: bool = True, cap_end: bool = True, cap_mat: str | None = None,
          group: str = "") -> SweepResult
```

Algorithm:
1. Rows: expand points to rows — a point with `smooth=False` that is interior to an open section (or
   any point of a closed section) is emitted twice, once for the edge before it and once for the edge
   after, so `R = P + #hard_interior` (open) or `R = 2P` if all hard / `P` if all smooth (closed).
2. Vertices: for station i and row r (point k): `o = point_o[i,k] if given else pts[k].o`, `h` likewise;
   `V = p_i + side·(lateral_i + o)·n_i + (height_i + h)·b_i`; `uv = (s_i, pts[k].v)`; per-vertex
   attributes `vs = s_i`, `vd = side·(lateral_i + o)`, `vh = height_i + h`. Vertices of masked
   stations are not emitted (`vidx = −1`).
3. Quads: for each edge k → k+1 of the section and each station pair (i, i+1) with `mask[i] &
   mask[i+1]`: two triangles over `(V_{i,k}, V_{i+1,k}, V_{i+1,k+1}, V_{i,k+1})` (split on the diagonal
   `V_{i,k}–V_{i+1,k+1}`), material `pts[k].mat`. **Winding is decided geometrically, never by listing
   order:** the exposed normal in section space is the left perpendicular of the edge direction,
   `(−Δh, Δo)`, mapped to world as `side·(−Δh)·n_i + Δo·b_i`; if the emitted triangle normal points
   against it the triangle is flipped. This makes the same routine correct for left and right sides
   and for centre sweeps.
4. Caps: each maximal run of `mask == True` (or the whole sweep) gets a cap at its first and last
   station if `cap_start`/`cap_end`: the section polygon (open sections are closed by the implicit
   edge last→first) is triangulated in `(o, h)` space by `mesh.triangulate_polygon_2d` (ear clipping,
   handles both orientations by signed area), reusing the station's ring vertices (so closed volumes
   stay watertight and the manifold test passes); normal `−t_h` at a run start, `+t_h` at a run end;
   material `cap_mat or pts[0].mat`; UV `(s_i + o, h)`. Barrier segment ends `[s0, s1]` are closed this
   way because `s0` and `s1` are mandatory stations and the mask edges fall exactly on them.
5. Group: `buf.group_id(group)` for all triangles of the call.

*Degenerate edges.* If two consecutive rows coincide at a station (e.g. lip radius scaled to 0 at a
full drop kerb) the quad degenerates; `sweep` skips triangles whose area < 1e-10 m² and
`MeshBuffer.validate` confirms none remain.

**UV convention** (all sweeps): `u = s` metres along the path; `v` = metres across the section as
authored in `SectionPoint.v` (cumulative section length by default; for the road `v = d`, signed;
for markings `v ∈ [0, width]`; for rails the section perimeter). Texel density is thus uniform in
metres everywhere and materials scale by `texture_repeat_m`.

Everything that has a cross-section is a `sweep` call: road ribbon and skirt (§5.7), marking strips,
kerb+pavement, wall boxes, chain-link panel, railing rails, batter, retaining wall, ballast, the two
rails, the hedge volume. Posts and sleepers are *instances* (transform lists), not sweeps.

### 5.6 `mesh.py`

```python
@dataclass
class MeshBuffer:
    v: np.ndarray   # (N,3) float64
    f: np.ndarray   # (M,3) int64
    uv: np.ndarray  # (N,2)
    vn: np.ndarray  # (N,3) filled by compute_normals()
    mat: np.ndarray # (M,) int32   material id per triangle
    grp: np.ndarray # (M,) int32   polygroup id per triangle
    vs: np.ndarray  # (N,) station s of the vertex
    vd: np.ndarray  # (N,) signed lateral offset d of the vertex from the centreline
    vh: np.ndarray  # (N,) section height above z_ref
    material_names: list[str] ; group_names: list[str] ; two_sided: set[str]
    def material_id(self, name: str) -> int ; def group_id(self, name: str) -> int
    def append_vertices(self, P: np.ndarray, uv: np.ndarray, s: np.ndarray, d: np.ndarray, h: np.ndarray) -> int   # returns first index
    def append_triangles(self, T: np.ndarray, mat_id: int, grp_id: int) -> None
    def append_quad_strip(self, rowA: np.ndarray, rowB: np.ndarray, mat_id: int, grp_id: int, normal_hint: np.ndarray) -> None
    def append_polygon(self, ring: np.ndarray, mat_id: int, grp_id: int, normal_hint: np.ndarray) -> None   # ear clipping in the ring's best plane via Newell normal (no LAPACK)
    def merge(self, other: "MeshBuffer") -> None            # remaps material/group ids by name
    def compute_normals(self) -> None                        # area-weighted face normals accumulated per vertex; duplicated verts give hard edges
    def validate(self) -> list[str]                          # NaN/inf, index range, degenerate (< 1e-10 m^2), duplicate triangles
    def is_closed_manifold(self, mat_filter: set[str] | None = None) -> bool   # every edge in exactly two triangles with opposite orientation
    def stats(self) -> dict                                  # {verts, tris, bbox, per_material: {name: {tris, verts}}}
    def save_npz(self, path) / load_npz(path)

def triangulate_polygon_2d(pts: np.ndarray) -> np.ndarray   # (K,2) -> (K-2,3); O(K^2) ear clipping; K <= 64 in practice
def measure_lateral_overlap(road: MeshBuffer, edge: MeshBuffer, side: int) -> dict
    # per station s (unique road.vs): road_extent = max(side*vd of road verts at s); kerb_face = min(side*vd of edge verts at s with grp == 'kerb' and vh >= -tuck)
    # returns {"min_m", "max_m", "per_station": (N,), "stations": (N,)}
def coincident_xy_pairs(a: MeshBuffer, b: MeshBuffer, d_band: tuple[float, float], side: int, tol_xy=1e-6, tol_z=1e-6) -> int
    # count of (vertex of a, vertex of b) pairs with |Δxy| <= tol_xy, |Δz| > tol_z, side*vd inside d_band
```
The `vs/vd/vh` attributes are what make the seam and marking tests measurements rather than
guesses; they are dropped by the bpy bridge and the glTF export.

### 5.7 `road.py` — Renderer A

```python
def build_road(spline: Spline, params: BuildParams | None = None) -> tuple[MeshBuffer, list[Instance]]
```
Dispatch: `spline.kind == "rail"` → `rail.build_rail(spline)`; else steps below. Result material
groups: `road`, `skirt_left`, `skirt_right`, `marking:<id>`.

**5.7.1 Lateral stations.** `n_int = max(7, 2·ceil(w_max / (2·lateral_station_spacing_m)) + 1)`
interior stations at fractions `f_k = −½ + k/(n_int−1)`, `d_k(i) = w_i·f_k`, plus two skirt stations
at `d = ±(w_i/2 + overlap_m)`. For `w ≤ 6` that is 9 rows. The ribbon is *one* `sweep` call with a
9-point open section, `point_o = d` (N,9) and `point_h = h` (N,9), `lateral = 0`, `side = +1`, no caps.
Rows are shared between adjacent strips (all points `smooth=True`) so the surface shades smoothly.

**5.7.2 Camber.** `surface_h(d, w)` with crown at `d = 0` and `−c` at the edges:
```
parabolic: h(d) = −c·(2d/w)²,  c = camber_m if given else (crossfall_pct/100)·w/4     (edge slope = crossfall)
planar:    h(d) = −(crossfall_pct/100)·|d|                                            (two planes; crown ridge)
none:      h(d) = 0
```
For w = 6, 2.5 %: c = 0.0375 m; the sagitta of the parabola over a 1 m lateral chord is 1.0 mm
(App. A), which is why stations are ≤ 1 m apart (keeps markings' 3 mm lift meaningful, §5.7.4).
Skirt rows: `h = surface_h(±w/2) − skirt_drop_m` (0.02): the 4 cm skirt slopes down 2 cm into the kerb
block and is hidden inside it (§6).

**5.7.3 Width change.** Nothing special: `d_k(i)` uses `w_i` per station; the taper is exactly the
piecewise-linear `w(s)` with stations at every knot. The road-edge row at `d = ±w/2` and the kerb's
face row are computed from the same `edge_offset` array so they coincide in (x, y) to float precision.

**5.7.4 Markings — same pass, separate material-id triangles.** For each `(s0, s1, markings)`
interval of `RoadTimeline.markings` and each marking with `pattern != none`:
```
centre c(s)  per anchor (§3.2.1), evaluated on the shared stations
strips       solid/dashed: [c − w_m/2, c + w_m/2] ; double: two strips centred at c ± (double_gap_m + w_m)/2
intervals    solid: [max(s0, m.s0), min(s1, m.s1)]
             dashed: for k with phase + k·(dash+gap) < s1: [phase + k·(dash+gap), … + dash] ∩ [s0, s1] ∩ [m.s0, m.s1]; k from floor((s0 − phase)/(dash+gap))
frames_m     = spline.frames.insert(all interval end stations)      (interpolated frames; NOT a re-sample of the spline)
mask         = station inside any interval
each strip   = sweep(section = [(o=−w_m/2, h=lift), (o=+w_m/2, h=lift)] with point_h = surface_h(c(s) ± w_m/2) + lift_m, lateral = c(s), side=+1, mask, no caps, material m.material, group "marking:<id>")
```
`phase_m` is global along `s`, so a dash pattern continues unbroken across a segment boundary that
merely changes the road width or profile. The strip lies on the road's bilinear patches: at every
shared station its edge vertices are exactly `lift_m` above the road's cross-line (same `p, n, b`, same
`surface_h`), and at an interpolated dash end the deviation between the bilinear patch and the road
triangles is at most a quarter of the quad's twist, `(1 m)·sin(Δβ)/4 ≈ 1 mm` for the maximum
0.25°/station bank change the smoothing allows. With the 1 mm parabola sagitta that leaves ≥ 1 mm of
the 3 mm lift as clearance in the worst case; typical clearance is the full 3 mm. Decision recorded in
§9 Q5.

**5.7.5 Rail kind (`rail.py`, called from `build_road`).** Heights are relative to the ballast top
(`z_ref`), camber none:
```
ballast   open 4-point section (CW rule): (−(tw/2 + depth·k), −depth) → (−tw/2, 0) → (+tw/2, 0) → (+(tw/2 + depth·k), −depth)
          swept at lateral 0, side +1; material ballast; no caps. tw = ballast.top_width_m, k = shoulder_slope, depth = ballast.depth_m
sleepers  stations s_j = phase + j·pitch for 0 <= s_j <= L; Instance(kind="sleeper", size=(length, width, height), transform from frames.at(s_j)
          with the box centred laterally and spanning h ∈ [−embed, height − embed]); mode "merged" appends 12-triangle boxes instead
rails     closed 12-point section (CW) built from RailSection, o centred on the rail axis, h from the rail base:
          (−fw/2,0) (−fw/2,ft) (−wt/2, ft+0.019) (−wt/2, H−hd) (−hw/2, H−hd) (−hw/2, H) (+hw/2, H) (+hw/2, H−hd) (+wt/2, H−hd) (+wt/2, ft+0.019) (+fw/2, ft) (+fw/2, 0)
          swept twice at lateral = ±(gauge/2 + hw/2) = ±0.75243 m, height = (sleeper.height − embed) + pad = 0.055 m; all points hard; caps at both ends
```
Rail head inner faces are then exactly `gauge_m` apart (1.435), rail centres `gauge + hw` = 1.50485 m
(the §7.8 test measures both). Rail profiles force the tighter sampling via `sampling_defaults`; the
spline may still override. Rail *does* read the same `edge_offset`: `w = 3.4` puts the kerb line at
the ballast shoulder for any future lineside fence profile.

### 5.8 `edge.py` — Renderer B

```python
def build_edge(spline: Spline, side: int, terrain: Heightfield, params: BuildParams | None = None) -> tuple[MeshBuffer, list[Instance]]
```
Reads `spec = spline.side_spec[side]`, `o0 = spline.edge_offset(side)`, `h0 = spline.edge_height(side)`.
Groups: `kerb`, `pavement`, `barrier:<type>:<s0>`, `embankment:<kind>:<s0>`.

**5.8.1 Kerb + pavement section** (outward `o` from the kerb line, `h` from the road-edge level;
`kw, kh, pw, cf` per station from `spec`; `hk = kh·(1 − f) + target·f` and `r = lip·hk/kh` with the
drop factor `f` of 5.8.2):

```
A  (−tuck_in,        −tuck_depth)      mat inner   hard      under the road skirt
B  (0,               −tuck_depth)      mat inner   hard      face bottom
C  (0,               hk − r)           mat inner   smooth    face top / lip start
Lj (r − r cos θj,    hk − r + r sin θj) mat inner  smooth    θj = 90°·j/(arc_points+1), j = 1..arc_points
D  (r,               hk)               mat top_in  smooth    lip end
S  (kw·boundary_frac, hk)              mat top_out smooth    only when split enabled
E  (kw,              hk)               mat pav     smooth    kerb back / pavement start — same h as D and S: FLUSH, no step
F  (kw + pw,         hk_back)          mat pav_bk  hard      hk_back = min(kh + pw·cf, hk + pw·max_cf)   (§5.8.2)
G  (kw + pw,         −skirt)           —           last      back face down to −0.30
```
`lip.kind = chamfer` replaces `C, L*, D` by `C' (0, hk − size)`, `D' (size, hk)`; `none` by a single
hard point `(0, hk)`. `kw = 0` removes A–E (section starts at `(0, −tuck)` and goes to F/G: a pavement
without a kerb); `pw = 0` removes F (E → G). `kw = pw = 0` (barrier-only profile) emits no kerb/pavement
sweep at all — only 5.8.3/5.8.4. Materials: without split `inner = top_in = materials.kerb`,
`top_out` unused, `pav = pav_bk = materials.pavement`; with split `inner = top_in = split.inner`,
`top_out = pav = pav_bk = split.outer` ("grass on the outer face, tarmac on the inner face; boundary
along the top edge", BRIEF.md:77). The split is a material change on a shared vertex row at identical
height — it cannot create a step. One `sweep` call: `lateral = o0`, `height = h0`, `point_h`
carrying `hk`-dependent rows, `point_o` carrying `r` and `kw·frac`, `mask = spec.present`, caps at
mask-run ends (a kerb that stops mid-spline is closed off).

**5.8.2 Drop kerbs.** For each drop kerb `(s_d, len, ramp, target)` of the resolved side:
```
f_k(s) = smoothstep((s − (s_d − ramp)) / ramp)        on [s_d − ramp, s_d]          smoothstep(t) = t²(3 − 2t), t clipped to [0,1]
       = 1                                            on [s_d, s_d + len]
       = 1 − smoothstep((s − (s_d + len)) / ramp)     on [s_d + len, s_d + len + ramp]
       = 0 elsewhere ; f(s) = max_k f_k(s) ; target(s) = target of the k attaining the max
```
`hk = kh(1 − f) + target·f` lowers the face, the lip radius scales with `hk/kh` (the lip "gap" of
BRIEF.md:74 is the lip collapsing to a 6 mm arris), and the pavement top follows through E while the
back edge F stays at its nominal height unless the crossfall would exceed `pavement_max_crossfall_pct`
— with pw = 1.8 m: `min(0.125 + 0.045, 0.006 + 0.144) = 0.150`, i.e. the back edge dips 20 mm over
the crossing, as a regraded UK footway does. Both split materials ride the same rows down. At the
ramp midpoint `f = 0.5` → `hk = 0.0655` for the default profile (test §7.5).

**5.8.3 Barriers.** For each `(s0, s1, spec)` with `spec.type != none` in `spec.barrier_timeline`:
base offset `ob = o0 + kw + pw + offset_m` (inner face), base height `hb = h0 + hk_back` (pavement
back edge; `= h0 + hk` if pw = 0; `= h0` if kw = pw = 0), `mask = (s ≥ s0) & (s ≤ s1)`:
- `brick_wall | stone_wall | retaining_wall`: closed CW section `(0, −skirt) (0, H) (−ov, H) (−ov, H+ch)
  (t+ov, H+ch) (t+ov, H) (t, H) (t, −skirt)` with `t = thickness_m, ov = coping_overhang_m, ch =
  coping_height_m`; wall faces `material`, coping edges `coping_material`; caps at both run ends.
- `chain_link`: posts as instances `Instance(kind="post_round", size=(post_size, post_size, H+0.05))`
  at `s0 + j·post_pitch` for `j ≥ 0` while `< s1 − 0.5·pitch`, plus one at `s1`; panel = open 2-point
  section `(t/2, 0.05) → (t/2, H)`, material `material` flagged two-sided (`MeshBuffer.two_sided`),
  no caps.
- `railing`: posts `Instance(kind="post_square", size=(post_size, post_size, H))` at the same
  stations; each height in `rails_m` (default `[H − 0.02, 0.5H, 0.10]`) a closed CW square section of
  side `rail_size_m` centred at `(t/2, h_rail)`, swept with caps.
All use the section origin `lateral = ob`, `height = hb` — behind the pavement, per side, per s-range.

**5.8.4 Embankment / retaining wall.** For each `(s0, s1, spec)` in `spec.embankment_timeline`,
per station: back point `xy_b = xy + side·(o0 + kw + pw)·n_flat.xy`, `dz = (z_ref + h0 + hk_back) −
terrain.sample(xy_b)` (NaN → no geometry). Side/kind gating:
`side ∈ {left,right}` must equal this side; `downhill` → only where `dz > threshold`; `uphill` → only
where `dz < −threshold`; `both/auto` → either. `kind auto` → batter where `dz > 0`, retaining wall
where `dz < 0`.
- batter (fill): open 2-point section `(o_b, hk_back) → (o_b + slope_ratio·(dz + toe_extra), hk_back −
  (dz + toe_extra))`, material `material`, mask where `dz > threshold`, no caps.
- retaining wall (cut): closed CW box `(o_b, hk_back − skirt) (o_b, hk_back + |dz| + wall_coping)
  (o_b + wall_thickness, …) (o_b + wall_thickness, hk_back − skirt)`, mask where `dz < −threshold`,
  caps at run ends.
Threshold 0.35 m: below it the standard 0.30 m skirt already hides the gap.

### 5.9 `hedge.py` — Renderer C

```python
def build_hedge(spline: Spline, side: int, params: BuildParams | None = None) -> tuple[MeshBuffer, list[Instance]]
```
Reads `spec = spline.side_spec[side]` — the *same object* `build_edge` read — and
`hedge = site.profiles.hedge[profile_ids.hedge_<side>]` (or the segment's `profile_id`).

**5.9.1 Placement.** For each `(s0, s1, hseg)` in `spec.hedge_timeline` (present ones): inner face
`o_h(s) = o0 + kw + pw + [barrier.offset_m + barrier.thickness_m if a barrier is in force at s else 0]
+ hseg.offset_m`; base height `hb = h0 + hk_back − base_sink_m`. Because `barrier_timeline` and
`hedge_timeline` come from one `SideTimeline`, the hedge steps outward by exactly the wall thickness
where the wall is and back where it is not — "stacks cleanly beside walls/fences" (BRIEF.md:81).

**5.9.2 Volume.** Closed CW section, `W = width, H = height + base_sink_m, r = min(corner_radius_m,
W/2, H/2)`, `m = corner_points`:
```
flat:    (0,0) (0,H−r) arc_TL(m pts) (r,H) (W−r,H) arc_TR(m pts) (W,H−r) (W,0)            → close along the bottom
rounded: (0,0) (0,H−W/2) semi-ellipse of 2m+3 pts over the top with centre (W/2, H−W/2), semi-axes (W/2, W/2) (W,H−W/2) (W,0)
domed:   as flat but the top edge replaced by a circular arc of rise 0.15·W through 2m+1 points
```
All points `smooth=True`; one `sweep` per hedge interval, `lateral = o_h`, `height = hb`, mask on the
interval, caps at both ends (closed manifold).

**5.9.3 Noise displacement (value noise, `noise.py`).** After the sweep, every vertex with `h > 0.05`
(the base stays planted) is displaced along its *section-space outward normal* mapped to world
(`side·(−Δh)·n + Δo·b`, averaged over the two adjacent section edges) by
`δ = A·clip(fbm3(V / scale, seed), −1, 1)` with `A = noise_amplitude_m`, `scale = noise_scale_m`,
`fbm3(q) = (value_noise3(q) + 0.5·value_noise3(2q + 17.3)) / 1.5`. `value_noise3` is trilinear
interpolation with the smoothstep fade of lattice values in `[−1, 1]` produced by the integer hash
```
lowbias32(x): x ^= x >> 16; x *= 0x7feb352d; x ^= x >> 15; x *= 0x846ca68b; x ^= x >> 16   (uint32 arithmetic)
lattice(ix, iy, iz, seed) = lowbias32(ix·0x9E3779B1 ^ lowbias32(iy·0x85EBCA77 ^ lowbias32(iz·0xC2B2AE3D ^ seed))) / 2^32·2 − 1
```
— chosen over simplex/Perlin because it is a dozen lines, needs no permutation table, and the
identical uint32 arithmetic ports to C++ bit-for-bit (measured: 1 octave range ±0.99, σ 0.37; two
octaves σ 0.41, App. A). Cap ring vertices are the sweep's own vertices, so displacement keeps the
volume closed; normals are recomputed afterwards.

**5.9.4 Foliage.** `foliage.mode = cards`: for each surface triangle with mean `vh > 0.05`, count
`n = floor(area·density + frac)` where `frac = unit_noise(tri_index, seed)` in `[0,1)`; each card:
barycentric position from two more hashes, normal = face normal, rotation about the normal =
`360°·hash`, → `Instance(kind="leaf_card", transform (4,4), size=(card_size, card_size, 0),
material=foliage.material)`. `instances` mode is identical with `kind="foliage_mesh:<mesh_id>"`.
Instances are a list, never merged into the buffer; the bridge decides how to draw them (§5.12).

### 5.10 `noise.py`

`lowbias32(x: np.ndarray[uint32]) -> uint32`, `unit_noise(i: int array, seed) -> [−1,1]`,
`value_noise3(p: (N,3), seed) -> (N,)`, `fbm3(p, seed)`. Also used by the tests as the deterministic
"random" source (§7.2) so the C++ tests can use the very same sequences.

### 5.11 `io_json.py`

```python
def load_site(path: str) -> schema.Site               # json.load → validate_structure → Site.from_dict ; raises SchemaError listing every problem
def save_site(site: schema.Site, path: str) -> None   # canonical: indent 1, sort_keys False (field order as dataclass), LF, 6 decimal places for floats via a custom encoder
def validate_structure(doc: dict) -> list[str]        # hand-written checks mirroring the JSON Schema subset actually used (see §3.10); no third-party package
def load_profile_file(path: str) -> tuple[str, str, object]   # schema/profiles/<id>.json → (kind, id, profile)
```
No `jsonschema` dependency: the env python does not have it (checked this session), Blender's and
UE's pythons certainly do not. The JSON Schema file remains the contract for external tools and the
UE loader; `test_io_json.py` cross-checks `validate_structure` against the draft's `examples` and
against ten deliberately broken documents.

### 5.12 `build.py`, `bpy_bridge.py`, `render.py`, `blender_main.py`

```python
@dataclass
class Instance: kind: str; transform: np.ndarray  # (4,4) local metres, columns = (t_h, n, b, p)
                size: tuple[float, float, float]; material: str; spline_id: str; side: int
@dataclass
class BuildResult: spline: Spline; road: MeshBuffer | None; edge: dict[int, MeshBuffer | None]; hedge: dict[int, MeshBuffer | None]
                   instances: list[Instance]; overlay: np.ndarray | None  # (K,3) raw OSM polyline densified at 2 m, z = terrain + 0.2
                   stats: dict
def build_spline(site: schema.Site, spline_id: str, terrain: Heightfield) -> BuildResult
def build_all(site, terrain) -> dict[str, BuildResult]
# CLI: python -m streetscape.build --site X.json --terrain DIR --out DIR   → <out>/<spline_id>/{road,edge_left,edge_right,hedge_left,hedge_right}.npz, instances.json, overlay.json, stats.json
```
`stats.json` per spline: `length_m`, `n_samples`, `min/max/mean step`, `z_raw_nan_count`, `bank
min/max`, per-buffer `MeshBuffer.stats()`, `measure_lateral_overlap` min/max per side, marking strip
count, instance counts by kind. The UE importer writes the same keys so the two builds are diffed
numerically (BRIEF.md:338-339).

`bpy_bridge.py` (bpy API from memory, verified only by running Blender in the implementation phase):
`to_object(buf, name, collection) -> bpy.types.Object`: `me = bpy.data.meshes.new(name);
me.from_pydata(v.tolist(), [], f.tolist())`; one `bpy.data.materials` per material *name* (created
once per session, colour from `site.materials[name].base_color`, `use_backface_culling = name not in
two_sided`), appended to `me.materials` in id order; `me.polygons.foreach_set("material_index",
mat)`; UVs via `me.uv_layers.new(name="UVMap"); layer.data.foreach_set("uv", uv[f.ravel()].ravel())`
(per-loop = per corner); `me.polygons.foreach_set("use_smooth", ones)` (hard edges come from the
duplicated rows). Collection per spline (`bpy.data.collections.new(spline_id)`), one object per
renderer buffer (`<spline_id>.road`, `.edge_left`, …), instances as linked duplicates of shared
primitive meshes (`post_round`, `post_square`, `sleeper`, `leaf_card`) with `matrix_world` from the
(4,4) transform, in a `<spline_id>.instances` sub-collection. Overlay as a mesh of edges with an
emissive magenta material. glTF: `bpy.ops.export_scene.gltf(filepath=..., export_format='GLB',
use_selection=False, export_yup=True, export_apply=True)` — operator and properties confirmed present
in the installed Blender 5.2: `5.2/scripts/addons_core/io_scene_gltf2/__init__.py:1890` (`bl_idname =
'export_scene.gltf'`), `:327 export_format`, `:618 use_selection`, `:673 export_yup`, `:679
export_apply`. glTF is Y-up; `export_yup=True` converts from Blender's Z-up, so the GLB is a viewer
convenience and the `.npz` remains the numeric reference.

`render.py`: **Workbench**, not Eevee — it needs no shader compilation or ray-tracing state and is the
engine that renders reliably under `blender.exe -b` on a VM; both ids exist in 5.2
(`5.2/scripts/startup/bl_ui/properties_render.py:57-58`: `'BLENDER_EEVEE'`, `'BLENDER_WORKBENCH'`).
Settings: `scene.render.engine = 'BLENDER_WORKBENCH'`, `scene.display.shading.light = 'STUDIO'`,
`color_type = 'MATERIAL'`, `show_cavity = True`, `show_shadows = True`, 1920×1080, PNG. Three fixed
cameras defined in spline terms so every build is comparable: **cam1** eye level — on the left
pavement at `s = 10`, `d = +(w/2 + 0.9)`, 1.7 m above the pavement, looking along `+t_h`, 60° FOV;
**cam2** three-quarter aerial — 40 m behind the first width knot, 25 m up, 35 m to the right, aimed at
the knot; **cam3** kerb close-up — at the first drop kerb, 6 m away on the carriageway side, 1.0 m up,
aimed at the kerb line. Output `<out>/renders/<spline_id>_cam{1,2,3}.png`; the ones to commit go to
`Tools/blender/renders/` (LFS; `Tools/blender/out/` is gitignored, `.gitignore:29`).

`blender_main.py`: parses args after `--`, `sys.path.insert(0, dirname(__file__)/..)`, calls
`build_all`, then the bridge, then optionally glTF and renders; exits non-zero on any
`MeshBuffer.validate()` message.

---

## 6. Seam and overlap rules — testable statements

Let `o0 = spline.edge_offset(side)`, `h0 = spline.edge_height(side)`, `ov = overlap_m`, `sd =
skirt_drop_m`, `td = tuck_depth_m`, `ti = tuck_in_m`.

1. **Lateral overlap.** At every station `i` and each side with an edge profile,
   `measure_lateral_overlap(road, edge, side).per_station[i] == ov` to 1e-9, and `ov ≥ 0.03` is
   enforced by the schema. Includes stations inside width ramps because both rows derive from `o0[i]`.
   Expected: `min == max == 0.040` on all three synthetic roads.
2. **Identical stations.** `np.array_equal(np.unique(road.vs), spline.s)` and the same for each edge
   and hedge buffer that exists; also `np.array_equal(edge_left.vs unique, edge_right.vs unique)`.
3. **Road owns the seam.** The road's skirt row at `d = side·(o0 + ov)`, `h = h0 − sd` lies strictly
   inside the kerb block cross-section `[0, kw] × [−td, hk]` at every station: `0 < ov < kw` and
   `−td < −sd < hk` — with defaults `0 < 0.04 < 0.125` and `−0.03 < −0.02 < hk` for every `hk ≥ 0.006`
   (the dropped-kerb minimum). Test asserts both inequalities per station with the minimum kerb
   height over all drop kerbs, and that the kerb's underside row A reaches `o = −ti = −0.02` under the
   skirt (so the skirt's 4 cm sits over a 2 cm kerb underside plus 2 cm of block interior).
4. **No accidental coincident verticals.** `coincident_xy_pairs(road, edge, d_band=[o0, o0 + ov],
   side)` counts road/kerb vertex pairs at the same (x, y) with different z inside the overlap band.
   Exactly **2 per station** are by design (the road-edge row at `d = o0` against the kerb face rows B
   and C at `o = 0`, same (x, y), different z); the test asserts `count == 2·N` for every configuration
   including drop kerbs and the width ramp, and 0 for `d_band = (o0 + 1e-6, o0 + ov]`.
5. **Height coherence.** `abs(road_edge_row.z − (spline.z_ref + h0))[i] < 1e-9` and the same for the
   kerb's row B minus `td`: both renderers put the seam at the same height because they call the same
   function — measured, not assumed.
6. **Width change is invisible at the seam.** On the 6 → 8 m ramp (below) rule 1 holds at `s = 40,
   42, …, 50` including the two knot stations, and the kerb face `x, y` at each station equals the
   road-edge `x, y` to 1e-9.

Synthetic roads used by every seam test (`tests/synthetic.py`), all on a flat terrain `z = 10`
(so heights are trivially checkable) unless stated:

| name | definition | expected numbers |
|---|---|---|
| `straight_100` | points (0,0) (40,0) w 6, (50,0) w 8, (100,0); `edge_uk_kerb` both sides; one left drop kerb at s = 70 (defaults) | N = 51 + 4 (drop-kerb stations 69.085, 70, 71.83, 72.745) = **55**; `w(45) = 7.0`; overlap 0.040 at all 55; coincident pairs 110; road verts 9·55 = 495, road tris 2·8·54 = 864 |
| `sine_5_50` | points every 5 m on `y = 5 sin(2πx/50)`, x ∈ [0, 100]; w 6 | L = 109.2 ± 0.1; N = 101 ± 3; crest spacing mean ≤ 0.85, inflection ≥ 1.5, ratio ≥ 1.8 (measured 0.817 / 1.601 / 1.96) |
| `curve_R20_200` | straight (0,0)→(60,0), 90° arc R = 20 (8 waypoints), straight to L = 200 | N = 117 ± 2; arc spacing mean 1.00 ± 0.03, straights 1.99 ± 0.02, ratio 2.0 ± 0.1; `s` strictly increasing |

---

## 7. Test plan — `projects/one/Tools/blender/tests/`

Runner: `C:/Users/Shadow/code/3duk-env/env/python.exe -m unittest discover -s
projects/one/Tools/blender/tests -p "test_*.py" -v` (stdlib `unittest`; each file also runs as a
script). Each test file does `sys.path.insert(0, <Tools/blender>)` and imports `streetscape`. No
`bpy`, no GDAL, no LAPACK (§1.10). `synthetic.py` provides the three roads of §6, a rail spline
(`rail_R300_600`: 600 m with a 300 m-radius bend), synthetic `Heightfield.from_function` terrains
(flat, planar cross slope `0.1·y`, 2 % grade + hash noise, a 1.5 m step "bank" for the embankment
test) and the site/profile fixtures.

| file | asserts | numeric expectation |
|---|---|---|
| `test_terrain.py` | `Heightfield.sample` equals a literal transcription of `ground()` (06_build_networks.py:54-69) on 10 000 hashed points over a 2×2-tile synthetic field; tile-boundary points identical from either tile; NaN off-coverage and on a NaN cell; a point at exactly (res−1) uses the inward clamp | max abs diff 0; NaN count exact |
| `test_spline.py` | Catmull-Rom passes through every waypoint; `s` monotone, `s[0]=0`, `s[-1]=L`; mandatory stations bitwise present; straight spacing; bend ratios; final gap rule | `straight_100` without drop kerb: N = 51, `max|Δs − 2| < 1e-9`; `sine_5_50` crest ≤ 0.85 / inflection ≥ 1.5 / ratio ≥ 1.8; `curve_R20_200` arc 1.00 ± 0.03, ratio 2.0 ± 0.1; min gap ≥ 0.125 everywhere |
| `test_spline.py::test_width` | `w(s)` at knots and mid-ramp; segment override with ramp 5 | `w(40)=6, w(50)=8, w(45)=7.0 ± 1e-9`; segment `{s0 60, s1 80, width 5, ramp 5}` → `w(55)=8, w(57.5)=6.5, w(60..80)=5, w(85)=8` |
| `test_spline.py::test_smoothing` | hash noise σ = 0.1 (`0.1·√3·unit_noise(i, 7)`) on a 2 % grade, W = 20, 51 stations: interior RMS reduction; max error; endpoints untouched; grade preserved; 8 m ripple | factor ≥ 3.5 (measured 4.01); max |err| ≤ 0.06 (0.053); `z'[0]==z[0]`, `z'[-1]==z[-1]`; `(z'(90)−z'(10))/80 = 0.020 ± 0.002`; ripple 0.1·sin(2πs/8) RMS 0.0707 → ≤ 0.010 (0.0065); W = 10 factor ≥ 2.0 (2.39); two passes W = 20 factor ≥ 4.0 (4.20) |
| `test_spline.py::test_bank` | terrain `z = 0.1·y`, road along +x: β before clamp, after clamp, with roll override | 5.71° ± 0.02 → 4.00°; roll 2° on all points → 2.000°; roll on the middle point only → mask blends 4.0 → 2.0 → 4.0 linearly between waypoints |
| `test_spline.py::test_frames` | `t_h·n = 0`, `|n| = |b| = 1`, `b·Z = cos β`, sign of `n·Z = sin β` | 1e-12 |
| `test_sweep_mesh.py` | closed square swept along `straight_100`: manifold, outward normals (dot with centroid direction > 0), triangle count `2·4·(N−1) + 2·2`; open kerb section: winding rule gives face normal pointing toward −side·n; caps at mask run ends; `triangulate_polygon_2d` on the kerb polygon (11 pts, non-convex) → 9 triangles with total area equal to the polygon area; `validate()` empty; UV `u == vs` | exact counts; area diff < 1e-12 |
| `test_road_markings.py` | on `straight_100` with `centre_1004` + `dyl_left_1018_1`: strip centres and widths measured from `vd` of `marking:*` vertices; dash intervals; lift; double gap; `anchor: edge_left` follows the 6→8 ramp | centre strip `vd ∈ {−0.05, +0.05}` ± 1e-9; dashes cover `[0,4] [6,10] … [96,100]` (17 dashes, ends within 1e-9); each marking vertex is `0.003 ± 1e-9` above the road surface at the same `(s, d)`; double yellow: pair centre at `o0 − 0.25`, line centres at `o0 − 0.35` and `o0 − 0.15` (each 0.10 wide, so the clear gap between `o0 − 0.30` and `o0 − 0.20` is exactly 0.10); at s = 45 (w = 7) every yellow vertex moves outward by exactly 0.5 relative to s = 40 |
| `test_road_markings.py::test_camber` | crown/edge heights | `surface_h(0)=0`, `surface_h(±3)=−0.0375` for w 6, 2.5 %; planar `−0.075` |
| `test_edge.py` | kerb rows heights: D, S, E all at `hk` (flush), lip points on the arc, B at `−0.03`, A at `o = −0.02`; drop kerb: `hk` at flat-run centre, at ramp midpoint, back-edge F rule; split materials: triangles of the top with `vd` inward of the boundary carry `inner`, outward `outer`; barriers: wall box manifold, coping edges, chain-link post count and panel two-sided flag, railing rail count; embankment on the step terrain: batter present only where `dz > 0.35`, retaining wall where `dz < −0.35`, `auto` picks sides correctly | flush 0.000 mm (`max|z_D − z_E| < 1e-12`); drop `hk(70.915) = 0.006 ± 1e-6` (flat-run centre), `hk(69.5425) = 0.0655 ± 1e-6` (down-ramp midpoint), `hk(72.2875) = 0.0655` (up-ramp midpoint); `F.h = 0.150` at the flat run; wall over [0,45] → posts n/a, `is_closed_manifold(wall)` True; chain-link [45, L]: posts at 45, 48, …, and one at L → `floor((L−45)/3) + 2` instances; 3 rails |
| `test_seam.py` | rules 1–6 of §6 on all three synthetic roads, with and without the drop kerb and with a mid-spline `edge_uk_half_grass` switch | overlap min = max = 0.040; identical stations; pairs = 2·N; heights coherent to 1e-9 |
| `test_hedge.py` | volume closed manifold before and after noise; bottom row undisplaced; displacement ≤ amplitude; hedge inner face offset = wall outer face + 0.1 where the wall is and back edge + 0.1 where not; leaf-card count ≈ area·density | `is_closed_manifold` True; `max|δ| ≤ 0.06 + 1e-9`; offsets to 1e-9; cards within ±5 % of `12·area` |
| `test_rail.py` | on `rail_R300_600`: inner-face distance between rail heads, rail centre distance, rail top above ballast, sleeper count/pitch, ballast toe width, tessellation tighter in the bend than on the straight | **1.435 ± 0.001** (inner faces), 1.5049 ± 0.001 (centres), rail top `0.2138 ± 1e-6`; sleepers `floor(L/0.65) + 1`, consecutive pitch `0.65 ± 1e-6` (measured along s); toe width `3.4 + 2·0.45·1.5 = 4.75`; straight spacing 1.00 ± 0.02, bend (R 300) spacing 0.83 ± 0.03 (`1/(1 + 60/300)`) |
| `test_noise.py` | `lowbias32` known-answer vector (`lowbias32(0)=0`, `lowbias32(1)=0x…` computed once and frozen); `value_noise3` range, determinism, continuity (adjacent samples 1 mm apart differ < 0.01) | exact |
| `test_io_json.py` | both draft `examples` load and round-trip (`save → load` equal); ten broken documents each raise with a message naming the path; every `profiles/*.json` default loads; unknown key rejected | |
| `test_examples.py` | builds worked example 1 on the flat terrain end-to-end and checks stats: 3 buffers + instances present; package exports exactly three builders; import-graph rule (§5.1); "no `width/2` outside spline.py" grep; Chaikin-vs-OSM overlay distance | overlay test: raw right-angle way with 40 m legs → step-06 pipeline (`densify 8`, `chaikin 2`, transcribed) → spline; Hausdorff distance spline↔raw ≤ 1.5 m (measured 1.335 raw→spline, 0.893 spline→raw); 30° kink ≤ 0.6 (0.489); a straight raw way → 0 |

Every number in the right-hand column was measured with the prototype in Appendix A or follows
from the definitions; where a tolerance is given the measured value is quoted in parentheses.

---

## 8. C++ mirror table

The port is mechanical: one class or struct per module, the same function names, the same arrays
(TArray<double> / TArray<FVector3d>), the same numbers in Automation tests. Header citations are
the installed UE 5.8 sources.

| numpy | UE class / method (Plugins/Streetscape/Source/Streetscape) | engine API used |
|---|---|---|
| `schema.py` dataclasses | `URoadProfile`, `UEdgeProfile`, `UHedgeProfile : UDataAsset` (`Engine/Source/Runtime/Engine/Classes/Engine/DataAsset.h:17`); USTRUCTs `FStreetMarking, FStreetRailSpec, FStreetLip, FStreetSplitMaterial, FStreetDropKerb, FStreetBarrier, FStreetEmbankment, FStreetHedgeSegment, FStreetPoint, FStreetSampling, FStreetSegment, FStreetSource, FStreetOverlay`; field names = JSON keys in PascalCase (`kerb_width_m → KerbWidthM`) | |
| `schema.resolve_side / resolve_road / paint_intervals / apply_ramped_override` | `FStreetSideTimeline::Resolve`, `FStreetRoadTimeline::Resolve`, `FStreetTimeline::PaintIntervals`, `FStreetMath::ApplyRampedOverride` | |
| `io_json.py` | `FStreetscapeJson::LoadSite / SaveSite / ValidateStructure` | `FJsonSerializer::Deserialize` (`Engine/Source/Runtime/Json/Public/Serialization/JsonSerializer.h:301,307`); `FJsonObjectConverter::JsonObjectStringToUStruct` / `UStructToJsonObjectString` (`Engine/Source/Runtime/JsonUtilities/Public/JsonObjectConverter.h:313,156`) for the USTRUCT rows |
| `terrain.Heightfield` | `IStreetTerrainSource { virtual TOptional<double> Sample(double X, double Y) const = 0; }`; `FHeightfieldTerrainSource` (f32 tiles, identical bilinear rule); `FLandscapeTerrainSource` | `ALandscapeProxy::GetHeightAtLocation` (`Engine/Source/Runtime/Landscape/Classes/LandscapeProxy.h:1101`, class at `:450`) |
| `spline.catmull_rom_dense` | `FStreetSplineMath::CatmullRomDense` | own implementation (not `USplineComponent`, `Engine/Classes/Components/SplineComponent.h:214`, whose Hermite tangents would give a different `s`) |
| `spline.adaptive_stations` | `UStreetSplineComponent::Resample()` | |
| `spline.moving_average_arclength / fill_nan_along / apply_pins` | `FStreetSplineMath::MovingAverageArcLength / FillGapsAlong / ApplyPins` | |
| `spline.terrain_bank_deg` + blend | `UStreetSplineComponent::ComputeBank()` | |
| `spline.build_frames`, `Frames.at/insert` | `FStreetFrames` (`TArray<FFrame3d>`-like: P, Th, NFlat, N, B) with `At()`, `Insert()` | `TFrame3<double>` for reference (`Engine/Source/Runtime/GeometryCore/Public/FrameTypes.h:26`, `FFrame3d :478`) |
| `Spline.edge_offset / edge_height / surface_h` | `UStreetSplineComponent::EdgeOffset(EStreetSide)`, `EdgeHeight(EStreetSide)`, `SurfaceH(const TArray<double>& D)` | |
| `sweep.sweep` | `FStreetSweep::Sweep(FDynamicMesh3&, const FStreetSection&, const FStreetFrames&, const FStreetSweepParams&) -> FStreetSweepResult` | `FDynamicMesh3::AppendVertex` (`Engine/Source/Runtime/GeometryCore/Public/DynamicMesh/DynamicMesh3.h:668`), `AppendTriangle(FIndex3i, GroupID)` (`:677`), `EnableTriangleGroups` (`:1015`), `EnableAttributes` (`:1048`); attribute set `EnableMaterialID` (`DynamicMeshAttributeSet.h:360`), `GetMaterialID()->SetValue(Tri, Id)` (`DynamicMeshTriangleAttribute.h:683`); UV/normal overlays `PrimaryUV` (`DynamicMeshAttributeSet.h:198`), `PrimaryNormals` (`:250`), `AppendElement` / `SetTriangle` (`DynamicMeshOverlay.h:322,342`). Not `UGeometryScriptLibrary_MeshPrimitiveFunctions::AppendSweepPolyline` (`Engine/Plugins/Runtime/GeometryScripting/Source/GeometryScriptingCore/Public/GeometryScript/MeshPrimitiveFunctions.h:503`, `AppendSweepPolygon :577`): it has no per-station per-point overrides, no per-edge material ids and different numerics |
| `mesh.MeshBuffer` | `FStreetMeshBuilder` owning an `FDynamicMesh3` + parallel `TArray<double> VS, VD, VH` (test builds only) with `MaterialIdFor(FName)`, `AppendQuadStrip`, `AppendPolygon`, `Validate()`, `Stats()` | `FDynamicMesh3::CheckValidity` (`DynamicMesh3.h:1741`); `FMeshNormals::QuickComputeVertexNormals` (`MeshNormals.h:141`) / `InitializeOverlayToPerVertexNormals` (`:188`) |
| `mesh.measure_lateral_overlap / coincident_xy_pairs` | test-module free functions in `StreetscapeTests` | |
| `noise.py` | `FStreetNoise::LowBias32 / UnitNoise / ValueNoise3 / Fbm3` (uint32 arithmetic) | |
| `road.build_road` | `UStreetRoadRenderer::Build()` → `BuildRoad()`, `BuildMarkings()`, `BuildRail()` (one component class; `Kind` decides) | |
| `edge.build_edge` | `UStreetEdgeRenderer::Build(EStreetSide)` → `BuildKerbPavement`, `BuildBarriers`, `BuildEmbankments` | |
| `hedge.build_hedge` | `UStreetHedgeRenderer::Build(EStreetSide)` → `BuildVolume`, `DisplaceNoise`, `ScatterFoliage` | |
| `bpy_bridge` | `UStreetRendererBase::Commit()`: `UDynamicMeshComponent::SetMesh(FDynamicMesh3&&)` (`Engine/Source/Runtime/GeometryFramework/Public/Components/DynamicMeshComponent.h:210`), `ConfigureMaterialSet` (`:619`), `NotifyMeshUpdated` (`:275`), `EnableComplexAsSimpleCollision` (`:714`); instances → `UInstancedStaticMeshComponent::AddInstances` (`Engine/Classes/Components/InstancedStaticMeshComponent.h:275`) per (kind, size, material) | `UDynamicMesh::SetMesh/ProcessMesh` (`Engine/Source/Runtime/GeometryFramework/Public/UDynamicMesh.h:190,195`) |
| `render.py` | `Tools/ue/screenshot.py` (out of scope here) | |
| `tests/*` | `Private/Tests/StreetSpline.spec.cpp`, `StreetSweep.spec.cpp`, `StreetRoad.spec.cpp`, `StreetEdge.spec.cpp`, `StreetSeam.spec.cpp`, `StreetHedge.spec.cpp`, `StreetRail.spec.cpp`, `StreetNoise.spec.cpp` | `IMPLEMENT_SIMPLE_AUTOMATION_TEST` (`Engine/Source/Runtime/Core/Public/Misc/AutomationTest.h:4297`), flags `EAutomationTestFlags::EditorContext | EAutomationTestFlags::ProductFilter` (`:144-149`), `TestNearlyEqual(double)` (`:2203`), `TestEqual(int32)` (`:1985`), `TestTrue` (`:2603`); `FMath::SmoothStep` (`Engine/Source/Runtime/Core/Public/Math/UnrealMathUtility.h:2362`) for the drop-kerb ramp |

Numeric expectations that become C++ Automation tests verbatim (same fixtures, same tolerances):
`straight_100` N = 51/55 and exact 2.0 m spacing; `curve_R20_200` ratio 2.0 ± 0.1; smoothing factor
≥ 3.5 with the hash-noise sequence (portable, unlike numpy's RNG); bank 5.71° → 4.0°; overlap
0.040 at every station; coincident pairs 2·N; flush split top 0 mm; drop kerb 0.006 / 0.0655; marking
centres/dash ends to 1e-6 (float64 in both); rail 1.435 ± 0.001 and 1.5049; hedge manifold; noise
known-answer vector; Chaikin-vs-OSM ≤ 1.5 m. The C++ tests read the same JSON fixtures from
`Tools/blender/tests/fixtures/*.json` (path resolved relative to the plugin) so there is one set of
inputs.

---

## 9. BRIEF §6 open questions closed here

**Q4 — one generic cross-section sweep.** Closed by §5.5: `sweep(buf, section, frames, side,
lateral, height, point_o, point_h, mask, caps, group)` in numpy and
`FStreetSweep::Sweep(FDynamicMesh3&, FStreetSection, FStreetFrames, FStreetSweepParams)` in C++.
A section is a list of `(o, h, material, v, smooth)` points, open or closed; per-station lateral
offset and height come from the shared spline (`edge_offset`, `edge_height`); per-station per-point
overrides express camber, width, lip shrink and drop kerbs without special cases; caps close mask
runs; winding is derived from the section geometry so left/right sides need no code. Kerb+pavement,
walls, railing rails, chain-link panel, batter, retaining wall, road ribbon and skirt, marking strips,
ballast, rails and hedge volume all go through it; posts, sleepers and leaf cards are instance lists.

**Q5 — markings.** Lifted strips, `lift_m` default 0.003 m, as separate material-id triangle sets in
the same `MeshBuffer` and the same build pass (§5.7.4). Reasons: (1) a real thermoplastic marking *is*
1.5–3 mm proud of the surface, so it is physically right rather than a hack; (2) same-plane material
ids would require the ribbon topology to depend on the marking layout (vertex rows at every marking
edge, changing with width-anchored offsets along s), coupling paint to carriageway tessellation; (3)
the clearance analysis in §5.7.4 shows ≥ 1 mm worst case against the road triangles with ≤ 1 m
lateral stations and the smoothing-limited bank rate. Parameterisation: `pattern ∈ solid|dashed|
double|none`, `dash_m`, `gap_m`, `phase_m` (global along s), `double_gap_m`, plus `anchor` and
optional `s0_m/s1_m`. Dash ends are interpolated frames, not extra spline stations, so paint never
changes the shared sample set.

**Q6 — hedge volume.** Swept rounded-rectangle (flat / rounded / domed top) closed volume with
per-vertex value-noise displacement (`lowbias32` hash, two octaves, amplitude 0.06 m, scale 0.6 m)
and optional instanced leaf cards emitted as an instance list (§5.9). Not Niagara/PCG for the volume:
the volume must exist identically in Blender and in the numpy tests, and PCG/Niagara can later
*consume* the instance list for richer foliage without touching the schema. Density knobs:
`foliage.density_per_m2` (12), `card_size_m` (0.25), `noise_amplitude_m`, `noise_scale_m`,
`corner_radius_m`, `corner_points`, `top_profile`.

**Q7 — junctions.** Reserved in the schema as `junctions[] {id, x, y, z, radius_m, kind, ends[{spline_id,
end}]}` plus `Spline.junction_start/junction_end` and the `junction:<id>` point tag (§3.7). Step 06's
`_junction` discs map 1:1. No renderer reads it this round; spline ends are untrimmed; the endpoint
smoothing rule (§5.4.5) already makes meeting splines agree on height at the node.

---

## 10. Contracts this design assumes from the other subsystems

1. **Adapter (`sources/adapters/unreal.py`)** writes, under `data/<site>/out/unreal/`:
   - `terrain/heightfield_manifest.json` `{site, crs, origin{E,N}, tile_m, res, px_m, vertical_datum,
     tiles:[{x, y, file}], clip?}` and `terrain/hf_x{i}_y{j}.f32` — raw little-endian float32,
     `res × res`, north-up row-major, **NaN** where step 05 has nodata or the Thanet clip removed the
     cell (BRIEF.md:222 distinguishes the two in the manifest; the sampler treats both as "no
     height"). This is in addition to whatever 16-bit form the landscape importer wants.
   - `streetscape/<site>.json` (or per tile `streetscape/tile_x{i}_y{j}.json`) conforming to the
     schema, with: `points` = step 06 `pts` minus origin, `z` **omitted** (heights come from terrain;
     the 06 `z` is dropped) except where the adapter decides to pin bridges/tunnels; `source.layer`
     from the input file; `profile_ids.road` from `cls` via a table (`residential → road_residential`,
     `primary|trunk → road_primary`, `service|track → road_service`, `rail → rail_standard`, barrier
     `wall → edge_wall_brick`, `fence → edge_chain_link`, `railing → edge_railing`, `hedge →
     hedge_privet`); `edge_left/right` from `sidewalk`, `sidewalk:left/right` tags (both → both sides;
     none/no → null); pavement width per class via a `Segment.edge.pavement_width_m` over the whole
     spline when it differs from the profile's 1.8; `overlay.pts` = the **raw OSM way vertices**, which
     step 06 does not output — the adapter must read them from the GeoPackage (`data/<site>/derived/
     <site>.gpkg`, layer `lines`, `osm_id`) or step 11 must emit `raw_pts`.
   - Nothing in Unreal units: the ×(100, −100, 100) happens only in the UE loader (BRIEF.md:231-233).
2. **Step 11** (`sources/derive/11_linear_features.py`): rail and barrier ways with `id, cls, pts` in
   the same record shape as roads (`sources/OUTPUT.md:45-59`) plus `raw_pts` if the adapter is not to
   read the GeoPackage; `height`/`material` OSM tags passed through so the adapter can override
   `Barrier.height_m` per spline via a segment.
3. **UE plan**: DataAsset/USTRUCT field names are the JSON keys in PascalCase; material *names* map to
   slots through a `UStreetMaterialTable` (`FName → UMaterialInterface*`); the loader reads
   `frame` and refuses anything but the const; the importer emits `stats.json` with the keys of §5.12
   so Blender and Unreal builds are diffed.
4. **Test-stretch author**: `projects/one/schema/examples/test_stretch.json` uses exactly the fields of
   §3; worked example 1 is a valid starting point (it is real Margate geometry).
5. **Pipeline `dryrun.py`**: unchanged by this design; the numpy tests here are separate.

---

## Appendix A — numbers measured in this session (prototype, env python, numpy 2.5.3)

Prototype of §5.4.1–5.4.6, §5.10 and the Chaikin comparison (scratchpad `proto.py`, `proto2.py`;
not in the repo). Output, verbatim where it matters:

```
straight100: L=100.00 m, n=53 (with mandatory 35,40,50,55), spacing mean 1.923 min 1.000 max 2.000 ; mandatory present: True
sine5/50: L=109.21 n=101 kmax 0.1000 (analytic 0.0790; analytic crest step 0.775)
   crest spacing mean 0.817 max 0.845; inflection mean 1.601 min 1.263; ratio 1.96
R20: n=117 L=200.00; straight-in mean 1.991; arc mean 0.995 max 1.007; straight-out mean 1.997 min 1.868; ratio 2.00
   s monotone: True  min gap 0.877  (after the final-gap rule; before it a 0.129 m sliver appeared at L)
straight+mandatory [40,50,69,70,72.4,73.4]: n=54, all present, min gap 0.400, max gap 2.000 ; road verts 9 stations: 486, tris 848
hash noise (0.1*sqrt3*unit_noise): mean 0.0069 std 0.0985
   W=10.0: raw 0.0975 smoothed 0.0407 factor 2.39; max|err| 0.1086 ; end pinned True
   W=20.0: raw 0.0946 smoothed 0.0236 factor 4.01; max|err| 0.0529 ; end pinned True
   two passes W=20: factor 4.20
   ripple 8 m: raw rms 0.0716 smoothed rms 0.0065
Gaussian noise seed 12345, W=20: factor 5.23 ; over 200 seeds mean 3.70 min 1.76 max 9.45   (why the tests use the hash sequence)
chaikin corner (90 deg, 40 m legs, densify 8, iters 2): spline->raw max 0.893 m, raw->spline max 1.335 m (analytic first-iteration chord 1.416)
chaikin 30 deg kink: spline->raw 0.436, raw->spline 0.489
value noise 1 octave: min -0.989 max 0.991 std 0.368; 2 octaves: min -1.373 max 1.379 std 0.412 ; deterministic: True
parabolic camber 2.5 %, w=6: crown 0.0375 m; sagitta over 1 m lateral chord 0.0010 m ; planar drop at edge 0.0750 m
bank unclamped atan(0.1) = 5.711 deg → clamped 4.0
rail centre offset 0.75243 m ; centre-to-centre 1.50485 m ; smoothstep(0.5) = 0.5 → kerb h at ramp mid 0.0625 (target 0) / 0.0655 (target 0.006)
```

The draft schema was checked with a subset validator (`$ref` resolution, type/required/enum/const/
range/pattern/oneOf/allOf/if-then): 34 `$ref`s, 0 unresolved; `examples[0]` and `examples[1]`: 0
errors; every `profile_ids` and segment `profile_id` in the examples resolves.

## Appendix B — environment fact: `numpy.linalg` LAPACK routines crash the env python

Reproduced 2026-09-07 with `C:/Users/Shadow/code/3duk-env/env/python.exe` (numpy 2.5.3, scipy
1.18.0): `python -c "import numpy as np; print(np.polyfit([0.,1,2],[0.,1,2],1))"` → no output, exit
code 127; same for `np.linalg.lstsq`, `np.linalg.solve`, `np.linalg.svd`. `np.linalg.norm` and
`np.cross` work. A whole test file that touched `polyfit` died silently with its buffered output lost,
which is how this was found. Consequence: §1.10 — nothing in the core or the tests may call a
LAPACK-backed routine; slopes in tests are computed as finite differences; plane normals by Newell's
method; no least squares anywhere. This should be recorded in the environment notes of the README
and investigated separately (probably an OpenBLAS/MKL DLL conflict in the conda env); it is not a
blocker for this design.

## Appendix C — repo facts relied on

- `sources/derive/06_build_networks.py:54-69` `ground()` bilinear rule; `:81-92` `densify`; `:95-106`
  `chaikin`; `:161` densify 8 m + Chaikin ×2 applied; `:195` vertices rounded to 2 dp.
- `sources/config/tuning.json:4-22` road class widths / pavement widths; `roads.densify_step_m 8.0`,
  `chaikin_iters 2`; `furniture.kerb_m 0.12`.
- `sources/config/sites/margate.json:9-15` origin E 632800 N 168200, tile 512, grid_res 513.
- `sources/OUTPUT.md:25-27` shared edge row; `:45-59` road record; `:61-62` `_junction`.
- `data/margate/raw/lidar/dtm_x0_y0.tif`: 513×513 Float32, `gt=(632799.5, 1.0, 0.0, 168712.5, 0.0,
  -1.0)`, nodata −3.4028234663852886e+38; `dtm_x1_y0.tif` `gt[0]=633311.5`; column 512 of x0 ==
  column 0 of x1 (True). `data/margate/out/terrain/dtm_x0_y0.tif`: same transform, nodata None.
- `data/margate/out/networks/roads_x0_y2.jsonl`: way `4590626` "Noble Gardens", residential, w 6.0,
  pav 1.5, 41 vertices from E 633310.19 N 169735.05 to E 633309.79 N 169661.06 (worked example 1).
- `.gitignore:29` `projects/*/Tools/blender/out/` ignored; `.gitattributes` PNG via LFS.
- Blender 5.2.1: `5.2/scripts/addons_core/io_scene_gltf2/__init__.py:1890,327,618,673,679`;
  `5.2/scripts/startup/bl_ui/properties_render.py:57-58`.
