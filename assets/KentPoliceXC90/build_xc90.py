"""Procedural XC90-inspired Kent Police asset. Blender 5.2, headless, no add-ons.

Metres, +X nose, +Y left in Blender (FBX converts to Unreal). Geometry/materials
are authored here; reference photos are not copied into the asset.
"""
import bpy
import math
import json
from pathlib import Path
from mathutils import Vector

OUT = Path(__file__).resolve().parent
bpy.ops.object.select_all(action='SELECT')
bpy.ops.object.delete(use_global=False)
bpy.context.scene.unit_settings.system = 'METRIC'

def material(name, color, metallic=0, roughness=.35, emission=0):
    m = bpy.data.materials.new(name)
    m.diffuse_color = (*color, 1)
    m.use_nodes = True
    p = m.node_tree.nodes.get('Principled BSDF')
    p.inputs['Base Color'].default_value = (*color, 1)
    p.inputs['Metallic'].default_value = metallic
    p.inputs['Roughness'].default_value = roughness
    p.inputs['Emission Color'].default_value = (*color, 1)
    p.inputs['Emission Strength'].default_value = emission
    return m

white = material('PearlWhite', (.82,.86,.88), .45)
yellow = material('ReflectiveYellow', (.83,.98,.008), .1)
blue = material('PoliceBlue', (.012,.10,.48), .25)
black = material('Rubber', (.016,.021,.027), 0, .8)
glass = material('TintedGlass', (.027,.065,.092), .55, .16)
silver = material('Alloy', (.48,.53,.57), .85, .23)
red = material('TailRed', (.65,.012,.016), .2, .25, .3)
lamp = material('Headlamp', (.75,.91,1), .2, .17, 2)
led = material('BlueLens', (.015,.15,.95), .35, .2, .8)
body_parts=[]

def cube(name, pos, size, mat, bevel=.025):
    bpy.ops.mesh.primitive_cube_add(size=1, location=pos)
    o=bpy.context.object; o.name=name; o.dimensions=size
    bpy.ops.object.transform_apply(location=False, rotation=False, scale=True)
    o.data.materials.append(mat)
    if bevel:
        m=o.modifiers.new('Soft stamped edges','BEVEL');m.width=bevel;m.segments=3
        bpy.context.view_layer.objects.active=o;bpy.ops.object.modifier_apply(modifier=m.name)
        o.modifiers.new('Weighted normals','WEIGHTED_NORMAL')
    body_parts.append(o)
    return o

def mesh(name, verts, faces, mat):
    d=bpy.data.meshes.new(name);d.from_pydata(verts,[],faces);d.update()
    o=bpy.data.objects.new(name,d);bpy.context.collection.objects.link(o)
    o.data.materials.append(mat);body_parts.append(o);return o

def panel(name, verts, mat): return mesh(name,verts,[tuple(range(len(verts)))],mat)

def text(name, value, pos, size, rotation, mat):
    bpy.ops.object.text_add(location=pos, rotation=rotation)
    o=bpy.context.object;o.name=name;o.data.body=value;o.data.align_x='CENTER';o.data.size=size;o.data.extrude=.0008
    o.data.materials.append(mat);bpy.ops.object.convert(target='MESH');body_parts.append(bpy.context.object)

# Longitudinal section loft: rounded shoulders, tapered nose and tail.
sections=[(-2.477,.82,.44,1.03),(-2.23,.95,.42,1.12),(-1.65,.985,.43,1.16),
          (.75,.975,.43,1.13),(1.55,.95,.46,1.08),(2.23,.90,.44,.99),(2.477,.81,.46,.88)]
verts=[]
for x,w,b,t in sections:
    verts += [(x,-w*.91,b),(x,-w,b+.12),(x,-w,t-.12),(x,-w*.91,t),
              (x,w*.91,t),(x,w,t-.12),(x,w,b+.12),(x,w*.91,b)]
faces=[tuple(reversed(range(8)))]
for i in range(len(sections)-1):
    for j in range(8): faces.append((i*8+j,i*8+(j+1)%8,(i+1)*8+(j+1)%8,(i+1)*8+j))
faces.append(tuple(range(len(verts)-8,len(verts))))
hull=mesh('Coachwork',verts,faces,white)
# Actual wheel openings, not painted circles.
for x in (-1.492,1.492):
    for y in (-.88,.88):
        bpy.ops.mesh.primitive_cylinder_add(vertices=48,radius=.445,depth=.65,location=(x,y,.38),rotation=(math.pi/2,0,0))
        cutter=bpy.context.object
        bpy.context.view_layer.objects.active=hull
        mod=hull.modifiers.new('Wheel opening','BOOLEAN');mod.operation='DIFFERENCE';mod.object=cutter
        bpy.ops.object.modifier_apply(modifier=mod.name);bpy.data.objects.remove(cutter,do_unlink=True)

