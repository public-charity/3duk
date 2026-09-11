"""Recreate a checkpointed data selection from raw source, with exact output hashes.

Writes only complete documents below Saved/Phase1, at most 32 per invocation.
The manifest records historical geometry evidence; recreation does not accept
terrain, structures, seams, native rendering or later geometry-core changes.
"""
import argparse,json,math,sys
from pathlib import Path
TOOLS=Path(__file__).resolve().parents[1];REPO=TOOLS.parents[2]
sys.path.insert(0,str(TOOLS))
from phase1_qc import atomic_json,sha256,run_lock
from diag.path_crossing_candidate import lane_width_candidate
from diag.structure_inventory import read_osm_way_tags


def pending_documents(root,expected,records):
    """Recover a valid document written just before an interrupted state update."""
    if not expected or set(records)-set(expected):raise ValueError('selection checkpoint coverage mismatch')
    pending=[]
    for name,digest in sorted(expected.items()):
        target=root/name
        if target.exists() and sha256(target)==digest:records[name]=dict(sha256=digest)
        else:records.pop(name,None);pending.append(name)
    return pending


def apply_retained_trims(docs,trims,end_trims):
    """Restore only existing, unambiguous bindings with bounded numeric requests."""
    junctions={}
    for raw in docs.values():
        for junction in raw['junctions']:
            jid=junction['id']
            if jid in junctions:raise ValueError('duplicate source junction binding')
            junctions[jid]=junction
    if (set(trims)|set(end_trims))-set(junctions):raise ValueError('retained trim coverage changed')
    def checked(value):
        if isinstance(value,bool) or not isinstance(value,(int,float)) or not math.isfinite(value) or not 0<value<=32:
            raise ValueError('invalid retained trim')
        return value
    edits=[]
    for jid,value in trims.items():edits.append((junctions[jid],checked(value)))
    for jid,requests in end_trims.items():
        ends=junctions[jid]['ends'];bindings={(e['spline_id'],e['end']):e for e in ends}
        if len(bindings)!=len(ends):raise ValueError('duplicate source end binding')
        seen=set()
        for request in requests:
            if set(request)!={'spline_id','end','trim_radius_m'}:raise ValueError('unexpected retained end trim fields')
            key=(request['spline_id'],request['end'])
            if key in seen or key not in bindings:raise ValueError('invalid retained end binding')
            seen.add(key);edits.append((bindings[key],checked(request['trim_radius_m'])))
    # Validate the entire selection before changing any source dictionary.
    for record,value in edits:record['trim_radius_m']=value


def apply_retained_controls(docs,selections):
    """Validate every endpoint-preserving source subsequence before any mutation."""
    if not selections:return
    from diag.road_control_candidates import verify_document
    import copy
    locations={}
    for name,raw in docs.items():
        for d in raw['splines']:
            if d['id'] in locations:raise ValueError('duplicate source control binding')
            locations[d['id']]=name
    if set(selections)-set(locations):raise ValueError('retained control coverage changed')
    proposals={}
    for sid,keep in selections.items():
        if not isinstance(keep,list) or any(type(i) is not int for i in keep):raise ValueError('retained indices must be integers')
        name=locations[sid]
        if name not in proposals:proposals[name]=copy.deepcopy(docs[name])
        d=next(d for d in proposals[name]['splines'] if d['id']==sid)
        if len(keep)<2 or keep!=sorted(set(keep)) or keep[0]!=0 or keep[-1]!=len(d['points'])-1:
            raise ValueError('retained control endpoints/order changed')
        d['points']=[d['points'][i] for i in keep]
    for name,raw in proposals.items():
        verify_document(docs[name],raw,{s:k for s,k in selections.items() if locations[s]==name})
    docs.update(proposals)


def apply_retained_connectors(docs,selections):
    """Restore reviewed local joins, validating the entire selection before mutation."""
    if not selections:return
    import copy
    sys.path.insert(0,str(TOOLS/'blender'))
    from streetscape import io_json
    if set(selections)-set(docs):raise ValueError('retained connector document missing')
    taken={j['id'] for raw in docs.values() for j in raw['junctions']};proposals={}
    for name,additions in selections.items():
        candidate=copy.deepcopy(docs[name]);definitions={d['id']:d for d in candidate['splines']}
        bound={(e['spline_id'],e['end']) for j in candidate['junctions'] for e in j['ends']}
        for addition in additions:
            j=copy.deepcopy(addition);jid=j['id'];ends=j['ends']
            if jid in taken or j.get('kind')!='connector' or len(ends)!=2 or ends[0]['spline_id']==ends[1]['spline_id']:
                raise ValueError('invalid retained connector topology')
            taken.add(jid)
            trim=j.get('trim_radius_m')
            if isinstance(trim,bool) or not isinstance(trim,(float,int)) or not math.isfinite(trim) or not 0<trim<=32:
                raise ValueError('invalid retained connector trim')
            for i,e in enumerate(ends):
                sid=e['spline_id'];end=e['end'];other=ends[1-i]['spline_id'];key='junction_'+end
                if sid not in definitions or end not in ('start','end') or (sid,end) in bound:
                    raise ValueError('retained connector end missing or already bound')
                d=definitions[sid]
                if d.get(key) is not None or d.get('continues_from' if end=='start' else 'continues_to')!=other:
                    raise ValueError('retained connector must use reciprocal continuation ends')
                p=d['points'][0 if end=='start' else -1]
                if not all(isinstance(j[k],(float,int)) and not isinstance(j[k],bool) and math.isfinite(j[k]) for k in ('x','y')) or math.hypot(p['x']-j['x'],p['y']-j['y'])>.001:
                    raise ValueError('retained connector node differs from source endpoints')
                d[key]=jid;bound.add((sid,end))
            candidate['junctions'].append(j)
        io_json.site_from_dict(candidate)
        proposals[name]=candidate
    docs.update(proposals)


