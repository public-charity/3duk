"""Scoped, restartable museum import in the existing Thanet World Partition map.

--inspect is read-only. --apply saves only Manston actor packages. --verify reopens
the saved map and tests the generated walk surfaces. Engine interfaces:
StreetscapeEditorLibrary.h: ImportStreetscapeJson, LoadRegion, ActorStatsJson;
Engine/Classes/Components/TextRenderComponent.h: SetText / SetWorldSize;
UnrealEd/Public/FileHelpers.h: UEditorLoadingAndSavingUtils::SavePackages.
"""
from pathlib import Path
import json
import hashlib
import math
import shutil
import importlib.util
from datetime import datetime, timezone
import sys
import unreal
import ue_common as uc

NAME='12_manston_museum'
PROJECT=Path(uc.project_dir())
RESEARCH=PROJECT/'docs/research/manston'
IMPL=RESEARCH/'implementation'
REPORTS=PROJECT/'Saved/Manston'
MAP='/Game/Thanet/Maps/Thanet'
TAG='3duk.manston.museum'
CONTENT=PROJECT/'Content'


def file_for_package(package):
    name=package.get_name()
    if not name.startswith('/Game/'):
        raise ValueError('Not a project package: '+name)
    return CONTENT/(name[6:]+'.uasset')


def vector(x,y,z):
    return unreal.Vector(x*100.,-y*100.,z*100.)


def museum_actors():
    return [a for a in unreal.get_editor_subsystem(unreal.EditorActorSubsystem).get_all_level_actors()
        if TAG in [str(t) for t in a.tags] or a.get_actor_label().startswith('manston:')]


def export_barriers():
    """Read the current saved definitions before proposing local fence openings."""
    base=json.loads((IMPL/'museum_walks.streetscape.json').read_text())
    source=dict(base);source['splines']=[];source['junctions']=[]
    source['profiles']={'road':{},'edge':{},'hedge':{}}
    root=PROJECT.parents[1]
    for path in sorted((root/'data/thanet/out/unreal/streetscape').glob('*.json')):
        d=json.loads(path.read_text())
        for s in d.get('splines',[]):
            if not s['id'].startswith('barriers:'):
                continue
            if any(4950<p['x']<6100 and 2550<p['y']<3720 for p in s['points']):
                source['splines'].append(s)
                for kind in ('road','edge','hedge'):
                    source['profiles'][kind].update(d['profiles'][kind])
    if not source['splines']:
        raise ValueError('No source barriers found')
    template=REPORTS/'barrier_export_template.json'
    save_json(template,source)
    dest=IMPL/'barriers.saved_baseline.streetscape.json'
    if dest.exists():
        raise ValueError('Baseline exists; preserve it rather than exporting over it')
    result=unreal.StreetscapeEditorLibrary.export_document_json(str(template),str(dest))
    if not result:
        raise RuntimeError('Could not export current barrier definitions')
    uc.report(NAME,{'barrier_baseline':str(dest),'barriers':len(source['splines'])})


