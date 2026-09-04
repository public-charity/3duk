import bpy, sys, math, os
from mathutils import Vector
argv = sys.argv[sys.argv.index("--")+1:] if "--" in sys.argv else []
SRC, OUT = argv[0], argv[1]

bpy.ops.wm.read_factory_settings(use_empty=True)
bpy.ops.import_scene.gltf(filepath=SRC)

objs = [o for o in bpy.context.scene.objects if o.type == 'MESH']
print(f"imported {len(objs)} mesh objects")
if not objs: sys.exit(1)

# world bounds
lo = Vector(( 1e9,  1e9,  1e9)); hi = Vector((-1e9, -1e9, -1e9))
for o in objs:
    for c in o.bound_box:
        w = o.matrix_world @ Vector(c)
        lo = Vector((min(lo[i], w[i]) for i in range(3)))
        hi = Vector((max(hi[i], w[i]) for i in range(3)))
ctr = (lo + hi) / 2; size = hi - lo
print("bounds", tuple(round(v,1) for v in lo), tuple(round(v,1) for v in hi))

# flat clay material so silhouette and massing read clearly
mat = bpy.data.materials.new("clay"); mat.use_nodes = True
bsdf = mat.node_tree.nodes["Principled BSDF"]
bsdf.inputs["Base Color"].default_value = (0.80, 0.76, 0.70, 1)
bsdf.inputs["Roughness"].default_value = 0.85
for o in objs:
    o.data.materials.clear(); o.data.materials.append(mat)

cam_d = bpy.data.cameras.new("cam"); cam_d.type = 'ORTHO'
cam_d.ortho_scale = max(size.x, size.y) * 1.06
cam = bpy.data.objects.new("cam", cam_d); bpy.context.scene.collection.objects.link(cam)
cam.location = (ctr.x, ctr.y, hi.z + max(size) * 2)
cam.rotation_euler = (0, 0, 0)
bpy.context.scene.camera = cam

sun_d = bpy.data.lights.new("sun", 'SUN'); sun_d.energy = 4.0; sun_d.angle = 0.15
sun = bpy.data.objects.new("sun", sun_d); bpy.context.scene.collection.objects.link(sun)
sun.rotation_euler = (math.radians(48), 0, math.radians(-135))

sc = bpy.context.scene
sc.render.engine = 'BLENDER_WORKBENCH'
sc.display.shading.light = 'STUDIO'
sc.display.shading.show_shadows = True
sc.display.shading.show_cavity = True
sc.display.shading.cavity_type = 'BOTH'
sc.render.resolution_x = 2000; sc.render.resolution_y = 1500
sc.render.film_transparent = False
sc.render.filepath = OUT
bpy.ops.render.render(write_still=True)
print("wrote", OUT)
