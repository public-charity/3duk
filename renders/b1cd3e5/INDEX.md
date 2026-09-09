# `renders/b1cd3e5` — what this snapshot shows

45 frames, one per location in [`projects/one/Tools/ue/render_set.json`](../../projects/one/Tools/ue/render_set.json) (spec sha256 `d8a8bc6702e77e3c`), rendered at commit **b1cd3e5** — *Conform the ground to the roads, close the seams, harden the gates, and put the whole isle in the level* — on 2026-09-09T19:30:57Z in 1149 s.

> The worktree was **dirty** when this was taken (12 uncommitted change(s), listed in `manifest.json`): the render harness itself was not yet committed. The landscape, massing and streetscape content is the content of b1cd3e5.

`manifest.json` beside this file holds, per image, the camera transform actually used, the sampled ground height, the streamed region, the file size and the sha256. **Compare snapshots through the manifest, never by eye alone**: identical spec sha256 plus identical camera blocks is the only proof that a visual difference is the model changing rather than the camera.

## The one-line verdict

The terrain, the coastline and the 20,121 building masses are in place and read correctly from the air. **On the ground, the road network is more often absent than present.** Of the 45 frames, 9 are aerials and 5 are beach-level views with no carriageway in shot; of the remaining **31 that stand on or look along a road, the carriageway is drawn in 15 and missing in 16** — and 4 of the 15 lose part of it to terrain breaking through or to the corridor simply stopping within 100 m. That is measured, not impressionistic; see *The road defect, measured* below.

## Automated quality check

Every image was decoded with an independent stdlib PNG decoder (no PIL on this machine) and tested for: file present, ≥ 50 KB, decodes, fully opaque, not a single flat colour (luminance variance ≥ 25 and ≥ 200 distinct RGB triples), and not more than 85 % one colour — the last being what an all-sky or all-grass frame looks like when a camera is wrong or a region never streamed.

| check | result |
|---|---|
| images expected / rendered | 45 / 45 |
| under 50 KB | 0 |
| failed to decode | 0 |
| not fully opaque | 0 |
| flat single colour | 0 |
| more than 85 % one colour | 0 (worst: 36.3 %, `westgate-on-sea/westgate_station_from_station_road`) |
| **failed any check** | **0** |

A soft measure worth recording for the future: the *edge fraction* — the share of pixels whose horizontal neighbour differs by more than 8 in luminance. It runs from 0.004 to 0.109 across the set, median about 0.010. That is very low, and it is the honest signature of a model with no textures: flat green ground, flat grey prisms, flat tarmac. It is a number to watch, not a failure — when materials arrive it should climb.

## The road defect, measured

Sixteen eye-level frames show a street with buildings down both sides and **grass where the carriageway should be**, usually with the magenta OSM debug overlay still drawn on top of the grass and often with the footways drawn either side of the missing road. Three checks were run to find out whether that is the camera, the streaming, or the model:

1. **Is there a road there at all?** A numpy probe of the source products against `data/thanet/out/unreal/streetscape` + `landscape_conformed`: at the Garlinge camera 17 road splines lie within 60 m, the nearest passes through the camera itself, and **not one sampled point of any of them is below the conformed ground** — median clearance 3.3–6.0 cm.
2. **Did the region stream?** `projects/one/Tools/ue/diag_frame_probe.py` re-loads the same World Partition region the frame used and asks the engine: the census reports `actors_without_samples: 0` and `actors_with_no_buffer: 0` for every loaded streetscape actor, and a downward trace along the view ray hits **the street, not the ground**, at 0, 2, 5, 10, 20, 40, 80 and 160 m ahead, 2.7–6.0 cm above the landscape — at the *same* cameras whose pictures show grass.
3. **So why is it not in the picture?** `projects/one/Tools/ue/diag_road_visibility.py` captures the same camera twice, once as the render set does and once with every `LandscapeProxy` hidden. With the landscape hidden, Ramsgate High Street and Birchington Station Road both come back as complete streets — carriageway, kerbs, both footways. See `projects/one/Saved/RoadVisibility/`.