mesh('Cabin', [(-2.40,-.85,1.06),(.93,-.90,1.10),(.25,-.76,1.75),(-1.97,-.77,1.75),
               (-2.40,.85,1.06),(.93,.90,1.10),(.25,.76,1.75),(-1.97,.77,1.75)],
     [(0,1,2,3),(4,7,6,5),(1,5,6,2),(0,3,7,4),(3,2,6,7)], white)
panel('Windscreen',[(.946,-.84,1.15),(.946,.84,1.15),(.29,.72,1.70),(.29,-.72,1.70)],glass)
panel('RearGlass',[(-2.318,.79,1.20),(-2.318,-.79,1.20),(-2.007,-.71,1.70),(-2.007,.71,1.70)],glass)
for side in (-1,1):
    def window(name, coords):
        return panel(name,[(x,side*(.91-(z-1.1)*.215),z) for x,z in coords],glass)
    window('Front door glass',[(.83,1.16),(.22,1.69),(-.43,1.69),(-.43,1.16)])
    window('Rear door glass',[(-.51,1.16),(-.51,1.69),(-1.32,1.69),(-1.32,1.16)])
    window('Quarter glass',[(-1.40,1.16),(-1.40,1.69),(-1.73,1.69),(-2.02,1.16)])
    cube('Sill',(-.05,side*.951,.44),(2.05,.045,.09),silver)
    cube('Mirror',(.60,side*1.005,1.25),(.28,.19,.16),white,.055)
    cube('Roof rail',(-.76,side*.68,1.80),(1.94,.035,.035),silver,.012)
    for x in (-.25,-1.19): cube('Door handle',(x,side*.978,1.06),(.19,.024,.043),silver,.015)
    # Battenburg rows on door skins, plus end panels clear of wheel openings.
    for i in range(4):
        x=-.78+i*.50
        for row,z in enumerate((.69,.94)):
            cube('Battenburg',(x,side*.985,z),(.495,.009,.235),yellow if (i+row)%2==0 else blue,.002)
    # End markings follow the narrowing flank rather than hovering off the skin.
    for x,w in [(-2.22,.951),(2.18,.906)]:
        panel('End livery',[(x-.10,side*w,.80),(x+.10,side*w,.80),(x+.10,side*w,.91),(x-.10,side*w,.91)],yellow)
    # Side text reads correctly from either side.
    text('Force identity','Kent\nPolice',(-.24,side*.997,.85),.095,(math.pi/2,0,0 if side<0 else math.pi),black)
    cube('Headlight',(2.28,side*.64,.93),(.19,.43,.095),glass,.024)
    cube('Thor hammer',(2.385,side*.64,.945),(.012,.39,.023),lamp,.005)
    cube('LED stem',(2.388,side*.64,.916),(.013,.026,.06),lamp,.003)
    panel('Tail upright',[(-2.41,side*.84,1.08),(-2.41,side*.78,1.08),(-2.02,side*.72,1.70),(-2.02,side*.78,1.70)],red)
    cube('Tail lower',(-2.43,side*.64,1.02),(.023,.40,.10),red,.018)

bonnet_sections=[(1.10,.80,1.111),(1.55,.81,1.083),(2.23,.77,.993),(2.36,.73,.935)]
for (x0,w0,z0),(x1,w1,z1) in zip(bonnet_sections,bonnet_sections[1:]):
    panel('Yellow bonnet',[(x0,-w0,z0),(x1,-w1,z1),(x1,w1,z1),(x0,w0,z0)],yellow)
text('Bonnet police','POLICE',(1.87,0,1.046),.26,(.132,0,math.pi/2),blue)
cube('Grille surround',(2.473,0,.76),(.04,1.02,.36),silver,.06)
cube('Grille',(2.501,0,.76),(.014,.94,.30),black,.04)
for y in range(-8,9): cube('Grille slat',(2.515,y*.05,.76),(.015,.012,.26),silver,.003)
bpy.ops.mesh.primitive_torus_add(major_radius=.092,minor_radius=.01,major_segments=32,minor_segments=8,location=(2.536,0,.77),rotation=(0,math.pi/2,0))
bpy.context.object.data.materials.append(silver);body_parts.append(bpy.context.object)
badge=cube('Grille diagonal',(2.535,0,.77),(.02,.58,.015),silver,.003);badge.rotation_euler.x=.42
cube('Badge centre',(2.551,0,.77),(.015,.14,.043),blue,.003)
cube('Lower intake',(2.46,0,.46),(.036,1.39,.11),black)
cube('Front plate',(2.535,0,.545),(.014,.52,.11),white,.005)
text('Front plate letters','GN74 ADV',(2.545,0,.515),.074,(math.pi/2,0,math.pi/2),black)
cube('Rear plate',(-2.49,0,.72),(.018,.52,.11),yellow,.005)
text('Rear plate letters','GN74 ADV',(-2.505,0,.69),.074,(math.pi/2,0,-math.pi/2),black)
cube('Rear chevron field',(-2.483,0,.93),(.014,1.59,.24),yellow,.001)
for side in (-1,1):
    for i in range(4):
        y0=side*(i*.20); y1=side*((i+1)*.20)
        panel('Rear red chevron',[(-2.496,y0,.82),(-2.496,y1,.92),(-2.496,y1,1.01),(-2.496,y0,.91)],red)