def apply(manifest,report):
    eas=unreal.get_editor_subsystem(unreal.EditorActorSubsystem)
    lib=unreal.StreetscapeEditorLibrary
    actors=museum_actors()
    gate_path=IMPL/'museum_gates.streetscape.json'
    gate_ids=set(s['id'] for s in json.loads(gate_path.read_text())['splines']) if gate_path.exists() else set()
    gate_actors=[a for a in eas.get_all_level_actors() if a.get_actor_label() in gate_ids]
    if len(gate_actors)!=len(gate_ids):
        raise ValueError('A gate target barrier is not loaded exactly once')
    by_label={a.get_actor_label():a for a in actors}
    if len(by_label)!=len(actors):
        raise ValueError('Duplicate museum actors: recover before applying')
    stamp=datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')
    backup=REPORTS/'checkpoints'/stamp
    # Save recovery bytes before any mutation. New actor creation is recorded too.
    saved=[]
    for src in sorted((CONTENT/'Thanet/Manston').rglob('*')):
        if src.is_file():
            dst=backup/'Content'/src.relative_to(CONTENT)
            dst.parent.mkdir(parents=True,exist_ok=True);shutil.copy2(src,dst)
            saved.append(str(src.relative_to(CONTENT)))
    for a in actors+gate_actors:
        src=file_for_package(a.get_package())
        if src.exists():
            dst=backup/'Content'/src.relative_to(CONTENT)
            dst.parent.mkdir(parents=True,exist_ok=True)
            shutil.copy2(src,dst);saved.append(str(src.relative_to(CONTENT)))
    save_json(backup/'before.json',{'status':'before_import','existing_actor_packages':saved,
        'existing_labels':sorted(by_label),'manifest_sha256':hashlib.sha256((IMPL/'museum_manifest.json').read_bytes()).hexdigest()})
    errors=list(lib.validate_streetscape_json(str(IMPL/'museum_walks.streetscape.json')))
    if errors:
        raise ValueError(errors)
    if 'manston:R1' in by_label and 'manston:R2' in by_label:
        # A missing final target must reject the entire update before R1 changes.
        # Check the saved definitions exported from memory, not just actor counts.
        good=IMPL/'museum_walks.streetscape.json'
        guard_before=backup/'guard_before.json'
        if not lib.export_document_json(str(good),str(guard_before)):
            raise RuntimeError('Could not export update-guard baseline')
        guard_hash=hashlib.sha256(guard_before.read_bytes()).hexdigest()
        negative=json.loads(good.read_text())
        negative['splines'][-1]['id']='manston:MissingPreflightTarget'
        invalid=backup/'invalid_missing_actor.json';save_json(invalid,negative)
        rejected=json.loads(unreal.StreetDocumentPatchLibrary.apply_independent_document(str(invalid)))
        guard_after=backup/'guard_after.json'
        if rejected.get('ok') or not lib.export_document_json(str(good),str(guard_after)) or hashlib.sha256(guard_after.read_bytes()).hexdigest()!=guard_hash:
            raise RuntimeError('Missing-target preflight changed existing definitions')
        report['patch_preflight_missing_target_preserved_definitions']=True
    def patch(path,expected):
        identities={a.get_actor_label():a.get_path_name() for a in eas.get_all_level_actors()
            if a.get_actor_label() in {s['id'] for s in json.loads(path.read_text())['splines']}}
        result=json.loads(unreal.StreetDocumentPatchLibrary.apply_independent_document(str(path)))
        if not result.get('ok') or result.get('actors')!=expected:
            raise RuntimeError('Existing actor update failed: '+str(result))
        after={a.get_actor_label():a.get_path_name() for a in eas.get_all_level_actors() if a.get_actor_label() in identities}
        if after!=identities:
            raise RuntimeError('A document update changed actor identities')
        return expected
    existing_routes=sum(label in by_label for label in ('manston:R1','manston:R2'))
    if existing_routes==2:
        count=patch(IMPL/'museum_walks.streetscape.json',2)
    elif existing_routes==0:
        # The legacy importer is used only for first creation, never replacement.
        count=lib.import_streetscape_json(str(IMPL/'museum_walks.streetscape.json'),False,False,0)
    else:
        raise RuntimeError('Partial route checkpoint: recover the missing actor before applying')
    if count != 2:
        raise RuntimeError('Expected two museum walk actors, got '+str(count))
    for a in museum_actors():
        a.tags=[TAG]
        by_label[a.get_actor_label()]=a
    if gate_ids:
        patch(gate_path,len(gate_ids))
    cube=unreal.load_asset('/Engine/BasicShapes/Cube.Cube')
    def material(name,rgb):
        path='/Game/Thanet/Manston/Materials/'+name
        mat=unreal.load_asset(path) if unreal.EditorAssetLibrary.does_asset_exist(path) else None
        if mat is None:
            mat=unreal.AssetToolsHelpers.get_asset_tools().create_asset(name,'/Game/Thanet/Manston/Materials',
                unreal.MaterialInstanceConstant,unreal.MaterialInstanceConstantFactoryNew())
        mel=unreal.MaterialEditingLibrary
        mel.set_material_instance_parent(mat,unreal.load_asset('/Game/Thanet/Materials/M_Street_Base'))
        mel.set_material_instance_vector_parameter_value(mat,'BaseColor',unreal.LinearColor(*rgb,1))
        mel.set_material_instance_scalar_parameter_value(mat,'Roughness',.8)
        mel.update_material_instance(mat)
        if not unreal.EditorAssetLibrary.save_loaded_asset(mat,False):
            raise RuntimeError('Material save failed '+name)
        return mat
    navy=material('MI_MuseumNavy',(.018,.035,.075))
    timber=material('MI_MuseumTimber',(.32,.19,.085))
    red=material('MI_MuseumRed',(.5,.025,.04))
    text_mat_path='/Game/Thanet/Manston/Materials/M_MuseumText'
    if not unreal.EditorAssetLibrary.does_asset_exist(text_mat_path):
        unreal.EditorAssetLibrary.duplicate_asset('/Engine/EngineMaterials/DefaultTextMaterialOpaque',text_mat_path)
        text_mat=unreal.load_asset(text_mat_path)
        mel=unreal.MaterialEditingLibrary
        vc=mel.create_material_expression(text_mat,unreal.MaterialExpressionVertexColor,-300,300)
        mel.connect_material_property(vc,'RGB',unreal.MaterialProperty.MP_EMISSIVE_COLOR)
    text_mat=unreal.load_asset(text_mat_path)
    text_mat.set_editor_property('shading_model',unreal.MaterialShadingModel.MSM_UNLIT)
    mel=unreal.MaterialEditingLibrary
    mel.recompile_material(text_mat)
    unreal.EditorAssetLibrary.save_loaded_asset(text_mat,False)
    active={'manston:R1','manston:R2'}
    def actor(label,cls,xyz,heading=0):
        a=by_label.get(label)
        if a and not isinstance(a,cls):
            raise ValueError('Museum label owned by wrong class: '+label)
        if a is None:
            a=eas.spawn_actor_from_class(cls,vector(*xyz),unreal.Rotator(0,0,-heading))
            if not a:
                raise RuntimeError('Failed to spawn '+label)
        a.set_actor_label(label)
        a.tags=[TAG]
        a.set_actor_hidden_in_game(False)
        a.set_actor_enable_collision(True)
        a.set_editor_property('is_editor_only_actor',False)
        active.add(label)
        a.set_actor_location(vector(*xyz),False,False)
        a.set_actor_rotation(unreal.Rotator(0,0,-heading),False)
        by_label[label]=a
        return a
    def box(label,xyz,scale,heading,mat):
        a=actor(label,unreal.StaticMeshActor,xyz,heading)
        c=a.static_mesh_component
        c.set_static_mesh(cube)
        c.set_material(0,mat)
        c.set_collision_profile_name('BlockAll')
        a.set_actor_scale3d(unreal.Vector(*scale))
        return a
    def text(label,xyz,heading,value,size=18,hidden=False):
        a=actor(label,unreal.TextRenderActor,xyz,heading)
        c=a.text_render
        c.set_text(value.replace('\n','<br>'))
        c.set_text_material(text_mat)
        c.set_world_size(size)
        c.set_horizontal_alignment(unreal.HorizTextAligment.EHTA_CENTER)
        c.set_vertical_alignment(unreal.VerticalTextAligment.EVRTA_TEXT_CENTER)
        c.set_text_render_color(unreal.Color(246,236,212,255))
        a.set_actor_hidden_in_game(hidden)
        if hidden:
            a.set_editor_property('is_spatially_loaded',False)
        return a
    for f in manifest['furniture']:
        x,y=f['bng'][0]-627680,f['bng'][1]-163080
        z=f['surface_z_odn_m'];heading=f['heading_deg']
        forward=(math.cos(math.radians(heading)),math.sin(math.radians(heading)))
        side=(-forward[1],forward[0])
        key='manston:'+f['id']
        if f['kind']=='sign':
            box(key+'_board',(x,y,z+1.7),(.12,4.0,2.0),heading,navy)
            box(key+'_stripe',(x+.07*forward[0],y+.07*forward[1],z+2.55),(.025,4.,.08),heading,red)
            for sign in (-1,1):
                box(key+'_post'+str(sign),(x+sign*1.6*side[0],y+sign*1.6*side[1],z+.8),(.12,.12,1.6),heading,navy)
            text(key+'_text',(x+.08*forward[0],y+.08*forward[1],z+1.65),heading,f['text'],18)
        else:
            box(key+'_seat',(x,y,z+.47),(.55,2.,.12),heading,timber)
            box(key+'_back',(x-.27*forward[0],y-.27*forward[1],z+.75),(.1,2.,.48),heading,timber)
            for sign in (-1,1):
                box(key+'_leg'+str(sign),(x+sign*.72*side[0],y+sign*.72*side[1],z+.22),(.44,.13,.44),heading,navy)
    # Editor research pins are never presented as public entrances in the game.
    for f in manifest['anchors']:
        if f['placement_surface_z_odn_m'] is None:
            continue
        text('manston:evidence_'+f['id'],(f['anchor_bng'][0]-627680,f['anchor_bng'][1]-163080,
            f['placement_surface_z_odn_m']+3.),0,f['id']+'\n'+f['name']+'\nAPPROXIMATE RESEARCH ANCHOR',30,True)
    packages=[]
    # Keep recoverable, inactive copies when a new route needs fewer rest stops.
    # They are excluded from play and can be reused if a later revision needs them.
    for a in museum_actors():
        if a.get_actor_label() not in active:
            a.set_actor_hidden_in_game(True)
            a.set_actor_enable_collision(False)
            a.set_editor_property('is_editor_only_actor',True)
    for a in museum_actors()+gate_actors:
        p=a.get_package()
        if p.get_name()==MAP:
            raise RuntimeError('Expected external actor package; refusing to save the shared map')
        if p not in packages:
            packages.append(p)
    if not unreal.EditorLoadingAndSavingUtils.save_packages(packages,False):
        raise RuntimeError('Museum actor package save failed')
    after=[]
    for p in packages:
        src=file_for_package(p)
        if not src.is_file():
            raise RuntimeError('Missing saved museum actor '+str(src))
        dst=backup/'after'/src.relative_to(CONTENT)
        dst.parent.mkdir(parents=True,exist_ok=True);shutil.copy2(src,dst)
        after.append({'path':str(src.relative_to(CONTENT)).replace('\\','/'),'sha256':hashlib.sha256(src.read_bytes()).hexdigest()})
    for src in sorted((CONTENT/'Thanet/Manston').rglob('*')):
        if src.is_file():
            dst=backup/'after'/src.relative_to(CONTENT)
            dst.parent.mkdir(parents=True,exist_ok=True);shutil.copy2(src,dst)
    for filename in ('museum_manifest.json','museum_walks.streetscape.json','museum_gates.streetscape.json','gate_schedule.json'):
        if (IMPL/filename).exists():
            shutil.copy2(IMPL/filename,backup/filename)
    report.update({'saved_actor_packages':after,'museum_actors':len(museum_actors()),'checkpoint':str(backup),
        'adapted_fence_actors':len(gate_ids),
        'routes_imported':count,'rest_stops':sum(f['kind']=='bench' for f in manifest['furniture']),
        'interpretation_boards':sum(f['kind']=='sign' for f in manifest['furniture'])})
    save_json(backup/'after.json',report)
    return report


