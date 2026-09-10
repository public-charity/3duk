# Resume here

## Current checkpoint — 2026-09-10, Phase 1 completion

### Eleventh milestone — 2026-09-11: bounded corner terrain contact

- Latest committed milestone **`dd9ee22`**, full junction QC census. No engine job.
- New working tools `diag/terrain_contact.py` and `diag/junction_contact_candidate.py`
  test sparse terrain cuts on ordinary non-occluded corners. Intersect actual mesh
  triangles with LOD-0 landscape triangles; constrain every intersection vertex;
  minimize total post lowering with a 0.5 m cap in INTEGER encoding steps, and
  update both copies of a tile seam. Source rasters never change. A first continuous
  solver was replaced because post-rounding can violate an adjacent edge's cut limit.
- **58/58 tool tests pass**, `Saved/phase1_tools_58.log`; six new contact tests cover
  sub-cell triangles, interior penetration despite clear vertices, shared seams,
  invalid/over-budget inputs, the actual terrain diagonal, and incompatible edge
  contact. No core/native geometry changed; NumPy 152 remains the current baseline.
- First real pilot junction:16_8:2 / :3 changed only **10 posts**, max 0.383 m.
  Both corner interiors became clear by >=10 mm; actual outer corner bases had
  no daylight before or after. State `junction_contact_candidates/415e8f5721e5b14326af/report.json`.
  It was correctly retained as REJECTED because the initial neighbour check found
  apparent float increases. That neighbour check included trimmed-out stations.
- The corrected emitted-row check still found real daylight. Final tool measures
  actual banked outer-base XY/Z at <=25 cm spacing and uses these as additional
  constraints. Some cuts are infeasible without changing pavement/support geometry.
- Passing candidates (current tool): **junction:16_8:3**, **junction:20_11:3**,
  **junction:22_4:1**. Reports respectively
  `junction_contact_candidates/c2c051f6797537904b34/report.json`,
  `junction_contact_candidates/e5259755dbcf4fbae8cc/report.json`,
  `junction_contact_candidates/b81563f0a651c2f8a0d3/report.json`.
  The third required a protected re-solve: 2 posts rather than its initial 1.
  Rejected :16_8:2, :5_12:7, :15_14:3/:22 and :15_13:3 need edge geometry work.
  Logs `Saved/phase1_corner_*.log` preserve all attempts; failed candidates are not
  silently dropped or materialized.
- **Derived product complete**, `Saved/Phase1/ground_contact_candidate/`:
  **8 changed posts across 3 tiles**, max additional lowering 0.171875 m, all
  **2,486 output files verified**. New `materialize_contact_candidate.py` validates
  every candidate/source hash, rejects interacting patches, resumes bounded copies,
  updates tile statistics and survey-relative signed deltas, and publishes the
  final manifest last. State `contact_build_state.json`, log
  `Saved/phase1_contact_materialize.log`. No production import or engine process.
- Independent read-back: all **391 heightmaps compared**, exactly 8 changes;
  all **246 available signed deltas recover raw survey bytes exactly**. Rebuilt
  all junctions in the 3 touched documents: **73 pass / 2 existing failures**
  (75 total), the three repaired corners pass. Evidence inside product:
  `independent_verification.json`; log `Saved/phase1_contact_verify.log`.
- Still need a safe unsaved terrain preview and visual acceptance. Native landscape
  importer saves/deletes assets; do not use it for previews. FHeightmapAccessor under
  a scoped base edit layer may support a bounded unsaved preview, but is not yet
  implemented. Current level still uses the older terrain product.
- Next substantial geometry work: bank-aware Renderer B supports (actual world edge,
  terrain-intersecting batter toes, downhill retaining walls), with NumPy/native
  parity and focused fixtures. Unconstrained cuts cannot solve the floating edges.
- Full junction census worst corner failures reach 6.79 m (junction:19_2:15),
  4.66 m (:21_3:4), 1.65 m (:20_3:21). All A patches pass. Do not turn these
  coastal/multi-level geometry defects into large terrain excavations.

### Tenth milestone: side-aware float and emitted junction mesh QC

- Latest commit **`d181075`** contains the Broadley candidate generator and previous
  full ground census. Working changes improve QC; source/terrain/render geometry
  remains unchanged. No engine process is running.
- Fixed `fusion.audit_spline`: a kerb on one side no longer hides a bare edge on the
  other side; road skirt depth is measured in world Z after bank. Asymmetric left/right
  fixtures prove the defect is detected. **152/152 NumPy core tests pass**,
  `Saved/phase1_numpy_152.log`; 19 focused conform tests also pass.
- Side-aware full census **62/62 chunks complete**, same LOD-0 max penetration
  0.8005 mm. Floating now **55,414 / 660,835 stations = 8.38545%**, **65.961 km**,
  max 12.2915 m. The old 8.0557% / 63.245 km undercounted asymmetric edges.
  State: `ground_candidate_qc/full/c05c542984ffdc521cc4/state.json`.
  Log: `Saved/phase1_ground_candidate_full_sides.log`.
  Reports now list EVERY floating run with ID, class, arc range, length and worst XY.
- Largest outliers are coastal stairs/landings: Augusta Steps / roads:138578171:0
  and adjacent footway roads:138578168:0 at local (11113,1991), plus steps/footways
  roads:43998874/75/76 at (10426,1432). Treat these as multi-level structures and
  stair/landing supports, not blindly as ordinary earthwork batters.
- The ribbon audit now explicitly labels its scope: **untrimmed ribbon envelopes**.
  It cannot certify junction patches/corners. Added `diag/junction_mesh_audit.py`
  builds actual trimmed-arm patch and upper corner triangles, samples interiors
  at <=25 cm edge spacing, and accounts for higher road geometry covering a lower
  corner. Missing ground and build failures fail. Deep road/pavement overlap is
  a separate review status. Every document is atomically checkpointed with hashes.
- **52/52 tool tests pass**, `Saved/phase1_tools_52.log`: interior penetration despite
  clear vertices, empty/missing terrain, and hidden lower surface classification.
  A first test fixture was too narrow for its arbitrary >10 cm expectation; widened
  the synthetic hill. The 5 mm production gate was never relaxed.
- Sample junction geometry completed 35 documents / **430 junctions** in 70.6 s:
  **401 passed, 18 overlap reviews, 10 failed, 1 needs structure model**.
  State `junction_mesh_qc/e0a4d8b565784253f11f/state.json`, log
  `Saved/phase1_junction_mesh_sample_complete.log`.
  This sample predates adding imported audit helpers to the input hash list;
  measured code is the same, but a fresh invocation will use a new state identity.