**Conclusion: the corridor geometry is complete and is above the ground by every number the engine will give you, and the landscape draws over it anyway.** The conform (commit `b1cd3e5`) left roughly 3 cm of clearance, and the surface the landscape actually rasterises is not the surface its own height query returns — the drawn ground wins wherever the 1 m DTM has more than ~3 cm of relief inside a quad. The capture already pins the landscape to LOD 0 (`landscape LOD0 screen size 8.0 on 17 landscape actor(s)` in every batch log), so this is not a coarse-LOD capture artefact.

`cliftonville/princess_margaret_avenue_at_northdown` is the picture to put in front of anyone who asks what this means: the road is drawn, and green terrain blades erupt through it across its whole width. `birchington/station_road_to_the_square` is the same defect at 100 %.

**No camera was changed and no image was re-rendered.** Every frame in this snapshot is the frame the committed spec produces. Nothing here is post-processed.

## Other defects visible across the whole set

| # | defect | where |
|---|---|---|
| 1 | **The magenta OSM debug overlay is drawn over everything**, including through buildings and across the sky, so it is depth-test-free debug output sitting in a deliverable render | all 45 |
| 2 | **No textures anywhere** — buildings are grey prisms, ground is flat green, tarmac is flat grey | all 45 |
| 3 | **No ambient or sky light on shaded faces**: every façade turned away from the sun renders solid black, which loses whole terraces | most eye-level frames |
| 4 | **Corridor ribbons stand proud of the ground with unlit vertical faces**, leaving black wedge gaps between road, footway and verge | minnis_bay, cheesemans_farm, manston_court_road, westwood_cross_sheds, eastern_esplanade |
| 5 | **The model ends in a hard vertical cut into dark blue** with no skirt and no sea | every aerial, acol_fields, margate_hill |
| 6 | **Beach-level cameras look across a flat plane with no beach drawn under them** | turner_contemporary, viking_bay_sands, ramsgate_sands |
| 7 | **Cliffs are not cliffs**: the 1 m DTM smooths them into sand-coloured ramps | walpole_bay_chalk_cliff |
| 8 | **The railway leaves the ground at bridges** and arcs tens of metres into the air | railway_bridge_over_minnis_road |
| 9 | **Manston's runway and aprons are not modelled** — 2.7 km of concrete renders as field | manston_airfield, manston_hangars |
| 10 | **Car park surfaces are missing**; only the aisle ribbons exist, floating | westwood_cross_sheds |
| 11 | **Lane markings are inconsistent** — drawn on some carriageways, absent on others | canterbury_road_west (present) vs haine_road, preston_road (absent) |

## Every image

`dom` is the largest share of the frame taken by one colour (fail above 0.85); `edge` is the detail measure described above. Both come from the QC pass, not from the renderer's own guards.

### margate (5 images, 7.7 MB)

