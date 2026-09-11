"""Check the complete generated surface cache before touching the saved map."""
from pathlib import Path
import json,hashlib
import numpy as np
P=Path(__file__).resolve().parents[2];OUT=P/'docs/research/manston/airfield'
def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
state=json.loads((OUT/'build_state.json').read_text());assert state['state']=='ready'
assert sha(OUT/'airfield_manifest.json')==state['manifest_sha256']
m=json.loads((OUT/'airfield_manifest.json').read_text());assert len({c['id'] for c in m['caches']})==len(m['caches'])
for path,h in m['source_sha256'].items():assert sha(P.parents[1]/path)==h
assert m['source_counts']=={'runway':1,'taxiway':23,'apron':24,'aerodrome':1}
assert m['runway_coverage_pass'] and m['runway_coverage_points']==1260
assert (m['runway_length_m'],m['runway_width_m'])==(2750.,61)
triangles=0
for c in m['caches']:
 p=Path(state['cache_dir'])/c['file'];assert sha(p)==c['sha256']
 d=json.loads(p.read_text());v=np.array(d['vertices']);f=np.array(d['triangles'])
 assert np.isfinite(v).all() and len(v)==c['vertices'] and len(f)==c['triangles']
 assert f[:,:3].min()>=0 and f[:,:3].max()<len(v)
 a=v[f[:,1],:2]-v[f[:,0],:2];b=v[f[:,2],:2]-v[f[:,0],:2]
 signed=a[:,0]*b[:,1]-a[:,1]*b[:,0]
 assert np.all(signed>1e-8),(c['id'],'inverted or collapsed surface face',signed.min())
 assert len(np.unique(np.sort(f[:,:3],axis=1),axis=0))==len(f),(c['id'],'duplicate triangles')
 triangles+=len(f)
report=dict(pass_checks=True,manifest_sha256=state['manifest_sha256'],caches=len(m['caches']),triangles=triangles,runway_coverage_points=1260,source_features_accounted_for=49)
(OUT/'geometry_verification.json').write_text(json.dumps(report,indent=2),encoding='utf8')
print(json.dumps(report))