- Specific real visible corner failures: junction:16_8:2 at (8370.13,4484.91),
  **296 mm** terrain above pavement; junction:16_8:3 at (8381.05,4438.47), **56.8 mm**.
  junction:15_9:1 has 47.3 mm visible penetration as well as buried pavement.
  A naive surface check falsely classified the worst buried point at junction:15_10:5
  as green terrain intrusion: the road patch above it is clear. It now correctly
  remains an overlap review (corner ~1.11 m below that road), not visible penetration.
  Evidence: `Saved/Phase1/probe_junction_occlusion.json`.
- Full emitted-junction census COMPLETE: **1,642 junctions = 1,513 passed,
  85 overlap reviews, 36 failed, 8 need structure models**. State
  `junction_mesh_qc/a087591d8ce94eb1833f/state.json`; log
  `Saved/phase1_junction_mesh_full.log`. Exit 1 correctly reflects open defects.
  No jobs are running. `--max-docs 4` gives a bounded continuation for new inputs.
- Next: finish full junction ledger, then correct visible corner terrain gaps on a
  small candidate first; investigate buried/overlapping pavement separately. A small
  derived-terrain patch can avoid re-stamping all 12k roads, but needs proof and hashes.
  Renderer B bank-aware support/toe geometry and stairs remain open.
- Changes to diagnostic core files deliberately invalidate old structure-inventory
  source hashes. Existing candidate artifacts retain their old provenance. Refresh
  the inventory to a NEW output path before generating new candidates; do not overwrite
  historical inventory/fit artifacts or rerun a 23-minute terrain conform solely
  because an unrelated diagnostic hash changed.

### Ninth milestone in progress: ground census complete, Broadley floor candidate

- Latest committed code: **`06d87d4`**, validated document export/refresh. Working
  changes add an underpass floor candidate generator and ground-candidate crossing audit.
- Full corrected-terrain census **62/62 chunks pass**, 595.24 s total worker time.
  State `Saved/Phase1/ground_candidate_qc/full/23e0541a1dd5b0a8a66e/state.json`.
  13,097 selected = **12,945 measured + 151 structures + 1 named no-terrain stub**.
  LOD 0: 660,835 stations / **961.532 km**, max penetration **0.8005 mm**, none over
  the 5 mm gate. Floating: **8.0557% of stations / 63.245 km**, max **12.292 m**.
  Coarser LODs still penetrate; structures, floating edges and engine acceptance OPEN.
  This candidate has NOT been imported. There are no running engine jobs.
- Broadley road floor candidate **generated**, three changed splines, full source
  document retained because the two approaches have remote junctions:
  `Saved/Phase1/broadley_road_candidate_v2/` (current tool), previous identical geometry
  `broadley_road_candidate/`. Source and survey unchanged. Max lowering 1.596 m.
  All 31 tested visible approach stations agree with DTM within 25 cm; p95 residual
  by segment <= 13.64 cm. The area under modelled rail footprints + 2 m raster margin
  is explicitly unobserved/inferred, not claimed as surveyed road floor.
- A long single height blend failed the visible-approach gate (68% support after
  the bridge). The accepted candidate uses nearby height anchors 5 m beyond the
  underpass ends and longer bank-only blends (20 m before / 40 m after). Endpoints
  match across all three splines. **49/49 tool tests pass**, `Saved/phase1_tools_49.log`.
  Added tests recover a known occluded floor/tangents exactly and reject short,
  nonfinite or excessive-grade inputs.
- Crossing measurement with the first equivalent road candidate:
  `rail_network_with_broadley_clearance.json`, 18 rail/road overlaps measured.
  Broadley minimum nominal ballast-base clearance improves from **1.971/1.779 m**
  to **3.557/3.410 m**. This is NOT structural soffit clearance. Original OSM road
  way 979368122 carries `maxheight=10'0\"`; actual bridge beam geometry is still absent.
- Candidate scope is **`document_elevations`**, not `delta`. Existing rail preview
  helper deliberately refuses this scope. Use complete-document refresh for a future
  safe in-memory preview; DO NOT reuse the replace-by-ID importer. Still needed:
  bank/width visual review, closed soffit/support geometry and candidate terrain conform.
- Next QC correction discovered during review: `fusion.audit_spline` uses `edge_any`
  to suppress BOTH bare road edges when EITHER side has a kerb. This can undercount
  daylight on the opposite bare side. Fix it per side with an asymmetric fixture,
  and refresh ground census numbers before relying on the float percentage.

### Eighth milestone: junction document editing/export and corrected terrain sample

- Full corrected terrain conform **completed**, 246 documents, 391 tiles, 1,390.5 s
  for the resumed 242-document invocation. Log: `Saved/phase1_ground_conform_complete.log`.
  State: `Saved/Phase1/ground_conform_state/31dcf1d182f95cf3a33a/state.json`.
  Output: `Saved/Phase1/ground_conformed_triangulated/`. Production is unchanged.
- Corrected sample **12/12 chunks pass**, 2,843 measured splines / 133,265 stations /
  192.737 km, **zero LOD-0 penetration**. 24 structures and the named no-terrain stub
  remain explicit exclusions. Floating remains **11.6287%**, max 4.480 m; this is NOT
  site acceptance. State `ground_candidate_qc/sample/6604853a1bbcfc30d0d7/state.json`.
- Full candidate census is COMPLETE (see current figures above), state
  `ground_candidate_qc/full/23e0541a1dd5b0a8a66e/state.json`, log
  `Saved/phase1_ground_candidate_full.log`. Resume `phase1_qc.py --scope full
  --landscape projects/one/Saved/Phase1/ground_conformed_triangulated
  --out projects/one/Saved/Phase1/ground_candidate_qc --max-jobs 0` through python.ps1.
  Do not modify its Python/core inputs while running. Each chunk is checkpointed.
- Working changes add `ExportDocumentJson(source, out)` and
  `RefreshDocumentJunctions(source)` in the editor module. Source supplies ALL junctions,
  loaded actors supply current spline/profile edits. The old generic exporter now
  refuses junction-bearing actors. Build **passed**, `Saved/phase1_document_edit_build.log`.
  **2/2 new native tests pass**, `Saved/phase1_document_edit_tests.runner.log`, covering
  all six junction fixtures, canonical round trips, disabled junction preservation,
  updated owner arm copies and incomplete/conflicting input rejection.
- Real edit/export/restore **passed**, `Saved/Phase1/document_roundtrip/report.json`:
  six actors / one junction in site_x1_y12. Moving roads:1291638667:0's non-junction
  point by 15 cm changed roads:30195361:1's owner patch; restoration matched original
  JSON and junction statistics exactly. Actor paths retained, all **15,913 Content
  files byte-identical**. Runner 41.3 s, only VC++ advisory waived.
  First diagnostic attempt failed before mutation on a non-exposed Python property;
  replacement verifies the owner's actual emitted patch statistics.
