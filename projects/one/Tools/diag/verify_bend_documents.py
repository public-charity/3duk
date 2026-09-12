"""Combine a frozen bend snapshot and verify at most two complete documents.

Every worker has a 60 s hard deadline. Local screen labels never bypass full
source/candidate builds, untouched-buffer checks or junction-specific seam gates.
"""
import argparse,json,subprocess,sys,time
from pathlib import Path
from collections import Counter
TOOLS=Path(__file__).resolve().parents[1];REPO=TOOLS.parents[2]
sys.path[:0]=[str(TOOLS),str(TOOLS/'blender')]
from phase1_qc import atomic_json,sha256,content_identity,run_lock
from streetscape.terrain import Heightfield
from diag.restore_geometry_selection import apply_retained_bends
from diag.connector_document_checks import check_complete_document


def read(path):return json.loads(path.read_text(encoding='utf-8'))


def worker(request_path):
    request=read(request_path);folder=request_path.parent;source=read(Path(request['source']))
    selected={request['document']:source};apply_retained_bends(selected,{request['document']:request['additions']})
    candidate=selected[request['document']];target=folder/request['document'];atomic_json(target,candidate)
    report=dict(status='running',phase1_accepted=False,document=request['document'],candidate=target.name,
                candidate_sha256=sha256(target),bend_additions=request['additions'])
    atomic_json(folder/'report.json',report);start=time.perf_counter()
    terrain=Heightfield.from_landscape_dir(request['terrain']);terrain.sampling='landscape_triangulated'
    try:report.update(check_complete_document(source,candidate,terrain))
    except ValueError as exc:report.update(status='held_geometry',error=str(exc))
    report['seconds']=round(time.perf_counter()-start,3);atomic_json(folder/'report.json',report)


def main():
    ap=argparse.ArgumentParser(description=__doc__);ap.add_argument('--snapshot',type=Path);ap.add_argument('--worker',type=Path)
    ap.add_argument('--max-docs',type=int,default=1)
    ap.add_argument('--out',type=Path,default=TOOLS.parent/'Saved/Phase1/bend_document_verification');args=ap.parse_args()
    if args.worker:worker(args.worker);return
    if args.snapshot is None or not 1<=args.max_docs<=2:raise ValueError('snapshot and 1..2 documents required')
    if not args.out.resolve().is_relative_to((TOOLS.parent/'Saved/Phase1').resolve()):raise ValueError('output must remain under Saved/Phase1')
    snapshot=read(args.snapshot)
    for path,h in snapshot['input_sha256'].items():
        if sha256(path)!=h:raise ValueError('frozen search input changed: '+path)
    manifest_path=Path(snapshot['source_manifest']);manifest=read(manifest_path);parent=Path(manifest['source_candidate'])
    groups=snapshot['documents'];terrain=REPO/'data/thanet/out/unreal/landscape'
    inputs=[Path(__file__),args.snapshot,manifest_path,TOOLS/'phase1_qc.py']
    for name in groups:
        if sha256(parent/name)!=manifest['document_sha256'][name]:raise ValueError('retained source changed: '+name)
        inputs.append(parent/name)
    inputs+=list((TOOLS/'blender/streetscape').glob('*.py'))
    inputs += [TOOLS/'diag'/name for name in ('connector_document_checks.py','restore_geometry_selection.py','road_body_quality.py',
                                            'corner_quality_audit.py','polygon_boundary_quality.py')]
    inputs += [terrain/'landscape_manifest.json']+list(terrain.glob('hm_*.r16'))+list(terrain.glob('clip_*.r8'))
    config=dict(scope='combined complete-document bend proof',groups=groups,parent=str(parent),worker_timeout_s=60)
    identity,hashes=content_identity(inputs,config);root=args.out/identity[:20];root.mkdir(parents=True,exist_ok=True)
    with run_lock(root/'run.lock'):
        state_path=root/'state.json';state=read(state_path) if state_path.exists() else dict(status='pending',phase1_accepted=False,
            fingerprint=identity,input_sha256=hashes,config=config,documents={},total_documents=len(groups))
        if state['fingerprint']!=identity:raise ValueError('document proof identity mismatch')
        for row in state['documents'].values():
            if sha256(root/row['report'])!=row['report_sha256']:raise ValueError('completed report changed')
            if row.get('candidate') and sha256(root/row['candidate'])!=row['candidate_sha256']:raise ValueError('completed candidate changed')
        atomic_json(state_path,state);processed=0
        for name,additions in sorted(groups.items()):
            if name in state['documents']:continue
            doc_root=root/Path(name).stem;doc_root.mkdir(exist_ok=True)
            folder=doc_root/f'attempt_{len(list(doc_root.glob("attempt_*")))+1:03d}';folder.mkdir()
            request=folder/'request.json';atomic_json(request,dict(source=str(parent/name),document=name,additions=additions,terrain=str(terrain)))
            with (folder/'worker.log').open('w',encoding='utf-8') as log:
                try:
                    result=subprocess.run([sys.executable,str(Path(__file__).resolve()),'--worker',str(request.resolve())],
                        stdout=log,stderr=subprocess.STDOUT,timeout=60,creationflags=getattr(subprocess,'CREATE_NO_WINDOW',0))
                    if result.returncode:raise ValueError('worker exit '+str(result.returncode))
                    report=read(folder/'report.json')
                except (subprocess.TimeoutExpired,ValueError) as exc:
                    report=dict(status='worker_timeout' if isinstance(exc,subprocess.TimeoutExpired) else 'worker_failed',error=str(exc))
                    atomic_json(folder/'report.json',report)
            row=dict(status=report['status'],report=str((folder/'report.json').relative_to(root)),report_sha256=sha256(folder/'report.json'))
            if report.get('candidate'):row.update(candidate=str((folder/report['candidate']).relative_to(root)),candidate_sha256=report['candidate_sha256'])
            state['documents'][name]=row;atomic_json(state_path,state);processed+=1
            print(json.dumps(dict(document=name,status=report['status'],additions=len(additions),seconds=report.get('seconds'),error=report.get('error'))),flush=True)
            if processed>=args.max_docs:break
        if content_identity(inputs,config)[0]!=identity:raise ValueError('proof inputs changed during run')
        state.update(status='complete' if len(state['documents'])==len(groups) else 'pending',completed=len(state['documents']),
                     totals=dict(Counter(row['status'] for row in state['documents'].values())))
        atomic_json(state_path,state);print(json.dumps(dict(root=str(root),completed=state['completed'],total=len(groups),totals=state['totals'])))


if __name__=='__main__':main()
