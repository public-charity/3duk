"""Apply an approved offshore delta to the saved map; preserve all other actors.

--preflight captures the current landscape and checks every touched baseline.
--apply checkpoints landscape packages, preflights, applies bounded tiles, saves
only landscape packages, then validates probes. --verify reopens saved assets.
"""
from pathlib import Path
import sys,json,hashlib,shutil,math,importlib.util
import unreal
import ue_common as uc
from content_guard import snapshot,differences,require_unchanged

NAME='14_offshore_cleanup';P=Path(uc.project_dir());ROOT=P.parents[1]
OUT=ROOT/'output/thanet_offshore_cleanup';CONTENT=P/'Content'
IMP=unreal.StreetscapeLandscapeImporter

def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def save(p,j):
    p.parent.mkdir(exist_ok=True,parents=True);tmp=p.with_suffix('.tmp');tmp.write_text(json.dumps(j,indent=1,allow_nan=False));tmp.replace(p)
def package_file(a):return CONTENT/(a.get_package().get_name()[6:]+'.uasset')

def captures(tag):
    spec=importlib.util.spec_from_file_location('offshore_capture',P/'Tools/ue/05_screenshot.py')
    ss=importlib.util.module_from_spec(spec);spec.loader.exec_module(ss)
    world=unreal.get_editor_subsystem(unreal.UnrealEditorSubsystem).get_editor_world()
    target=ss.make_render_target(world,2000,1462);rows=[]
    for name,x,y,z in [('whole',6656,4864,10050),('north',6100,8850,2250),('east',12400,5000,2000),('southeast',12200,1400,2200)]:
        path=OUT/'captures'/(tag+'_'+name+'.png')
        cam=dict(eye_ue=[x*100,-y*100,z*100],roll=0,pitch=-90,yaw=-90,fov_deg=70)
        if not ss.capture(world,cam,target,str(path),'final_ldr',0.,0.):raise ValueError('capture failed')
        size,colours,lum=ss.force_opaque(str(path))
        if colours<20 or not 4<lum<250:raise ValueError('capture empty/overexposed')
        rows.append(dict(path=str(path),bytes=size,colours=colours,luminance=lum,camera=cam))
    return rows

def probes(man):
    land=IMP.find_landscape();errors=[];n=0;maxe=maxc=maxw=0.
    for tile in man['patches']:
        for p in tile['probes']:
            x,y=p['x'],p['y'];e=IMP.probe_height_m(land,x,y,False);c=IMP.probe_height_m(land,x,y,True)
            w=IMP.probe_layer_weight(land,x,y,'water');n+=1
            if not math.isfinite(e) or not math.isfinite(c):errors.append(dict(point=p,missing=True));continue
            de,dc,dw=abs(e-p['z_m']),abs(c-p['z_m']),abs(w-p['water'])
            maxe=max(maxe,de);maxc=max(maxc,dc);maxw=max(maxw,dw)
            if de>.001 or dc>.001 or dw>.006:errors.append(dict(point=p,editor=e,collision=c,water=w))
    return dict(probes=n,max_editor_error_m=maxe,max_collision_error_m=maxc,max_water_weight_error=maxw,errors=errors,passed=not errors)

