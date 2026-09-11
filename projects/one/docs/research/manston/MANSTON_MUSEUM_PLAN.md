# Manston museum and explorer plan

## The proposal for approval

Create a walkable museum landscape at Manston that restores selected historic buildings within the present mapped landscape. Keep the runway, open flying field, road relationships and surviving structures at real scale. Use the two existing museums as the visitor gateway, connect the RAF control tower and Battle Headquarters to a short introductory walk, and establish a larger circuit through the technical area, fighter pen, T2 hangar and civilian tower. Extend this with optional trails to the early War Flight area, sunken hangars and FIDO installation.

This is an imagined present-day decommissioned museum for the Thanet explorer. It is not a description of the airport's actual use or an approved physical redevelopment. RSP reported ongoing airport-reopening work in June 2026 and support for Coastguard search-and-rescue operations from January 2026. The historical domestic camp is included within the imagined museum scenario.[^1][^2]

The recommended first build combines a **636 m museum-and-command loop** with a **2,203 m aircraft-and-engineering circuit**. These are separately measured concept polylines and should not be added as a single deduplicated route length. The experience should include aircraft conservation, airfield defence, rescue, station life and the transition to jets and civil aviation. Restore one early technical-building bay and one War Flight shed selectively; make the Alland Grange sunken hangar the principal later expansion.

The below-ground model must remain evidence-led. There are documented shelters and sunken hangars, a Battle HQ, buried services and separately reported tunnels. The evidence does **not** currently establish a walkable tunnel system connecting them. Exact underground alignments, portal coordinates and levels remain unresolved for the important interiors.[^3][^4][^5]

Approve the concept, the restoration shortlist, the four proposed access roles and the phased explorer build described below. Detailed interior geometry remains subject to the evidence gates, rather than being silently invented to fill gaps.

<!-- PAGEBREAK -->

## The information chest

The acquisition on 11 September 2026 retrieved **110 posts and 43 pages** from manstonhistory.org.uk, including historical articles, book notices, old pages and utility pages. All six published sitemap files were checked: their 222 URLs revealed no additional post/page URL absent from the REST article inventory. The collection is therefore reconciled for those public article/page collections, rather than merely a selection of search results.

The public media endpoint returned **491 records across six pages**, although its count header reported 503. That 12-object discrepancy is unresolved; the pack does not claim those objects were retrieved. Media records preserve image/file URLs, attachment relationships, types and dimensions where available. Linked resources are indexed separately. Photographs and whole articles are not republished in the approval pack, and rights to reuse images as textures or exhibition panels have not been assumed.

The chest also indexes **305 Kent Historic Environment Record entries**, including 298 children of the principal airfield record and seven additional relevant records. Of these, **32 features have curated concept notes**. The wider inventory is a discovery layer: indexing a record does not mean its entire interpretation or geometry has been independently verified. Current background mapping contains 624 building records, 517 tiled road segments and 49 additional aeroway features. Road-segment counts are not counts of unique roads.

| File | Purpose |
|---|---|
| SOURCE_CHEST.md | Searchable article/page and heritage catalogue with review status |
| website_inventory.json | Article IDs, titles, dates, categories, keywords and content hashes |
| media_inventory.json / linked_resources.json | Media and embedded-resource discovery; source links retained |
| sitemap_inventory.json / acquisition_manifest.json | Coverage reconciliation, method and explicit gaps |
| features.bng.json | 32 curated features; facts, survival, proposals and null unknown geometry |
| museum_proposal.bng.json | Proposed gates and routes, with measured concept lengths |
| basemap.bng.json / aeroway_source.json | Reusable mapped context and fresh OSM aeroway provenance |

The history website is valuable for narrative, photographs and leads. The principal spatial evidence is Kent HER's recent aerial interpretation, with its references to specific photographs and RAF Museum plans. Contemporary eyewitness/inspection accounts add interior observations, but must be dated. Neither a HER point nor a small web-map image is a measured building survey.[^3][^6]

<!-- PAGEBREAK -->

## Surface layout and historical layers

The main runway lies across the southern airfield, broadly west-northwest to east-southeast. The northern flying ground and the station's built-up areas evolved through several different eras. The western technical area, northern domestic camp and eastern War Flight area should remain distinct spatial groups. Their separation explains the site's layout better than a single collection of hangars arranged around a modern visitor plaza.[^3]

