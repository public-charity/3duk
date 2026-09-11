#!/usr/bin/env python3
"""Materialize accepted sparse contact candidates into an isolated terrain product.

All unmodified rasters are copied byte-for-byte. Survey-relative signed deltas are
recomputed for touched tiles, including shared seams. A final manifest is only
published after every output is verified. A same-input interrupted copy resumes.
"""
import argparse
import json
import os
from pathlib import Path
import shutil
import sys
import numpy as np

TOOLS = Path(__file__).resolve().parents[1]
REPO = TOOLS.parents[2]
sys.path.insert(0,str(TOOLS))
sys.path.insert(0,str(TOOLS/"blender"))
from phase1_qc import atomic_json, sha256, run_lock, content_identity
from conform_landscape import slope_stats
from diag.terrain_contact import apply_posts
from diag.terrain_finish import apply_adjustments
from streetscape.terrain import Heightfield


def atomic_bytes(path, data):
    temp = path.with_name(path.name+".pending")
    with open(temp,"wb") as handle:
        handle.write(data)
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(temp,path)


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument("--candidate",type=Path,action="append",required=True,help="candidate report.json")
    ap.add_argument("--out",type=Path,required=True)
    args = ap.parse_args()
    root = args.out.resolve()
    if not root.is_relative_to((TOOLS.parent/"Saved/Phase1").resolve()):
        raise ValueError("contact terrain output must be an isolated Saved/Phase1 directory")
    reports = [json.loads(p.read_text()) for p in args.candidate]
    sources = {row["config"]["landscape"] for row in reports}
    if len(sources)!=1:
        raise ValueError("candidates do not share a terrain baseline")
    source = Path(sources.pop()).resolve()
    if root==source or root.is_relative_to(source) or source.is_relative_to(root):
        raise ValueError("candidate output must not overlap its baseline")
    posts,groups = {},[]
    dependencies = [Path(__file__),TOOLS/"phase1_qc.py",TOOLS/"conform_landscape.py",
                    TOOLS/"diag/terrain_contact.py",TOOLS/"diag/terrain_finish.py",TOOLS/"blender/streetscape/terrain.py"]
    finish=any(row['config'].get('model')=='bounded_surface_edge_finish' for row in reports)
    if finish and not all(row['config'].get('model')=='bounded_surface_edge_finish' for row in reports):
        raise ValueError('surface finish and corner-cut candidates require a joint validation before merging')
    for path,row in zip(args.candidate,reports):
        post_file = path.parent/"posts.json"
        if row["status"]!="candidate" or row["problems"] or sha256(post_file)!=row.get("posts_sha256"):
            raise ValueError("contact report is not a verified passing candidate: "+str(path))
        # Verify sources, geometry code and rasters, not just an old green label.
        for name,digest in row["input_sha256"].items():
            if sha256(Path(name))!=digest:
                raise ValueError("contact candidate input changed: "+name)
            dependencies.append(Path(name))
        data = json.loads(post_file.read_text())
        if data["fingerprint"]!=row["fingerprint"] or data["status"]!="candidate":
            raise ValueError("sparse contact identity/status mismatch")
        group = []
        for x,y,z in data["posts"]:
            if not (isinstance(x,int) and isinstance(y,int) and np.isfinite(z)) or (x,y) in posts:
                raise ValueError("invalid or overlapping contact post")
            posts[(x,y)] = z
            group.append((x,y))
        if not group:
            raise ValueError("empty contact candidate")
        for old in groups:
            if np.any(np.max(np.abs(np.asarray(group)[:,None,:]-np.asarray(old)[None,:,:]),axis=2)<=2):
                raise ValueError("candidate patches interact; regenerate and validate their union")
        groups.append(group)
        dependencies += [path,post_file]
    files = sorted(p for p in source.iterdir() if p.is_file())
    dependencies += files
    identity,hashes = content_identity(dependencies,{"candidates":[str(p.resolve()) for p in args.candidate],
                                                     "output":str(root),"numpy":np.__version__})
    root.mkdir(parents=True,exist_ok=True)
    state_path = root/"contact_build_state.json"
    with run_lock(root/"contact_build.lock"):
        state = json.loads(state_path.read_text()) if state_path.exists() else dict(fingerprint=identity,files={})
        if state["fingerprint"]!=identity or (not state_path.exists() and any(p.name!="contact_build.lock" for p in root.iterdir())):
            raise ValueError("output belongs to other work")
        state.update(status="running",phase1_accepted=False,input_sha256=hashes)
        atomic_json(state_path,state)
        baseline = Heightfield.from_landscape_dir(str(source))
        baseline.sampling = "landscape_triangulated"
        if finish:
            for row in reports:
                if row['config']['max_raise_m']>.5 or row['config']['max_cut_m']>.5:
                    raise ValueError('terrain finish exceeds the bounded adjustment budget')
            unit=baseline.manifest['heightmap']['z_encoding']['per_unit']
            offset=baseline.manifest['heightmap']['z_encoding']['offset']
            for key,z in posts.items():
                old=float(baseline.sample(key[0]*baseline.px_m,key[1]*baseline.px_m))
                if not np.isfinite(old) or abs(z-old)>.5+1e-8 or abs(z*unit+offset-round(z*unit+offset))>1e-5 or not 0<=z*unit+offset<=65535:
                    raise ValueError('invalid encoded terrain finish adjustment')
            candidate=apply_adjustments(baseline,posts)
        else:
            candidate=apply_posts(baseline,posts)
        manifest = json.loads((source/"landscape_manifest.json").read_text())
        enc = manifest["heightmap"]["z_encoding"]
        unit,offset = enc["per_unit"],enc["offset"]
        replacements, changed = {}, []
        survey_dir = REPO/"data/thanet/out/unreal/landscape"
        for tile in manifest["tiles"]:
            key = (tile["x"],tile["y"])
            if key not in candidate.tiles or candidate.tiles[key] is baseline.tiles[key]:
                continue
            name = tile["files"]["heightmap"]
            raw = np.fromfile(source/name,dtype="<u2").reshape(baseline.res,baseline.res)
            updated = raw.copy()
            mask = np.isfinite(candidate.tiles[key]) & (candidate.tiles[key]!=baseline.tiles[key])
            updated[mask] = np.rint(candidate.tiles[key][mask]*unit+offset).astype("<u2")
            replacements[name] = updated.tobytes()
            delta = updated.astype(np.int32)-np.fromfile(survey_dir/name,dtype="<u2").reshape(updated.shape).astype(np.int32)
            if np.any((delta < -32768)|(delta > 32767)):
                raise ValueError("survey-relative contact delta exceeds signed encoding")
            delta_name = "conform_delta_x%d_y%d.r16"%key
            replacements[delta_name] = delta.astype("<i2").tobytes()
            values = candidate.tiles[key][np.isfinite(candidate.tiles[key])]
            tile.update(min_m=float(values.min()),max_m=float(values.max()),
                        h16_min=int(updated.min()),h16_max=int(updated.max()))
            slopes = slope_stats(candidate.tiles[key],None,baseline.px_m)
            tile.update(slope_max_deg=slopes["max_deg"],slope_p99_deg=slopes["p99_deg"],cells_over_45deg=slopes["cells_over_45deg"])
            changed.append(dict(x=key[0],y=key[1],changed_posts=int(mask.sum()),
                max_additional_cut_m=float(max(0,(baseline.tiles[key]-candidate.tiles[key])[mask].max())),
                max_additional_raise_m=float(max(0,(candidate.tiles[key]-baseline.tiles[key])[mask].max())),
                delta_file=delta_name,slope=slopes))
        for index,name in enumerate(sorted({p.name for p in files}|set(replacements))):
            if name=="landscape_manifest.json":
                continue
            target = root/name
            if name in replacements:
                import hashlib
                expected = hashlib.sha256(replacements[name]).hexdigest()
            else:
                expected = sha256(source/name)
            if not (target.exists() and sha256(target)==expected):
                if name in replacements:
                    atomic_bytes(target,replacements[name])
                else:
                    temp = target.with_name(target.name+".pending")
                    shutil.copyfile(source/name,temp)
                    os.replace(temp,target)
            if sha256(target)!=expected:
                raise ValueError("contact terrain output verification failed: "+name)
            state["files"][name] = expected
            # Bounded copy batches; every existing file is hash-checked on resume,
            # including files written since the last state checkpoint.
            if index%25==0:
                atomic_json(state_path,state)
        if any(sha256(Path(p))!=digest for p,digest in hashes.items()):
            raise ValueError("contact terrain inputs changed during materialization")
        manifest["terrain_contact"] = dict(fingerprint=identity,status="candidate",phase1_accepted=False,
            baseline=str(source),baseline_manifest_sha256=sha256(source/"landscape_manifest.json"),
            candidate_reports={str(p.resolve()):sha256(p) for p in args.candidate},
            unique_changed_posts=len(posts),changed_tiles=changed,
            note="Conform/global survey QA blocks describe their original baseline. This block and updated tile statistics describe the subsequent constrained contact adjustments. Signed conform_delta rasters still recover the original survey exactly.")
        manifest["heightmap"]["semantics"] += " + constrained contact adjustments; see terrain_contact."
        atomic_json(root/"landscape_manifest.json",manifest)
        state.update(status="complete",manifest_sha256=sha256(root/"landscape_manifest.json"),
                     unique_changed_posts=len(posts),changed_tiles=changed)
        atomic_json(state_path,state)
        print(json.dumps(dict(output=str(root),posts=len(posts),tiles=len(changed),verified_files=len(state["files"]))))


if __name__=="__main__":
    main()
