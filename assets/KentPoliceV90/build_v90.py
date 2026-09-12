"""Smooth stylised V90 estate. Run make_atlas.py before headless Blender.

One symmetric subdivision shell carries UV-mapped paint, glazing and lamps.
Wheel openings are quad topology, not Boolean cuts. Metres, +X forward, +Z up.
"""
import bpy
import json
import math
import sys
from pathlib import Path
from mathutils import Vector, kdtree

OUT=Path(__file__).resolve().parent
bpy.ops.object.select_all(action='SELECT'); bpy.ops.object.delete(use_global=False)
scene=bpy.context.scene; scene.unit_settings.system='METRIC'
parts=[]

def material(name,color,metal=0,rough=.4,emission=0):
    m=bpy.data.materials.new(name); m.diffuse_color=(*color,1)
    p=m.node_tree.nodes.get('Principled BSDF')
    p.inputs['Base Color'].default_value=(*color,1)
    p.inputs['Roughness'].default_value=rough; p.inputs['Metallic'].default_value=metal
    p.inputs['Emission Color'].default_value=(*color,1); p.inputs['Emission Strength'].default_value=emission
    return m

paint=material('M_V90_Atlas',(.70,.76,.79),.12,.37)
nodes=paint.node_tree.nodes; links=paint.node_tree.links; p=nodes.get('Principled BSDF')
for filename,name in [('T_V90_BaseColor.png','BaseColor'),('T_V90_Surface.png','Surface')]:
    image=bpy.data.images.load(str(OUT/filename))
    if name=='Surface': image.colorspace_settings.name='Non-Color'
    node=nodes.new('ShaderNodeTexImage'); node.image=image; node.label=name
    node.interpolation='Linear'; node.extension='EXTEND'
    if name=='BaseColor':
        links.new(node.outputs['Color'],p.inputs['Base Color'])
        links.new(node.outputs['Color'],p.inputs['Emission Color'])
    else:
        split=nodes.new('ShaderNodeSeparateColor'); links.new(node.outputs['Color'],split.inputs['Color'])
        links.new(split.outputs['Red'],p.inputs['Roughness'])
        links.new(split.outputs['Green'],p.inputs['Metallic'])
        links.new(split.outputs['Blue'],p.inputs['Emission Strength'])
p.inputs['Coat Weight'].default_value=.20; p.inputs['Coat Roughness'].default_value=.28
white=material('M_V90_Pearl',(.70,.76,.79),.12,.36)
black=material('M_V90_Rubber',(.013,.020,.026),0,.60)
trim=material('M_V90_Trim',(.023,.038,.049),.10,.40)
alloy=material('M_V90_Alloy',(.32,.41,.46),.62,.31)
blue=material('M_V90_BlueLens',(.025,.19,.55),.20,.21,.3)

def mesh(name,vertices,faces,mat,smooth=True):
    data=bpy.data.meshes.new(name); data.from_pydata(vertices,[],faces); data.update()
    o=bpy.data.objects.new(name,data); bpy.context.collection.objects.link(o); data.materials.append(mat)
    for f in data.polygons: f.use_smooth=smooth
    parts.append(o); return o

def apply(o,mod):
    bpy.context.view_layer.objects.active=o; bpy.ops.object.modifier_apply(modifier=mod.name)

def box(name,pos,scale,mat,radius=.025):
    bpy.ops.mesh.primitive_cube_add(size=1,location=pos); o=bpy.context.object; o.name=name; o.dimensions=scale
    bpy.ops.object.transform_apply(location=False,rotation=False,scale=True)
    o.data.materials.append(mat); parts.append(o)
    mod=o.modifiers.new('Soft manufactured edges','BEVEL'); mod.width=radius; mod.segments=3; apply(o,mod)
    for f in o.data.polygons: f.use_smooth=True
    mod=o.modifiers.new('Weighted face normals','WEIGHTED_NORMAL'); mod.keep_sharp=True; apply(o,mod)
    return o