The surface baseline comes from the project's existing EPSG:27700 mapping, supplemented with current OSM runway, taxiway and apron geometry. The runway is tagged 10/28, 2,750 m long and 60 m wide in the retrieved OSM record. These are current mapping attributes, not surveyed measurements or the dimensions of the wartime emergency strip. The historic crash-runway record includes a much broader feature extent and salvage bays; that extent must not become the width of the modern pavement.[^7]

Historic layers should be selectable without forcing incompatible eras into one supposedly authentic snapshot:

| Layer | Spatial emphasis | Museum interpretation |
|---|---|---|
| 1916-1918 | Early eastern flying sheds, western expansion, sunken hangars, railway | RNAS origins, training and the emergence of the RAF |
| 1920s-1930s | Technical school, erecting shops, railway terminus and domestic camp | Engineering skills, maintenance and everyday station life |
| 1940-1942 | Fighter pens, shelters, defence positions and wartime command | Battle of Britain, ground crews, protection and resilience |
| 1943-1945 | Emergency runway, salvage arrangements and FIDO | Bringing damaged aircraft home and technological experimentation |
| Postwar to 1999 | Jet-age occupation, rescue and later station changes | RAF/USAF relationship, Cold War, rescue and transition |
| Imagined museum | Selected restorations, visitor paths and exhibition facilities | One coherent present-day experience with dated interpretation |

The website provides plans dated 1916, 1922 with revisions to 1930, 1944, and a circa-2017 context map. The available 1944 web image is only 450 by 307 pixels: useful for broad relationships, insufficient for tracing entrances. The 1930 plan's archival reference is **MFC/78/24/0883**; another important RAF Museum plan is **X004/2380**, also rendered X004-2380 in some records.[^6][^8][^9]

![Museum masterplan](museum_masterplan.png)

<!-- PAGEBREAK -->

## Museum districts and restoration choices

**The gateway and command district** uses the existing RAF Manston History Museum and Spitfire and Hurricane Memorial Museum as its starting point. Retain their separate identities and collections. Add a common orientation court, a tactile/site model, toilets, shelter, cycle parking and a clear start to the walks. These shared facilities are proposed additions; the pack does not assert that they already exist. The museums' own public pages confirm their continuing roles and the Spitfire/Hurricane collection.[^10][^11]

Connect the court to the **RAF control tower**, at HER anchor E633500 N166570, and **Battle HQ**, E633570 N166580. The old tower's c.1941 origin and later modifications give it a strong interpretive role. A chosen wartime appearance must be justified by photographs; the model should not erase all later fabric under an unsupported restoration date. The HQ provides a defence-command exhibit, subject to its unresolved survival and floorplan.[^12][^5]

The **working-station district**, west of the gateway, explains how aircraft were built, maintained and supplied. Restore one interpretable structural bay of the erecting shops, with the remaining lost footprint legible in paving. Add a short railway/platform exhibit after registering its historical plan. A power-house outline can connect the railway to the story of utilities. The original buildings' positions are documented, but the listed HER extents include associated space and cannot be used as wall dimensions.[^8][^9][^13]

The **fighter-pen and T2 district** anchors the main aircraft walk. Preserve the surviving earthwork of the E-type fighter pen, distinguish any replacement arm or revetment, and show aircraft protection and the work of ground crews. Reuse the T2 hangar as the large-aircraft/conservation hall, with a public viewing edge to the workshop. Its WWII frame and later rebuilding should be explained rather than presenting the entire shell as original.[^14][^15]

The **civil tower and rescue district** provides a lookout over the runway and an account of the transition from RAF to civil use. The civilian tower is a separate 1999 structure at E633460 N165820, built over a pyrotechnic store believed to be from the USAF period. That store is not evidence of a nuclear bunker or a walkable undercroft. Plan the visitor lookout around verified stairs and floors at blockout stage.[^16]

The **eastern War Flight district** receives one restored early aeroplane shed, a second footprint, ground-crew displays and the chalk-shelter interpretation. Farther southeast, the **FIDO district** uses tank/bund traces, a small control exhibit and an atmospheric demonstration of fog dispersal. The western **sunken-hangar district** becomes a later major attraction. Outlying northern unfinished excavations and The Loop remain optional satellite visits, not reasons to compress the whole airfield.[^17][^18][^19][^20]