| image | kind | bytes | dom | edge | what it shows | defects visible in it |
|---|---|---:|---:|---:|---|---|
| [`margate_bay_from_the_north_west.png`](margate/margate_bay_from_the_north_west.png) | aerial | 1,857,773 | 0.071 | 0.082 | Margate bay from 300 m up: the Main Sands, the harbour arm, and the town climbing away west to east. | Roads read as grey ribbons only along the seafront and at the larger junctions; over most of the town the network is nothing but the magenta OSM overlay lying on unbroken green. Buildings are untextured grey prisms. Offshore is a flat teal plate and the model's northern edge is a hard straight cut into dark blue. |
| [`marine_terrace_west_past_dreamland.png`](margate/marine_terrace_west_past_dreamland.png) | street | 1,526,279 | 0.085 | 0.015 | Marine Terrace at eye level looking west past Dreamland, with Arlington House as the tall block on the left. | The best road in the set: carriageway, white edge line, kerb and footway all drawn and correctly above the ground. Facades are unlit and read as solid black; the beach on the right is a featureless tan plane; the magenta centreline runs the length of the carriageway. |
| [`canterbury_road_east_at_garlinge.png`](margate/canterbury_road_east_at_garlinge.png) | street | 1,486,153 | 0.119 | 0.008 | Canterbury Road (A28) at Garlinge, looking north-east into Margate. | ROAD NOT DRAWN. The camera stands on the trunk road - a downward trace hits the carriageway 5.5 cm above the landscape - and the lower half of the frame is unbroken grass. Roads appear only as magenta and thin slivers at the horizon. |
| [`turner_contemporary_from_the_sands.png`](margate/turner_contemporary_from_the_sands.png) | seafront | 1,492,642 | 0.191 | 0.010 | The Turner Contemporary (the grey block at centre) and the harbour from the Main Sands. | The lower 55 % of the frame is a flat dark plane with no beach drawn under the camera. Magenta streaks run across the slipway and the sky. Harbour buildings are unlit blocks. |
| [`millmead_road_east_up_the_hill.png`](margate/millmead_road_east_up_the_hill.png) | street | 1,362,351 | 0.076 | 0.009 | Millmead Road climbing east through the estate: carriageway, both footways, grass verges and housing. | The corridor geometry stops about 150 m ahead and only the magenta overlay continues. The left-hand terrace is in full shadow and renders solid black. |

### cliftonville (5 images, 7.5 MB)

| image | kind | bytes | dom | edge | what it shows | defects visible in it |
|---|---|---:|---:|---:|---|---|
| [`cliftonville_from_over_walpole_bay.png`](cliftonville/cliftonville_from_over_walpole_bay.png) | aerial | 2,085,243 | 0.067 | 0.109 | Cliftonville from over Walpole Bay: the terraced grid, the seafront and the bay. | Street grid is legible and the seafront road is drawn, but most inland streets are magenta only. The sand/water boundary is mottled where the fabricated offshore plate meets the coast. Grass is a single flat green with no variation. |
| [`northdown_road_east_through_the_shops.png`](cliftonville/northdown_road_east_through_the_shops.png) | street | 1,108,381 | 0.313 | 0.017 | Northdown Road looking east through the shopping street - the most complete street canyon in the set. | Road, footways and shopfront blocks all drawn. The left-hand side is in full shadow and reads black. Corridor geometry stops about 250 m out. |
| [`eastern_esplanade_seafront_terrace.png`](cliftonville/eastern_esplanade_seafront_terrace.png) | street | 1,412,701 | 0.097 | 0.015 | Eastern Esplanade along the seafront terrace, with the clifftop lawns and paths on the left. | Black wedge gaps between the paths and the ground on the left, where the ribbons stand proud of the terrain and their vertical faces are unlit. |
| [`walpole_bay_chalk_cliff_from_the_sands.png`](cliftonville/walpole_bay_chalk_cliff_from_the_sands.png) | seafront | 1,444,606 | 0.150 | 0.006 | Looking up at the Walpole Bay cliff from the sands. | NO CLIFF. The chalk face renders as a smooth sand-coloured ramp filling the bottom half of the frame - the 1 m DTM has smoothed the cliff and the sand weightmap is painted up it. The clifftop barrier reads as a long brown board fence floating above the town behind it. |
| [`princess_margaret_avenue_at_northdown.png`](cliftonville/princess_margaret_avenue_at_northdown.png) | street | 1,472,018 | 0.080 | 0.010 | Princess Margaret Avenue running downhill at Northdown. | THE CLEAREST IMAGE OF THE ROAD/TERRAIN DEFECT. The carriageway is drawn, and green terrain erupts through it in a series of blade-shaped wedges right across its width. |

### broadstairs (5 images, 7.8 MB)

