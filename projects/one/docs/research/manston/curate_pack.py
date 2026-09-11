"""Curated factual notes and explicit museum proposals. Never imports into Unreal."""
import json
import math
import re
from pathlib import Path
from bs4 import BeautifulSoup
from collect_sources import get, save, NOW

HERE=Path(__file__).resolve().parent
ORIGIN=[627680,163080]
her=json.loads((HERE/'heritage_inventory.json').read_text(encoding='utf-8'))
lookup={r['id']:r for r in her['records']}
for ident in ['MKE97293','MKE98021']:
    url='https://heritage.kent.gov.uk/Monument/'+ident
    body,_=get(url)
    s=BeautifulSoup(body,'html.parser'); t=s.get_text(' ',strip=True)
    grid=re.search(r'Grid reference\s+(.+?)\s+Map sheet',t)[1]
    m=re.search(r'TR\s+(\d+)\s+(\d+)',grid)
    lookup[ident]={'id':ident,'title':s.find('h1').get_text(' ',strip=True),'url':url,'grid_reference':grid,'anchor_bng':[600000+int(m[1].ljust(5,'0')),100000+int(m[2].ljust(5,'0'))],'geometry_role':'HER representative point/extent centre, NOT a surveyed entrance or footprint','retrieved_utc':NOW,'fetch_status':'ok'}
her['records']=list(lookup.values()); save('heritage_inventory.json',her)
manifest=json.loads((HERE/'acquisition_manifest.json').read_text())
manifest['heritage_records']=len(lookup)
manifest['supplemental_records']=['MKE97293','MKE98021']
manifest['sitemap_reconciliation']='222 sitemap URLs; no post/page sitemap URL absent from the REST article inventory'
manifest['media_discrepancy']='491 objects returned across all six REST media pages; API total says 503. No claim that the other 12 are archived or publicly accessible.'
save('acquisition_manifest.json',manifest)