def verify(manifest,report):
    actors=museum_actors()
    by_label={a.get_actor_label():a for a in actors}
    expected=json.loads((REPORTS/'import_report.json').read_text())
    if len(by_label)!=len(actors) or len(actors)!=expected['museum_actors']:
        raise ValueError('Saved museum actors missing or duplicated')
    samples=json.loads((IMPL/'walk_samples.json').read_text())['routes']
    world=unreal.get_editor_subsystem(unreal.UnrealEditorSubsystem).get_editor_world()
    landscape=unreal.StreetscapeLandscapeImporter.find_landscape()
    routes=[]
    route_actors=[by_label['manston:'+r['id']] for r in samples]
    for r in samples:
        a=by_label['manston:'+r['id']]
        road=a.get_editor_property('road')
        stats=json.loads(unreal.StreetscapeEditorLibrary.actor_stats_json('manston:'+r['id']))
        xyz=r['local_xyz_m']
        missing=[];buried=[];obstacles=[];checks=0;max_error=0.
        # Probe the centre and both usable edges against THIS road component,
        # so ordinary terrain cannot masquerade as a surviving museum walkway.
        for i in range(1,len(xyz)-1,4):
            p=xyz[i];before=xyz[max(0,i-2)];after=xyz[min(i+2,len(xyz)-1)]
            dx,dy=after[0]-before[0],after[1]-before[1]
            length=math.hypot(dx,dy)
            if length<.001:
                continue
            for side in (-1.25,0,1.25):
                x,y=p[0]-side*dy/length,p[1]+side*dx/length
                hit=road.line_trace_component(vector(x,y,p[2]+2),vector(x,y,p[2]-2),True,False,False)
                checks+=1
                if hit is None:
                    missing.append([i,side,x,y]);continue
                hit_z=hit[0].z/100
                ground=unreal.StreetscapeLandscapeImporter.probe_height_m(landscape,x,y,False)
                if math.isfinite(ground) and hit_z < ground-.02:
                    buried.append({'sample':i,'side':side,'depth_m':ground-hit_z})
                if side==0:
                    max_error=max(max_error,abs(hit_z-p[2]))
        # Raised body sweep represents the 34 cm radius / 88 cm half-height
        # explorer capsule, with its 45 cm step allowance. This checks obstacles,
        # not the full CharacterMovement simulation, which still needs PIE.
        for i in range(0,len(xyz)-1,4):
            p,q=xyz[i],xyz[min(i+4,len(xyz)-1)]
            hit=unreal.SystemLibrary.capsule_trace_single_by_profile(world,
                vector(p[0],p[1],p[2]+1.33),vector(q[0],q[1],q[2]+1.33),34.,88.,
                'Pawn',True,route_actors,unreal.DrawDebugTrace.NONE,True)
            if hit is not None:
                values=hit.to_tuple()
                actor_hit=values[9]
                obstacles.append({'sample':i,'actor':actor_hit.get_actor_label() if actor_hit else str(values),
                    'xyz_m':p})
        routes.append({'id':r['id'],'road_triangles':stats['buffers']['road']['tris'],
            'collision_samples':checks,'missing_surface_hits':missing,'buried_samples':buried,
            'capsule_obstacles':obstacles,'max_native_centre_height_error_m':max_error,
            'material':road.get_material(0).get_path_name() if road.get_material(0) else None})
    report.update({'saved_actor_count':len(actors),'routes':routes,
        'full_character_walk_test':'pending; line and capsule traces are not a PIE movement test'})
    save_json(REPORTS/'verification_report.json',report)
    # Capture the reopened world, including signs and existing museum massing.
    spec=importlib.util.spec_from_file_location('manston_capture',str(PROJECT/'Tools/ue/05_screenshot.py'))
    ss=importlib.util.module_from_spec(spec);spec.loader.exec_module(ss)
    ss.apply_cvars('landscape.OverrideLOD=0')
    rt=ss.make_render_target(world,1600,1000)
    photos=[]
    welcome=next(f for f in manifest['furniture'] if f['id']=='welcome')
    fx,fy=math.cos(math.radians(welcome['heading_deg'])),math.sin(math.radians(welcome['heading_deg']))
    cameras=[('arrival',welcome['bng'][0]-627680+9*fx,welcome['bng'][1]-163080+9*fy,
        welcome['surface_z_odn_m']+1.8,180-welcome['heading_deg'],-2.,65.),
        ('museum_overview',5650.,3390.,210.,-30.,-64.,70.)]
    for name,x,y,z,yaw,pitch,fov in cameras:
        camera={'eye_ue':[100*x,-100*y,100*z],'roll':0.,'pitch':pitch,'yaw':yaw,'fov_deg':fov}
        path=REPORTS/(name+'.png')
        if not ss.capture(world,camera,rt,str(path),'final_ldr',0.,0.):
            raise RuntimeError('Capture failed '+name)
        size,distinct,lum=ss.force_opaque(str(path))
        photos.append({'path':str(path),'bytes':size,'distinct_rgb':distinct,'mean_luminance':lum})
        if distinct<12 or not 6<lum<250:
            raise RuntimeError('Empty or overexposed museum capture')
    report['captures']=photos
    report['pass']=all(not r['missing_surface_hits'] and not r['buried_samples'] and not r['capsule_obstacles']
        and r['max_native_centre_height_error_m']<.03 for r in routes)
    save_json(REPORTS/'verification_report.json',report)
    return report