- Editing is an explicit whole-document refresh, not an automatic gizmo listener.
  `Tools/ue/README.md` records point synchronization and export workflow. No production
  actors, source JSON or survey pixels changed. Original 35-test native baseline remains
  valid; two new editor tests were run separately. Ground/core Python unchanged.
- Broadley underpass probe confirms survey contamination: source roads:979368122:0
  is 15.85 m long, DTM rises from ~23.55 m at its approach to **27.23 m** at s=8 m,
  where DSM is ~27.78 m (rail deck). Smoothed road is incorrectly up at ~25 m.
  `Saved/Phase1/probe_broadley.json`, `Saved/phase1_broadley_probe.log`. Next: infer
  road floor from connected visible approaches with explicit occlusion provenance;
  do not blindly raise the rail to compensate. No road candidate created yet.

### Seventh milestone: resumable corrected terrain conform

- Committed checkpoint: **`ac51e3e`**, exact sparse conformance checkpoints (previous
  **`78a81ff`** contains connected rail profiles, safe preview and restored baseline).
- `conform_landscape.py --checkpoint-dir <dir> --max-docs 4` stamps at most four
  NEW documents and returns pending (exit 2) until all documents are processed.
  Checkpoint includes exact accumulator key/float32 targets, class/run/structure
  diagnostics, raw earthwork samples, input hashes and document coverage. An OS lock
  serializes writers. No output product is emitted for a pending invocation.
  Resume uses the same command; `--max-docs 0` completes remaining documents,
  still checkpointing every four. Interrupted final raster output can be rewritten
  from the completed stamping state without recomputing splines.
- Former silent spline/junction-arm construction exceptions now stop conformance.
  Intentional structure and no-terrain exclusions remain named in the report.
- **46/46 tool tests pass**, `Saved/phase1_tools_46.log`. Tests prove exact
  float-bit/rank arbitration after resume, changed-source rejection and damaged-cache
  rejection. Real two-document interrupted/resumed conform compared against uninterrupted:
  **398/398 heightmap/delta rasters byte-identical**, zero differences.
  Proof folders `Saved/Phase1/conform_resume_proof/`, `conform_uninterrupted_proof/`;
  state `conform_resume_state/4d615f2fe8b2051ea3e7/state.json`.
  First one-document checkpoint is only **1.44 MB**, not a full landscape copy.
- Starting full-site corrected (triangulated) baseline conform into
  `Saved/Phase1/ground_conformed_triangulated/`, with state under
  `Saved/Phase1/ground_conform_state/`; first four-document run log:
  `Saved/phase1_ground_conform_batch1.log`. This is a candidate product. Do NOT
  import before auditing it. Bridge-profile candidate overrides are still separate.
- Current baseline ground sample completed again: **10 pass / 2 fail** at
  `sample/6a0b0866f116a8cb1337/state.json`, same max 13.644/23.116 mm penetration.
  Next: complete resumable conform, audit the resulting sample, then full census.
  Structure/support, junction editing/export and visual acceptance remain open.

### Preview importer side effect recovered and verified

- The full Margate preview failed because an original actor was absent on the next
  engine load. Traced to the earlier preview helper calling ImportStreetscapeJson:
  it calls DeleteActorsAndPackages, which deletes existing external .uasset files
  immediately even without SaveAll. Prior claims that the preview left Content
  unchanged were wrong. Source JSON and survey products ARE unchanged.
- Affected successful previews: six Minnis rail IDs from minnis_bridge_candidate,
  six Margate rail IDs from paired_bridge_candidate. The full four-span preview
  failed before applying anything. Restore the union of those 12 original IDs.
- New native PreviewElevationJson mutates only loaded spline elevation profiles;
  no spawn/delete/save. RestoreMissingBaselineJson creates only absent original
  non-junction actors and saves only their new external packages.
- Recovery build succeeded. Targeted restore **completed**, 12 original IDs restored,
  twelve new actor packages; no pre-existing Content file changed or was deleted.
  Evidence: Saved/Phase1/preview_recovery/restore.json and
  Saved/phase1_preview_recovery.runner.log (146 s, post-success teardown crash).
- Fresh-process verification **completed**: all twelve original IDs reload exactly
  once; no Content file added, changed or deleted. Runner verdict passed with the
  known post-success teardown crash (107.6 s).
  Report: Saved/Phase1/preview_recovery/verify_reload.json.
  Log: Saved/phase1_preview_recovery_verify.runner.log.
  The script checks source hashes, ID counts, per-actor stats and Content changes.
- **43/43 tool tests pass**, Saved/phase1_tools_43_final.log. The safe four-span render
  **passed and was visually inspected**, Saved/Phase1/margate_four_bridge_preview_safe;
  runner log Saved/phase1_margate_four_preview_safe.runner.log (115 s). Its manifest
  proves actor_paths_unchanged=true, saved=false, all **15,913 Content files
  byte-identical**. New preview/recovery code compiled successfully.
- Standard captures now include a byte-level Content-integrity guard. Do not run
  the old candidate_preview.py from commit 68e32c0 or 5dc05d9.

### Sixth milestone: connected rail structures and verified transient preview

- Previous checkpoint **`5dc05d9`** contains the bounded structure screening.
- `bridge_profile_candidate.py --connected` now follows unambiguous ground track
  across tile-boundary stubs, includes passing neighbouring decks across short links,
  interpolates height/tangent continuously between those decks, and splits the shared
  profile back to the original per-spline arcs. Reversed fragments flip signed bank.
  Overlapping incompatible edits fail; all changed station heights still need DSM support.
  Candidate outputs now refuse to overwrite an existing manifest.
- **40/40 tool tests pass**, including reversed bank/arc roundtrip, paired spans with
  a reversed 2 m stub, unsupported neighbouring deck rejection and conflicting edits.
  No core renderer/schema change in this milestone; native tests remain 35/35.
- Connected census: `Saved/Phase1/structures/8d47c7fb87e6c61b2583/state.json`:
  **16 candidate rail groups, 8 approach reviews** (was 8/16). Other 109 groups remain
  unresolved as before. Three bridge pairs appear from either seed, so the ledger
  explicitly flags their duplicate changed IDs; do not concatenate candidate documents.
  Use one connected generation with the union of selected groups.
- Margate four-span candidate: `Saved/Phase1/margate_four_bridge_candidate/`, 12
  splines across two selected tracks, two short connectors and two tile-boundary stubs.
  Generated in 5.6 s; nominal rail-base clearance min **4.407 m** above road mesh
  (`margate_four_bridge_clearance.json`). This still is not a designed soffit.
- Initial pair, six-spline before/after renders inspected:
  `Saved/Phase1/paired_bridge_before/`, `paired_bridge_after/`.
  Selected track is continuous above both crossings; adjacent unmodified track
  retains the old dips. Renderer B support geometry remains absent.
  The first full four-span render (`margate_four_bridge_preview/`) failed and exposed
  the importer side effect described above. Safe replacement render
  `margate_four_bridge_preview_safe/` passed with file and actor-identity evidence.
