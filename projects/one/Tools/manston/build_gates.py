"""Author museum fence openings from saved native definitions, preserving the baseline."""
from pathlib import Path
import copy
import json
import sys
import numpy as np
from scipy.spatial import cKDTree

sys.path.insert(0,str(Path(__file__).resolve().parent))
from build_museum import OUT,ROOT,save
from streetscape.io_json import load_site,validate_structure
from streetscape.terrain import Heightfield
from streetscape.build import build_spline


def main():
    path=OUT/'barriers.saved_baseline.streetscape.json'
    baseline=json.loads(path.read_text())
    site=load_site(str(path))
    hf=Heightfield.from_landscape_dir(str(ROOT/'data/thanet/out/unreal/landscape'))
    hf.sampling='landscape_triangulated'
    manifest=json.loads((OUT/'museum_manifest.json').read_text())
    walks=json.loads((OUT/'walk_samples.json').read_text())['routes']
    xy=np.vstack([np.asarray(w['local_xyz_m'])[:,:2] for w in walks])
    walktree=cKDTree(xy)
    signs=np.array([np.array(f['bng'])-[627680,163080] for f in manifest['furniture'] if f['kind']=='sign'])
    signstree=cKDTree(signs)
    candidate=copy.deepcopy(baseline);candidate['splines']=[]
    records=[]
    for original in baseline['splines']:
        res=build_spline(site,original['id'],hf)
        distances=walktree.query(res.spline.xy)[0]
        sign_distances=signstree.query(res.spline.xy)[0]
        selected=(distances<3.5)|(sign_distances<2.6)
        indices=np.flatnonzero(selected)
        if not len(indices):
            continue
        splits=np.flatnonzero(np.diff(indices)>1)+1
        spline=copy.deepcopy(original)
        for k,group in enumerate(np.split(indices,splits)):
            lo=max(0,float(res.spline.s[group[0]])-1.5)
            hi=min(float(res.spline.s[-1]),float(res.spline.s[group[-1]])+1.5)
            if hi<=lo:
                continue
            spline['segments'].append({'id':'manston_gate_'+str(k),'s0_m':lo,'s1_m':hi,'side':'both',
                'edge':{'barrier':None}})
            records.append({'barrier_id':spline['id'],'gate_id':'manston_gate_'+str(k),
                's0_m':lo,'s1_m':hi,'opening_length_along_fence_m':round(hi-lo,2),
                'approximate_bng':(res.spline.xy[group[len(group)//2]]+[627680,163080]).tolist(),
                'status':'New museum circulation opening; not a historical entrance'})
        candidate['splines'].append(spline)
    errors=validate_structure(candidate)
    if errors:
        raise ValueError(errors)
    save(OUT/'museum_gates.streetscape.json',candidate)
    save(OUT/'gate_schedule.json',{'baseline':path.name,'openings':records,'barrier_actors':len(candidate['splines'])})
    print(json.dumps({'adapted_barriers':len(candidate['splines']),'openings':len(records),
        'opening_lengths_m':[r['opening_length_along_fence_m'] for r in records]}))


if __name__=='__main__':
    main()
