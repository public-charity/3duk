"""Scoped airfield cache import/reopen checks; saved every eight actor updates.

UE 5.8 headers: DynamicMeshActor.h:26; DynamicMeshComponent.h:722;
UnrealEd/Public/FileHelpers.h:86. No global map save, landscape edit or existing-road import.
"""
from pathlib import Path
from datetime import datetime,timezone
import sys,json,hashlib,shutil,math,importlib.util
import unreal
import ue_common as uc
from content_guard import snapshot,differences,require_unchanged
P=Path(uc.project_dir());CONTENT=P/'Content';OUT=P/'docs/research/manston/airfield';SAVED=P/'Saved/ManstonAirfield'
NAME='13_manston_airfield';TAG='3duk.manston.airfield';MAP='/Game/Thanet/Maps/Thanet'

def save(p,d):
 p.parent.mkdir(parents=True,exist_ok=True);t=p.with_suffix(p.suffix+'.tmp');t.write_text(json.dumps(d,indent=2),encoding='utf8');t.replace(p)
def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def vec(p):return unreal.Vector(p[0]*100,-p[1]*100,p[2]*100)
def owned():return [a for a in unreal.get_editor_subsystem(unreal.EditorActorSubsystem).get_all_level_actors() if TAG in [str(t) for t in a.tags]]
def pkgfile(a):return CONTENT/(a.get_package().get_name()[6:]+'.uasset')
def capture(label):
 spec=importlib.util.spec_from_file_location('airfield_capture',str(P/'Tools/ue/05_screenshot.py'));ss=importlib.util.module_from_spec(spec);spec.loader.exec_module(ss)
 world=unreal.get_editor_subsystem(unreal.UnrealEditorSubsystem).get_editor_world()
 rt=ss.make_render_target(world,1800,1150);results=[]
 for name,xy,z,yaw,pitch,fov in [('overview',[5450,3050],2800,-90,-90,70),('runway_west',[4036,2790],75,9,-4,80),('dispersals',[5210,3000],240,-45,-45,80)]:
  path=SAVED/(label+'_'+name+'.png');camera=dict(eye_ue=[xy[0]*100,-xy[1]*100,z*100],roll=0.,pitch=pitch,yaw=yaw,fov_deg=fov)
  if not ss.capture(world,camera,rt,str(path),'final_ldr',0.,0.):raise RuntimeError('Capture failed')
  size,colours,lum=ss.force_opaque(str(path));results.append(dict(file=path.name,bytes=size,colours=colours,luminance=lum))
 return results

def materials():
 colors={'Asphalt':(.085,.091,.096),'Concrete':(.32,.31,.28),'Apron':(.29,.31,.29),'Grass':(.25,.42,.14),'White':(.78,.78,.72),'Yellow':(.75,.53,.06)}
 mel=unreal.MaterialEditingLibrary
 for name,rgb in colors.items():
  path='/Game/Thanet/Manston/Airfield/M_'+name
  if unreal.EditorAssetLibrary.does_asset_exist(path):mat=unreal.load_asset(path)
  else:mat=unreal.AssetToolsHelpers.get_asset_tools().create_asset('M_'+name,'/Game/Thanet/Manston/Airfield',unreal.MaterialInstanceConstant,unreal.MaterialInstanceConstantFactoryNew())
  mel.set_material_instance_parent(mat,unreal.load_asset('/Game/Thanet/Materials/M_Street_Base'))
  mel.set_material_instance_vector_parameter_value(mat,'BaseColor',unreal.LinearColor(*rgb,1.))
  mel.set_material_instance_scalar_parameter_value(mat,'Roughness',.94)
  if not unreal.EditorAssetLibrary.save_loaded_asset(mat,False):raise RuntimeError('Material save failed')