def pchip(x,keys):
    """Shape-preserving cubic interpolation with continuous first derivatives."""
    if x<=keys[0][0]: return keys[0][1]
    if x>=keys[-1][0]: return keys[-1][1]
    h=[b[0]-a[0] for a,b in zip(keys,keys[1:])]
    d=[(b[1]-a[1])/step for a,b,step in zip(keys,keys[1:],h)]; m=[d[0]]
    for i in range(1,len(keys)-1):
        if d[i-1]*d[i]<=0: m.append(0)
        else:
            w1=2*h[i]+h[i-1]; w2=h[i]+2*h[i-1]
            m.append((w1+w2)/(w1/d[i-1]+w2/d[i]))
    m.append(d[-1])
    for i,((a,v),(b,w)) in enumerate(zip(keys,keys[1:])):
        if x<=b:
            t=(x-a)/(b-a)
            return (2*t**3-3*t*t+1)*v+(t**3-2*t*t+t)*h[i]*m[i]+(-2*t**3+3*t*t)*w+(t**3-t*t)*h[i]*m[i+1]

def width(x): return pchip(x,[(-2.36,.884),(-1.5,.949),(-.3,.945),(1.47,.952),(2.36,.895)])
def belt(x): return pchip(x,[(-2.36,.846),(-1.8,.925),(-.3,.941),(.8,.923),(1.65,.891),(2.36,.817)])
def roof(x): return pchip(x,[(-2.36,.897),(-2.22,.984),(-1.76,1.407),(-1.54,1.447),(-.38,1.449),(.015,1.423),(.22,1.328),(.82,.956),(1.0,.944),(2.36,.852)])

def arch(x):
    base=.244
    for axle in (-1.4705,1.4705):
        u=(x-axle)/.392
        if abs(u)<1: base=max(base,.244+.470*math.sqrt(1-u*u))
    return base

def cross_section(x):
    w=width(x); z=belt(x); top=roof(x); a=arch(x)
    half=[(0,.211),(.57*w,.211),(.647*w,.221),(.683*w,a-.016),(.912*w,a-.016),
          (.956*w,a),(.983*w,a+.07*(z-a)),(w,a+.33*(z-a)),(.996*w,a+.72*(z-a)),
          (.978*w,z-.016),(.943*w,z+.010),(.901*w,z+.035),
          (.804*w,z+.035+.78*(top-z-.035)),(.752*w,top-.002),(.572*w,top+.018),(0,top+.027)]
    return half+[(-y,z) for y,z in half[-2:0:-1]]

xs=set(round(-2.36+i*4.72/88,6) for i in range(89))
for axle in (-1.4705,1.4705):
    for side in (-1,1):
        for d in (.392,.390,.382,.370,.35): xs.add(round(axle+side*d,6))
xs=sorted(xs); n=len(cross_section(0)); v=[]
rings=[(-2.485,-2.36,.02),(-2.479,-2.36,.65),(-2.454,-2.36,.88),(-2.400,-2.36,.98)]
rings += [(x,x,1) for x in xs]
rings += [(2.400,2.36,.98),(2.454,2.36,.88),(2.479,2.36,.65),(2.485,2.36,.02)]
for x,sample,scale in rings:
    for y,z in cross_section(sample): v.append((x,y*scale,.53+(z-.53)*scale))
f=[tuple(reversed(range(n)))]
f += [(i*n+j,(i+1)*n+j,(i+1)*n+(j+1)%n,i*n+(j+1)%n) for i in range(len(rings)-1) for j in range(n)]
f += [tuple(range(len(v)-n,len(v)))]
shell=mesh('V90 single continuous symmetric shell',v,f,paint)
# Temporary slot indices are discrete face regions, preserved by subdivision.
# This avoids choosing UV seams from changing face normals on curved corners.
for _ in range(4): shell.data.materials.append(paint)
shell.data.polygons[0].material_index=4
shell.data.polygons[-1].material_index=3
for i in range(len(rings)-1):
    for j in range(n):
        region=4 if i<4 else 3 if i>=len(rings)-5 else 2 if 13<=j<=16 else 1 if j<15 else 0
        shell.data.polygons[1+i*n+j].material_index=region
bpy.context.view_layer.objects.active=shell; shell.select_set(True)
bpy.ops.object.mode_set(mode='EDIT'); bpy.ops.mesh.select_all(action='SELECT')
bpy.ops.mesh.normals_make_consistent(inside=False); bpy.ops.object.mode_set(mode='OBJECT')
sub=shell.modifiers.new('Continuous coachwork curvature','SUBSURF'); sub.levels=1; sub.render_levels=1; apply(shell,sub)

