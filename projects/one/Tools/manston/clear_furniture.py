"""Move only furniture found by the loaded-world walk obstruction check.

Keep each group's orientation, test its entire footprint against both walking loops,
and update the canonical museum recipe so a future import preserves the correction.
"""
from pathlib import Path
import json,hashlib,sys,math
import numpy as np
from shapely.geometry import LineString,Polygon,box
from shapely.affinity import rotate,translate
P=Path(__file__).resolve().parents[2];R=P.parents[1];OUT=P/'docs/research/manston/airfield';IMPL=OUT.parent/'implementation'
sys.path.insert(0,str(P/'Tools/blender'))
from streetscape.terrain import Heightfield

def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def save(p,d):
 t=p.with_suffix('.tmp');t.write_text(json.dumps(d,indent=2,allow_nan=False),encoding='utf8');t.replace(p)

def main():
 report=json.loads((P/'Saved/ManstonAirfield/museum_regression.json').read_text())
 manifest=json.loads((IMPL/'museum_manifest.json').read_text());old_hash=sha(IMPL/'museum_manifest.json')
 assert report['implementation_manifest_sha256']==old_hash
 blockers={o['actor'] for r in report['routes'] for o in r['capsule_obstacles']}
 furniture=[f for f in manifest['furniture'] if any(a.startswith('manston:'+f['id']+'_') for a in blockers)]
 assert {f['id'] for f in furniture}=={'sign_MKE98027','sign_MKE98024','sign_MKE98021','rest_R1_1'}
 paths=[LineString(np.array(r['local_xyz_m'])[:,:2]) for r in json.loads((IMPL/'walk_samples.json').read_text())['routes']]
 base=json.loads((OUT.parent/'basemap.bng.json').read_text())
 buildings=[Polygon(np.array(b['rings'][0]['pts'])-[627680,163080]) for b in base['buildings']]
 hf=Heightfield.from_landscape_dir(str(R/'data/thanet/out/unreal/landscape_conformed'));hf.sampling='landscape_triangulated'
 changes=[]
 for f in furniture:
  old=dict(f);xy=np.array(f['bng'])-[627680,163080];heading=f['heading_deg']
  footprint=rotate(box(-.06,-2,.095,2) if f['kind']=='sign' else box(-.32,-1,.275,1),heading,origin=(0,0))
  chosen=None
  for radius in np.arange(.5,15.5,.5):
   for turn in [0,30,-30,60,-60,90,-90,120,-120,150,-150,180]:
    theta=math.radians(heading+180+turn);q=xy+radius*np.array([math.cos(theta),math.sin(theta)])
    shape=translate(footprint,*q)
    clearance=min(p.distance(shape) for p in paths)
    if clearance<2. or any(b.distance(shape)<1 for b in buildings):continue
    z=float(hf.sample(q[0],q[1]))
    if not math.isfinite(z):continue
    chosen=(q,z,clearance);break
   if chosen is not None:break
  if chosen is None:raise ValueError('No safe furniture location '+f['id'])
  q,z,clearance=chosen;f['bng']=(q+[627680,163080]).tolist();f['surface_z_odn_m']=z
  changes.append(dict(id=f['id'],kind=f['kind'],old=old,new=dict(f),movement_m=float(np.linalg.norm(q-xy)),minimum_footprint_to_route_centre_m=clearance))
 save(IMPL/'museum_manifest.json',manifest)
 state=json.loads((IMPL/'build_state.json').read_text());state['sha256']['museum_manifest.json']=sha(IMPL/'museum_manifest.json');save(IMPL/'build_state.json',state)
 save(OUT/'furniture_adjustments.json',dict(original_manifest_sha256=old_hash,revised_manifest_sha256=sha(IMPL/'museum_manifest.json'),changes=changes))
 print(json.dumps([{k:c[k] for k in ['id','movement_m','minimum_footprint_to_route_centre_m']} for c in changes]))

if __name__=='__main__':main()