| image | kind | bytes | dom | edge | what it shows | defects visible in it |
|---|---|---:|---:|---:|---|---|
| [`the_town_and_viking_bay_from_the_sea.png`](broadstairs/the_town_and_viking_bay_from_the_sea.png) | aerial | 2,131,848 | 0.039 | 0.054 | Broadstairs and Viking Bay from over the sea: the town, the bay, the harbour arm. | Land is lit from behind so the massing reads dark. Water carries wave detail here; the sand/water boundary is ragged and the beach reaches into the water in patches. |
| [`broadstairs_high_street.png`](broadstairs/broadstairs_high_street.png) | street | 1,167,711 | 0.261 | 0.017 | Broadstairs High Street looking down to the sea, buildings both sides. | A green verge wedge intrudes over the right-hand footway and into the edge of the carriageway. The left terrace is solid black. Road geometry stops about 200 m out. |
| [`st_peters_high_street.png`](broadstairs/st_peters_high_street.png) | street | 1,474,297 | 0.122 | 0.006 | St Peter's High Street looking east. | ROAD NOT DRAWN. A trace at the camera hits the carriageway 4.7 cm above the landscape, and the frame shows unbroken grass with a single magenta line poking through it. No footway, no kerb; the nearest building is a distant block. |
| [`viking_bay_sands_and_the_cliff_town.png`](broadstairs/viking_bay_sands_and_the_cliff_town.png) | seafront | 1,430,053 | 0.165 | 0.011 | Viking Bay sands looking up at the cliff town. | The lower half is a flat sea plane; the cliff town is a black silhouette. Magenta overlay lines float across the buildings, showing the overlay is drawn without depth testing. |
| [`north_foreland_lighthouse.png`](broadstairs/north_foreland_lighthouse.png) | landmark | 1,599,384 | 0.050 | 0.015 | North Foreland lighthouse from North Foreland Road, with its compound wall and the road in the foreground. | The lighthouse is a square prism - the massing extrudes the footprint with no taper. The compound wall is a slab-like brown barrier about 3 m high. No lane markings on the road. |

### ramsgate (5 images, 7.4 MB)

| image | kind | bytes | dom | edge | what it shows | defects visible in it |
|---|---|---:|---:|---:|---|---|
| [`royal_harbour_and_town_from_the_sea.png`](ramsgate/royal_harbour_and_town_from_the_sea.png) | aerial | 1,902,885 | 0.074 | 0.059 | Ramsgate from over the sea: the Royal Harbour and both piers, the sands, the town on the cliff. | The best-covered aerial for roads - much of the network is drawn. The sea is two-tone, near teal and far navy, where the fabricated offshore plate ends. The far edge of the model is a hard cut. |
| [`military_road_at_the_royal_harbour.png`](ramsgate/military_road_at_the_royal_harbour.png) | street | 1,414,907 | 0.079 | 0.009 | Military Road east along the Royal Harbour, under the East Cliff. | The carriageway ends abruptly about 80 m ahead into a bare sand-and-grass plane while the magenta overlay carries on. The cliff and harbour buildings are unlit black. |
| [`high_street_down_to_the_harbour.png`](ramsgate/high_street_down_to_the_harbour.png) | street | 1,020,182 | 0.318 | 0.018 | Ramsgate High Street falling south-east to the harbour, buildings both sides. | ROAD NOT DRAWN. The buildings prove this is a street; its surface is grass with a magenta centreline. Only a sliver of footway on the right is drawn. A trace at the camera hits the carriageway 6 cm above the landscape. |
| [`ramsgate_station_from_the_approach.png`](ramsgate/ramsgate_station_from_the_approach.png) | landmark | 1,464,873 | 0.071 | 0.006 | Ramsgate station from Station Approach Road. | A five-way junction drawn entirely in magenta centrelines over unbroken grass - not one square metre of carriageway in the frame. The station is a black block. |
| [`ramsgate_sands_and_the_east_cliff.png`](ramsgate/ramsgate_sands_and_the_east_cliff.png) | seafront | 1,559,357 | 0.124 | 0.021 | The East Cliff and the town from Ramsgate Sands. | The lower half is the flat sea plane, the cliff is in silhouette, and the magenta overlay sprays across the sky at wrong angles where it is drawn over occluding geometry. |

### westgate-on-sea (5 images, 7.9 MB)