layout=json.loads((OUT/'atlas_layout.json').read_text())
uv=shell.data.uv_layers.new(name='UV0_PaintAtlas')
for face in shell.data.polygons:
    island=['left','right','top','front','rear'][face.material_index]
    rect,domain=layout['islands'][island]
    for loop in face.loop_indices:
        p=shell.data.vertices[shell.data.loops[loop].vertex_index].co
        if island=='left': a,b=p.x,p.z
        elif island=='right': a,b=-p.x,p.z
        elif island=='front': a,b=p.y,p.z
        elif island=='rear': a,b=-p.y,p.z
        else: a,b=p.x,p.y
        u=(a-domain[0])/(domain[1]-domain[0]); vv=(b-domain[2])/(domain[3]-domain[2])
        uv.data[loop].uv=((rect[0]+u*(rect[2]-rect[0]))/layout['size'],1-(rect[3]-vv*(rect[3]-rect[1]))/layout['size'])
    face.material_index=0
while len(shell.data.materials)>1: shell.data.materials.pop(index=len(shell.data.materials)-1)
tree=kdtree.KDTree(len(shell.data.vertices))
for i,vert in enumerate(shell.data.vertices): tree.insert(vert.co,i)
tree.balance()
symmetry=max(tree.find((p.co.x,-p.co.y,p.co.z))[2] for p in shell.data.vertices)
assert symmetry<1e-5,symmetry
assert all(math.isfinite(a) for item in uv.data for a in item.uv)

for sign in (-1,1):
    box('Mirror base',(.566,sign*.867,1.020),(.13,.11,.058),trim,.020)
    box('Rounded mirror',(.55,sign*.963,1.066),(.23,.145,.100),white,.046)
    box('Mirror glass',(.453,sign*.963,1.066),(.018,.104,.062),trim,.020)
    box('Lightbar foot',(-.12,sign*.40,1.491),(.105,.07,.040),trim,.015)
box('Lightbar base',(-.12,0,1.518),(.190,1.17,.040),trim,.018)
box('Lightbar smooth housing',(-.12,0,1.555),(.180,1.16,.051),blue,.022)
box('Lightbar center',(-.12,0,1.555),(.182,.37,.052),white,.019)
box('Lightbar cap',(-.12,0,1.585),(.179,1.13,.012),alloy,.005)

def export(objects,name):
    bpy.ops.object.select_all(action='DESELECT')
    for o in objects: o.select_set(True)
    bpy.context.view_layer.objects.active=objects[0]
    bpy.ops.object.convert(target='MESH'); bpy.ops.object.join(); o=bpy.context.object; o.name=name
    bpy.ops.object.mode_set(mode='EDIT'); bpy.ops.mesh.select_all(action='SELECT')
    bpy.ops.mesh.remove_doubles(threshold=.000001)
    bpy.ops.mesh.normals_make_consistent(inside=False); bpy.ops.object.mode_set(mode='OBJECT')
    scene.cursor.location=(0,0,0); bpy.ops.object.origin_set(type='ORIGIN_CURSOR')
    mod=o.modifiers.new('Stable export triangles','TRIANGULATE'); apply(o,mod)
    bpy.ops.export_scene.fbx(filepath=str(OUT/(name+'.fbx')),use_selection=True,object_types={'MESH'},
        axis_forward='X',axis_up='Z',apply_unit_scale=True,bake_space_transform=True,mesh_smooth_type='FACE',path_mode='RELATIVE')
    return o

body=export(parts,'SM_KentPoliceV90_Body'); parts=[]

def lathe(name,profile,mat,segments=64):
    verts=[(r*math.cos(i*math.tau/segments),y,r*math.sin(i*math.tau/segments)) for i in range(segments) for y,r in profile]
    n=len(profile)
    faces=[(i*n+j,((i+1)%segments)*n+j,((i+1)%segments)*n+(j+1)%n,i*n+(j+1)%n)
           for i in range(segments) for j in range(n)
           if profile[j][1]>0 or profile[(j+1)%n][1]>0]
    return mesh(name,verts,faces,mat)

lathe('Simple rounded road tyre',[(-.100,.227),(-.122,.252),(-.125,.293),(-.105,.323),(-.08,.335),(.08,.335),(.105,.323),(.125,.293),(.122,.252),(.100,.227)],black)
lathe('Soft alloy rim',[(-.116,.212),(-.126,.226),(-.119,.238),(.119,.238),(.126,.226),(.116,.212)],alloy)
lathe('Dark inner barrel',[(-.106,0),(-.106,.210),(.106,.210),(.106,0)],trim)
for sign in (-1,1):
    for i in range(5):
        angle=i*math.tau/5
        o=box('Broad five-spoke alloy',(.126*math.sin(angle),sign*.120,.126*math.cos(angle)),(.045,.024,.206),alloy,.010)
        o.rotation_euler.y=angle
    lathe('Hub cap',[(sign*.127,0),(sign*.127,.053),(sign*.146,.050),(sign*.147,0)],alloy,48)
