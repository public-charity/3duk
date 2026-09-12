"""Read-only geometry checks on the saved game export. Run inside Blender."""
import bpy
import bmesh
import json
from pathlib import Path

out=Path(__file__).resolve().parent
bpy.ops.wm.open_mainfile(filepath=str(out/'KentPoliceV90.blend'))
report={}
for name in ('SM_KentPoliceV90_Body','SM_KentPoliceV90_Wheel'):
    obj=bpy.data.objects[name]
    bm=bmesh.new(); bm.from_mesh(obj.data)
    remaining=set(bm.faces); volumes=[]
    while remaining:
        first=remaining.pop(); faces=[first]; pending=[first]
        while pending:
            face=pending.pop()
            for edge in face.edges:
                for adjacent in edge.link_faces:
                    if adjacent in remaining:
                        remaining.remove(adjacent); pending.append(adjacent); faces.append(adjacent)
        volume=0.0
        for face in faces:
            p=face.verts[0].co
            for i in range(1,len(face.verts)-1):
                volume += p.dot(face.verts[i].co.cross(face.verts[i+1].co))/6
        volumes.append(volume)
    bad_edges=sum(not edge.is_manifold for edge in bm.edges)
    zero_area=sum(face.calc_area()<1e-12 for face in bm.faces)
    report[name]={'components':len(volumes),'minimum_component_volume_m3':min(volumes),
                  'non_manifold_edges':bad_edges,'degenerate_faces':zero_area,
                  'uv_channels':len(obj.data.uv_layers),'triangles':len(obj.data.polygons)}
    assert bad_edges==0, (name,'open or non-manifold surface',bad_edges)
    assert min(volumes)>0, (name,'inward-facing component',volumes)
    assert zero_area==0, (name,'zero-area face',zero_area)
    bm.free()
(out/'geometry_audit.json').write_text(json.dumps(report,indent=2))
print('V90_GEOMETRY_AUDIT_OK',json.dumps(report))
