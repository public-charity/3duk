"""Render the actual Unreal pawn in a disposable preview world (no map saved)."""
import importlib
import math
from pathlib import Path
import unreal
import ue_common as uc

shots = importlib.import_module('05_screenshot')
world = unreal.EditorLoadingAndSavingUtils.new_blank_map(False)
actors = unreal.get_editor_subsystem(unreal.EditorActorSubsystem)
car = actors.spawn_actor_from_class(unreal.ThanetPoliceCar, unreal.Vector(0,0,60))
car.chassis.set_simulate_physics(False)
floor = actors.spawn_actor_from_class(unreal.StaticMeshActor, unreal.Vector(0,0,-10))
floor.static_mesh_component.set_static_mesh(unreal.load_asset('/Engine/BasicShapes/Cube'))
floor.set_actor_scale3d(unreal.Vector(200,200,.2))
sun = actors.spawn_actor_from_class(unreal.DirectionalLight, unreal.Vector(0,0,600), unreal.Rotator(0,-40,-35))
sun.light_component.set_editor_property('intensity',6.0)
fill = actors.spawn_actor_from_class(unreal.DirectionalLight, unreal.Vector(0,0,600), unreal.Rotator(0,-30,140))
fill.light_component.set_editor_property('intensity',4.0)
out = Path(uc.project_dir()).parents[1]/'assets'/'KentPoliceV90'
rt = shots.make_render_target(world,1400,900)
unreal.StreetscapeEditorLibrary.finish_shader_compilation()
unreal.StreetscapeEditorLibrary.finish_render_asset_compilation()
report={}
for name, eye in [('unreal_front',(730,-950,210)),('unreal_rear',(-700,950,200))]:
    direction=unreal.Vector(-eye[0],-eye[1],78-eye[2])
    rotation=unreal.MathLibrary.conv_vector_to_rotator(direction)
    cam={'eye_ue':eye,'roll':0,'pitch':rotation.pitch,'yaw':rotation.yaw,'fov_deg':34}
    path=str(out/(name+'.png'))
    assert shots.capture(world,cam,rt,path,'final_ldr',2,0,prepare_heightmaps=False)
    size,distinct,lum=shots.force_opaque(path)
    assert distinct>100 and lum>1, (distinct,lum)
    report[name]={'bytes':size,'distinct':distinct,'luminance':lum}
uc.report('11_render_police_car',report)