wheel=export(parts,'SM_KentPoliceV90_Wheel'); wheel.hide_render=True
for x in (-1.4705,1.4705):
    for y in (-.817,.817):
        o=wheel.copy(); o.data=wheel.data; bpy.context.collection.objects.link(o); o.location=(x,y,.335); o.hide_render=False

draft='--draft' in sys.argv
scene.render.engine='CYCLES'; scene.cycles.samples=16 if draft else 32; scene.cycles.use_denoising=True
scene.render.threads_mode='FIXED'; scene.render.threads=4
scene.render.resolution_x=1280 if draft else 1600; scene.render.resolution_y=800 if draft else 1000
scene.render.resolution_percentage=100
scene.view_settings.view_transform='AgX'; scene.view_settings.look='AgX - Medium High Contrast'; scene.view_settings.exposure=-.45
scene.world.node_tree.nodes['Background'].inputs[0].default_value=(.55,.64,.72,1)
scene.world.node_tree.nodes['Background'].inputs[1].default_value=.30
studio=material('Studio warm grey',(.235,.269,.281),0,.8)
box('Studio floor',(0,0,-.06),(2000,2000,.1),studio,.001)
cove=[(6+3*math.sin(i*math.pi/64),2.99-3*math.cos(i*math.pi/64)) for i in range(33)]+[(9,50)]
mesh('Continuous studio backdrop',[(x,y,z) for y,z in cove for x in (-100,100)],
     [(i*2,i*2+1,i*2+3,i*2+2) for i in range(len(cove)-1)],studio)
for name,pos,power,size in [('Key',(1,-4,6),1200,6),('Roof reflection',(-2,3,5),1350,5),('Front fill',(5,0,3),500,4)]:
    bpy.ops.object.light_add(type='AREA',location=pos); light=bpy.context.object; light.name=name
    light.data.energy=power; light.data.shape='DISK'; light.data.size=size
    light.rotation_euler=(Vector((0,0,.8))-light.location).to_track_quat('-Z','Y').to_euler()
bpy.ops.object.camera_add(); cam=bpy.context.object; scene.camera=cam
cam.location=(7.1,-10,2.6); cam.data.lens=66
cam.rotation_euler=(Vector((0,0,.79))-cam.location).to_track_quat('-Z','Y').to_euler()
views=[('front',(7.1,-10,2.6),66),('side',(0,-45,2.5),250),('rear',(-7.1,-10,2.6),66)]
for arg in sys.argv:
    if arg.startswith('--views='): views=[v for v in views if v[0] in arg.split('=',1)[1].split(',')]
if draft: views=views[:1]
if '--no-render' in sys.argv: views=[]
for name,pos,lens in views:
    cam.location=pos; cam.data.lens=lens
    cam.rotation_euler=(Vector((0,0,.79))-cam.location).to_track_quat('-Z','Y').to_euler()
    scene.render.filepath=str(OUT/(('draft_' if draft else '')+name+'.png'))
    bpy.ops.wm.save_as_mainfile(filepath=str(OUT/'KentPoliceV90.blend'))
    bpy.ops.render.render(write_still=True)
manifest={'model':'Volvo V90 stylised estate','revision':2,'body_vertices':len(body.data.vertices),
    'body_triangles':len(body.data.polygons),'wheel_vertices':len(wheel.data.vertices),'wheel_triangles':len(wheel.data.polygons),
    'body_uv_channels':len(body.data.uv_layers),'atlas_size':4096,'geometry_symmetry_max_error_m':symmetry,
    'wheelbase_m':2.941,'wheel_radius_m':.335,'forward':'+X','glass_and_lamps':'flush UV atlas features on continuous shell'}
(OUT/'build_manifest.json').write_text(json.dumps(manifest,indent=2))
bpy.ops.wm.save_as_mainfile(filepath=str(OUT/'KentPoliceV90.blend'))
print('KENT_V90_BUILD_OK',json.dumps(manifest))
