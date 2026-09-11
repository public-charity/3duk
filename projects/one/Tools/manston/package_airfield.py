"""Freeze a matching verified airfield import, before/after assets and mesh recipes."""
from pathlib import Path
import json,hashlib,shutil,zipfile
P=Path(__file__).resolve().parents[2];R=P.parents[1]
OUT=P/'docs/research/manston/airfield';SAVED=P/'Saved/ManstonAirfield'
def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def main():
 imp=json.loads((SAVED/'import_report.json').read_text());ver=json.loads((SAVED/'verification_report.json').read_text())
 state=json.loads((OUT/'build_state.json').read_text());m=json.loads((OUT/'airfield_manifest.json').read_text())
 assert ver['pass_checks'] and imp['checkpoint']==ver['checkpoint'] and imp['manifest_sha256']==ver['manifest_sha256']==state['manifest_sha256']==sha(OUT/'airfield_manifest.json')
 assert not any(imp['unexpected_changes'].values()) and ver['content_guard']['unchanged']
 walks=json.loads((SAVED/'museum_regression.json').read_text())
 assert walks['pass'] and walks['airfield_manifest_sha256']==state['manifest_sha256']
 for row in imp['saved_files']:assert sha(P/'Content'/row['path'])==row['sha256']
 checkpoint=Path(imp['checkpoint'])
 for name in ['import_report.json','verification_report.json','museum_regression.json','before_overview.png','after_overview.png','after_runway_west.png','after_dispersals.png']:
  shutil.copy2(SAVED/name,OUT/name);shutil.copy2(SAVED/name,checkpoint/name)
 guide=f'''# Manston airfield completion

Saved in `/Game/Thanet/Maps/Thanet`. This is the museum reconstruction in the explorer.

- Complete 2,750 m × 61 m runway 10/28, including the western half previously removed by the map crop.
- Approximately 230 m broad historic pavement envelope, with separate old concrete and asphalt materials.
- White thresholds, runway numbers, centre dashes, edges and aiming marks; yellow taxiway centre lines.
- All 23 taxiway references and 24 mapped apron areas, including the northern dispersal pads and northeastern paved strip.
- One additional central apron interpreted from aerial imagery, approximately 71,368 m² before surface overlap removal.
- Total pavement {m['areas_m2']['paved']:,.0f} m² and {m['areas_m2']['terrain_extension']:,.0f} m² of restored ground on the clipped side of the airport.

The whole-island landscape crop and original roads were not rewritten. A local terrain mesh restores the airport land from raw Environment Agency DTM. Existing museum actors are preserved. The source JSON splines drive the runway/taxiways; joined footprint caches eliminate coplanar pavement overlaps. The same road renderer generates the marking footprints, which are fitted 9 mm above their exact supporting pavement triangles.

## Evidence and interpretation

The [LiDAR comparison](lidar_references.png) reveals the broad runway and dispersal pads. Esri World Imagery was inspected at the whole-airfield scale and in a runway close-up. Its imagery capture date is unknown. The [Manston layout history](https://www.manstonhistory.org.uk/manston-layout-history/) corroborates the emergency-runway history; the [2018 masterplan](https://rsp.co.uk/wp-content/uploads/2018/01/04-Masterplan-2018.pdf) identifies redundant runway pavement. Proposed new development on that plan was not copied into the museum.

Widths and the central apron boundary are authored reconstruction estimates, not a new measured airport survey. LiDAR dark/light anomalies are not assumed to be structures. The exact function of the northeastern paved strip remains unconfirmed; no new underground geometry is inferred.

## Validation

Geometry checks passed {len(m['caches'])} caches / {sum(c['triangles'] for c in m['caches']):,} triangles, including finite coordinates, triangle orientation, duplicate-face rejection, source hashes and 1,260 whole-runway footprint checks.

The saved map was reopened. {ver['probes']:,} surface probes and {ver['runway_width_and_length_probes']:,} additional runway probes passed. No missing runway samples or buried pavement samples were found. Maximum native/cache collision discrepancy: {ver['maximum_cache_collision_error_m']:.6f} m. This is computational agreement, not LiDAR accuracy. Verification changed no Content files. The visual review and complete engine runner verdict are recorded in PROGRESS.md.

The original landscape's visibility clip excludes {ver['hidden_landscape_probe_count']:,} samples from the terrain-occlusion comparison; Unreal's editor height query reports filled texels even where that landscape is hidden. Surface collision remains checked at all samples. The existing R1/R2 museum walks also passed {sum(r['collision_samples'] for r in walks['routes']):,} floor checks and the raised body-capsule obstruction checks with the new airfield loaded. A full manual character walk remains untested.

## Visit and resume

Open `projects/one/Thanet.uproject`, load Thanet and fly to Manston. For the western runway, use the Unreal console command:

```text
BugItGo 412000 -276000 6000 0 9 0
```

This navigation shortcut has not been tested in a manual Play-in-Editor session. The explorer's F key toggles flight.

Read `PROGRESS.md` before continuing. From the repository root, use `C:/Users/Shadow/code/3duk-env/env/python.exe`. The generator uses the existing NumPy/SciPy/GDAL environment plus Pillow and Shapely 2.1 or newer:

1. Run `projects/one/Tools/manston/build_airfield.py` and `check_airfield.py`.
2. If native sources changed, build with `powershell.exe -NoProfile -File projects/one/Tools/build.ps1`.
3. Import with `powershell.exe -NoProfile -File projects/one/Tools/ue/run_ue_python.ps1 -Script 13_manston_airfield.py -Args "--apply" -Render`.
4. Reopen/check using the same command with `-Args "--verify"`.
5. Package with `projects/one/Tools/manston/package_airfield.py` after reviewing the renders and runner verdict.

The generator writes its ready state last. The importer rejects stale geometry checks/caches and saves every eight actor updates. Latest native checkpoint: `{checkpoint.name}`. Its journal lists saved IDs. Existing owned assets are copied before updates; `before/` contains the preceding iteration and `after/` contains this verified result. The original absence of these airfield assets is recorded separately in `initial_before.json`. Resulting assets and generated caches are included in the ZIP with hashes. Recover only declared paths while the project has no active writer. The archive requires the existing Thanet world; it is not a standalone game.

## Sources

- Environment Agency LiDAR DTM and existing conformed terrain: Open Government Licence. Raw crop E631400–634850, N165050–167250; EPSG:27700 / ODN.
- OpenStreetMap contributors: ODbL; source snapshot and full metadata in the research chest.
- [Esri aerial review](https://services.arcgisonline.com/ArcGIS/rest/services/World_Imagery/MapServer/export?bbox=631400,165050,634850,167250&bboxSR=27700&imageSR=27700&size=1800,1150&format=png&f=image): visual corroboration only; imagery is not bundled or applied as a texture.
'''
 (OUT/'README.md').write_text(guide,encoding='utf8')
 files={}
 for directory in [OUT,P/'Tools/manston']:
  for p in directory.rglob('*'):
   if p.is_file() and '__pycache__' not in p.parts:files[str(p.relative_to(R)).replace('\\','/')]=p
 for relative in ['Tools/ue/13_manston_airfield.py','Plugins/Streetscape/Source/StreetscapeEditor/Public/StreetMeshCacheLibrary.h','Plugins/Streetscape/Source/StreetscapeEditor/Private/StreetMeshCacheLibrary.cpp','Plugins/Streetscape/Source/StreetscapeEditor/StreetscapeEditor.Build.cs']:
  p=P/relative;files[str(p.relative_to(R)).replace('\\','/')]=p
 for name in ['basemap.bng.json','aeroway_source.json','acquisition_manifest.json','SOURCE_CHEST.md']:
  p=OUT.parent/name;files[str(p.relative_to(R)).replace('\\','/')]=p
 files['recovery/initial_before.json']=SAVED/'checkpoints/20260911T220935Z/before.json'
 for folder in ['before','after']:
  for p in (checkpoint/folder).rglob('*'):
   if p.is_file():files['recovery/'+folder+'/'+str(p.relative_to(checkpoint/folder)).replace('\\','/')]=p
 for row in m['caches']:
  p=Path(state['cache_dir'])/row['file'];assert sha(p)==row['sha256'];files['generated/'+p.name]=p
 for name in ['before.json','journal.json']:
  p=checkpoint/name
  if p.exists():files['recovery/'+name]=p
 archive=R/'output/manston_airfield_checkpoint.zip';temp=archive.with_suffix('.tmp.zip')
 with zipfile.ZipFile(temp,'w',zipfile.ZIP_DEFLATED,compresslevel=6) as z:
  for name,p in sorted(files.items()):z.write(p,name)
  z.writestr('archive_manifest.json',json.dumps({'checkpoint':checkpoint.name,'hashes':{n:sha(p) for n,p in files.items()}},indent=2))
 with zipfile.ZipFile(temp) as z:assert z.testzip() is None
 temp.replace(archive);print(json.dumps(dict(archive=str(archive),files=len(files),bytes=archive.stat().st_size)))

if __name__=='__main__':main()