- Fixed camera is now tracked at `Tools/ue/render_structure_probes.json`; it has
  exactly the same capture controls and transform as the initial Saved diagnostic.
- A union candidate for all 16 supported rail groups generated in 6.7 s, **50
  splines**, `Saved/Phase1/rail_network_candidate/`; `phase1_rail_network.log`.
  Crossing report `rail_network_clearance.json` measures 18 overlaps. Two spans,
  rail:28752680:0 and rail:311074731:0, are only **1.971 m / 1.779 m** above the
  current Broadley Road mesh (roads:979368122:0, unclassified). Positive clearance
  alone is insufficient; inspect and model the road-under-bridge alignment before
  these groups can pass. Do not combine candidate status with production acceptance.
  An additional six-span/18-spline Margate candidate exists at
  `margate_six_bridge_candidate/` (three selected tracks, not yet rendered).
  There are actually EIGHT bridge spans near this camera. The last pair
  rail:30725164:0 / rail:30725166:0 is blocked by the latter's rejected DSM p20 fit.
  Diagnostic `probe_rejected_deck.py` shows centre/upper returns are supported
  while lower lateral samples fall through the edge. Do not silently swap estimators:
  resolve deck width/return selection and approach continuity with provenance first.
  Next: checkpoint, then add actual support geometry and address unresolved
  structures plus road/junction/full-ground acceptance. Production source documents
  and survey data are unchanged. Recovered actor packages contain original definitions.

- Ground QC resumed against current core: sample state
  Saved/Phase1/sample/6a0b0866f116a8cb1337/state.json. Four of twelve chunks
  passed; eight remain pending. Check phase1_ground_resume*.log. Production
  conformed terrain still uses the older sampler; correction/import remains open.

### Fifth milestone: bounded structure rollout

- Current committed source: **`68e32c0`**, continuous Minnis bridge candidate and
  shared elevation-profile schema. No production data or saved level changed.
- Source structure semantics are now recorded in `structures_baseline.json`:
  14 building passages, two covered passages, nine rail sidings requiring cover
  context review. Do not treat every boolean `tunnel` flag as an underground road.
- Inventory now hashes the actual DSM raster dependencies, survey samples/masks,
  OSM source and geometry modules. Unchanged VRT filenames alone cannot validate
  cached fits. Inventory and deck fits regenerated; historical candidate folders
  still describe earlier evidence and must not be mixed with the new inventory.
- `Tools/diag/structure_workflow.py` accounts for all 133 groups, then attempts four
  passing rail fits per call (60 s deadline each). Uses content fingerprint, OS lock,
  atomic per-group checkpoints, separate attempt directories, output hashes, final
  input recheck, and shared-approach conflict reporting. `--max-jobs 0` runs remaining
  groups. State pointer: `Saved/Phase1/structures/latest.json`.
- Candidate generation also requires 80% of changed stations to match DSM within
  0.25 m. Supported span fits alone cannot certify unsupported approaches.
- **36/36 tool tests pass**, `Saved/phase1_tools_36.log`. Completed 24 rail-fit jobs,
  about 4.6–5.4 s each: **8 candidates, 16 requiring approach work**. All 133 groups
  accounted for: also 34 deck-fit reviews, 25 road-approach models, 50 context models.
  State: `Saved/Phase1/structures/c6e5169baf705bcf9ea1/state.json`. Logs:
  `phase1_structure_batch1.log`, `phase1_structure_remaining.log`; repeated invocation
  reused every result in 7.4 s (`phase1_structure_resume.log`). None of the eight
  candidates share a changed approach; crossing/support/visual checks remain open.
- Short approaches are real: several bridge pairs have only 9–13 m between them,
  and tile-boundary stubs can be 0.5–3 m. They need a connected alignment across
  segments, not a forced 40 m transition on each segment. Other failures need
  locally supported curvature/grade handling; do not relax gates to turn them green.
- Next: resolve short/shared approach cases, then
  add actual bridge/support geometry and road/junction treatments. No Phase 1 pass.

### Fourth milestone: continuous Minnis bridge/approach candidate

- Previous source checkpoint **`ac64942`** contains the verified capture-readiness fix.
- Added optional `Spline.elevation_profile` knots `{s_m,z_m,bank_deg}` to the shared
  JSON, NumPy and C++ schema/build. Profiles cover exactly the untrimmed spline arc;
  knots become shared mandatory stations. They override reference elevation/bank,
  preserve raw survey samples, roundtrip, and fail if an edited horizontal path
  invalidates their length. Existing documents without the field behave unchanged.
- NumPy suite **151/151** passes (`Saved/phase1_elevation_numpy.log`); Unreal build
  passed after correcting a negative-test fixture pointer; Unreal **35/35** passes
  (`Saved/phase1_elevation_tests.runner.log`). All five new profile parity arrays are
  **56/56 bit-identical**. Do not reuse the old seven-case parity JSON.
- `Tools/diag/bridge_profile_candidate.py` builds explicitly selected, passing rail
  DSM fits with supported 40–120 m Hermite approach blends. Missing/ambiguous anchors,
  excessive grade/bank rate, stale source documents and conflicting profiles fail.
  The initial two Minnis spans plus four approaches generate in **2.1 seconds**:
  `Saved/Phase1/minnis_bridge_candidate/candidate_manifest.json` (delta scope).
  All four blends are 40 m; maximum grade 1.381%; changed-approach DSM residual p95
  3.5–7.2 cm. Profile endpoints match exactly in height/bank; remote approach geometry
  remains at its earlier reference. Bridge spans have zero modelled bank.
- Reproduce: `& projects/one/Tools/python.ps1 projects/one/Tools/diag/bridge_profile_candidate.py --group rail:310977210:0 --group rail:4596560:0 --out projects/one/Saved/Phase1/minnis_bridge_candidate`.
- `Tools/diag/bridge_crossing_audit.py` samples the nominal ballast base against
  actual road triangles at 0.25 m spacing. Minnis minimum is **4.633 m**. This is a
  model envelope, not a surveyed/designed soffit: ballast is currently open below.
  Report: `Saved/Phase1/minnis_bridge_clearance.json`.
- Fixed-camera engine preview inspected: `Saved/Phase1/minnis_bridge_preview/manifest.json`.
  Both spans now cross above the road with continuous approaches; sag and foreground
  grass patches are absent. Capture takes 103 s with the recorded post-success
  teardown crash. Renderer B supports/retaining edges and broader rollout remain open.