text('Rear police','POLICE',(-2.433,0,1.045),.12,(math.pi/2,0,-math.pi/2),blue)
cube('Lightbar base',(-.10,0,1.82),(.28,1.30,.055),black)
cube('Lightbar centre',(-.10,0,1.89),(.24,.50,.095),silver)
for side in (-1,1):
    cube('Blue emergency lens',(-.10,side*.46,1.89),(.24,.41,.095),led,.025)
    cube('Grille blue light',(2.53,side*.32,.77),(.02,.08,.045),led,.006)
# Right-hand-drive interior silhouette, visible through the opaque tinted glazing only at openings.
cube('Dashboard',(.45,0,1.08),(.27,1.45,.14),black)

def export(objects, name):
    bpy.ops.object.select_all(action='DESELECT')
    for o in objects: o.select_set(True)
    bpy.context.view_layer.objects.active=objects[0]
    bpy.ops.object.convert(target='MESH')
    bpy.ops.object.join()
    o=bpy.context.object;o.name=name
    bpy.context.scene.cursor.location=(0,0,0);bpy.ops.object.origin_set(type='ORIGIN_CURSOR')
    bpy.ops.export_scene.fbx(filepath=str(OUT/(name+'.fbx')),use_selection=True,object_types={'MESH'},
         axis_forward='X',axis_up='Z',apply_unit_scale=True, bake_space_transform=True, mesh_smooth_type='FACE')
    return o

body=export(body_parts,'SM_KentPoliceXC90_Body')
body_parts=[]
# A single centred wheel is instanced four times in the runtime pawn.
bpy.ops.mesh.primitive_cylinder_add(vertices=48,radius=.38,depth=.245,rotation=(math.pi/2,0,0))
o=bpy.context.object;o.data.materials.append(black);body_parts.append(o)
for side in (-1,1):
    bpy.ops.mesh.primitive_cylinder_add(vertices=40,radius=.265,depth=.012,location=(0,side*.127,0),rotation=(math.pi/2,0,0))
    o=bpy.context.object;o.data.materials.append(silver);body_parts.append(o)
    bpy.ops.mesh.primitive_cylinder_add(vertices=40,radius=.224,depth=.013,location=(0,side*.135,0),rotation=(math.pi/2,0,0))
    o=bpy.context.object;o.data.materials.append(black);body_parts.append(o)
    for i in range(5):
        a=i*math.tau/5
        spoke=cube('Alloy spoke',(.13*math.sin(a),side*.146,.13*math.cos(a)),(.062,.025,.25),silver,.01)
        spoke.rotation_euler.y=a
    cube('Hub',(0,side*.16,0),(.11,.025,.11),silver,.04)
wheel=export(body_parts,'SM_KentPoliceXC90_Wheel')
wheel.hide_render=True
for x in (-1.492,1.492):
    for y in (-.84,.84):
        o=wheel.copy();o.data=wheel.data;bpy.context.collection.objects.link(o);o.location=(x,y,.38);o.hide_render=False

scene=bpy.context.scene
scene.view_settings.look='AgX - Medium High Contrast'
scene.render.engine='CYCLES';scene.cycles.samples=32
scene.render.resolution_x=1400;scene.render.resolution_y=900;scene.render.resolution_percentage=100
scene.world.color=(.22,.22,.22)
floor=cube('Studio ground',(0,0,-.065),(200,200,.10),material('Studio',(.075,.09,.115),0,.85),0)
for pos,power,size in [((3,-4,7),1800,5),((-3,2,5),2200,4),((1,5,3),1300,3)]:
    bpy.ops.object.light_add(type='AREA',location=pos);o=bpy.context.object;o.data.energy=power;o.data.shape='DISK';o.data.size=size
    o.rotation_euler=(Vector((0,0,.8))-o.location).to_track_quat('-Z','Y').to_euler()
bpy.ops.object.camera_add(location=(7.7,-7.4,4.5));cam=bpy.context.object
cam.rotation_euler=(Vector((0,0,.9))-cam.location).to_track_quat('-Z','Y').to_euler();cam.data.lens=53;scene.camera=cam
bpy.ops.wm.save_as_mainfile(filepath=str(OUT/'KentPoliceXC90.blend'))
for name,pos in [('front',(7.7,-7.4,4.5)),('rear',(-7.7,7.4,3.8))]:
    cam.location=pos;cam.rotation_euler=(Vector((0,0,.9))-cam.location).to_track_quat('-Z','Y').to_euler()
    scene.render.filepath=str(OUT/(name+'.png'));bpy.ops.render.render(write_still=True)
(OUT/'build_manifest.json').write_text(json.dumps({'body_vertices':len(body.data.vertices),'wheel_vertices':len(wheel.data.vertices),
    'length_m':4.953,'wheelbase_m':2.984,'wheel_radius_m':.38,'source':'build_xc90.py','forward':'+X'},indent=2))
print('KENT_CAR_BUILD_OK')