<!-- PAGEBREAK -->

## What is known below ground

**Four semi-sunken hangar sites are identifiable in the aerial evidence.** Alland Grange and Cheeseman's Farm are separate western sites; two further excavations lie on opposite sides of Manston Road to the north. The latter were unfinished. These are large excavated hangar settings, approached from the surface, not buried hangar caverns joined by tunnels. For the Alland Grange example, the cited KCC description specifically distinguishes the design from a roof covered with soil.[^4][^21][^22][^23]

Make Alland Grange a partial reconstructed hangar in an exposed chalk excavation: ramp, retaining surfaces, interpretable frame and a controlled roof reconstruction when drawings allow. Keep the northern sites as unfinished excavations or outlines. Do not complete them simply because finished buildings would be more spectacular. Cheeseman's site has later uses and older archaeological earthworks nearby, so its interpretation requires careful separation.[^21][^22][^23]

**The chalk shelter is the strongest specific underground passage record.** It was encountered in 2004 and surveyed by Kent Underground Research Group. The published record describes one passage with an entrance at each end, a width of 1.3 m, timber supports and corrugated metal protection. It gives a dimension of 1.8-2 m as depth; that must not be treated as the burial depth below the ground surface. The original survey is needed to resolve length, section terminology, alignment and exact portal locations.[^24]

**The shelter groups are numerous, separate and mostly recorded as levelled earthworks.** Eight group/individual records account for 63 mapped shelter earthworks: 15 in the western technical area, 14 to the north, 23 by the parade-ground area, five and three in eastern groups, and three isolated examples. This is an arithmetic total of the cited records, not a count of accessible or surviving rooms. The separately recorded chalk shelter must not simply be added as another surviving chamber without checking overlap and identity.[^25][^26][^27][^28][^29][^30][^31][^32]

**The Battle HQ remains a reconstruction candidate.** A 2009 visit reports an unusually tall cupola, an internal ladder and an additional room to the right of the entrance. The later HER aerial interpretation records the likely surface structure as demolished. These observations have different dates and methods: a lost surface signature cannot establish whether all buried fabric has gone. Present survival, precise plan and floor levels remain unknown.[^5][^33]

![Below-ground evidence](subsurface_evidence.png)

<!-- PAGEBREAK -->

## Services, tunnels and interiors

FIDO belongs to the engineering interpretation, not to the visitor tunnel network. Its recorded components include fuel tanks, pump houses, a control building, offices/workshop and buried pipes. The supply line from railway facilities near Abbey Farm included a six-inch main. Southern service trenches are also mapped, but their interpretation does not establish human-sized passages. A building called a control chamber should not automatically be placed underground.[^19][^34][^35][^36][^37]

The FIDO chronology needs particular care. The detailed HER account distinguishes the initial burner installation from a HADES conversion completed in May 1945, followed by trial operation. Therefore a spectacular fog-clearing scene labelled as routine Battle of Britain activity would be wrong. Use a clearly dated engineering demonstration, with symbolic light and sound rather than a persistent line of fire across the visitor route.[^19]

Alland Grange also has a separate HER record for tunnels associated with an Auxiliary Units wireless role. It rests on a 2015 verbal account and reports substantial later loss. The record warns of confusion with other local air-raid tunnels; the alleged crypt is unresolved. This is suitable for a regional history marker, not a connected airfield interior. Ramsgate's civilian tunnels similarly remain a separate Thanet location.[^38][^39]

The proposed walkable interiors should use three different treatments:

| Interior | Historical treatment | Visitor treatment |
|---|---|---|
| Chalk shelter | Reproduce the surveyed passage when the original drawing is obtained | A clearly labelled interpretive prototype may be built separately; provide an equivalent level-access presentation |
| Sunken hangar | Restore a supported ramp, frame and retaining-wall arrangement | Add a distinct museum path/viewing edge; do not invent an earth-covered roof |
| Battle HQ | Reconstruct only documented room relationships until a full plan is recovered | Keep the cupola ladder as an exhibit; provide a camera/viewpoint alternative and proposed museum egress separately |

A historically narrow shelter must not be widened and then labelled an exact replica. If the explorer requires an accessible interpretation route, make the addition visually and informationally distinct. Every physical-looking entrance needs a state: reconstructed historic portal, proposed museum entrance, closed evidence marker, or unknown. Unknown points must remain null in data rather than receiving plausible-looking coordinates.

