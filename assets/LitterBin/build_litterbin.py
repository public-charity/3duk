"""Build the Glasdon Jubilee 110 litter bin prop: FBX with three LODs + one 1024x512 albedo.

    blender --background --factory-startup --python assets/LitterBin/build_litterbin.py

Self-contained: no scan, no bake, no inputs beyond a serif font for the LITTER plates.
Every dimension below was measured from a RealityScan photogrammetry scan of a real
Thanet bin (see the README and provenance.json beside this file), then snapped
to the manufacturer's published size: 1158 x 598 x 553 mm.

Output -> assets/LitterBin/ (beside this script)
    SM_LitterBin_Jubilee110.fbx   LitterBin_LOD0/1/2 (Unity auto-creates the LODGroup)
    T_LitterBin_D.png             shared albedo, sRGB, 1024x512

Then in Unity run  Margate/7 - Build Props  (MargatePropBuilder.cs) to get materials,
collider and P_LitterBin.prefab.

Caveats
- Units: geometry is built in "scan units" (1 unit ~ 76 mm) because that is what the
  measurements are in, and scaled to metres only at export. Do not "simplify" this.
- The bin is NOT square. 598 x 553. The scan looked like it had a dented face until the
  spec was checked.
- The atlas is a single UV strip: u = arc length around the body, v = profile length
  from the foot to the stubber cup floor, with extra texel density on the LITTER band.
  Anything painted here is placed by z, so the profile can change without moving the art.
- Text is rendered through Blender's Workbench from a real font, so it is crisp at any
  atlas size. Different machines have different fonts; the candidates list falls back
  to Blender's built-in sans if none exist, which is legible but not the bin's serif.
"""
import bpy, bmesh, numpy as np, os, sys, math, time
from mathutils import Vector, Matrix

HERE = os.path.dirname(os.path.abspath(__file__))
OUT_DIR = HERE  # the FBX and its texture live beside this script
FBX_NAME, TEX_NAME = "SM_LitterBin_Jubilee110.fbx", "T_LitterBin_D.png"
FONTS = [r"C:\Windows\Fonts\timesbd.ttf", "/System/Library/Fonts/Supplemental/Times New Roman Bold.ttf",
         "/Library/Fonts/Times New Roman Bold.ttf", "/usr/share/fonts/truetype/liberation/LiberationSerif-Bold.ttf"]

# ---- measured shape (scan units; body half-width 3.78 along x) -------------------------
RY = 553.0 / 598.0                      # depth/width from the Glasdon spec
FOOT = 0.37                             # foot lost to the ground cut in the scan, restored
SPEC_H = 1.158                          # metres, Glasdon Jubilee 110
S = SPEC_H / (14.85 + FOOT)             # metres per scan unit
WALL = 0.30                             # shell thickness (LOD0/1)
AP_W, AP_H, AP_Z, AP_R = 4.0, 2.0, 12.6, 0.7    # apertures: width, height, centre z, corner radius
GOLD_TOP, GOLD_BASE = (10.64, 10.86), (1.61, 1.89)   # gold lines, z
LITTER_PLATE = (9.92, 10.54)                          # LITTER plate z range, sits under the top line
PLATES = {0: (6.00, 7.55, 1.10), 1: (6.00, 7.55, 1.10), 2: (6.00, 7.55, 1.10), 3: (5.25, 8.25, 2.40)}  # face: z0, z1, width
TONE = np.array([0.290, 0.289, 0.322], np.float32)    # body plastic, sRGB (sampled from the scan)
GOLD = np.array([0.655, 0.584, 0.490], np.float32)
DARK = np.array([0.05, 0.05, 0.06], np.float32)
GW, GH = 2048, 1024                                   # generation size; exported at half

def shoulder(phis):
    return [(13.90 + 0.95 * math.sin(math.radians(p)), 2.90 + 1.10 * math.cos(math.radians(p)), 3.4 - 1.3 * p / 90) for p in phis]
# (z, half-width, superellipse exponent): body n=5.2 is squarer, bands and hood n=3.4 are rounder
PROFILE = [(-FOOT, 4.02, 3.4), (0.00, 4.02, 3.4), (1.00, 4.02, 3.4), (1.15, 3.80, 5.2), (8.95, 3.85, 5.2), (9.10, 4.03, 3.4),
           (11.20, 4.03, 3.4), (13.90, 4.00, 3.4)] + shoulder((30, 60, 90)) + [(14.85, 2.35, 2.05), (14.85, 1.80, 2.0), (13.85, 1.80, 2.0)]