- `render_set.ps1 -CandidateStreetscape <dir>` verifies candidate hashes, requires
  exactly one loaded actor per ID, imports the delta in memory, checks the unchanged
  actor census, and records per-actor stats. **It never saves the level.** Currently
  restricted to splines without junction ownership. Production data and level are
  still unchanged. Candidate provenance lives with the separate modelled documents.
- Source checkpoint: **`68e32c0`**. Next: inspect unsupported structure groups,
  extend bounded candidate generation beyond the two rail pilots, add support/edge
  geometry, and then conform/import only reviewed derived products. Full Phase 1
  acceptance remains open; do not infer it from the pilot or unit-test totals.

### Third milestone: Minnis foreground capture defect isolated and fixed

- Source checkpoint before this milestone: **`7e15e8d`**. That commit contains the
  corrected production sampler, hardened parity gate and structure/DSM diagnostics.
- `Tools/diag/mesh_clearance.py` samples actual emitted triangle interiors at 0.25 m
  spacing. Five Minnis road carriageways have no penetration above 5 mm; the maximum
  is 2.09 mm. Runtime bounding boxes and ten-metre height probes match NumPy exactly.
  Evidence: `Saved/Phase1/minnis_mesh_clearance.json`, `minnis_engine_probe.json`.
  Edge counts include potentially covered tuck faces and are diagnostic, not an
  exposed-surface acceptance claim. Four deliberate-defect tests pass.
- Hiding the landscape removes the green patches. Explicitly forcing all **96**
  loaded terrain components to LOD 0 does **not** remove them. Evidence directories:
  `Saved/Phase1/minnis_landscape_hidden/`, `minnis_forced_lod0/`.
- **Root cause: asynchronous heightmap compilation/residency in headless captures.**
  Before preparation, texture APIs report placeholder one-mip resources; later the
  real nine-mip textures have only seven resident. Completing texture compilation
  and requesting/waiting for full residency produces nine resident mips and removes
  every foreground green patch, with NO terrain/road elevation changes. Engine source
  `LandscapeRender.cpp:4516` clamps rendered detail to the first resident height mip,
  independently of the component's forced LOD. `Saved/Phase1/minnis_residency.json`.
- Standard `05_screenshot.capture` now completes/streams loaded landscape heightmaps
  before the final capture and fails for incomplete residency. `07_render_set` and
  `render_set.ps1` retain per-texture readiness evidence in their reports/manifests.
  Diagnostic variants can bypass preparation explicitly to reproduce the defect.
- Build passed; **26 tool tests pass**, including missing/coarse-mip failure proofs.
  Standard two-camera render: `Saved/Phase1/capture_ready/`; both images inspected.
  Minnis carriageway is clear; urban road remains continuous. Railway sag, steep
  unsupported cutting sides and black massing shadows are still visible and open.
  The known post-success engine teardown crash still occurs; inspect runner verdict.
- No production terrain, streetscape data or saved level assets changed. Next work:
  explicit shared-schema elevation/bank profiles, first on the two DSM-supported
  Minnis rail spans with continuous approach transitions; then sample/full expansion.

### Second milestone after source checkpoint `6ef72f0`

- **The earlier green sample used bilinear road construction. The saved Unreal
  site uses triangulated construction** (`Saved/Logs/render_set_all.log`, line
  reporting the loaded `landscape` terrain source, not the capture's private
  `landscape_conformed` probe). `road_fusion_audit.py` and `conform_landscape.py`
  now have explicit `--survey-sampling`, defaulting to `landscape_triangulated`;
  the generic geometry fixture default remains bilinear. QC records the choice.
- Corrected sample state: `Saved/Phase1/sample/714a0b1d99df9fdd3309/state.json`:
  **10 batches pass, 2 fail**, worst ground penetration 13.644 mm and 23.116 mm.
  This mismatch is a real QC
  defect; it has not yet been proved to explain the visible Minnis cutting patches.
- `Tools/diag/structure_inventory.py` measures all 151 flagged segments in 133
  connected groups (83 bridges, 50 tunnels), including five groups across documents.
  It uses mutual nearest endpoints so a 7 cm split stub does not create a branch.
  Latest report: `Saved/Phase1/structures_baseline.json`, now triangulated survey.
- **Useful new evidence at Minnis Road:** raw first-return DSM is almost flat around
  13 m ODN across both rail spans while DTM falls to ~7.5 m under them. Even bridge
  DTM endpoints are too low. Do not use a chord of the DTM endpoints as the deck.
- `Tools/diag/fit_structure_decks.py` fits robust candidate lines to DSM lateral
  20th-percentile samples and rejects coverage, abutment, residual, lateral-spread
  and grade failures. Initial result: 49 bridge candidates, 34 requiring review,
  50 tunnels requiring a different model. **No candidate is production accepted.**
  Minnis fits match first return to max 4.5 cm, at ~0.9% grade. Approaches still need
  up to ~2.8 m correction, so changing the deck alone would leave endpoint steps.
- Five deck-fit failure tests plus 14 QC tests pass (19 total). Inventory and deck-fit
  reports have both been regenerated against triangulated construction.
- Another dishonest green was found: `Streetscape.Spline.NumpyParity` returned success
  when no reference JSON existed, and skipped missing cases/arrays. It now fails
  for those conditions; `run_ue_tests.ps1` generates a fresh reference by default.
  The reference now includes rail and non-planar terrain under both sampling rules.
  Build and fresh-reference automation passed **34/34**, including bit-identical
  non-planar triangulated arrays. `Saved/phase1_tests_sampling.runner.log`.
  Deliberate empty reference `{}` fails with seven missing-case errors and exit 2:
  `Saved/phase1_parity_negative.runner.log`.
- One-document triangulated conform completed in **14.9 seconds** under
  `Saved/Phase1/minnis_conform_triangulated`. It is explicitly a **subset**, despite
  having the full raster directory layout: never import it over the full site.
  Production terrain is unchanged. Its audit has zero LOD-0 station penetration,
  but 7.959% floating stations and 4.480 m maximum float. Partial conform now refuses
  the default production destination; a failure test proves that guard.
- Same Minnis camera with `landscape_lod0_screen_size=0.01` still shows foreground
  grass through the road: `Saved/Phase1/minnis_lod_diagnostic/manifest.json`.
  One frame took 93 s, with the recorded post-success teardown crash. The original
  45 camera definitions remain untouched; `render_set.ps1 -Spec` accepts a candidate
  capture specification. The LOD knob is **not** a proven fix for this cutting.
- Next: audit interiors of actual emitted road triangles, not only sampled analytic
  station cross-sections. Check runtime mesh/probe agreement at the breakthrough.
  Then implement explicit deck profiles plus supported approach transitions.

### Completed first milestone (historical numerical baseline uses bilinear)

This section supersedes the historical September 9 handover below. Read
`PHASE1_QC.md` for the active strategy and acceptance ledger.