![Interior concepts](interior_concepts.png)

<!-- PAGEBREAK -->

## Entrances, paths and a complete visit

The four access points below are **authored museum proposals**, not identified current gates. Their BNG positions are placement anchors for review, not surveyed doorway coordinates. The precise alignments must be fitted to roads, buildings and gradients in the blockout.

| Gate | Proposed anchor E / N | Function |
|---|---|---|
| G1 Main gateway | 633315 / 166510 | Museum arrival, drop-off orientation, cycle parking and common visitor start |
| G2 Eastern visitor gate | 634030 / 166370 | Manston-village approach and entry to the War Flight trail |
| G3 Western service gate | 632730 / 166260 | Aircraft restoration, deliveries and staff access toward the T2 apron |
| G4 Western heritage threshold | 632390 / 166340 | Walking connection to the Alland Grange route |

Use the existing road network as context. Treat the Manston Road crossing between museum/command destinations and airfield destinations as a specific design problem: show a proposed formal crossing, traffic calming or a museum-controlled road arrangement in the imagined reuse. Do not let a rendered path simply cross the road without treatment. Avoid adding an unplanned direct visitor junction on the A299. Emergency and service access should reach the main halls from surface routes and should not depend on historic shelters.

| Route | Concept length | Walking time at 3 km/h | Visit role |
|---|---|---|---|
| R1 Museum and command loop | 636 m, closed loop | 13 min moving | 45-75 min with museum/command stops |
| R2 Aircraft and engineering circuit | 2,203 m, closed loop | 44 min moving | Approximately 2-3 hours with exhibitions |
| R3 War Flight and FIDO extension | 3,322 m, gateway to civil tower | 66 min moving, before return | Longer half-day extension; return using the relevant R2 leg |
| R4 Sunken hangars and railway trail | 2,390 m, closed loop | 48 min moving | Optional archaeology and early-aviation circuit |
| R5 Northern hangar branch | 1,501 m one way | 30 min each way | Specialist out-and-back visit; not a finished museum interior |

Distances are calculated from the authored polylines, without elevations or indoor walking. They are useful for comparing the concept, but change when paths are fitted to terrain. R3 is not a loop and R5's quoted distance does not include its return. The full runway alone represents approximately 5.5 km out and back; visitors should not need to walk it to understand the site.

Place seating, shelter and drinking-water/toilet opportunities at the gateway, T2/civil-tower circuit and long-trail junctions. Use a proposed accessible shuttle between the gateway, aircraft hall and FIDO end for the long visit. Reserve a broad, simple principal promenade; as concept targets, use about 3 m clear width and gentle gradients, with detailed accessibility design still to be checked. Keep quiet remembrance spaces outside the loud demonstration areas. Provide a clear route home at every branch.

<!-- PAGEBREAK -->

## The museum experience

Make the airfield itself the main exhibit. A visitor should understand the open flying ground from the tower, the protection offered by a fighter pen at ground level, the engineering challenge of a sunken hangar by descending its ramp, and the work required to recover damaged aircraft by following the runway landscape. Avoid filling every empty area with new buildings; the long sightlines and distances explain Manston's function.

The interpretive sequence is chronological but can be explored freely. Begin with RNAS and the RAF's formation, move through technical training and station life, then explain the Battle of Britain and later emergency-landings role. Continue through early jets, the Cold War, rescue, civil aviation and the imagined museum. The history site's centenary material provides these broad themes, while individual labels should cite unit/aircraft records and distinguish a type associated with Manston from a specific surviving airframe.[^40][^41]

Balance aircraft displays with the people who made the station work: engineers, armourers, firefighters, medical staff, WAAF personnel, air traffic staff, rescuers and local civilians. Include RAF, RNAS and associated Commonwealth and Allied stories; interpret the USAF period as part of Manston's history without relabelling it as an RAF unit. A hands-on engineering area, oral-history listening stations and a school route can occupy restored technical-space bays.

The existing museums already provide important aircraft, cockpit, engine and wartime-life interpretation. The masterplan offers virtual extensions, not a claim to transfer ownership of collections. The Spitfire and Hurricane airframes should use their correct museum identities rather than generic Battle of Britain aircraft markings. Other aircraft allocations, aircraft dimensions and liveries must be selected and sourced during the asset phase.[^10][^11]