def main():
    opts=uc.parse_args(sys.argv,flags=('preflight','apply','verify'),options={'limit':'0'})
    if sum(bool(opts[k]) for k in ('preflight','apply','verify'))!=1:raise ValueError('choose one mode')
    man=json.loads((OUT/'patch_manifest.json').read_text());validation=json.loads((OUT/'candidate_validation.json').read_text())
    if not validation['all_checks_pass'] and not opts['preflight']:raise ValueError('candidate checks failed')
    for row in man['patches']:
        p=OUT/'patches'/row['file']
        if sha(p)!=row['sha256']:raise ValueError('patch changed '+row['file'])
        j=json.loads(p.read_text())
        for k,s in j['sha256'].items():
            if sha(p.parent/j[k])!=s:raise ValueError('patch payload changed')
    before=snapshot(CONTENT)
    if not unreal.get_editor_subsystem(unreal.LevelEditorSubsystem).load_level('/Game/Thanet/Maps/Thanet'):raise ValueError('load failed')
    # UE 5.8's parallel D3D12 translation exhausted residency command-list slots
    # on the first full landscape layer update. Serialize this isolated job's
    # translation; no project settings or saved rendering properties change.
    world=unreal.get_editor_subsystem(unreal.UnrealEditorSubsystem).get_editor_world()
    unreal.SystemLibrary.execute_console_command(world,'r.RHICmd.ParallelTranslate.Enable 0')
    count=IMP.load_landscape_for_review(True)
    if count<1:raise ValueError('landscape not loaded')
    actors=unreal.get_editor_subsystem(unreal.EditorActorSubsystem).get_all_level_actors()
    identities=sorted(a.get_path_name() for a in actors)
    landscape=[a for a in actors if isinstance(a,unreal.LandscapeProxy)]
    save(OUT/'native_landscape_state.json',dict(state=json.loads(IMP.landscape_state_json(IMP.find_landscape())),loaded_landscape=len(landscape),actors=len(actors)))
    if opts['verify']:
        report=probes(man);report['captures']=captures('after_reopened');report['content_guard']=require_unchanged(before,snapshot(CONTENT))
        save(OUT/'native_verification.json',report)
        if not report['passed']:raise ValueError('saved world probes failed')
        uc.report(NAME,dict(mode='verify',probes=report['probes'],passed=True));return
    check=[];limit=int(opts['limit']);rows=man['patches'][:limit] if limit else man['patches']
    for row in rows:
        result=json.loads(IMP.apply_offshore_tile_json(str(OUT/'patches'/row['file']),True))
        check.append(dict(file=row['file'],**result));save(OUT/'native_preflight.json',check)
        if not result['ok']:raise ValueError('preflight failed '+row['file']+': '+str(result))
    if not (OUT/'captures/before_whole.png').exists():save(OUT/'before_captures.json',captures('before'))
    if opts['preflight']:
        require_unchanged(before,snapshot(CONTENT));uc.report(NAME,dict(mode='preflight',tiles=len(check),loaded=count));return
    if limit:raise ValueError('apply requires complete patch manifest')
    checkpoint=OUT/'native_checkpoint'
    if not (checkpoint/'content_before.json').exists():
        save(checkpoint/'content_before.json',before)
        for a in landscape:
            src=package_file(a);dst=checkpoint/'before'/src.relative_to(CONTENT)
            dst.parent.mkdir(parents=True,exist_ok=True);shutil.copy2(src,dst)
    packages=list({a.get_package().get_name():a.get_package() for a in landscape}.values())
    completed=[]
    for row in rows:
        result=json.loads(IMP.apply_offshore_tile_json(str(OUT/'patches'/row['file']),False))
        completed.append(dict(file=row['file'],**result));save(OUT/'native_apply_journal.json',completed)
        if not result['ok']:raise ValueError('apply failed '+row['file']+': '+str(result))
        if len(completed)%8==0:
            if not unreal.EditorLoadingAndSavingUtils.save_packages(packages,True):raise ValueError('checkpoint save failed')
            uc.log('offshore saved %d/%d tile patches'%(len(completed),len(rows)))
    if not unreal.EditorLoadingAndSavingUtils.save_packages(packages,True):raise ValueError('final save failed')
    if identities!=sorted(a.get_path_name() for a in unreal.get_editor_subsystem(unreal.EditorActorSubsystem).get_all_level_actors()):raise ValueError('actor identities changed')
    result=probes(man)
    changes=differences(before,snapshot(CONTENT));allowed={str(package_file(a).relative_to(CONTENT)).replace('\\','/') for a in landscape}
    unexpected={k:[p for p in v if p not in allowed] for k,v in changes.items()}
    result.update(changes=changes,unexpected=unexpected,actor_identities_preserved=True)
    save(OUT/'native_apply_report.json',result)
    if any(unexpected.values()) or not result['passed']:raise ValueError('native scope/probe check failed')
    uc.report(NAME,dict(mode='apply',tiles=len(completed),passed=True,changed_packages=len(changes['modified'])))

if __name__=='__main__':main()
