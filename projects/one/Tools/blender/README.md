# Tools/blender — the numpy geometry core and its Blender bridge

Pure-numpy prototype of the shared spline, Renderer A (road + markings, rail as a profile kind),
Renderer B (kerb / pavement / drop kerbs / split materials / barriers / embankments) and Renderer C
(volumetric hedge), with a thin `bpy` layer for meshes, glTF and EEVEE renders.  Normative documents:
`docs/DESIGN.md` 3–8, 14, 18 and `docs/SCHEMA.md`; this file records what the implementation does where
those documents left a choice, and how to run it.

## Layout

```
streetscape/
  schema.py      dataclasses for every JSON object (SPEC tables = the structural validator) + resolve_road /
                 resolve_side / paint_intervals / apply_ramped_override / SideTimeline.evaluate -> SideSpec
  io_json.py     load_site / save_site / validate_structure / validate_warnings / load_profile_file
  terrain.py     Heightfield: from_landscape_dir (r16 + clip), from_step05_dir (GDAL), from_function, npz cache,
                 rebased(E, N) for a document in another origin; sample() = step 06 ground() per tile
  noise.py       lowbias32 / unit_noise / lattice / value_noise3 / fbm3 (uint32, bit-exact known answers)
  spline.py      Spline: duplicate merge, centripetal Catmull-Rom, adaptive + mandatory stations, width / roll,
                 heights (arc-length moving average, pins), bank (probes, clamp, mask, rate limit), Frames,
                 and the ONLY kerb-line functions edge_offset(side) / edge_height(side)
  sweep.py       the one cross-section sweep (rows, geometric winding, caps, quad masks, per-station materials)
  mesh.py        MeshBuffer (+ vs / vd / vh attributes), triangulate_polygon_2d, is_closed_manifold,
                 measure_lateral_overlap, coincident_xy_pairs, surface_height_at, deterministic .npz
  road.py        build_road: ribbon rows at +-edge_offset, skirts, camber, lifted marking strips; dispatches to
  rail.py        build_rail: ballast ribbon, sleeper instances, two BS113A rails (called only from road.py)
  edge.py        build_edge: A-B-C-lip-D-S-E-F-G section, drop kerbs, split materials, barriers, embankments
  hedge.py       build_hedge: swept rounded volume + fbm3 displacement + leaf-card instances
  instance.py    Instance (kind, 4x4 transform with columns t_h / n / b / p, size along t_h / n / b, material)
  build.py       build_spline / build_all / write_result / CLI  (python -m streetscape.build)
  bpy_bridge.py  MeshBuffer -> bpy objects, instances as linked duplicates, overlay, terrain context patch, GLB
  render.py      EEVEE, the three fixed cameras (cam1 pavement eye level, cam2 aerial at the first width knot,
                 cam3 kerb close-up at the first drop kerb)
  blender_main.py  blender.exe -b --python blender_main.py -- --site X --terrain T --out D [--gltf] [--render]
tests/
  schema_check.py           JSON-Schema-subset validator; `schema_check.py <files>` prints VALID per file
  schema_check_negative.py  89 mutation cases against the validator
  synthetic.py              straight_100 / sine_5_50 / curve_R20_200 / rail_R300_600 documents + terrains
  make_fixtures.py          writes fixtures/*.json and fixtures/expected.json (every frozen number)
  test_*.py                 unittest modules (no bpy, no GDAL needed; GDAL used when present)
renders/                     committed PNG renders (LFS) + trinity_square.stats.json (the Unreal parity reference)
out/                         ignored build products (npz, GLB, terrain npz caches, logs)
```

## Commands (Git Bash, repo root)

```bash
PY=C:/Users/Shadow/code/3duk-env/env/python.exe
export PATH="/c/Users/Shadow/code/3duk-env/env/Library/bin:$PATH"     # GDAL + OpenBLAS for the env python

# tests (85 tests)
$PY -m unittest discover -s projects/one/Tools/blender/tests -p "test_*.py" -v

# fixtures + frozen numbers
$PY projects/one/Tools/blender/tests/make_fixtures.py

# validator: VALID per file, exit 0 iff all valid
$PY projects/one/Tools/blender/tests/schema_check.py projects/one/schema/examples/*.json projects/one/schema/profiles/*.json

# numeric build (env python).  --terrain: adapter landscape dir | step-05 terrain dir (GDAL) | heightfield .npz
PYTHONPATH=projects/one/Tools/blender $PY -m streetscape.build --site projects/one/schema/examples/test_stretch.json \
    --terrain data/margate/out/terrain --out projects/one/Tools/blender/out/test_stretch \
    --export-terrain-npz projects/one/Tools/blender/out/terrain_margate_step05_thanetframe.npz

# Blender (its python has no GDAL: pass the landscape dir or the .npz cache)
"C:/Program Files/Blender Foundation/Blender 5.2/blender.exe" -b --python projects/one/Tools/blender/streetscape/blender_main.py -- \
    --site projects/one/schema/examples/test_stretch.json \
    --terrain projects/one/Tools/blender/out/terrain_margate_step05_thanetframe.npz \
    --out projects/one/Tools/blender/out/test_stretch --renders projects/one/Tools/blender/out/test_stretch/renders --gltf --render
```

