"""Import the smooth V90 and explicitly wire its UV paint / surface textures."""
from pathlib import Path
import json
import unreal
import ue_common as uc

source=Path(uc.project_dir()).parents[1]/'assets'/'KentPoliceV90'
dest='/Game/Thanet/Vehicles/KentPoliceV90'
tools=unreal.AssetToolsHelpers.get_asset_tools()
mel=unreal.MaterialEditingLibrary
report={}


def save(asset):
    if not unreal.EditorAssetLibrary.save_loaded_asset(asset,only_if_is_dirty=False):
        raise RuntimeError('Could not save '+asset.get_path_name())


textures={}
for name in ('T_V90_BaseColor','T_V90_Surface'):
    task=unreal.AssetImportTask()
    task.filename=str(source/(name+'.png')); task.destination_path=dest
    task.destination_name=name; task.automated=True; task.replace_existing=True; task.save=True
    tools.import_asset_tasks([task])
    texture=unreal.load_asset(dest+'/'+name)
    if not isinstance(texture,unreal.Texture2D): raise RuntimeError('Missing texture '+name)
    texture.set_editor_property('srgb',name.endswith('BaseColor'))
    if name.endswith('Surface'):
        texture.set_editor_property('compression_settings',unreal.TextureCompressionSettings.TC_MASKS)
    save(texture); textures[name]=texture


def new_material(name):
    mat=unreal.load_asset(dest+'/'+name)
    if not mat:
        mat=tools.create_asset(name,dest,unreal.Material,unreal.MaterialFactoryNew())
    if not isinstance(mat,unreal.Material): raise RuntimeError('Unexpected material type: '+name)
    mel.delete_all_material_expressions(mat)
    mat.set_editor_property('two_sided',False)
    return mat


def scalar(mat,value,prop):
    node=mel.create_material_expression(mat,unreal.MaterialExpressionConstant)
    node.set_editor_property('r',value)
    mel.connect_material_property(node,'',prop)


atlas=new_material('M_V90_Runtime_Atlas')
color=mel.create_material_expression(atlas,unreal.MaterialExpressionTextureSample,-550,0)
color.set_editor_property('texture',textures['T_V90_BaseColor'])
mel.connect_material_property(color,'RGB',unreal.MaterialProperty.MP_BASE_COLOR)
packed=mel.create_material_expression(atlas,unreal.MaterialExpressionTextureSample,-550,250)
packed.set_editor_property('texture',textures['T_V90_Surface'])
packed.set_editor_property('sampler_type',unreal.MaterialSamplerType.SAMPLERTYPE_MASKS)
mel.connect_material_property(packed,'R',unreal.MaterialProperty.MP_ROUGHNESS)
mel.connect_material_property(packed,'G',unreal.MaterialProperty.MP_METALLIC)
emit=mel.create_material_expression(atlas,unreal.MaterialExpressionMultiply,-250,400)
mel.connect_material_expressions(color,'RGB',emit,'A')
mel.connect_material_expressions(packed,'B',emit,'B')
mel.connect_material_property(emit,'',unreal.MaterialProperty.MP_EMISSIVE_COLOR)
mel.recompile_material(atlas); save(atlas)
materials={'M_V90_Atlas':atlas}

# These are the same linear colors and surface values as the Blender source.
for suffix,rgb,metal,rough,emission in [
    ('Pearl',(.70,.76,.79),.12,.36,0),('Rubber',(.013,.020,.026),0,.60,0),
    ('Trim',(.023,.038,.049),.10,.40,0),('Alloy',(.32,.41,.46),.62,.31,0),
    ('BlueLens',(.025,.19,.55),.20,.21,.3)]:
    mat=new_material('M_V90_Runtime_'+suffix)
    color=mel.create_material_expression(mat,unreal.MaterialExpressionConstant3Vector)
    color.set_editor_property('constant',unreal.LinearColor(*rgb,1))
    mel.connect_material_property(color,'',unreal.MaterialProperty.MP_BASE_COLOR)
    scalar(mat,metal,unreal.MaterialProperty.MP_METALLIC)
    scalar(mat,rough,unreal.MaterialProperty.MP_ROUGHNESS)
    if emission:
        glow=mel.create_material_expression(mat,unreal.MaterialExpressionConstant3Vector)
        glow.set_editor_property('constant',unreal.LinearColor(*(c*emission for c in rgb),1))
        mel.connect_material_property(glow,'',unreal.MaterialProperty.MP_EMISSIVE_COLOR)
    mel.recompile_material(mat); save(mat); materials['M_V90_'+suffix]=mat

for name in ('SM_KentPoliceV90_Body','SM_KentPoliceV90_Wheel'):
    task=unreal.AssetImportTask()
    task.filename=str(source/(name+'.fbx')); task.destination_path=dest; task.destination_name=name
    task.automated=True; task.replace_existing=True; task.save=True
    opts=unreal.FbxImportUI()
    opts.import_mesh=True; opts.import_as_skeletal=False; opts.import_materials=False; opts.import_textures=False
    opts.automated_import_should_detect_type=False; opts.mesh_type_to_import=unreal.FBXImportType.FBXIT_STATIC_MESH
    opts.static_mesh_import_data.combine_meshes=True; opts.static_mesh_import_data.auto_generate_collision=False
    opts.static_mesh_import_data.convert_scene=True; opts.static_mesh_import_data.convert_scene_unit=True
    opts.static_mesh_import_data.normal_import_method=unreal.FBXNormalImportMethod.FBXNIM_IMPORT_NORMALS_AND_TANGENTS
    task.options=opts; tools.import_asset_tasks([task])
    mesh=unreal.load_asset(dest+'/'+name)
    if not isinstance(mesh,unreal.StaticMesh): raise RuntimeError('Mesh import failed: '+name)
    assigned=[]
    slots=list(mesh.static_materials)
    for index,slot in enumerate(slots):
        slot_name=str(slot.material_slot_name)
        key=next((key for key in materials if key in slot_name),None)
        if key:
            slot.material_interface=materials[key]; slots[index]=slot; assigned.append(key)
    expected={'M_V90_Atlas','M_V90_Pearl','M_V90_Trim','M_V90_Alloy','M_V90_BlueLens'} if name.endswith('Body') else {'M_V90_Rubber','M_V90_Trim','M_V90_Alloy'}
    if not expected.issubset(set(assigned)):
        raise RuntimeError('Missing material assignment: '+str((name,assigned,[str(s.material_slot_name) for s in mesh.static_materials])))
    mesh.set_editor_property('static_materials',slots)
    bounds=mesh.get_bounding_box(); size=bounds.max-bounds.min
    report[name]={'size_cm':[size.x,size.y,size.z],'materials':assigned}
    if name.endswith('Body') and not 490<size.x<520: raise RuntimeError('Wrong body scale '+str(size))
    if name.endswith('Wheel') and not 66<size.x<69: raise RuntimeError('Wrong wheel scale '+str(size))
    save(mesh)
report['textures']={name:tex.get_path_name() for name,tex in textures.items()}
report['surface_channels']={'R':'roughness','G':'metalness','B':'emission weight','sRGB':False}
(source/'import_report.json').write_text(json.dumps(report,indent=2))
uc.report('10_import_police_car',report)