def apply(manifest,state):
 caches=manifest['caches'];cache_dir=Path(state['cache_dir'])
 for row in caches:
  if sha(cache_dir/row['file'])!=row['sha256']:raise ValueError('Cache changed '+row['file'])
 actors=owned();by={a.get_actor_label():a for a in actors}
 if len(by)!=len(actors):raise ValueError('Duplicate existing airfield labels')
 checkpoint=SAVED/'checkpoints'/datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ');checkpoint.mkdir(parents=True)
 baseline=snapshot(CONTENT);save(checkpoint/'before.json',baseline)
 for src in [pkgfile(a) for a in actors]+list((CONTENT/'Thanet/Manston/Airfield').glob('*.uasset')):
  if src.exists():
   dst=checkpoint/'before'/src.relative_to(CONTENT);dst.parent.mkdir(parents=True,exist_ok=True);shutil.copy2(src,dst)
 if not (SAVED/'before_overview.png').exists():capture('before')
 materials();eas=unreal.get_editor_subsystem(unreal.EditorActorSubsystem)
 complete=[];pending=[];identities={k:a.get_path_name() for k,a in by.items()};current=set()
 first_probes={}
 for p in manifest['probes']:first_probes.setdefault(p['actor'],p)
 def flush():
  if pending and not unreal.EditorLoadingAndSavingUtils.save_packages([a.get_package() for a in pending],False):raise RuntimeError('Airfield checkpoint save failed')
  for a in pending:
   src=pkgfile(a);dst=checkpoint/'after'/src.relative_to(CONTENT);dst.parent.mkdir(parents=True,exist_ok=True);shutil.copy2(src,dst)
  pending.clear();save(checkpoint/'journal.json',dict(state='applying',saved_ids=complete,manifest_sha256=state['manifest_sha256']))
 for row in caches:
  key=row['id'];current.add(key);a=by.get(key)
  if a is None:
   a=eas.spawn_actor_from_class(unreal.DynamicMeshActor,vec(row['origin_local_m']));a.set_actor_label(key);a.tags=[TAG];by[key]=a
  a.set_actor_location(vec(row['origin_local_m']),False,False);a.set_actor_hidden_in_game(False);a.set_actor_enable_collision(True)
  result=json.loads(unreal.StreetMeshCacheLibrary.apply_mesh_cache(a,str(cache_dir/row['file'])))
  if not result['ok']:raise RuntimeError(key+': '+str(result))
  if row['paint']:
   a.set_actor_enable_collision(False);a.get_dynamic_mesh_component().set_cast_shadow(False)
  else:
   p=first_probes[key];x,y=p['xy_local_m'];z=p['z_m']
   if a.get_dynamic_mesh_component().line_trace_component(vec([x,y,z+3]),vec([x,y,z-3]),True,False,False) is None:
    raise RuntimeError('Immediate top-face collision failed before save: '+key)
  pending.append(a);complete.append(key)
  if len(pending)==8:flush()
 for k,a in by.items():
  if k not in current:a.set_actor_hidden_in_game(True);a.set_actor_enable_collision(False);pending.append(a)
 flush()
 if any(by[k].get_path_name()!=identity for k,identity in identities.items()):raise RuntimeError('Existing actor identity changed')
 paths=[pkgfile(a) for a in by.values()]+list((CONTENT/'Thanet/Manston/Airfield').glob('*.uasset'))
 records=[]
 for src in paths:
  dst=checkpoint/'after'/src.relative_to(CONTENT);dst.parent.mkdir(parents=True,exist_ok=True);shutil.copy2(src,dst)
  records.append(dict(path=str(src.relative_to(CONTENT)).replace('\\','/'),sha256=sha(src)))
 changes=differences(baseline,snapshot(CONTENT));allowed={r['path'] for r in records};unexpected={k:[p for p in v if p not in allowed] for k,v in changes.items()}
 report=dict(checkpoint=str(checkpoint),manifest_sha256=state['manifest_sha256'],actors=len(caches),existing_identities_preserved=True,saved_files=records,changes=changes,unexpected_changes=unexpected)
 save(SAVED/'import_report.json',report);save(checkpoint/'import_report.json',report);shutil.copy2(OUT/'airfield_manifest.json',checkpoint/'airfield_manifest.json')
 if any(unexpected.values()):raise RuntimeError('Content outside owned scope changed')
 save(checkpoint/'journal.json',dict(state='saved',saved_ids=complete,manifest_sha256=state['manifest_sha256']))
 uc.report(NAME,dict(imported=len(caches),checkpoint=str(checkpoint),unexpected=unexpected))