def apply_retained_bends(docs,selections):
    """Append reviewed station masks while preserving every complete source spline.

    Validate all affected document plans before mutating any input. This is exact
    reconstruction only; the manifest still needs separate physical evidence.
    """
    if not selections:return
    import copy
    sys.path.insert(0,str(TOOLS/'blender'))
    from streetscape import io_json
    from streetscape.spline import JunctionPlan
    if set(selections)-set(docs):raise ValueError('retained bend document missing')
    taken={j['id'] for raw in docs.values() for j in raw['junctions']};proposals={}
    for name,additions in selections.items():
        candidate=copy.deepcopy(docs[name])
        for addition in additions:
            j=copy.deepcopy(addition)
            if j.get('kind')!='bend' or j.get('id') in taken:
                raise ValueError('invalid retained bend topology or duplicate id')
            taken.add(j.get('id'));candidate['junctions'].append(j)
        JunctionPlan(io_json.site_from_dict(candidate))
        proposals[name]=candidate
    docs.update(proposals)


def main():
    ap=argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--manifest',type=Path,default=TOOLS.parent/'docs/checkpoints/phase1_23_geometry_selection.json')
    ap.add_argument('--max-docs',type=int,default=32)
    ap.add_argument('--out',type=Path,default=TOOLS.parent/'Saved/Phase1/restored_geometry_selection')
    args=ap.parse_args()
    if not 1<=args.max_docs<=32:raise ValueError('max-docs must be 1..32')
    if not args.out.resolve().is_relative_to((TOOLS.parent/'Saved/Phase1').resolve()):raise ValueError('output must stay under Saved/Phase1')
    manifest=json.loads(args.manifest.read_text(encoding='utf-8'));digest=sha256(args.manifest)
    for name,expected in manifest['input_sha256'].items():
        if sha256(REPO/name)!=expected:raise ValueError('source dependency changed: '+name)
    source=REPO/'data/thanet/out/unreal/streetscape';names=sorted(manifest['document_sha256'])
    if set(names)!={p.name for p in source.glob('site_x*_y*.json')}:raise ValueError('source document coverage changed')
    root=args.out/digest[:20];root.mkdir(parents=True,exist_ok=True)
    with run_lock(root/'run.lock'):
        path=root/'state.json'
        state=json.loads(path.read_text(encoding='utf-8')) if path.exists() else dict(status='pending',phase1_accepted=False,
            manifest=str(args.manifest),manifest_sha256=digest,documents={})
        if state['manifest_sha256']!=digest:raise ValueError('selection identity changed')
        pending=pending_documents(root,manifest['document_sha256'],state['documents'])
        if pending:
            docs={name:json.loads((source/name).read_text(encoding='utf-8')) for name in names}
            definitions=[d for raw in docs.values() for d in raw['splines']]
            selected=manifest['width_spline_ids']
            osm=REPO/'data/thanet/raw/thanet.osm'
            tags=read_osm_way_tags(osm,{d['source']['osm_id'] for d in definitions if d['id'] in selected})
            tuning=json.loads((REPO/'sources/config/tuning.json').read_text(encoding='utf-8'))['roads']
            profiles={}
            for raw in docs.values():
                for key,profile in raw['profiles']['road'].items():
                    if key in profiles and profiles[key]!=profile:raise ValueError('conflicting source road profile')
                    profiles[key]=profile
            lane_width_candidate(dict(splines=definitions,profiles=dict(road=profiles)),selected,tags,tuning)
            selected=set(selected)
            for name,raw in docs.items():
                for d in raw['splines']:
                    if d['id'] in selected:
                        pid=d['profile_ids']['road'];raw['profiles']['road'][pid]=profiles[pid]
            apply_retained_trims(docs,manifest['junction_trims_m'],manifest.get('junction_end_trims_m',{}))
            apply_retained_controls(docs,manifest.get('retained_point_indices',{}))
            apply_retained_connectors(docs,manifest.get('connectors',{}))
            apply_retained_bends(docs,manifest.get('bends',{}))
            for name in pending[:args.max_docs]:
                target=root/name;atomic_json(target,docs[name])
                actual=sha256(target)
                if actual!=manifest['document_sha256'][name]:raise ValueError('recreated document differs from verified checkpoint: '+name)
                state['documents'][name]=dict(sha256=actual);atomic_json(path,state)
        if sha256(args.manifest)!=digest:raise ValueError('selection manifest changed during recreation')
        state.update(status='complete' if len(state['documents'])==len(names) else 'pending',completed=len(state['documents']),total=len(names))
        atomic_json(path,state)
        print(json.dumps(dict(state=str(path),status=state['status'],completed=state['completed'],total=state['total'])))


if __name__=='__main__':main()