PROFILE_LOD2 = PROFILE[:-1]             # no stubber cup; the dark cap at r=1.8 reads as the hole
SHARP_Z = {1.00, 1.15, 8.95, 9.10, 11.20}
LODS = [("LitterBin_LOD0", PROFILE, 32, True, True, 4), ("LitterBin_LOD1", PROFILE, 16, True, True, 2),
        ("LitterBin_LOD2", PROFILE_LOD2, 12, False, False, 0)]     # name, profile, ring verts, shell, cut apertures, corner segs

def weight(z_top):                      # atlas rows per unit of profile, by segment
    return 2.6 if 9.05 < z_top <= 11.25 else (0.5 if z_top <= 0.0 else (0.65 if z_top > 11.25 else 1.0))
def ring(a, n, z, M):
    t = np.linspace(0, 2 * np.pi, M, endpoint=False); c, s = np.cos(t), np.sin(t)
    ry = 1.0 if n <= 2.05 else RY
    return np.stack([a * np.sign(c) * np.abs(c) ** (2 / n), a * ry * np.sign(s) * np.abs(s) ** (2 / n), np.full(M, z)], 1)
def params(prof, M):
    body = ring(3.78, 5.2, 0, M); seg = np.linalg.norm(np.roll(body, -1, 0) - body, axis=1)
    U = np.concatenate([[0], np.cumsum(seg)]); P = U[-1]; U = U / P
    rings = [ring(a, n, z, M) for z, a, n in prof]
    V = [0.0]
    for i in range(1, len(prof)):
        V.append(V[-1] + math.hypot(prof[i][0] - prof[i - 1][0], prof[i][1] - prof[i - 1][1]) * weight(prof[i][0]))
    return rings, U, np.array(V) / V[-1], P
def z_to_v(z, prof, V):
    zs, vs = [], []
    for (zz, a, n), v in zip(prof, V):
        if zs and zz <= zs[-1]: break
        zs.append(zz); vs.append(v)
    return np.interp(z, zs, vs)

sc = bpy.context.scene
def text_mask(text, w_px, h_px):
    fnt = None
    for p in FONTS:
        if os.path.exists(p): fnt = bpy.data.fonts.load(p); break
    if fnt is None: print("[litterbin] WARNING: no serif font found, using Blender's built-in font")
    cu = bpy.data.curves.new("txt", 'FONT'); cu.body = text; cu.align_x = 'CENTER'; cu.align_y = 'CENTER'
    if fnt: cu.font = fnt
    tob = bpy.data.objects.new("txt", cu); sc.collection.objects.link(tob); bpy.context.view_layer.update()
    bb = [Vector(c) for c in tob.bound_box]
    x0, x1 = min(c.x for c in bb), max(c.x for c in bb); y0, y1 = min(c.y for c in bb), max(c.y for c in bb)
    cam = bpy.data.objects.new("tcam", bpy.data.cameras.new("tcam")); sc.collection.objects.link(cam); sc.camera = cam
    cam.data.type = 'ORTHO'; cam.data.ortho_scale = max((x1 - x0) * 1.04, (y1 - y0) * 1.04 * w_px / h_px)
    cam.matrix_world = Matrix.Translation(((x0 + x1) / 2, (y0 + y1) / 2, 5.0))
    sc.render.engine = 'BLENDER_WORKBENCH'; sc.display.shading.light = 'FLAT'; sc.display.shading.color_type = 'SINGLE'
    sc.display.shading.single_color = (1, 1, 1); sc.render.film_transparent = True; sc.display.render_aa = '8'
    sc.render.resolution_x, sc.render.resolution_y, sc.render.resolution_percentage = w_px, h_px, 100
    sc.render.image_settings.file_format = 'PNG'; sc.render.image_settings.color_mode = 'RGBA'
    path = os.path.join(bpy.app.tempdir, "litterbin_text.png"); sc.render.filepath = path; bpy.ops.render.render(write_still=True)
    im = bpy.data.images.load(path); a = np.empty(w_px * h_px * 4, np.float32); im.pixels.foreach_get(a)
    mask = a.reshape(h_px, w_px, 4)[..., 3] > 0.5
    bpy.data.objects.remove(tob); bpy.data.objects.remove(cam); sc.render.film_transparent = False
    rows = np.flatnonzero(mask.any(1)); cols = np.flatnonzero(mask.any(0))
    return mask[rows[0]:rows[-1] + 1, cols[0]:cols[-1] + 1]