| image | kind | bytes | dom | edge | what it shows | defects visible in it |
|---|---|---:|---:|---:|---|---|
| [`westgate_from_over_st_mildreds_bay.png`](westgate-on-sea/westgate_from_over_st_mildreds_bay.png) | aerial | 1,959,403 | 0.086 | 0.071 | Westgate-on-Sea from over St Mildred's Bay: the town, the seafront road curving round the bay, the sands. | Roads are drawn near the camera and fade to magenta only towards the top of the frame. The model edge is a hard cut. |
| [`westgate_bay_avenue_east_to_the_town.png`](westgate-on-sea/westgate_bay_avenue_east_to_the_town.png) | street | 1,504,882 | 0.059 | 0.012 | Westgate Bay Avenue looking east into the town, with a crossing junction ahead. | Black skirt gaps under the left-hand footway; the housing on the left sits over a dark gap rather than meeting the ground; geometry ends about 250 m out. |
| [`canterbury_road_west_at_westgate.png`](westgate-on-sea/canterbury_road_west_at_westgate.png) | street | 1,458,847 | 0.085 | 0.010 | Canterbury Road looking west out of Westgate - the one frame where white lane markings read clearly. | The carriageway becomes grass with a magenta line about 150 m ahead. Buildings on the left are unlit black. |
| [`st_mildreds_bay_from_the_sands.png`](westgate-on-sea/st_mildreds_bay_from_the_sands.png) | seafront | 1,756,158 | 0.041 | 0.006 | St Mildred's Bay from the sands, aimed at the sea wall 88 m away. | A grazing view over a nearly flat beach: two thirds of the frame is horizontal teal and sand banding, the sand/water weight blend seen almost edge-on. The sea wall is not legible at this distance. |
| [`westgate_station_from_station_road.png`](westgate-on-sea/westgate_station_from_station_road.png) | landmark | 1,172,221 | 0.363 | 0.017 | Westgate-on-Sea station from Station Road: road, footway, verge and the timber boundary fence along the railway. | The right-hand building mass is entirely black. The fence renders as solid brown boards rather than a railway boundary. |

### birchington (5 images, 7.5 MB)

| image | kind | bytes | dom | edge | what it shows | defects visible in it |
|---|---|---:|---:|---:|---|---|
| [`birchington_and_the_wantsum_edge.png`](birchington/birchington_and_the_wantsum_edge.png) | aerial | 1,797,087 | 0.073 | 0.064 | Birchington, Minnis Bay and the western edge of the model from over the sea. | The land simply ends in a hard straight cut into dark blue with no skirt and no sea beyond it. Roads are drawn across the town; the coast is a sand strip over a mottled water boundary. |
| [`canterbury_road_a28.png`](birchington/canterbury_road_a28.png) | street | 1,456,910 | 0.111 | 0.005 | Canterbury Road, the A28 through Birchington. | THE EMPTIEST FRAME IN THE SET. No carriageway, no footway and not even a magenta line anywhere near the camera - unbroken grass to a distant band of buildings. |
| [`station_road_to_the_square.png`](birchington/station_road_to_the_square.png) | street | 1,171,685 | 0.316 | 0.007 | Station Road looking north-west to The Square. | A full street canyon, buildings on both sides, with grass where the street should be: no carriageway, no footway, no overlay. The buildings meet the grass with no footing. |
| [`minnis_bay_where_the_model_ends.png`](birchington/minnis_bay_where_the_model_ends.png) | seafront | 1,502,260 | 0.072 | 0.013 | Minnis Bay looking west to where the model stops: road, both footways and verges drawn. | Black wedge gaps between every ribbon and the ground - the road and footway stand proud of the terrain and their vertical faces are unlit. |
| [`railway_bridge_over_minnis_road.png`](birchington/railway_bridge_over_minnis_road.png) | landmark | 1,528,199 | 0.118 | 0.009 | The Chatham Main Line bridge over Minnis Road. | THE RAILWAY LEAVES THE GROUND. The rail ribbon arcs high into the air on both sides of the bridge, tens of metres above the terrain, with unlit black undersides and a ladder of dark structure at the break. The road in the foreground is not drawn. |