def verify(manifest,state):
 baseline=snapshot(CONTENT);imp=json.loads((SAVED/'import_report.json').read_text())
 if imp['manifest_sha256']!=state['manifest_sha256']:raise ValueError('Verification source differs from saved import')
 for r in imp['saved_files']:
  if sha(CONTENT/r['path'])!=r['sha256']:raise ValueError('Saved assets changed since import')
 if (OUT/'furniture_adjustments.json').exists():
  furniture=json.loads((SAVED/'furniture_import_report.json').read_text())
  if furniture['revised_manifest_sha256']!=sha(OUT.parent/'implementation/museum_manifest.json'):raise ValueError('Furniture import is stale')
  for r in furniture['saved_files']:
   if sha(CONTENT/r['path'])!=r['sha256']:raise ValueError('Furniture assets changed since correction')
 by={a.get_actor_label():a for a in owned()};missing=[];buried=[];max_error=0.;max_lift=0.;minimum_clearance=100.;landscape=unreal.StreetscapeLandscapeImporter.find_landscape()
 triangle_counts={row['id']:by[row['id']].get_dynamic_mesh_component().get_dynamic_mesh().get_triangle_count() for row in manifest['caches']}
 if any(triangle_counts[row['id']]!=row['triangles'] for row in manifest['caches']):raise ValueError('Saved mesh triangle count differs from its cache')
 for p in manifest['probes']:
  a=by.get(p['actor'])
  if a is None:raise ValueError('Missing airfield actor '+p['actor'])
  x,y=p['xy_local_m'];z=p['z_m'];hit=a.get_dynamic_mesh_component().line_trace_component(vec([x,y,z+3]),vec([x,y,z-3]),True,False,False)
  if hit is None:missing.append(p);continue
  hz=hit[0].z/100;max_error=max(max_error,abs(hz-z))
  terrain=unreal.StreetscapeLandscapeImporter.probe_height_m(landscape,x,y,False)
  # GetHeightAtLocation(Editor) reports filled heightmap texels even in visibility holes.
  # Only the source clip's surviving landscape may occlude the pavement; the restored
  # airport extension deliberately occupies the previously hidden side of this boundary.
  if p['native_landscape_present'] and math.isfinite(terrain) and p['kind']!='grass':
   clearance=hz-terrain;max_lift=max(max_lift,clearance);minimum_clearance=min(minimum_clearance,clearance)
   if clearance<-.02:buried.append(dict(**p,burial_m=-clearance))
 # Independent regular grid across the full marked runway, including its formerly absent western half.
 runway=json.loads((OUT/'airfield.streetscape.json').read_text())['splines'][0]['points'];w,e=runway
 dx,dy=e['x']-w['x'],e['y']-w['y'];length=math.hypot(dx,dy);ux,uy=dx/length,dy/length
 runway_missing=[];runway_checks=0
 for i in range(111):
  s=.1+(length-.2)*i/110
  for j in range(9):
   d=-30.4+60.8*j/8;x=w['x']+ux*s-uy*d;y=w['y']+uy*s+ux*d
   tx=631400+256*math.floor((x+627680-631400)/256);ty=165050+256*math.floor((y+163080-165050)/256)
   a=by.get('manston_airfield:asphalt_%d_%d'%(tx,ty));runway_checks+=1
   if a is None or a.get_dynamic_mesh_component().line_trace_component(vec([x,y,150]),vec([x,y,-10]),True,False,False) is None:
    runway_missing.append([x,y])
 photos=capture('after')
 surface_pass=not missing and not buried and not runway_missing and max_error<.005
 regression=None
 if surface_pass:
  # Reuse the established walk validation with the new pavement present in this reopened world.
  spec=importlib.util.spec_from_file_location('airfield_museum_regression',str(P/'Tools/ue/12_manston_museum.py'))
  museum=importlib.util.module_from_spec(spec);spec.loader.exec_module(museum)
  regression=museum.verify(json.loads((museum.IMPL/'museum_manifest.json').read_text()),
   dict(map=MAP,airfield_manifest_sha256=state['manifest_sha256']))
 guard=require_unchanged(baseline,snapshot(CONTENT))
 if regression is not None:
  regression['content_guard']=guard;save(SAVED/'museum_regression.json',regression)
 report=dict(pass_checks=surface_pass and regression is not None and regression['pass'],surface_checks_pass=surface_pass,
  museum_regression_pass=regression['pass'] if regression else None,
  checkpoint=imp['checkpoint'],manifest_sha256=state['manifest_sha256'],probes=len(manifest['probes']),
  runway_width_and_length_probes=runway_checks,missing_runway_probes=runway_missing,saved_triangle_count=sum(triangle_counts.values()),
  hidden_landscape_probe_count=sum(not p['native_landscape_present'] for p in manifest['probes']),
  missing=missing,buried=buried,maximum_cache_collision_error_m=max_error,maximum_pavement_lift_m=max_lift,minimum_pavement_clearance_m=minimum_clearance,captures=photos,content_guard=guard)
 save(SAVED/'verification_report.json',report)
 uc.report(NAME,{k:v for k,v in report.items() if k not in ('missing','buried')})
 if not report['pass_checks']:uc.fail(NAME,'Airfield saved-world checks failed')

def main():
 opts=uc.parse_args(sys.argv,flags=('apply','verify'))
 if sum(bool(v) for v in opts.values())!=1:raise ValueError('Choose --apply or --verify')
 state=json.loads((OUT/'build_state.json').read_text())
 if state.get('state')!='ready' or sha(OUT/'airfield_manifest.json')!=state['manifest_sha256']:raise ValueError('Incomplete airfield generation')
 checked=json.loads((OUT/'geometry_verification.json').read_text())
 if not checked['pass_checks'] or checked['manifest_sha256']!=state['manifest_sha256']:raise ValueError('Geometry checks do not match this generation')
 manifest=json.loads((OUT/'airfield_manifest.json').read_text());SAVED.mkdir(parents=True,exist_ok=True)
 if not unreal.get_editor_subsystem(unreal.LevelEditorSubsystem).load_level(MAP):raise RuntimeError('Map load failed')
 if not unreal.StreetscapeEditorLibrary.load_region(unreal.Vector(545000,-305000,0),185000.):raise RuntimeError('Airfield region load failed')
 if opts['apply']:apply(manifest,state)
 else:verify(manifest,state)

if __name__=='__main__':main()
