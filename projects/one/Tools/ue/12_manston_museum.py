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


def apply(manifest,report):
    eas=unreal.get_editor_subsystem(unreal.EditorActorSubsystem)
    lib=unreal.StreetscapeEditorLibrary
    actors=museum_actors()
    by_label={a.get_actor_label():a for a in actors}
    if len(by_label)!=len(actors):
        raise ValueError('Duplicate museum actors: recover before applying')
    stamp=datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')
    backup=REPORTS/'checkpoints'/stamp
    # Save recovery bytes before any mutation. New actor creation is recorded too.
    saved=[]
    for a in actors:
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
    count=lib.import_streetscape_json(str(IMPL/'museum_walks.streetscape.json'),False,False,0)
    if count != 2:
        raise RuntimeError('Expected two museum walk actors, got '+str(count))
    for a in museum_actors():
        a.tags=[TAG]
        by_label[a.get_actor_label()]=a
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
        c.set_text(value)
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
    for a in museum_actors():
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
    report.update({'saved_actor_packages':after,'museum_actors':len(museum_actors()),'checkpoint':str(backup),
        'routes_imported':count,'rest_stops':sum(f['kind']=='bench' for f in manifest['furniture']),
        'interpretation_boards':sum(f['kind']=='sign' for f in manifest['furniture'])})
    save_json(backup/'after.json',report)
    return report


def save_json(path,data):
    path.parent.mkdir(parents=True,exist_ok=True)
    temp=path.with_suffix(path.suffix+'.tmp')
    temp.write_text(json.dumps(data,indent=2,allow_nan=False),encoding='utf-8')
    temp.replace(path)


def main():
    opts=uc.parse_args(sys.argv,flags=('inspect','apply','verify'))
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
    if opts['apply']:
        report=apply(manifest,report)
        save_json(REPORTS/'import_report.json',report)
        uc.report(NAME,{k:v for k,v in report.items() if k!='saved_actor_packages'})
    else:
        raise RuntimeError('Verification implementation pending; do not treat import as validation')


if __name__=='__main__':
    main()