- Start: clean tree at `e67b876`, branch `thanet-explorer`. No Unreal editor process
  was running when inspected. Survey and generated products are present.
- User objective: finish a base for high-quality building overlays, with roads and
  streets in a sane state; use fast iterations and durable restart checkpoints.
- Completed: resumable, fail-closed numerical QC; debug overlay off by default in
  Unreal and Blender presentation. O-key now controls the actual world line batch,
  including newly streamed cells. No survey, road geometry or level asset changes.
- Verified: numpy baseline 147 tests; pipeline 167 checks; adapter 47 tests;
  QC failure/resume tests 13; Unreal build succeeded; Unreal automation **34/34**,
  including `Streetscape.Overlay.Lifecycle`. Logs: `Saved/phase1_*.log` and
  `Saved/Logs/phase1_tests.log`. The handover's 32-test count was stale.
- QC sample: 48 documents, 2,868 selected splines = 2,843 measured + 24 structures
  explicitly excluded + one named no-terrain stub. Twelve chunks took 111.34 seconds
  of audit time, about 7–13 seconds each. A second invocation reused all twelve in
  ~5 seconds. State: `Saved/Phase1/sample/70b1f1ab251bc2f0c187/state.json`.
- Numerical baseline: 133,265 stations / 192.737 km; LOD 0 has zero penetration above
  5 mm, but **11.638%** of stations float over 125 mm (max 4.475 m). Penetrated length:
  LOD 1 0.366%, LOD 2 2.657%, LOD 3 7.626%. These are recorded defects, not acceptance.
- Two fixed renders inspected: `Saved/Phase1/overlay_smoke/manifest.json`; overlay
  absent in both. `birchington/station_road_to_the_square.png` has continuous road
  and junction corner. `birchington/railway_bridge_over_minnis_road.png` still has
  conspicuous terrain breakthrough and a sagging railway span. Both PNG guards pass
  with low-detail warnings. Engine had the known **post-success teardown access
  violation**; runner recorded raw -1073741819 after the images/report/log closed.
- Findings: junction conform is already wired; overlay uses SDPG_World already;
  `road_fusion_audit.py --all` in HANDOVER.md is invalid (use `--n 0`).
- Next: investigate Minnis Road using its fixed camera and neighbouring documents;
  separate missing structure elevation from ground/LOD conflict. Inventory connected
  bridge segments and approach endpoint heights before choosing a deck model. Keep
  modelled structure heights in a separate derived product with explicit provenance.
- Useful implementation warning: `Spline.apply_pins` applies sequential local
  triangular corrections, so pinning only a bridge's endpoints does **not** create
  a straight deck. Do not mistake existing Z-pin support for a structure profile.
- Commands (PowerShell, repository root):
  `& projects/one/Tools/python.ps1 projects/one/Tools/phase1_qc.py --max-jobs 2`
  resumes up to two sample chunks (exit 2 = pending, 1 = failed, 0 = numerical
  checks complete). `--scope full --max-jobs 0` measures the full census, still with
  per-chunk checkpoints. Run commands to validate freshness; do not trust an old
  `latest.json` alone after changing source/data.
- Engine build/tests/render require writable AppData engine caches. Sandbox launches
  failed before work; rerunning with approved cache access succeeded. Do not work
  around permissions with another engine invocation.
- No full-site Phase 1 acceptance has been earned. Bridges, cuttings/bare edges,
  crossing paths and junction editing/roundtrip remain open.

---

## Historical checkpoint (superseded; retained for diagnostic context)

The VM this is built on drops without warning, and it has already taken the session down five
times. This file is the handover: read it first after any disconnect, and it should be enough to
pick the work up cold. Keep it current — it is the only file that claims to describe *now*.

Last updated: 2026-09-09, at the end of the "roads above ground, joined properly" round, by the
integrity agent. Sections 3 and 8 are the ones that go stale first.

---

## 1. One paragraph of context

`projects/one` is an Isle of Thanet digital-twin base in Unreal Engine 5.8, built from the `3duk`
pipeline's public-data products (EA 1 m LIDAR + OpenStreetMap, EPSG:27700, ODN metres). The isle is
cut from the mainland by a straight line along the old Wantsum Channel. On top of the terrain sits a
data-driven streetscape system: one shared spline read by three renderers (road, edge extrusion,
hedge), with every variant expressed as profile JSON and arc-length segment lists rather than code.
`docs/BRIEF.md` is the binding brief; section 4 wins over every other document.

## 2. Where the work stands

| | |
|---|---|
| Branch | `thanet-explorer` (not merged to `main`) |
| Last commit | `44f36bd` — a fixed set of 45 viewpoints rendered at every commit, and the road defect finally explained |
| Before that | `b1cd3e5` conform + seams + honest gates + the whole isle in the level, `b1a7c52` this file + `TERRAIN_ROADS.md`, `3e26561` integrity fixes, `4bfee9d` massing + explorer pawn, `bc08e22` renderers + landscape import |
| Re-measured 2026-09-09 by the integrity pass (at `44f36bd` + working tree) | `dryrun.py` **167 passed, 0 failed** · `test_unreal_adapter.py` **Ran 47 … OK** · numpy suite **Ran 116 … OK** · `build.ps1` **Result: Succeeded** · `run_ue_tests.ps1` **26 `Result={Success}`, 0 failures** (`Saved/Logs/tests.log`) · Margate gate **green** (below) |

**The Margate regression gate passes again**, and it can still fail:

```bash
export PY=C:/Users/Shadow/code/3duk-env/env/python.exe
./sources/tests/regress_outputs.sh compare  margate terrain_fix_before   # 1582 identical, 1 extended, 0 problems
./sources/tests/regress_outputs.sh compare  margate baseline_2026-09-08  # 794 identical, 1 extended, 788 added, 0 problems
./sources/tests/regress_outputs.sh selftest margate                      # 12 cases, 0 failed
```

`before` and `fixer_before` are **superseded snapshots and are still red on purpose** — see
`docs/STAGES.md` note (a). Use `terrain_fix_before` or `baseline_2026-09-08`.

**Data on disk (all git-ignored, hours to rebuild — do not delete):**

- `data/thanet/raw/` 3.9 GB — 988 LIDAR rasters and the 30 MB OSM extract. Re-fetching costs ~6 min
  for LIDAR and one Overpass call, but the OSM extract will differ from the one everything was built
  against (`sources/provenance/thanet.osm.json` records its sha256).
- `data/thanet/out/` — the survey products: 391 terrain tiles, roads, massing, coast, furniture, rail
  and barriers.
