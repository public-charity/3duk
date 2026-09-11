"""Save a bounded, identity-preserving move of the four obstructing furniture groups."""
from pathlib import Path
from datetime import datetime,timezone
import json,hashlib,shutil
import unreal
import ue_common as uc
from content_guard import snapshot,differences
P=Path(uc.project_dir());C=P/'Content';OUT=P/'docs/research/manston/airfield';S=P/'Saved/ManstonAirfield'
def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def save(p,d):
 p.parent.mkdir(parents=True,exist_ok=True);t=p.with_suffix('.tmp');t.write_text(json.dumps(d,indent=2),encoding='utf8');t.replace(p)
def path(a):return C/(a.get_package().get_name()[6:]+'.uasset')
def main():
 spec=json.loads((OUT/'furniture_adjustments.json').read_text())
 assert sha(OUT.parent/'implementation/museum_manifest.json')==spec['revised_manifest_sha256']
 assert unreal.get_editor_subsystem(unreal.LevelEditorSubsystem).load_level('/Game/Thanet/Maps/Thanet')
 assert unreal.StreetscapeEditorLibrary.load_region(unreal.Vector(560000,-310000,0),85000.)
 actors=unreal.get_editor_subsystem(unreal.EditorActorSubsystem).get_all_level_actors();moves=[]
 for change in spec['changes']:
  prefix='manston:'+change['id']+'_';group=[a for a in actors if a.get_actor_label().startswith(prefix)]
  assert len(group)==(5 if change['kind']=='sign' else 4),prefix
  ref=next(a for a in group if a.get_actor_label()==prefix+('board' if change['kind']=='sign' else 'seat'))
  old,new=change['old'],change['new'];loc=ref.get_actor_location()
  expected=unreal.Vector((old['bng'][0]-627680)*100,-(old['bng'][1]-163080)*100,(old['surface_z_odn_m']+(1.7 if change['kind']=='sign' else .47))*100)
  if (loc-expected).length()>.1:raise ValueError('Furniture already moved or source differs: '+prefix)
  delta=unreal.Vector((new['bng'][0]-old['bng'][0])*100,-(new['bng'][1]-old['bng'][1])*100,(new['surface_z_odn_m']-old['surface_z_odn_m'])*100)
  moves.extend((a,delta) for a in group)
 checkpoint=S/'furniture_checkpoints'/datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')
 baseline=snapshot(C);save(checkpoint/'before.json',baseline)
 for a,d in moves:
  src=path(a);dst=checkpoint/'before'/src.relative_to(C);dst.parent.mkdir(parents=True,exist_ok=True);shutil.copy2(src,dst)
 saved=[];pending=[]
 for a,d in moves:
  a.set_actor_location(a.get_actor_location()+d,False,False);pending.append(a)
  if len(pending)==8 or a==moves[-1][0]:
   assert unreal.EditorLoadingAndSavingUtils.save_packages([v.get_package() for v in pending],False)
   saved.extend(v.get_actor_label() for v in pending);pending.clear();save(checkpoint/'journal.json',dict(state='saving',labels=saved))
 files=[]
 for a,d in moves:
  src=path(a);dst=checkpoint/'after'/src.relative_to(C);dst.parent.mkdir(parents=True,exist_ok=True);shutil.copy2(src,dst)
  files.append(dict(path=str(src.relative_to(C)).replace('\\','/'),sha256=sha(src)))
 changes=differences(baseline,snapshot(C));allowed={r['path'] for r in files}
 unexpected={k:[p for p in v if p not in allowed] for k,v in changes.items()}
 assert not any(unexpected.values()),unexpected
 report=dict(checkpoint=str(checkpoint),saved_files=files,groups=4,actors=len(files),changes=changes,unexpected_changes=unexpected,
  revised_manifest_sha256=spec['revised_manifest_sha256'],adjustments_sha256=sha(OUT/'furniture_adjustments.json'))
 save(S/'furniture_import_report.json',report);save(checkpoint/'import_report.json',report);save(checkpoint/'journal.json',dict(state='saved',labels=saved))
 uc.report('14_manston_furniture',dict(groups=4,actors=len(files),checkpoint=str(checkpoint),unexpected_changes=unexpected))
if __name__=='__main__':main()