# Own factual paraphrases. HER extents include earthworks/aprons and are not building sizes.
notes=[
('MKE98025','RAF control tower','1941-1999','surface','recorded standing in 2021','high','A modified wartime watch office, used until the civil tower replaced it in 1999. Model its chosen historic phase separately from later additions.','Restore the wartime exterior where supported; interpret later changes indoors.'),
('MKE98027','Battle Headquarters','WWII','subsurface','conflicting observations; buried survival unresolved','medium','HER maps a likely HQ surface structure as demolished in 2021. A 2009 Subterranea Britannica visit describes rooms, an unusually tall cupola and a ladder. These observations do not establish the present buried condition.','Evidence-labelled reconstruction candidate beside the old tower; no invented connected tunnels.'),
('MKE98021','Civilian control tower','1999 onward','surface','described in 2016 survey; current condition unverified','high','The civilian tower was built in 1999 over a pyrotechnic store believed to date from USAF use. Store dimensions and internal arrangement are not established.','Retain as the postwar/civil aviation lookout; store only as an unmodelled evidence marker.'),
('MKE98020','T2 hangar','WWII onward','surface','recorded standing in 2021; substantially rebuilt','high','The 1980s rebuilding retained the original steel frame; later cladding and other fabric should not be presented as original wartime material.','Main aircraft and conservation hall; retain the building in its actual location.'),
('MKE98024','E-type fighter pen','c.1940 onward','surface','partly surviving earthwork in 2021','high','A surviving part of a fighter pen with an associated revetted slit trench; the trench was mapped as levelled. The footprint includes the earthwork setting.','Restore missing arms selectively and label additions; aircraft and ground-crew exhibit.'),
('MKE92406','Alland Grange sunken hangar','1918','sunken','banks survived in 2021; walls recorded demolished','high','The hangar occupied a chalk excavation with a ramp, retaining structures and frame supports. The cited KCC account says soil covering was not intended.','Flagship partial reconstruction with visible chalk cut and interpreted roof/frame; dimensions await plan registration.'),
('MKE92407','Cheeseman sunken hangar','1918','sunken','earthworks recorded levelled in 2021','high','Aerial evidence distinguishes this hangar from nearby earlier earthworks. Later military features occupied the site.','Outline and archaeological garden; restore only if surviving-landscape conflicts are resolved.'),
('MKE97296','Northern hangar excavation','1918','sunken','unfinished; earthworks recorded levelled in 2021','high','Two spoil banks and an approach from Manston Road were mapped. Completion and roofing are not established.','Show the unfinished project through earthwork outlines, not a finished hangar.'),
('MKE125405','Opposite unfinished hangar','1918','sunken','unfinished; levelled in 2021','high','Initial pits and spoil were mapped opposite the other northern excavation. This was not a completed underground building.','Companion landscape interpretation; no walkable interior.'),
('MKE90888','Surveyed chalk air-raid shelter','probably 1940','subsurface','surveyed after rediscovery in 2004; present state unknown','high','KURG surveyed a single chalk passage with an entrance at each end, 1.3 m wide; HER gives a 1.8-2 m depth dimension. Length, bearing, overburden and exact portals are absent from the public record.','Place an approximate evidence marker. Prototype an explicitly interpretive interior separately until the original survey is obtained.'),
('MKE125197','Western technical-site shelters','WWII','subsurface','15 earthworks mapped; levelled in 2021','high','Fifteen separate shelter earthworks flanked former hangars/workshops. At least two had revetted slit-trench approaches.','Select one representative exhibit after acquiring geometry; use ground traces for others.'),
('MKE125196','Northern station shelters','WWII','subsurface','14 earthworks mapped; levelled in 2021','high','Fourteen shelters were mapped on the north of the station; one record represents a group.','Historical layer only until individual footprints are available.'),
('MKE125195','Parade-ground shelter group','WWII','subsurface','23 earthworks mapped; levelled in 2021','high','Twenty-three shelters were arranged in parallel rows northeast of the parade ground. This is evidence of distribution, not underground links.','Camp-life interpretation and separate traces; no connecting corridors.'),
('MKE125191','Southern War Flight shelters','WWII','subsurface','5 earthworks mapped; levelled in 2021','high','Five shelters were mapped toward the southern end of the eastern War Flight area.','Place group evidence marker; recover individual portal geometry before reconstruction.'),
('MKE125192','Northern War Flight shelters','WWII','subsurface','3 earthworks mapped; levelled in 2021','high','Three shelters were mapped in the northern part of the eastern War Flight area.','Ground-trace interpretation; entrances unresolved.'),
('MKE125193','Officers quarters shelter','WWII','subsurface','1 earthwork mapped; levelled in 2021','high','A shelter stood behind the Married Officers Quarters near the north of the War Flight area.','Small life-on-base interpretation marker.'),
('MKE125389','Far northern War Flight shelter','WWII','subsurface','1 earthwork mapped; levelled in 2021','high','An isolated shelter earthwork was mapped north of the main eastern group.','Evidence marker, not a verified surviving chamber.'),
('MKE125439','Rose Farm shelter','WWII','subsurface','1 earthwork mapped; levelled in 2021','high','An individual air-raid shelter was mapped north of Rose Farm.','Include on the western archaeology trail.'),
('MKE104167','FIDO tanks and pump houses','1943-1958','surface_services','recorded demolished/levelled by 2021','high','Four bunded tanks and two pump houses supplied the fog-dispersal installation. HADES conversion was finished in May 1945; later operation was under trial conditions.','Reconstruct selected tank/bund outlines and a non-burning interpretation display.'),
('MKE125093','FIDO pipe trenches','1943-1944','buried_services','aerially mapped construction traces','high','Mapped trench fragments identify fuel-line installation around the eastern runway and approach. They do not demonstrate a passage people could walk through.','Subsurface service overlay only.'),
('MKE125138','FIDO control chamber','1943-1945','surface','recorded demolished in 2021','high','A small control building is identified on RAF Museum plan X004-2380. The word chamber does not establish a bunker below ground.','Small reconstructed control exhibit if the original plan supports dimensions.'),
('MKE125142','FIDO workshop and office','1943-1945','surface','recorded demolished in 2021','high','The FIDO facility included a repair shop, office hut and staff ablutions.','Small support ensemble or outlines on the long runway trail.'),
('MKE125137','FIDO supply from Abbey Farm','1943-1945','buried_services','route mapped; some building survival uncertain','high','A six-inch fuel main connected railway-side facilities to the tanks. Its HER point represents a long feature extent, not a building or portal.','Regional context overlay; do not turn the pipeline into a tunnel.'),
('MKE125117','Southern service trenches','WWII','buried_services','mapped filled trenches/cropmarks','medium','Long trenches parallel to the south of the crash runway are interpreted as services. Their detailed purpose and construction are not established.','Do not create traversable galleries.'),
('MKE97293','Alland Grange reported tunnels','WWII attribution','reported_subsurface','oral-history record; much reportedly lost','low','A 2015 verbal account links tunnels to an Auxiliary Units wireless role and says much was lost to later works. The record distinguishes these from other nearby air-raid tunnels.','Regional interpretation marker only; no connection to the sunken hangar or airfield shelter is evidenced.'),
('MKE98031','Crash runway and salvage bays','1943-1944 onward','surface','historic runway transformed by later airport use','high','The wartime emergency landing layout preceded later resurfacing and modern runway markings. HER extent dimensions cover mapped features and are not pavement width.','Keep modern surveyed runway scale; reveal historic emergency-landing layout in a dated overlay.'),
('MKE125515','Camp railway terminus','WWI/interwar','surface','recorded demolished in 2021','high','A platform served the camp railway from the Birchington/Minnis Bay connection. The public HER centre and extent do not define the platform edges.','Restore a short platform/track exhibit after plan registration; regional route shown separately.'),
('MKE125654','Power house','interwar/WWII','surface','recorded demolished in 2021','high','Plans identify the power house; the modern mapping conflicts with older online statements that a building survived.','Trace first, reconstruct selected facade only after identity check.'),
('MKE125655','Erecting shops','WWI/interwar','surface','demolished by a mid-century plan','high','A twin side-opening hangar served technical training and was labelled Erecting Shops on the 1930 plan.','Rebuild one selected structural bay as an engineering gallery; preserve readable lost-building footprint.'),
('MKE125213','War Flight aeroplane shed','c.1917','surface','recorded demolished in 2021','medium','A side-opening shed and apron were mapped in the eastern War Flight area. Its precise standard type is interpreted, not definitively proved.','One restored early flying shed; detailed geometry and type await drawings.'),
('MKE125218','Second War Flight shed','c.1917','surface','recorded demolished in 2021','medium','A second side-opening shed was mapped farther north.','Outline by default to keep the early layout legible without rebuilding everything.'),
('MKE100021','The Loop / Hangar No.4','mid-century','surface','historic hangar recorded demolished in 2021','medium','A mid-century plan identifies Hangar No.4 here. Older claims about present-building continuity are uncertain.','Optional jet-age satellite trail; do not assert a surviving WWII hangar.'),
]
features=[]
for ident,name,era,layer,survival,confidence,fact,proposal in notes:
    r=lookup[ident]; e,n=r['anchor_bng']
    features.append({'id':ident,'name':name,'era':era,'layer':layer,'source_url':r['url'],'source_grid_reference':r['grid_reference'],'anchor_bng':[e,n],'local_xy_m':[e-ORIGIN[0],n-ORIGIN[1]],'tile':[int((e-ORIGIN[0])//512),int((n-ORIGIN[1])//512)],'anchor_role':'public HER representative point, not entrance or building footprint','horizontal_accuracy_m':None,'surface_z_odn_m':None,'floor_z_odn_m':None,'portal_positions_bng':None,'historical_footprint_bng':None,'fact_confidence':confidence,'survival_as_recorded':survival,'research_note':fact,'proposed_museum_treatment':proposal,'review_status':'reviewed for concept; survey geometry pending'})
save('features.bng.json',{'schema':'manston-research-0.1','crs':'EPSG:27700','origin':dict(zip(['E','N'],ORIGIN)),'vertical_datum':'ODN','warning':'Research anchors only. Not a Streetscape import document. All z values and portal geometries unknown remain null. HER extents are not building dimensions.','features':features})

routes=[
{'id':'R1','name':'Museum and command loop','kind':'short','points':[[633315,166510],[633420,166535],[633500,166570],[633570,166580],[633575,166630],[633460,166640],[633335,166565],[633315,166510]]},
{'id':'R2','name':'Aircraft and engineering circuit','kind':'core','points':[[633315,166510],[633170,166510],[633040,166480],[633000,166390],[633060,166340],[632930,166260],[632880,166170],[632930,166050],[633180,165950],[633460,165820],[633540,166070],[633510,166300],[633420,166430],[633315,166510]]},
{'id':'R3','name':'War Flight and FIDO extension','kind':'long','points':[[633315,166510],[633680,166480],[633900,166435],[634030,166370],[633990,166280],[634010,166140],[634080,165900],[634300,165640],[634510,165280],[634460,165190],[634300,165280],[633970,165360],[633650,165520],[633460,165820]]},
{'id':'R4','name':'Sunken hangars and railway trail','kind':'long','points':[[633315,166510],[633160,166560],[632930,166610],[632860,166660],[632650,166790],[632410,166740],[632300,166600],[632310,166470],[632390,166340],[632610,166350],[632810,166450],[633040,166480],[633315,166510]]},
{'id':'R5','name':'Northern unfinished hangar branch','kind':'optional','points':[[633335,166565],[633700,166655],[634100,166880],[634210,167160],[634170,167250],[634070,167305],[633970,167420]]},
]
for r in routes:
    r['length_m']=round(sum(math.dist(a,b) for a,b in zip(r['points'],r['points'][1:])))
    r['walking_minutes_at_3kmh']=round(r['length_m']/50)
    r['geometry_status']='authored concept alignment, not current public access or a collision-checked route'
    r['closed_loop']=r['points'][0]==r['points'][-1]
    r['z_status']='terrain and gradients not yet sampled; no floor/portal elevation implied'
gates=[{'id':'G1','name':'Main museum gateway','bng':[633315,166510],'role':'Walk/cycle arrival, parking/drop-off orientation and start of every core itinerary.'}, {'id':'G2','name':'Eastern visitor gate','bng':[634030,166370],'role':'Proposed link from Manston village approach to War Flight trail; verify road crossing in blockout.'},{'id':'G3','name':'Western service gate','bng':[632730,166260],'role':'Proposed restoration/delivery access toward T2 apron; separate from visitor promenade.'},{'id':'G4','name':'Western heritage trail threshold','bng':[632390,166340],'role':'Proposed connection to Alland Grange trail; not a present property entrance.'}]
save('museum_proposal.bng.json',{'status':'FOR APPROVAL - counterfactual museum reuse','crs':'EPSG:27700','origin':dict(zip(['E','N'],ORIGIN)),'date':NOW,'gates':gates,'routes':routes,'new_paths':'All route polylines are design proposals that may cross current parcels or require new paths. Do not use for real-site navigation.','modern_camp':'Historical museum scenario only; no current processing-centre layout or security arrangements modelled.'})

web=json.loads((HERE/'website_inventory.json').read_text(encoding='utf-8'))
lines=['# Manston source chest index','','The public article/page inventory is complete against the retrieved REST collections and post/page sitemaps. Indexing is distinct from verifying every statement. Historical details require the evidence notes and original sources.','', '## History website articles and pages','', '| Type | Title | Modified | Layout keywords |','|---|---|---|---|']
for r in sorted(web['articles'],key=lambda x:x['title'].lower()):
    lines.append(f"| {r['kind']} | [{r['title'].replace('|','/')}](<{r['url']}>) | {r['modified'][:10]} | {', '.join(r['layout_keywords'])} |")
lines += ['','## Heritage records','','These are catalogue anchors. One record may represent many structures. A HER bounding extent is not a footprint, and a centre point is not an entrance.','','| Record | Feature | BNG anchor | Review |','|---|---|---|---|']
curated={x['id'] for x in features}
for r in sorted(lookup.values(),key=lambda x:x['id']):
    lines.append(f"| [{r['id']}]({r['url']}) | {r['title'].split(' - ',1)[-1]} | {r.get('anchor_bng')} | {'Concept evidence reviewed' if r['id'] in curated else 'Indexed; detail review pending'} |")
(HERE/'SOURCE_CHEST.md').write_text('\n'.join(lines)+'\n',encoding='utf-8')
print('Curated',len(features),'features;',len(lookup),'HER records; route lengths:',[(r['id'],r['length_m']) for r in routes])
