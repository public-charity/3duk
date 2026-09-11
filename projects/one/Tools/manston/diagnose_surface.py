"""Compare the actual ribbon's highest triangle at native diagnostic points."""
from pathlib import Path
import json
import hashlib
import sys
import numpy as np
sys.path.insert(0,str(Path(__file__).resolve().parent))
from build_museum import PROJECT,OUT,ROOT,save
from streetscape.io_json import load_site
from streetscape.terrain import Heightfield
from streetscape.build import build_spline

site=load_site(str(OUT/'museum_walks.streetscape.json'))
hf=Heightfield.from_landscape_dir(str(ROOT/'data/thanet/out/unreal/landscape_conformed'))
hf.sampling='landscape_triangulated'
report_path=PROJECT/'Saved/Manston/verification_report.json'
report=json.loads(report_path.read_text()) if report_path.exists() else {}
current_manifest_hash=hashlib.sha256((OUT/'museum_manifest.json').read_bytes()).hexdigest()
comparable=report.get('implementation_manifest_sha256')==current_manifest_hash
old_routes={r['id']:r for r in report.get('routes',[])}
checks=[]
references=[]
walks={r['id']:r['local_xyz_m'] for r in json.loads((OUT/'walk_samples.json').read_text())['routes']}
for route_id in walks:
    route={'id':route_id}
    p=old_routes.get(route_id,{}).get('worst_height_comparison') if comparable else None
    mesh=build_spline(site,'manston:'+route['id'],hf).road
    triangles=mesh.v[mesh.f]
    lo,hi=triangles[:,:,:2].min(axis=1)-1e-5,triangles[:,:,:2].max(axis=1)+1e-5
    def query(xy):
        selected=np.all((xy>=lo)&(xy<=hi),axis=1)
        tri=triangles[selected]
        a,b,c=tri[:,0],tri[:,1],tri[:,2]
        ab,ac=b[:,:2]-a[:,:2],c[:,:2]-a[:,:2]
        delta=xy-a[:,:2]
        determinant=ab[:,0]*ac[:,1]-ab[:,1]*ac[:,0]
        good=np.abs(determinant)>1e-12
        divisor=np.where(good,determinant,1.)
        u=(delta[:,0]*ac[:,1]-delta[:,1]*ac[:,0])/divisor
        v=(ab[:,0]*delta[:,1]-ab[:,1]*delta[:,0])/divisor
        good &= (u>=-1e-5)&(v>=-1e-5)&(u+v<=1.00001)
        heights=(a[:,2]+u*(b[:,2]-a[:,2])+v*(c[:,2]-a[:,2]))[good]
        if not len(heights):
            raise ValueError('No reference mesh triangle at '+str(xy))
        return float(heights.max())
    rows=[]
    for i in range(1,len(walks[route['id']])-1,4):
        xyz=walks[route['id']][i]
        rows.append({'sample':i,'mesh_z_m':query(np.array(xyz[:2]))})
    references.append({'id':route['id'],'samples':rows})
    if p is None:
        continue
    xy=np.array(p['xyz_m'][:2])
    selected=np.all((xy>=triangles[:,:,:2].min(axis=1)-1e-5)&(xy<=triangles[:,:,:2].max(axis=1)+1e-5),axis=1)
    hits=[]
    for tri in triangles[selected]:
        a,b,c=tri
        ab,ac=b[:2]-a[:2],c[:2]-a[:2]
        delta=xy-a[:2]
        determinant=ab[0]*ac[1]-ab[1]*ac[0]
        if abs(determinant)<1e-12:
            continue
        u=(delta[0]*ac[1]-delta[1]*ac[0])/determinant
        v=(ab[0]*delta[1]-ab[1]*delta[0])/determinant
        if u>=-1e-5 and v>=-1e-5 and u+v<=1.00001:
            hits.append(float(a[2]+u*(b[2]-a[2])+v*(c[2]-a[2])))
    if not hits:
        raise ValueError('No independent mesh hit')
    checks.append({'id':route['id'],'reference_z':p['xyz_m'][2],'numpy_surface_z':max(hits),
        'native_surface_z':p['hit_z_m'],'mesh_native_error_m':abs(max(hits)-p['hit_z_m']),
        'number_of_overlapping_faces':len(hits),'all_surface_heights':sorted(set(round(z,6) for z in hits))})
save(OUT/'surface_diagnostics.json',{'native_report_matches_current_manifest':comparable,
    'current_manifest_sha256':current_manifest_hash,'comparisons':checks})
save(OUT/'collision_reference.json',{'walk_document_sha256':hashlib.sha256((OUT/'museum_walks.streetscape.json').read_bytes()).hexdigest(),
    'method':'Highest independent numpy ribbon triangle at the native centre probe XY; includes overlaps.',
    'routes':references})
print(json.dumps(checks))