- `data/thanet/out/unreal/` — the engine products: `landscape/` (391 `hm_*.r16`, 391 `clip_*.r8`,
  31 `vis_*.r8`, weightmaps), 246 streetscape documents (~15,422 splines), massing, furniture, **and
  `landscape_conformed/`** — see §4. `landscape_clean/` and `landscape_seam/` are 25-file 2×2 cutouts
  left behind by `Tools/ue/gate_proofs.py`; they are scratch, not products.
- `projects/one/Content/` 2.1 GB — the generated level: landscape (2,067 components, 140 proxies),
  216 massing actors, 15,423 streetscape actors. **Regenerable** by the `Tools/ue` scripts, which is
  why it is ignored; regenerating the landscape costs ~6 minutes plus editor startup.
- `renders/<commit>/` — the fixed 45-viewpoint render set, committed via LFS with a `manifest.json`
  holding each camera transform and each image's sha256. `renders/b1cd3e5/INDEX.md` is the
  defect-by-defect reading of what the model looks like.

## 3. What this round did, agent by agent

Three agents worked in parallel on Alex's request — *"fix the roads so they are all above ground as
necessary and make sure they join together properly … make this a solid foundation"*. The binding
architectural call was:

> A junction is road **surface**, so filling it is **Renderer A**. There is no fourth renderer.
> The **trimming** of a spline end back to a junction belongs one level lower, in the **shared spline
> layer**, so Renderer A and Renderer B read one trimmed extent and cannot drift. Renderer B stops the
> kerb and pavement at the trim and turns the corner with a radius. Junctions are **data** — 1,642
> `_junction` records already in `data/thanet/out/networks/roads_*.jsonl`, already carried into every
> site document as `junctions[]` — use them, do not invent a parallel mechanism.

- **Geometry / spline** — `Tools/blender/streetscape/{spline,schema,road,edge,hedge,mesh,build,
  terrain,conform}.py`, `tests/synthetic.py`, `tests/test_conform.py`, `Tools/conform_landscape.py`,
  `Tools/road_fusion_audit.py`, `schema/streetscape.schema.json`. A `JunctionPlan` resolves the trim
  once per site; `Spline` takes `trim=(t_start, t_end)` as a **mask on `s`**, not a re-basing (so every
  segment list and every `s`-ranged override keeps its meaning), and both trim stations are added to
  the mandatory station set so they exist exactly in every renderer's list. `resolve_widths` became
  the one definition of half-width that `Spline` and `JunctionPlan` both call.
- **Clearance / adapter** — `sources/adapters/unreal.py` gained `derived_products()`, so
  `unreal_manifest.json` finally indexes `landscape_conformed`: what wrote it, when, at which commit,
  how many cells it changed, and that its heights inside the corridor are the road and not the survey.
  An absent directory yields `present: false` rather than no entry, so "not built yet" and "not known
  about" cannot be confused.
- **Integrity** (this file's author) — `sources/tests/regress_outputs.sh`, `sources/OUTPUT.md`,
  `README.md`, `Tools/ue/run_ue_python.ps1`, `docs/STAGES.md`, `docs/RESUME.md`. See §5 and §6.

**Both of the other two were still mid-flight when this was written.** `git status --short` and
`git diff --stat` first, then run the suites in §2 before believing any of it.

## 4. The defects, and where each one stands

`docs/TERRAIN_ROADS.md` is the measured analysis; `renders/b1cd3e5/INDEX.md` is what it looks like.

**D1 — tile-boundary seams. FIXED** (`b1cd3e5`). Step 05 no longer nearest-fills open sea and no
longer fills per tile; the fill is decided once over the site mosaic, and `terrain_manifest.json`
gained a `shared_edges` block that step 05 exits non-zero on. Thanet: 737 pairs, **0 of 378,081**
shared samples disagreeing, worst 0.0 m (was 29,188 cells and 5.34 m). Margate: 162 pairs, 0 of
83,106.

**D2 — "two terrain truths" was a misdiagnosis.** The heightfield and the ALandscape are the same
data, agreeing at every grid post to 0.53 mm; they differ only between posts, bilinear versus the
landscape's triangle pairs, bounded by `|twist|/4` (max 6.12 m over the site, 0.026 % of quads over
0.5 m). `Streetscape.Terrain.Triangulated` exists and passes. **The §3.5 recommendation was NOT
carried out** and this is easy to assume otherwise: `StreetTerrainSource.h:53` and `:138` still
default to `EStreetHeightSampling::Bilinear`, and `Tools/blender/streetscape/terrain.py`'s
`Heightfield.sample` is still bilinear only — so the conform was burned against the bilinear rule
while the ground the player sees and collides with is triangulated. Checked 2026-09-09; it is a
coordinated change (`DESIGN.md` §8 specifies bilinear and the frozen fixtures move with it).

**D3 — roads fusing with the ground. FIXED in the data** (`b1cd3e5`). The corridor conform burns the
road's own built surface into a copy of the landscape. Whole isle, 13,097 splines, 666,314 stations:
stations with ground above the built surface **565,545 → 0**, carriageway penetrated **826.7 km →
0.000 km**, worst penetration **13.826 m → 0.000000 m**.

**D3b — and yet the road is not in the picture. OPEN, and it is now the headline.** Measured over the
45-frame set at `b1cd3e5`: of the 31 frames that stand on or look along a road, **the carriageway is
drawn in 15 and missing in 16**. It is not the geometry — a downward trace at those same cameras hits
the street 2.7–6.0 cm above the landscape, and hiding the `LandscapeProxy` actors brings the whole
street back (`Tools/ue/diag_road_visibility.py`, `Saved/RoadVisibility/`). **The surface the landscape
rasterises is not the surface its own height query returns**, and the drawn ground wins wherever a
1 m quad holds more than the conform's 3 cm sink. Pinning LOD 0 removes it in a capture
(`05_screenshot.py --landscape-lod0-screen-size`) but not at runtime. Deepening the sink is not free:
the kerb tuck is 0.03 m, so a deeper sink shows daylight under the kerb.

**D4 — dishonest gates. FIXED** (`b1cd3e5` for the import gates, this round for the two below).

**D5 — the network is in the level.** 15,423 streetscape actors, 216 massing actors, 140 proxies,
`PlayerStart`, game mode and pawn set, `problems: []` (`Saved/Tests/d5_assert_final.json`).

## 5. The two integrity defects closed this round

**The Margate gate could not pass under any snapshot on disk.** A gate that compares one hash per
file dies the first time a manifest gains a key or `generator` records a new commit sha, and it had.
`regress_outputs.sh` now compares rasters and record files **byte for byte with no allowance of any
kind**, and JSON products **structurally**: `PROVENANCE` when only the `generator` string differs,
`EXTENDED` when the only difference is a key named in the script's `ALLOW_ADDED` table, `CHANGED`
otherwise. Both allowances are proved by re-serialising the reduced file and hashing it against the
snapshot, so one changed digit still fails. What actually changed is in `docs/STAGES.md` note (a),
with the byte counts. `selftest` breaks twelve things on purpose and requires the exact verdict for
each.