def save_json(path,data):
    path.parent.mkdir(parents=True,exist_ok=True)
    temp=path.with_suffix(path.suffix+'.tmp')
    temp.write_text(json.dumps(data,indent=2,allow_nan=False),encoding='utf-8')
    temp.replace(path)


def main():
    opts=uc.parse_args(sys.argv,flags=('inspect','apply','verify','export_gates'))
    if sum(bool(v) for v in opts.values()) != 1:
        raise ValueError('Choose exactly one of --inspect, --apply, --verify')
    if not unreal.get_editor_subsystem(unreal.LevelEditorSubsystem).load_level(MAP):
        raise RuntimeError('Could not load Thanet')
    hf=uc.heightfield()
    if hf is None:
        raise RuntimeError('No registered terrain')
    report={'map':MAP,'terrain':hf.describe_source(),'landscape_dir':str(hf.get_editor_property('landscape_dir')),
        'gateway_height_odn_m':hf.probe_m(633315-627680,166510-163080)}
    if opts['inspect']:
        if (IMPL/'walk_samples.json').exists():
            unreal.StreetscapeEditorLibrary.load_region(unreal.Vector(560000,-310000,0),85000.)
            landscape=unreal.StreetscapeLandscapeImporter.find_landscape()
            checks=[]
            for route in json.loads((IMPL/'walk_samples.json').read_text())['routes']:
                points=route['local_xyz_m']
                for x,y,z in points[::max(1,len(points)//24)]:
                    actual=unreal.StreetscapeLandscapeImporter.probe_height_m(landscape,x,y,False)
                    checks.append({'x':x,'y':y,'landscape_z':actual,'survey_z':hf.probe_m(x,y),'planned_walk_z':z})
            report['terrain_checks']=checks
        save_json(REPORTS/'inspection.json',report)
        uc.report(NAME,report)
        return
    manifest=json.loads((IMPL/'museum_manifest.json').read_text())
    unreal.StreetscapeEditorLibrary.load_region(unreal.Vector(560000,-310000,0),85000.)
    if opts['export_gates']:
        export_barriers()
        return
    if opts['apply']:
        state=json.loads((IMPL/'build_state.json').read_text())
        if state.get('state')!='ready' or any(hashlib.sha256((IMPL/n).read_bytes()).hexdigest()!=h for n,h in state['sha256'].items()):
            raise RuntimeError('Incomplete or changed museum generation; rebuild before importing')
        gates=json.loads((IMPL/'gate_schedule.json').read_text())
        if gates['walk_samples_sha256']!=state['sha256']['walk_samples.json'] or gates['gate_document_sha256']!=hashlib.sha256((IMPL/'museum_gates.streetscape.json').read_bytes()).hexdigest():
            raise RuntimeError('Gate schedule does not match the current walks; rebuild gates')
        from content_guard import snapshot,differences
        before=snapshot(CONTENT)
        report=apply(manifest,report)
        changes=differences(before,snapshot(CONTENT))
        allowed={row['path'] for row in report['saved_actor_packages']}
        unexpected={kind:[p for p in paths if p not in allowed and not p.startswith('Thanet/Manston/')]
            for kind,paths in changes.items()}
        report['content_changes']=changes
        report['unexpected_content_changes']=unexpected
        save_json(REPORTS/'import_report.json',report)
        if any(unexpected.values()):
            raise RuntimeError('Unexpected Content mutation; see saved import report')
        uc.report(NAME,{k:v for k,v in report.items() if k!='saved_actor_packages'})
    else:
        from content_guard import snapshot,require_unchanged
        before=snapshot(CONTENT)
        report=verify(manifest,report)
        report['content_guard']=require_unchanged(before,snapshot(CONTENT))
        save_json(REPORTS/'verification_report.json',report)
        uc.report(NAME,{'pass':report['pass'],'saved_actor_count':report['saved_actor_count'],
            'routes':[{k:(len(v) if isinstance(v,list) else v) for k,v in r.items()} for r in report['routes']],
            'captures':report['captures'],'content_guard':report['content_guard']})


if __name__=='__main__':
    main()