Output per spline: `<out>/<id with ':' -> '~'>/{road,edge_left,edge_right,hedge_left,hedge_right}.npz`,
`spline.npz`, `instances.json`, `overlay.json`, `stats.json`.  NTFS refuses ':' in file names, so the
directory of `authored:trinity_square` is `authored~trinity_square` ('~' is outside the Id charset, so the
mapping is reversible; `stats.json.spline_id` carries the real id).

## Terrain sources

* `data/thanet/out/unreal/landscape` (adapter product, `landscape_manifest.json` + `hm_*.r16` + `clip_*.r8`) is
  the reference once it exists: `Heightfield.from_landscape_dir`, readable by every python.
* Until then the documented convenience: `Heightfield.from_step05_dir(data/margate/out/terrain)` (GDAL, env
  python only) with the document's Thanet origin applied through `rebased(E, N)` (= the +5120 m shift:
  Margate tile (5, 5) is Thanet tile (15, 15)).  `--export-terrain-npz` writes the tiles under the site as an
  `.npz` cache that Blender loads.  `stats.json.terrain.source` names the source that was used.

## Decisions taken by the implementation (where DESIGN / SCHEMA left a choice, or could not be met literally)

1. **Arc-length moving average.** `moving_average_arclength` integrates the piecewise-linear z(s) over
   `[s_i - hw_i, s_i + hw_i]` (trapezoidal weights), so the smoothed height does not depend on how densely the
   stations happen to fall inside the window.  Uniform station weights (the design prototype) missed the B6
   `dtm_ma15` table at s = 100 by 2.5 cm because six mandatory stations cluster in 94–101 m; arc-length
   weights reproduce the table to 1 mm (20.469 / 19.349 / 18.239 at s = 10 / 100 / 160).  The frozen
   smoothing factors are re-measured with it (W20 2.748, W10 2.039, 2-pass 3.175, ripple 0.0072); every
   threshold of SCHEMA.md 9.3 still holds.
2. **Waypoints are mandatory stations** (SCHEMA.md 3.2).  DESIGN.md 3.7's N = 101 / 117 for `sine_5_50` /
   `curve_R20_200` were counted by the design prototype without that rule; with it N = 119 / 125 (rail 653).
   The spacing statistics (crest 0.84 / inflection 1.54 / arc 0.98 / bend 0.833) reproduce the design when
   measured on adaptive-to-adaptive gaps, which is what the tests do.  `fixtures/expected.json` records both.
3. **Profile switches add ramp stations.**  A `Segment.edge.profile_id` / `road.profile_id` acts as a ramped
   scalar override (SCHEMA.md 5.3), so it contributes `s0 - ramp` and `s1 + ramp` as mandatory stations as well
   as `s0`, `s1` (the stretch has 100.9 from the half-grass switch ending at 95.9).  Its list replacement
   happens at the profile-layer level, below every spline-segment layer (SCHEMA.md 5.4 layer order).
4. **The split row S is always emitted** (at 0.5 kw with the kerb material where no split is in force) so one
   row set serves the whole sweep and a profile switch changes only materials: kerb rows are 13 per station
   (A, B×2, C, L1–L3, D, S, E, F×2, G).
5. **Marking heights sit on the road MESH** at every station (shared stations too): the strip vertex height is
   the barycentric height of the ribbon triangle pair under it plus `lift_m`, so `surface_height_at` on the
   mesh gives exactly `lift_m` everywhere (at a shared station the analytic parabola is up to 1 mm above the
   mesh chord).  Dash ends are interpolated frames, never stations.
6. **`profile_ids.road = null`** gives `w(s) = 0` even when points carry `width_m` (SCHEMA.md 4.13).
7. **Hedge leaf cards** are generated only for triangles whose mean section height is above 0.05 m (the base
   band and the bottom face carry none); the test compares the count with 12 x that area.
8. **Renders**: the DTM context patch is sunk 0.3 m (the raw DTM already carries the real road's crown, and
   the skirts hide 0.30 m); it is decoration, not part of the build.  EEVEE only (Workbench is not
   selectable headless on this machine).

## Frozen numbers (see fixtures/expected.json for all of them)

straight_100: N 54, gaps 0.17 / 2.0, w(45) 7.0, ribbon 11 rows 594 verts 1060 tris, overlap 0.040 both
sides, coincident positions 2 per station (108), hk 0.006 / 0.0655, back edge 0.150, 17 dashes, double
yellow at o0 − 0.35 / − 0.15, lift 0.004 ± 1e-9, 19 strips; rail_R300_600: inner faces 1.435, centres
1.50485, rail top 0.21375, 924 sleepers at 0.65, toe 4.75, bend spacing 0.833; test stretch (Margate
tiles, +5120): L 171.405, N 116, overlap 0.040, 31 strips, road 1794/2756, edge_left 1508/2318,
edge_right 2696/3448, hedge_right 364/724, posts 18 round + 23 square, 1650 leaf cards, z_ref(10/100/160)
20.469 / 19.349 / 18.239.