### westwood (5 images, 7.8 MB)

| image | kind | bytes | dom | edge | what it shows | defects visible in it |
|---|---|---:|---:|---:|---|---|
| [`westwood_cross_and_the_retail_grid.png`](westwood/westwood_cross_and_the_retail_grid.png) | aerial | 1,875,524 | 0.085 | 0.057 | Westwood Cross and the inland retail band from the east: sheds with pitched roofs, car parks, roundabouts and dual carriageways. | The best-resolved aerial - most of the road network is drawn here. Faint linear artefacts run across the fields. Grass is flat and untextured. |
| [`haine_road_past_westwood_cross.png`](westwood/haine_road_past_westwood_cross.png) | street | 1,436,194 | 0.092 | 0.020 | Haine Road past Westwood Cross: both carriageways drawn, with the hedge renderer visible as leaf cards on the left. | No lane markings on either carriageway. The retail sheds behind are unlit black. Hedges read as loose scattered quads. |
| [`new_haine_road_at_haine.png`](westwood/new_haine_road_at_haine.png) | street | 1,516,611 | 0.103 | 0.012 | New Haine Road looking south to Haine, at a junction with two crossing carriageways. | The road the camera stands on is not drawn - magenta over grass - while both crossing carriageways are. A grey island mid-frame is where the missing road briefly surfaces through the ground. |
| [`westwood_cross_sheds_from_the_carpark.png`](westwood/westwood_cross_sheds_from_the_carpark.png) | landmark | 1,444,676 | 0.151 | 0.010 | The Westwood Cross sheds from the car park. | The parking aisles float above the grass as narrow ribbons casting hard black shadows; there is no parking surface between them. The sheds are unlit black. |
| [`manston_court_road_and_the_farmland.png`](westwood/manston_court_road_and_the_farmland.png) | street | 1,499,807 | 0.082 | 0.012 | Manston Court Road and the farmland west of Westwood: road and both footways drawn. | Black gaps under the right-hand footway where it stands proud of the ground. Corridor geometry ends about 200 m out. |

### manston (5 images, 7.5 MB)

| image | kind | bytes | dom | edge | what it shows | defects visible in it |
|---|---|---:|---:|---:|---|---|
| [`manston_airfield_from_the_east.png`](manston/manston_airfield_from_the_east.png) | aerial | 1,604,034 | 0.087 | 0.025 | Manston airfield from the east. | THE RUNWAY IS NOT THERE. 2.7 km of concrete renders as green field with thin dark outlines and magenta specks; only a few hangar blocks stand up. The model edge cuts across the top left. |
| [`spitfire_way_along_the_airfield.png`](manston/spitfire_way_along_the_airfield.png) | street | 1,505,802 | 0.100 | 0.009 | Spitfire Way north-east along the airfield, with a footway on the left and the airfield fence on the right. | ROAD NOT DRAWN. The footway and the fence are both drawn, and the carriageway between them is grass with a magenta centreline - a trace at the camera hits the road 3.4 cm above the landscape. |
| [`manston_high_street_by_the_green.png`](manston/manston_high_street_by_the_green.png) | street | 1,445,351 | 0.138 | 0.009 | Manston High Street south-west from The Green, with footways on both sides. | The carriageway between the two drawn footways is grass with a magenta line. The shed on the right is unlit black. |
| [`manston_hangars_and_control_tower.png`](manston/manston_hangars_and_control_tower.png) | landmark | 1,604,119 | 0.065 | 0.005 | The control tower and hangars from the apron road. | Nothing in the near field at all: a flat green field with a specular sheen, and the subject a thin band on the horizon. The apron road is not drawn. |
| [`preston_road_north_east_of_the_village.png`](manston/preston_road_north_east_of_the_village.png) | street | 1,331,529 | 0.206 | 0.009 | Preston Road north-east out of Manston village: carriageway and footway drawn. | A continuous unlit black wall - the airfield boundary barrier - runs the whole length of the left side and reads as a 3 m slab. No lane markings. |