Use four visible evidence labels in the explorer: **documented**, **reconstructed from evidence**, **interpretive addition**, and **unresolved**. A compact source panel should explain what the selected building represents and its chosen date. Keep documentary information available without forcing visitors to read technical metadata during every interaction. Historical outlines can appear through a map toggle; present-day museum additions remain legible in the default scene.

For subterranean areas, the first-person journey should include real transitions: an outdoor approach, a threshold, a controlled change of light, a visible route onward and a clear return. Put any teleport or cutaway view behind a deliberate museum interaction. Do not hide an unsolved alignment by silently teleporting through what appears to be a historically continuous tunnel. The map should show when a space is a detached interpretive reconstruction.

<!-- PAGEBREAK -->

## Integration into the Thanet explorer

The research uses the established project frame: **EPSG:27700**, origin **E627680 N163080**, with elevation in **ODN metres**. For local geometry, x = E - 627680 and y = N - 163080; z stays in ODN metres. The Unreal conversion remains (100x, -100y, 100z) centimetres and happens once at the consumer boundary. Keep these documents separate from the Streetscape schema until an explicit heritage importer or conversion step exists.

The feature register supplies identity, era, evidence source, representative coordinate, confidence and survival statement. Every unknown floor height, footprint and portal remains null. Do not use the size printed beside a HER grid reference as a hangar's wall dimensions: it can include spoil banks, aprons or an entire group. Do not use a HER group centre as the start of a tunnel. The new basemap's numeric precision likewise does not imply cadastral or survey accuracy.

Before the first terrain-changing edit, inspect the existing LiDAR DTM/DSM around the selected features, sample the route slopes and register historical plans against independently identifiable control points. Record at least six well-distributed controls when practical, the transformation, residuals and withheld check points. A small residual on a few fitted points cannot make a distorted oblique photograph a measured plan. Broad web images stay as context until better scans are obtained.

Create separate content/data layers for the present base, documented historical geometry, supported reconstruction, proposed museum additions and unresolved evidence markers. Suppress duplicate modern massing only within verified replacement footprints; avoid removing an entire tile. Use distinct material treatment for replacement historical fabric. The old and civilian control towers need separate identifiers and models.

Terrain surfaces do not contain underground voids. Every sunken hangar or shelter needs an explicit terrain cutout, retaining/roof mesh and collision model. Where the landscape cannot resolve a small portal, use a local authored transition rather than a terrain hole large enough to expose the world below. Subterranean floors, walls and ceilings need navigation and collision checks; lighting must prevent daylight leaking through the ground. Keep one-way drops out of public visitor routes.

The current Thanet clip line excludes parts of the wider Minster landscape. The Abbey Farm FIDO supply route may therefore extend beyond the playable area. Keep it as a regional map connection or propose a deliberate future map extension. Do not move it into the airfield to make it fit. Long lines such as railways and pipelines require their actual geometry before they can become spatially faithful overlays.

The first implementation should validate this concrete experience: arrive at G1, choose R1 or R2, reach every intended hall, return to G1, and enter/leave each enabled reconstructed interior without getting stuck. Check the current explorer capsule against clear widths and headroom, both directions of every transition, terrain seams and streaming boundaries. A credible plan must become a continuous walk, not only an attractive aerial view.

<!-- PAGEBREAK -->

## Uncertainties and the next evidence needed

| Issue | Consequence | Required evidence or decision |
|---|---|---|
| Battle HQ: 2009 interior account versus 2021 demolished surface record | No claim of an intact present bunker | Later survey/record photographs and measured floorplan; inspect the original evidence for both observations |
| Chalk shelter: no published alignment, length or portal coordinates | No exact underground placement | KURG 2005, Caves and Tunnels in South East England, Part 17; original 2004 survey |
| Sunken hangars: four mapped sites versus five approved in a provisional narrative source[^6] | Count proposals separately from completed/unfinished sites | RAF Museum plans, construction photographs and the cited early-Manston histories |
| Historic maps at low web resolution | No trustworthy doorway tracing | High-resolution Plan 78 / MFC/78/24/0883 and X004/2380 |
| Shelter groups recorded as levelled | Surface loss does not prove every buried chamber destroyed | Individual archaeological polygons, survey notes and later observations |
| Older power-house survival claim versus recent HER interpretation | Building identity may be confused | Match the original plan, aerial photograph and present footprint |
| Early runway dates vary between construction and opening; some narratives differ | Avoid a falsely precise single date | Use dated aerial stages; April 1944 operation supported by the FIDO record |
| Former Glider School shelter/infill references in PEIR | Cannot equate them automatically with the 2004 chalk shelter | Obtain full Appendix 9.1 records and map source IDs/building numbers |
| Alland Grange tunnel attribution is verbal and distinct from hangars | No detailed connected reconstruction | Original local survey/archival material; retain low confidence until corroborated |
| Present buildings and museum access arrangements | Concept paths may need repositioning | Current footprint/entrance survey and terrain/road fitting |

