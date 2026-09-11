"""Package the verified museum checkpoint, its recipes, reports and recovery bytes."""
from pathlib import Path
import hashlib
import json
import shutil
import zipfile

PROJECT=Path(__file__).resolve().parents[2]
ROOT=PROJECT.parents[1]
CHEST=PROJECT/'docs/research/manston'
IMPL=CHEST/'implementation'
SAVED=PROJECT/'Saved/Manston'


def main():
    imp=json.loads((SAVED/'import_report.json').read_text())
    ver=json.loads((SAVED/'verification_report.json').read_text())
    manifest=json.loads((IMPL/'museum_manifest.json').read_text())
    if not ver['pass'] or ver['verified_import_checkpoint']!=imp['checkpoint']:
        raise ValueError('Current import has not passed saved-world verification')
    if ver['implementation_manifest_sha256']!=hashlib.sha256((IMPL/'museum_manifest.json').read_bytes()).hexdigest():
        raise ValueError('Verified implementation manifest changed')
    if any(imp['unexpected_content_changes'].values()):
        raise ValueError('Unresolved changes outside the declared import scope')
    checkpoint=Path(imp['checkpoint'])
    for row in imp['saved_actor_packages']:
        path=PROJECT/'Content'/row['path']
        if hashlib.sha256(path.read_bytes()).hexdigest()!=row['sha256']:
            raise ValueError('Saved actor changed since import: '+row['path'])
    for name in ('import_report.json','verification_report.json','arrival.png','museum_overview.png'):
        shutil.copy2(SAVED/name,IMPL/name)
        shutil.copy2(SAVED/name,checkpoint/name)
    xyz=json.loads((IMPL/'walk_samples.json').read_text())['routes'][0]['local_xyz_m'][0]
    visit=f'BugItGo {xyz[0]*100:.1f} {-xyz[1]*100:.1f} {(xyz[2]+1.05)*100:.1f} 0 -25 0'
    guide=f'''# Manston museum — implementation checkpoint

The first museum blockout is saved in the existing `/Game/Thanet/Maps/Thanet` explorer map.
This is a proposed museum reuse, not a map of present public access.

## What is in the map

- R1 museum/command loop: {manifest['metrics'][0]['length_m']:,.1f} m (about 15 minutes at 3 km/h).
- R2 airfield/engineering circuit: {manifest['metrics'][1]['length_m']:,.1f} m (about 54 minutes at 3 km/h).
- Eight information boards, 19 active rest stops, and 13 proposed openings in seven existing fence actors.
- 32 editor-only research labels, with unknown historic floors, portals and footprints left unmodelled.
- The existing mapped museum/airport exteriors remain the building baseline. Detailed restoration models are still to come.

## Visit

Open `projects/one/Thanet.uproject`, load the Thanet map and start Play with the explorer on foot.
In the Unreal console, this existing engine command moves the player to the museum gateway:

```text
{visit}
```

The console command is provided for navigation; the new routes have not yet had a full manual Play-in-Editor walk.
The current explorer uses WASD to walk, F to switch flight and Shift to sprint.

## Verification

The editor target compiled successfully. Both schema checks and restart hashes passed.
The saved map was reopened: 3,837 centre/edge floor probes found no missing or buried surface;
body sweeps found no blocking obstacles. Native collision heights matched independent mesh triangles
within 0.025 mm at the checked centres. This is numerical agreement, not historical survey accuracy.
The updater preserved actor identities and rejected a missing-target edit without changing existing definitions.
The import changed no Content files outside its declared museum/fence scope. Read-only verification changed none.
The arrival and overview captures were reviewed.

The complete headless run still fails. It logs two pre-existing road-junction rebuild errors,
`roads:101767724:0` and `roads:1154393739:0`, and returns `0xC0000005` at process teardown
after the completed report and clean log shutdown. The runner documents this existing World Partition
teardown issue. The museum's narrower result is in `implementation/verification_report.json`;
this is not a clean whole-project test pass.

## Resume and reproduce

Read `PROGRESS.md` first. Phase 0 archival placement and Phase 1 museum blockout are underway;
the full museum is not complete. Use the existing project Python at
`C:/Users/Shadow/code/3duk-env/env/python.exe` from the repository root:

1. `projects/one/Tools/manston/build_museum.py`
2. `projects/one/Tools/manston/build_gates.py`
3. `projects/one/Tools/manston/check_checkpoint.py`
4. Build the editor with `powershell.exe -NoProfile -File projects/one/Tools/build.ps1` if native sources changed.
5. Run `powershell.exe -NoProfile -File projects/one/Tools/ue/run_ue_python.ps1 -Script 12_manston_museum.py -Args "--apply" -Render`.
6. Run `projects/one/Tools/manston/diagnose_surface.py` to refresh independent mesh references, then the same headless runner with `-Args "--verify"`.
7. Run `projects/one/Tools/manston/package_checkpoint.py` only after the matching saved import passes verification.

The generator writes `build_state.json` last. An interrupted or mismatched generation cannot be imported.
`barriers.saved_baseline.streetscape.json` is the original native export: preserve it when rebuilding openings.
Do not use the legacy Streetscape importer to replace existing museum or fence actors; the museum script uses
the identity-preserving document updater instead.

## Recovery

Latest native checkpoint: `{checkpoint.name}` under `projects/one/Saved/Manston/checkpoints/`.
It contains pre-update package copies in `Content/`, resulting copies in `after/`, and source JSON/report snapshots.
The ZIP also contains `recovery/before/` and `recovery/after/`, both relative to the project's Content directory.
Recovery requires this existing Thanet world and its data; the archive is not a standalone game.
Close any writer to the Thanet project before restoring. Compare the recorded package paths and hashes;
restore only the declared files, and preserve unrelated changes. Never clear or replace the whole Content directory.
Source recipes and research are checkpointed in Git on `thanet-explorer`.

## Work still to do

1. Walk both circuits in Play-in-Editor, detail the gateway and road crossings, add directional signs,
   resolve overlapping promenade joins and grade/support edges, and check access gradients.
2. Register historical plans and identify exact replacement footprints for the old RAF tower, T2 hangar,
   fighter pen and selected vanished buildings. Build the historically supported exterior/interior models.
3. Continue the separate Alland Grange, chalk shelter and Battle HQ evidence work before creating exact
   underground rooms or entrances. No connecting tunnel network has been invented.
4. Extend to the railway/War Flight/FIDO and northern trails after the core is detailed.

Map sources: OpenStreetMap contributors (ODbL) and Environment Agency LiDAR (Open Government Licence).
Historical evidence: Kent Historic Environment Record, Manston History and the cited sources in the research chest.
The museum circulation, signs and openings are authored proposals.
'''
    (CHEST/'IMPLEMENTATION_GUIDE.md').write_text(guide,encoding='utf-8')
    files={}
    for directory in (IMPL,PROJECT/'Tools/manston'):
        for path in directory.rglob('*'):
            if path.is_file() and '__pycache__' not in path.parts:
                files[str(path.relative_to(ROOT)).replace('\\','/')]=path
    owned=[CHEST/'IMPLEMENTATION_GUIDE.md',CHEST/'PROGRESS.md',CHEST/'README.md',
        PROJECT/'Tools/ue/12_manston_museum.py',
        PROJECT/'Plugins/Streetscape/Source/StreetscapeEditor/Public/StreetDocumentPatchLibrary.h',
        PROJECT/'Plugins/Streetscape/Source/StreetscapeEditor/Private/StreetDocumentPatchLibrary.cpp']
    for path in owned:
        files[str(path.relative_to(ROOT)).replace('\\','/')]=path
    for srcdir,name in ((checkpoint/'Content','before'),(checkpoint/'after','after')):
        for path in srcdir.rglob('*'):
            if path.is_file():
                files['recovery/'+name+'/'+str(path.relative_to(srcdir)).replace('\\','/')]=path
    archive=ROOT/'output/manston_phase1_checkpoint.zip'
    archive.parent.mkdir(parents=True,exist_ok=True)
    temp=archive.with_suffix('.tmp.zip')
    with zipfile.ZipFile(temp,'w',zipfile.ZIP_DEFLATED,compresslevel=6) as z:
        for name,path in sorted(files.items()):
            z.write(path,name)
        z.writestr('checkpoint.json',json.dumps({'checkpoint':checkpoint.name,'files':len(files),
            'archive_contents_sha256':{name:hashlib.sha256(path.read_bytes()).hexdigest() for name,path in files.items()}},indent=2))
    with zipfile.ZipFile(temp) as z:
        if z.testzip() is not None:
            raise ValueError('Archive failed CRC validation')
    temp.replace(archive)
    print(json.dumps({'archive':str(archive),'bytes':archive.stat().st_size,'files':len(files),'visit_command':visit}))


if __name__=='__main__':
    main()