def rounded_cols(prof, V, U, P, M, z0, z1, half_w, rr, k):
    """Row/col index arrays for a rounded rectangle centred on face k (rounded in the flat texture)."""
    r0, r1 = int(z_to_v(z0, prof, V) * GH), int(z_to_v(z1, prof, V) * GH)
    uc = U[(M // 4) * k]; c0, c1 = int((uc - half_w / P) * GW), int((uc + half_w / P) * GW)
    rows = np.arange(r0, r1); cols = np.arange(c0, c1)
    zz = (rows[:, None] - (r0 + r1) / 2) / max(r1 - r0, 1) * (z1 - z0)          # back to units
    xx = (cols[None, :] - (c0 + c1) / 2) / max(c1 - c0, 1) * (2 * half_w)
    dx = np.maximum(np.abs(xx) - (half_w - rr), 0); dz = np.maximum(np.abs(zz) - ((z1 - z0) / 2 - rr), 0)
    inside = np.hypot(dx, dz) <= rr
    return rows, cols % GW, inside

def build_atlas(prof, V, U, P, M, litter):
    rng = np.random.default_rng(5)
    out = np.empty((GH, GW, 3), np.float32); out[:] = TONE + (0.006 * rng.normal(0, 1, (GH, GW, 1))).astype(np.float32)
    face_len = lambda k: 2 * (4.03 * RY if k % 2 == 0 else 4.03)
    for k, (z0, z1, w) in PLATES.items():                       # framed plates
        rows, cols, _ = rounded_cols(prof, V, U, P, M, z0, z1, w / 2, 0.0, k)
        out[rows[0]:rows[-1] + 1][:, cols] = GOLD; ins = 6
        out[rows[0] + ins:rows[0] + ins + 2][:, cols[ins:-ins]] = TONE; out[rows[-1] - ins - 1:rows[-1] - ins + 1][:, cols[ins:-ins]] = TONE
        out[rows[0]:rows[-1] + 1][:, cols[ins:ins + 2]] = TONE; out[rows[0]:rows[-1] + 1][:, cols[-ins - 2:-ins]] = TONE
    for z0, z1 in (GOLD_TOP, GOLD_BASE):                        # straight gold lines
        a0, a1 = int(z_to_v(z0, prof, V) * GH), int(z_to_v(z1, prof, V) * GH); out[a0:a1] = GOLD
    p0, p1 = int(z_to_v(LITTER_PLATE[0], prof, V) * GH), int(z_to_v(LITTER_PLATE[1], prof, V) * GH); ph = p1 - p0
    for k in range(4):                                          # LITTER plates with crisp text
        uc = U[(M // 4) * k]; half = 0.23 * face_len(k) / P
        cols = np.arange(int((uc - half) * GW), int((uc + half) * GW)) % GW
        out[p0:p1, cols] = TONE
        out[p0:p0 + 2, cols] = GOLD; out[p1 - 2:p1, cols] = GOLD; out[p0:p1, cols[:2]] = GOLD; out[p0:p1, cols[-2:]] = GOLD
        th = int(ph * 0.62); tw = min(int(th * litter.shape[1] / litter.shape[0]), len(cols) - 12)
        ys = np.linspace(0, litter.shape[0] - 1, th).astype(int); xs = np.linspace(0, litter.shape[1] - 1, tw).astype(int)
        m = litter[ys][:, xs]; rr0 = p0 + (ph - th) // 2; cc0 = (len(cols) - tw) // 2
        region = out[rr0:rr0 + th][:, cols[cc0:cc0 + tw]]; region[m] = GOLD; out[rr0:rr0 + th, cols[cc0:cc0 + tw]] = region
    h0 = int(z_to_v(11.20, prof, V) * GH); out[h0:] = TONE + (0.006 * rng.normal(0, 1, (GH - h0, GW, 1))).astype(np.float32)
    out[:int(z_to_v(0.0, prof, V) * GH)] = TONE
    for k in range(4):                                          # apertures: invisible on the cut LODs, the opening on LOD2
        rows, cols, inside = rounded_cols(prof, V, U, P, M, AP_Z - AP_H / 2, AP_Z + AP_H / 2, AP_W / 2, AP_R, k)
        sub = out[rows[0]:rows[-1] + 1][:, cols]; sub[inside] = DARK; out[rows[0]:rows[-1] + 1, cols] = sub
    return np.clip(out, 0, 1)

def build_mesh(name, prof, M, shell, apertures, ap_k, mats):
    rings, U, V, P = params(prof, M)
    bm = bmesh.new(); uvl = bm.loops.layers.uv.new("UVMap")
    verts = [[bm.verts.new(tuple(p)) for p in r] for r in rings]
    for i in range(len(rings) - 1):
        for j in range(M):
            j1 = (j + 1) % M
            f = bm.faces.new((verts[i][j], verts[i][j1], verts[i + 1][j1], verts[i + 1][j]))
            for lp, uv in zip(f.loops, ((U[j], V[i]), (U[j + 1], V[i]), (U[j + 1], V[i + 1]), (U[j], V[i + 1]))): lp[uvl].uv = uv
    caps = [bm.faces.new(tuple(verts[0])), bm.faces.new(tuple(verts[-1]))]
    for f in caps: f.material_index = 1
    for f in bmesh.ops.triangulate(bm, faces=caps)['faces']: f.material_index = 1
    for i, (z, a_, n) in enumerate(prof):
        if z in SHARP_Z or (a_ <= 1.81 and n <= 2.0):
            for j in range(M):
                e = bm.edges.get((verts[i][j], verts[i][(j + 1) % M]))
                if e: e.smooth = False
    bmesh.ops.recalc_face_normals(bm, faces=bm.faces)
    me = bpy.data.meshes.new(name); bm.to_mesh(me); bm.free()
    ob = bpy.data.objects.new(name, me); sc.collection.objects.link(ob)
    for p in me.polygons: p.use_smooth = True
    me.materials.append(mats[0]); me.materials.append(mats[1])
    bpy.ops.object.select_all(action='DESELECT'); ob.select_set(True); bpy.context.view_layer.objects.active = ob
    if shell:
        sol = ob.modifiers.new("shell", 'SOLIDIFY'); sol.thickness = WALL; sol.offset = -1.0; sol.material_offset = 1; sol.use_even_offset = True
        bpy.ops.object.modifier_apply(modifier=sol.name)
    if apertures:
        cb = bmesh.new(); pts = []
        for cx, cy, a0 in ((AP_W / 2 - AP_R, AP_H / 2 - AP_R, 0), (-AP_W / 2 + AP_R, AP_H / 2 - AP_R, 90), (-AP_W / 2 + AP_R, -AP_H / 2 + AP_R, 180), (AP_W / 2 - AP_R, -AP_H / 2 + AP_R, 270)):
            for i in range(ap_k + 1):
                an = math.radians(a0 + 90 * i / ap_k); pts.append((cx + AP_R * math.cos(an), cy + AP_R * math.sin(an)))
        for side in range(4):
            an = math.radians(90 * side); cs, sn = math.cos(an), math.sin(an); lo, hi = [], []
            for (l, zz) in pts:
                for depth, lst in ((2.2, lo), (5.2, hi)): lst.append(cb.verts.new((depth * cs - l * sn, depth * sn + l * cs, AP_Z + zz)))
            n = len(lo)
            for i in range(n): cb.faces.new((lo[i], lo[(i + 1) % n], hi[(i + 1) % n], hi[i]))
            cb.faces.new(tuple(lo[::-1])); cb.faces.new(tuple(hi))
        bmesh.ops.recalc_face_normals(cb, faces=cb.faces)
        cme = bpy.data.meshes.new("cutter"); cb.to_mesh(cme); cb.free(); cme.materials.append(mats[1])
        cut = bpy.data.objects.new("cutter", cme); sc.collection.objects.link(cut)
        bo = ob.modifiers.new("ap", 'BOOLEAN'); bo.operation = 'DIFFERENCE'; bo.solver = 'EXACT'; bo.object = cut; bo.material_mode = 'TRANSFER'
        bpy.ops.object.modifier_apply(modifier=bo.name); bpy.data.objects.remove(cut)
    me = ob.data
    lt = np.empty(len(me.polygons), np.int64); me.polygons.foreach_get('loop_total', lt)
    return ob, int(np.sum(lt - 2))

def main():
    t0 = time.time()
    if not hasattr(bpy.ops.export_scene, "fbx") or not bpy.ops.export_scene.fbx.poll():
        bpy.ops.preferences.addon_enable(module="io_scene_fbx")
    os.makedirs(OUT_DIR, exist_ok=True)
    litter = text_mask("LITTER", 1024, 256)
    # texture: laid out for the LOD0 profile; LOD1/2 share the profile (LOD2 minus the cup, which is beyond the last painted row)
    _, U, V, P = params(PROFILE, 32)
    atlas = build_atlas(PROFILE, V, U, P, 32, litter)
    small = atlas.reshape(GH // 2, 2, GW // 2, 2, 3).mean((1, 3))
    img = bpy.data.images.new("T_LitterBin_D", GW // 2, GH // 2, alpha=False)
    px = np.ones((GH // 2, GW // 2, 4), np.float32); px[..., :3] = small; img.pixels.foreach_set(px.ravel())
    tex_path = os.path.join(OUT_DIR, TEX_NAME); img.filepath_raw = tex_path; img.file_format = 'PNG'; img.save()
    tex = bpy.data.images.load(tex_path)
    m_out = bpy.data.materials.new("M_LitterBin"); m_out.use_nodes = True
    bsdf = m_out.node_tree.nodes["Principled BSDF"]; tn = m_out.node_tree.nodes.new("ShaderNodeTexImage"); tn.image = tex
    m_out.node_tree.links.new(tn.outputs["Color"], bsdf.inputs["Base Color"]); bsdf.inputs["Roughness"].default_value = 0.65
    m_in = bpy.data.materials.new("M_LitterBin_Inner"); m_in.use_nodes = True
    m_in.node_tree.nodes["Principled BSDF"].inputs["Base Color"].default_value = (0.02, 0.02, 0.025, 1)
    m_in.node_tree.nodes["Principled BSDF"].inputs["Roughness"].default_value = 0.9
    objs, report = [], []
    for name, prof, M, shell, ap, apk in LODS:
        ob, tris = build_mesh(name, prof, M, shell, ap, apk, (m_out, m_in))
        me = ob.data; co = np.empty(len(me.vertices) * 3); me.vertices.foreach_get('co', co); co = co.reshape(-1, 3)
        co[:, 2] += FOOT; co *= S; me.vertices.foreach_set('co', co.ravel()); me.update()        # foot on the ground, metres
        objs.append(ob); report.append("%s %d tris" % (name, tris))
    bpy.ops.object.select_all(action='DESELECT')
    for ob in objs: ob.select_set(True)
    bpy.context.view_layer.objects.active = objs[0]
    bpy.ops.export_scene.fbx(filepath=os.path.join(OUT_DIR, FBX_NAME), use_selection=True, object_types={'MESH'},
                             use_mesh_modifiers=True, mesh_smooth_type='OFF', use_triangles=True, add_leaf_bones=False,
                             bake_anim=False, apply_scale_options='FBX_SCALE_ALL', apply_unit_scale=True, global_scale=1.0,
                             axis_forward='-Z', axis_up='Y', bake_space_transform=True, path_mode='RELATIVE', embed_textures=False)
    co = np.concatenate([np.array([v.co for v in o.data.vertices]) for o in objs])
    print("[litterbin] %s | height %.3f m, %.3f x %.3f m | %s + %s (%dx%d) in %.1fs" % (
        ", ".join(report), co[:, 2].max(), co[:, 0].max() - co[:, 0].min(), co[:, 1].max() - co[:, 1].min(),
        FBX_NAME, TEX_NAME, GW // 2, GH // 2, time.time() - t0))

if __name__ == "__main__":
    bpy.ops.wm.read_factory_settings(use_empty=True); sc = bpy.context.scene
    main()