Prioritise the RAF Museum drawings, KURG shelter survey, KCC's 2016 building/structure survey (SKE31558), and the Historic England Thanet mapping polygons. The newer HER descriptions identify the relevant aerial sorties, including RAF/HLA/564 on 1 June 1942 and US/7PH/GP/LOC286 on 19 April 1944. These provide a concrete archive request list; the originals have not all been acquired.[^8][^9][^24]

The large 2018 PEIR volumes were discoverable and search-indexed but could not be fully retrieved in this run. They are therefore leads, not the foundation for a measured underground plan. The 2019 heritage submission is an interested-party representation, useful for locating concerns and photographs, and does not substitute for the cited Historic England/KCC originals.[^42][^43]

No physical site work is part of this approval. For any later real-world museum proposal, ownership, access, condition, archaeology and building approvals would be a separate project. For the digital reconstruction, the immediate dependency is reliable source geometry and a documented distinction between historical fabric and museum invention.

<!-- PAGEBREAK -->

## Delivery phases and approval scope

**Phase 0 - evidence and placement.** Preserve this source chest, resolve the priority drawings, register the main plans and inspect the terrain. Set up the historical/reconstruction/museum layers, place the 32 curated evidence anchors, and agree the replacement footprints. Exit with a map that distinguishes measured geometry from indicative placement. The present pack completes the research-and-concept portion; it does not complete the measured-plan work.

**Phase 1 - a complete walkable core.** Build G1, the two museum exteriors, the RAF tower exterior, the Battle HQ interpretation point, R1 and R2, the fighter pen, T2 hall shell and civilian-tower destination. Include seating, crossings, route signs and a coherent return to the gateway. Add a partial erecting-shop/railway interpretation. Initially keep unsupported historic interiors closed or explicitly identified as detached interpretive exhibits. Exit only when the whole core can be walked continuously and the scene preserves real airfield scale.

**Phase 2 - early aviation and a supported underground experience.** Build the Alland Grange sunken hangar and R4 once the plan is registered. Add one reconstructed War Flight shed and the R3 connection. Build the chalk shelter at its documented geometry only after the KURG drawing is available; otherwise use an openly labelled detached museum reconstruction. Resolve the HQ floorplan before presenting a complete authentic interior. Exit with enter/exit checks, source labels and terrain/collision seams verified.

**Phase 3 - the wider airfield museum.** Extend the FIDO and runway interpretation, northern unfinished-hangar branch, station-life exhibits, rescue and postwar content. Add shuttle/fast-travel options for distance, archive/photo displays where rights are established, and time-layer comparison. Keep the unfinished hangar sites unfinished in their historical layer. The Loop and regional railway/pipeline links are optional extensions rather than blockers for opening the core.

**Recommended approval:** adopt the selective-restoration museum concept; keep the real-scale runway and open landscape; retain both museum identities; build the short/core circuits first; treat Alland Grange as the principal expansion; and make historical uncertainty visible. Approve G1-G4 by function and approximate position, with detailed path, crossing and entrance fitting in Phase 0/1.

**Decisions reserved:** exact historic room plans, underground floor levels and portal coordinates; any claim that the Battle HQ still survives intact; completion of the northern unfinished hangars; a connected airfield tunnel network; and extensive replacement of present-day buildings. None is necessary to approve the proposed museum experience.

The current deliverable is a reviewable plan and reusable information chest. No Unreal level, gameplay code, terrain or existing project data has been changed by this research pack.

<!-- PAGEBREAK -->

## Sources

All web sources below were accessed on 11 September 2026. Kent HER sources are public record summaries; their underlying surveys, photographs and plans are identified where available. The full catalogue appears in SOURCE_CHEST.md.