### acol (5 images, 7.5 MB)

| image | kind | bytes | dom | edge | what it shows | defects visible in it |
|---|---|---:|---:|---:|---|---|
| [`acol_fields_and_the_isle_edge.png`](acol/acol_fields_and_the_isle_edge.png) | aerial | 1,386,815 | 0.188 | 0.004 | The fields around Acol and the edge of the isle. (Acol's own anchor is outside the clip - see render_set.json known_soft_spot.) | Roads appear only as isolated grey fragments in a green field, with faint magenta between them. The isle edge is a hard cut into dark blue void with no sea at all. |
| [`manston_road_west_towards_acol.png`](acol/manston_road_west_towards_acol.png) | street | 1,605,079 | 0.056 | 0.005 | Manston Road west towards Acol. | The carriageway is not drawn - magenta over grass with a faint footway sliver on the right. A broad specular sheen washes the grass out on the right. |
| [`shottendane_road_between_the_fields.png`](acol/shottendane_road_between_the_fields.png) | street | 1,517,111 | 0.176 | 0.005 | Shottendane Road north-east between the fields. | The carriageway is not drawn at the camera; it surfaces about 200 m out as a small triangular wedge next to a black block. |
| [`margate_hill_at_the_isle_edge.png`](acol/margate_hill_at_the_isle_edge.png) | street | 1,502,875 | 0.162 | 0.007 | Margate Hill south-west towards the Wantsum cut. | The carriageway is not drawn at the camera and is visibly climbing out of the ground about 200 m ahead, where it emerges as a grey wedge. A footway is drawn on the left throughout. |
| [`cheesemans_farm_from_manston_road.png`](acol/cheesemans_farm_from_manston_road.png) | street | 1,473,699 | 0.104 | 0.008 | Cheesemans Farm from Manston Road. | A footway ribbon floats above the grass with a large black gap beneath it. The carriageway is not drawn - magenta over grass. Farm buildings are a distant band. |

## Two frames a future session should look at again

Neither failed a check and neither was changed, but both are weak *as viewpoints* rather than because of a defect they capture, and a deliberate decision about them belongs in `render_set.json`'s `replaced` array, not in a quiet re-aim:

- `westgate-on-sea/st_mildreds_bay_from_the_sands` — 88 m off a sea wall about 4 m high, on a flat beach, so two thirds of the frame is horizontal sand/water banding and the subject subtends under 3°. The harness moved this camera *back* from 24 m to clear an occlusion gate; the cure may have been worse than the complaint.
- `manston/manston_hangars_and_control_tower` — nothing whatever in the near field; the subject is a thin band on the horizon over an empty green field.

## How this was checked

```
# render (19 min 9 s, nine editor batches, ~11 GB peak per batch)
powershell.exe -NoProfile -ExecutionPolicy Bypass -File projects/one/Tools/render_set.ps1 -PerTown

# quality-check every PNG, independently of the renderer's own guards
C:/Users/Shadow/code/3duk-env/env/python.exe projects/one/Tools/qc_renders.py renders/b1cd3e5

# why is the carriageway missing? (both write JSON into projects/one/Saved/Tests/)
powershell.exe ... run_ue_python.ps1 -Script diag_frame_probe.py    -Render -Args "--only <id> --report <path>"
powershell.exe ... run_ue_python.ps1 -Script diag_road_visibility.py -Render -Args "--only <id> --out <dir>"
```

Every batch ended with the engine's raw exit code `-1073741819` (0xC0000005) *after* `LogExit`, which `run_ue_python.ps1` rewrites to 0; `render_set.ps1` records it per batch in `manifest.json → batches`. Every batch also logged its `THANET_OK` line, wrote its report, and produced all five images, so this is the known teardown crash and not a lost render.

Totals: **45 images, 68,470,522 bytes (68.5 MB)**, 1149 s wall clock.