**The headless runner was reporting crashes as successes — read this before trusting any THANET_OK.**
`Tools/ue/run_ue_python.ps1` used to attribute *every* non-zero exit to this machine's VC++
redistributable advisory. There are two causes, not one, and they were measured on 2026-09-09:

| what the run did | raw exit | why |
|---|---|---|
| `ue_common.py`, with and without `-Render` | **1** | the VC++ advisory, counted as an error by the commandlet framework |
| `04_probe.py --points … ` (no `--landscape`, `regions_loaded 0`) | **1** | the same |
| `04_probe.py --points … --landscape` (`regions_loaded 1`) | **0xC0000005** | access violation at teardown |
| `07_assert_level.py --census-only` (streams the whole world) | **0xC0000005** | the same |
| all nine `render_set.ps1` batches at `b1cd3e5` | **0xC0000005** | the same (`renders/b1cd3e5/manifest.json`) |

**It fires when, and only when, the run streamed in a World Partition region, and it fires after
everything is finished.** In every measured case the Python script printed `THANET_OK`, the output
files were written (`Saved/probe/census.json`, all 45 images and their reports), and the log ran all
the way through the Warning/Error Summary to `LogExit: Exiting.` and `Log file closed` with no crash
marker anywhere. **No output is lost.** There is also **no callstack**: UE writes no
`Saved/Crashes/` entry and Windows writes no dump, because the fault is after the crash handler has
been torn down. Getting a stack would mean attaching a debugger (procdump/windbg, neither installed)
to the commandlet — that is the next step if it ever starts costing work rather than exit codes.

The runner now names the NTSTATUS, waives the teardown crash **only** against positive proof that the
work finished (Python succeeded, ≥1 `THANET_OK`, no `THANET_FAIL`, no crash marker, clean shutdown),
prints a banner when it does, writes a `VERDICT` line and a row in
`Saved/Logs/run_ue_python_verdicts.tsv`, refuses the waiver under `-StrictExit`, and fails loudly with
a 40-line log excerpt for anything else. Verified on four cases: advisory → 0, teardown crash → 0 with
the banner, teardown crash `-StrictExit` → non-zero, deliberate Python failure → non-zero.

## 6. Rules that cost previous sessions hours

- **PATH must use the `/c/` form**: `export PATH="/c/Users/Shadow/code/3duk-env/env/Library/bin:$PATH"`.
  A `C:/...` entry is invisible to bash — GDAL disappears and numpy's LAPACK dies silently with no
  output at all.
- **Python is only** `C:/Users/Shadow/code/3duk-env/env/python.exe`. The `python`/`python3` on PATH
  are broken Microsoft Store stubs. `regress_outputs.sh` needs one too — `export PY=` it.
- **`run_ue_python.ps1` exit 0 is not proof.** Read the `VERDICT` line it prints and confirm the
  output files exist. §5 says why.
- **UE 5.8 prints `Test Completed. Result={Success}`**, not `{Passed}`.
- **Close the GUI editor before headless work.** Both processes fight over asset locks in `Content/`.
- **Never launch the GUI from an agent**; it blocks on a modal dialog with no one to click it.
- **`--max-components 256` on the landscape import.** With `0` the importer tries all 2,067 components
  in one `Import` call and the D3D12 device dies with `E_OUTOFMEMORY` after ~12 minutes.
- **Blender headless renders with EEVEE only** in `-b` mode on this machine, and its scripts must sit
  on a short path — the session scratchpad path is 270 characters and Blender cannot open files there.
- **Long jobs must run in the background with a log.** The Bash tool caps at 600 s; a landscape import
  is ~6 min, the conform ~13.5 min, the 45-frame render set ~19 min, the first editor start several
  minutes.
- **Never `git commit/stash/checkout/reset` from an agent** — the orchestrator commits between phases.

## 7. If you are starting completely cold

```bash
cd /c/Users/Shadow/code/3duk && git log --oneline -6 && git status --short && git diff --stat
```

Then read, in order: this file, `docs/BRIEF.md` sections 1.1, 4 and 7, `docs/TERRAIN_ROADS.md`
sections 1 and 8, `renders/b1cd3e5/INDEX.md`, and `docs/STAGES.md` §0 for what each stage's acceptance
command is and what was last seen to pass. Confirm the tree is still green before changing anything:

```bash
export PATH="/c/Users/Shadow/code/3duk-env/env/Library/bin:$PATH"
export PY=C:/Users/Shadow/code/3duk-env/env/python.exe
$PY sources/tests/dryrun.py | tail -1                               # 167 passed, 0 failed
$PY sources/tests/test_unreal_adapter.py 2>&1 | tail -1             # OK
$PY -m unittest discover -s projects/one/Tools/blender/tests -p "test_*.py" 2>&1 | tail -1
./sources/tests/regress_outputs.sh compare margate terrain_fix_before | tail -1
./sources/tests/regress_outputs.sh selftest margate | tail -1
powershell -NoProfile -ExecutionPolicy Bypass -File projects/one/Tools/build.ps1 | tail -3
powershell -NoProfile -ExecutionPolicy Bypass -File projects/one/Tools/ue/run_ue_tests.ps1 | tail -5
```

To look at the world rather than rebuild it, open the editor on the saved level — but only when no
headless job is running:

```bash
"/c/Program Files/Epic Games/UE_5.8/Engine/Binaries/Win64/UnrealEditor.exe" "C:/Users/Shadow/code/3duk/projects/one/Thanet.uproject"
```

## 8. Uncommitted work

Agents write into the working tree and the orchestrator commits between phases, so after a crash
there will usually be uncommitted changes from the agents that were mid-flight. They are not
necessarily broken — check them, build, run the tests, and commit what passes rather than discarding
it. `git status --short` and `git diff --stat` are the first two commands after any disconnect.

At the moment this file was written the tree held, uncommitted: the geometry track's junction trim
(`Tools/blender/streetscape/**`, `schema/streetscape.schema.json`, `Tools/conform_landscape.py`,
`Tools/road_fusion_audit.py`), the adapter's `derived_products` block
(`sources/adapters/unreal.py`), this round's integrity work (`sources/tests/regress_outputs.sh`,
`sources/OUTPUT.md`, `README.md`, `projects/one/Tools/ue/run_ue_python.ps1`, `docs/STAGES.md`, this
file), an unrelated edit to `sources/fetch/photos.py`, and `sources/config/thanet_towns.json`
untracked. The trim work changes the geometry the conform is burned from, so
**`Tools/conform_landscape.py` and `Tools/road_fusion_audit.py` have to be re-run and the landscape
re-imported before the level matches the splines again** — a `conform_v2` run was in progress.