[^1]: RiverOak Strategic Partners. [Stage 3 Airspace Change Consultation Now Closed](https://rsp.co.uk/news/stage-3-airspace-change-consultation-now-closed/), 25 June 2026.
[^2]: RiverOak Strategic Partners. [Bristows Search and Rescue](https://rsp.co.uk/news/bristows-search-and-rescue/), 15 January 2026.
[^3]: Kent HER. [Manston military and civil aviation airfield, MKE40120](https://heritage.kent.gov.uk/Monument/MKE40120), incorporating 2024 aerial mapping.
[^4]: Kent HER. [Alland Grange semi-sunken hangar, MKE92406](https://heritage.kent.gov.uk/Monument/MKE92406), amended 4 December 2024; cites KCC 2016 and aerial imagery.
[^5]: Kent HER. [World War Two RAF Battle HQ, MKE98027](https://heritage.kent.gov.uk/Monument/MKE98027), recent mapping assessed against 2021 imagery.
[^6]: History of Manston Airfield. [Manston Layout History](https://www.manstonhistory.org.uk/manston-layout-history/), evolving plan/photo collection; [The Manston Camp Light Railway](https://www.manstonhistory.org.uk/the-manston-camp-light-railway/), updated 19 February 2026, explicitly provisional.
[^7]: Kent HER. [Crash runway, MKE98031](https://heritage.kent.gov.uk/Monument/MKE98031). Modern mapping: [OpenStreetMap runway way 35310906](https://www.openstreetmap.org/way/35310906), retrieved 11 September 2026; ODbL.
[^8]: Kent HER. [Erecting shops / hangar and hard standing, MKE125655](https://heritage.kent.gov.uk/Monument/MKE125655); RAF Museum MFC/78/24/0883 and X004/2380 referenced.
[^9]: Kent HER. [Power House, MKE125654](https://heritage.kent.gov.uk/Monument/MKE125654); same RAF Museum plan references.
[^10]: RAF Manston History Museum. [Museum history](https://www.rafmanston.co.uk/home/history/) and [aircraft/cockpit collection](https://rafmanston.co.uk/visit-us/our-aircraft-and-cockpit-displays/), current public museum pages.
[^11]: Spitfire and Hurricane Memorial Museum. [Museum and collection](https://www.spitfiremuseum.org.uk/), current public museum website.
[^12]: Kent HER. [RAF Manston Control Tower, MKE98025](https://heritage.kent.gov.uk/Monument/MKE98025); c.1941 watch office and later alterations.
[^13]: Kent HER. [Railway platform, MKE125515](https://heritage.kent.gov.uk/Monument/MKE125515), 2024 mapping.
[^14]: Kent HER. [Fighter pen, MKE98024](https://heritage.kent.gov.uk/Monument/MKE98024), KCC 2016 and recent aerial interpretation.
[^15]: Kent HER. [T2 Hangar, MKE98020](https://heritage.kent.gov.uk/Monument/MKE98020), amended 9 April 2026.
[^16]: Kent HER. [Civil Control Tower, MKE98021](https://heritage.kent.gov.uk/Monument/MKE98021), citing KCC 2016 survey.
[^17]: Kent HER. [War Flight hangar and apron, MKE125213](https://heritage.kent.gov.uk/Monument/MKE125213), 2024 mapping.
[^18]: Kent HER. [War Flight hangar, MKE125218](https://heritage.kent.gov.uk/Monument/MKE125218), 2024 mapping.
[^19]: Kent HER. [FIDO fuel tanks and pumphouses, MKE104167](https://heritage.kent.gov.uk/Monument/MKE104167), amended 27 November 2024; cites Geoffrey Williams, Flying Through Fire, 1995.
[^20]: Kent HER. [Hangar No.4 / The Loop, MKE100021](https://heritage.kent.gov.uk/Monument/MKE100021), citing RAF Museum plan X004/2380 and 1950 imagery.
[^21]: Kent HER. [Cheeseman's Farm semi-sunken hangar, MKE92407](https://heritage.kent.gov.uk/Monument/MKE92407), amended 4 December 2024.
[^22]: Kent HER. [Northern semi-sunken hangar, MKE97296](https://heritage.kent.gov.uk/Monument/MKE97296), amended 4 December 2024.
[^23]: Kent HER. [Unfinished semi-sunken hangar, MKE125405](https://heritage.kent.gov.uk/Monument/MKE125405), amended 4 December 2024.
[^24]: Kent HER. [Chalk-cut air-raid shelter, MKE90888](https://heritage.kent.gov.uk/Monument/MKE90888), amended 13 May 2026; cites Kent Underground Research Group, Caves and Tunnels in South East England - Part 17, 2005, SKE25124.
[^25]: Kent HER. [Western technical-area shelters, MKE125197](https://heritage.kent.gov.uk/Monument/MKE125197), 15 mapped earthworks.
[^26]: Kent HER. [Northern station shelters, MKE125196](https://heritage.kent.gov.uk/Monument/MKE125196), 14 mapped earthworks.
[^27]: Kent HER. [Parade-ground shelters, MKE125195](https://heritage.kent.gov.uk/Monument/MKE125195), 23 mapped earthworks.
[^28]: Kent HER. [Southern War Flight shelters, MKE125191](https://heritage.kent.gov.uk/Monument/MKE125191), five mapped earthworks.
[^29]: Kent HER. [Northern War Flight shelters, MKE125192](https://heritage.kent.gov.uk/Monument/MKE125192), three mapped earthworks.
[^30]: Kent HER. [Air-raid shelter, MKE125193](https://heritage.kent.gov.uk/Monument/MKE125193).
[^31]: Kent HER. [Air-raid shelter, MKE125389](https://heritage.kent.gov.uk/Monument/MKE125389).
[^32]: Kent HER. [Shelter north of Rose Farm, MKE125439](https://heritage.kent.gov.uk/Monument/MKE125439).
[^33]: Mike Tucknott / Iain Taylor, Subterranea Britannica. [Manston Airfield Battle HQ](https://www.subbrit.org.uk/sites/manston-airfield-battle-hq/), 16 September 2009.
[^34]: Kent HER. [FIDO pipe trenches, MKE125093](https://heritage.kent.gov.uk/Monument/MKE125093), 2024 mapping.
[^35]: Kent HER. [FIDO control chamber, MKE125138](https://heritage.kent.gov.uk/Monument/MKE125138), amended 27 November 2024.
[^36]: Kent HER. [FIDO supply line and pump house, MKE125137](https://heritage.kent.gov.uk/Monument/MKE125137), 2024 mapping.
[^37]: Kent HER. [Southern service trenches, MKE125117](https://heritage.kent.gov.uk/Monument/MKE125117), 2024 mapping.
[^38]: Kent HER. [Alland Grange tunnels, MKE97293](https://heritage.kent.gov.uk/Monument/MKE97293), 15 September 2020; cites Ron Stilwell's 2015 verbal communication SKE30958.
[^39]: History of Manston Airfield. [Raids on Manston and Ramsgate, 24 August 1940](https://www.manstonhistory.org.uk/heavy-luftwaffe-raids-on-manston-and-ramsgate-on-24th-august-1940-leave-the-airfield-unserviceable/), includes a separately identified Ramsgate tunnel map.
[^40]: History of Manston Airfield. [Manston: 100 years of Flight](https://www.manstonhistory.org.uk/manston100years/), centenary project overview and linked period essays.
[^41]: History of Manston Airfield. [Squadrons and Units Timeline](https://www.manstonhistory.org.uk/squadrons-and-units/) and [Aircraft at Manston](https://www.manstonhistory.org.uk/aircraft-at-manston/).
[^42]: Supporters of Manston Airport / History of Manston Airfield. [Submission regarding heritage aspects](https://nsip-documents.planninginspectorate.gov.uk/published-documents/TR020002-004375-AS%20-%20Supporters%20of%20Manston%20Airport%20-%20Submission%20regarding%20heritage%20aspects.pdf), 16 June 2019, especially pp. 4-8. Interested-party representation; distinguishes its authors from the museum organisations.
[^43]: RSP / Amec Foster Wheeler. [PEIR Volume VI](https://rsp.co.uk/wp-content/uploads/2018/01/02-PEIR-Volume-VI-2018.pdf) and [PEIR Volume VII](https://rsp.co.uk/wp-content/uploads/2018/01/02-PEIR-Volume-VII-2018.pdf), 2018. Discovery/indexed excerpts only; full files not retrieved successfully in this research.
