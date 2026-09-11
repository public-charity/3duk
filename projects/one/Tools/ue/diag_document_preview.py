"""Preview a complete checked document on existing actors, render, then restore.

No production import/save. Complete source/candidate/export comparison, stable
actor identities, native rollback, and durable all-Content hashes protect both
successful and failed runs. An optional bounded terrain preview is restored too.
"""
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import sys

import unreal
import ue_common as uc
from content_guard import snapshot, require_unchanged
from diag_document_roundtrip import canonical

NAME="diag_document_preview"


def digest(path):
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def main(argv):
    opts=uc.parse_args(argv,options={"candidate_report":"", "out":"", "camera_report":"", "terrain":"", "bounds":"8320,4408,8400,4510"})
    if not opts["candidate_report"] or not opts["out"] or not opts["camera_report"]:
        uc.fail(NAME,"--candidate-report, --out and --camera-report required")
    provenance_path=Path(opts["candidate_report"]).resolve()
    provenance=json.loads(provenance_path.read_text(encoding='utf-8'))
    if provenance.get("status")!="complete":
        raise ValueError("candidate is not complete")
    candidate_path=Path(provenance["candidate_document"]).resolve()
    if digest(candidate_path)!=provenance["candidate_sha256"]:
        raise ValueError("candidate document changed")
    for path,expected in provenance["input_sha256"].items():
        if digest(path)!=expected:
            raise ValueError("candidate input changed: "+path)
    source=Path(uc.data_dir())/"streetscape"/candidate_path.name
    original=json.loads(source.read_text(encoding='utf-8'))
    candidate=json.loads(candidate_path.read_text(encoding='utf-8'))
    ids={d["id"] for d in original["splines"]}
    root=Path(opts["out"]).resolve()
    root.mkdir(parents=True,exist_ok=True)
    if (root/"content_before.json").exists():
        raise ValueError("use a fresh output directory to retain interruption evidence")
    content=Path(__file__).resolve().parents[2]/"Content"
    before=snapshot(content)
    (root/"content_before.json").write_text(json.dumps(before,sort_keys=True),encoding='utf-8')
    report=dict(status="running",source=str(source),candidate=str(candidate_path),candidate_sha256=digest(candidate_path),
                candidate_report_sha256=digest(provenance_path),terrain=opts["terrain"],saved=False)
    lib=unreal.StreetscapeEditorLibrary

    def checkpoint():
        temp=root/"report.tmp"
        temp.write_text(json.dumps(report,indent=2,allow_nan=False),encoding='utf-8')
        os.replace(str(temp),str(root/"report.json"))

    def require(reply,what):
        if not reply.get("ok"):
            raise ValueError(what+": "+str(reply))
        return reply

    def exported(name):
        path=root/(name+".json")
        if not lib.export_document_json(str(source),str(path)):
            raise ValueError("complete document export failed: "+name)
        return json.loads(path.read_text(encoding='utf-8'))

    checkpoint()
    try:
        if not unreal.get_editor_subsystem(unreal.LevelEditorSubsystem).load_level("/Game/Thanet/Maps/Thanet"):
            raise ValueError("load failed")
        points=[p for d in original["splines"] for p in d["points"]]
        lo=[min(p[k] for p in points) for k in ("x","y")]
        hi=[max(p[k] for p in points) for k in ("x","y")]
        if not lib.load_region(unreal.Vector((lo[0]+hi[0])*50,-(lo[1]+hi[1])*50,0),max(hi[0]-lo[0],hi[1]-lo[1])*50+15000):
            raise ValueError("source region load failed")
        eas=unreal.get_editor_subsystem(unreal.EditorActorSubsystem)
        actors=[a for a in eas.get_all_level_actors() if isinstance(a,unreal.StreetscapeActor) and str(a.get_editor_property("street_id")) in ids]
        by_id={str(a.get_editor_property("street_id")):a for a in actors}
        if len(actors)!=len(ids) or set(by_id)!=ids:
            raise ValueError("source actors not loaded exactly once")
        paths={sid:a.get_path_name() for sid,a in by_id.items()}
        baseline=exported("baseline")
        if canonical(baseline)!=canonical(original):
            raise ValueError("loaded source differs from disk source")
        report["actors"]=len(actors)
        report["junctions"]=len(original.get("junctions",[]))
        camera=json.loads(Path(opts["camera_report"]).read_text(encoding='utf-8'))["camera"]
        report["camera"]=camera
        spec=importlib.util.spec_from_file_location("document_preview_capture",Path(__file__).with_name("05_screenshot.py"))
        capture=importlib.util.module_from_spec(spec); spec.loader.exec_module(capture)
        world=unreal.get_editor_subsystem(unreal.UnrealEditorSubsystem).get_editor_world()
        target=capture.make_render_target(world,1600,900)

        def picture(tag):
            path=str(root/(tag+".png"))
            if not capture.capture(world,camera,target,path,"final_ldr",0.,0.):
                raise ValueError("capture failed: "+tag)
            size,distinct,lum=capture.force_opaque(path)
            report.setdefault("captures",{})[tag]=dict(path=path,bytes=size,distinct_rgb=distinct,mean_luminance=lum,readiness=capture.LAST_CAPTURE_STATE)
            if distinct<24 or not 4<=lum<=250:
                raise ValueError("empty or overexposed image")
            checkpoint()

        picture("before")
        report["preview"]=require(json.loads(lib.preview_document_json(str(source),str(candidate_path))),"document preview")
        checkpoint()
        current=exported("candidate_export")
        if canonical(current)!=canonical(candidate):
            raise ValueError("native preview/export differs from complete candidate")
        if opts["terrain"]:
            bounds=list(map(float,opts["bounds"].split(",")))
            report["terrain_preview"]=require(json.loads(lib.preview_landscape_heights_json(opts["terrain"],*bounds)),"terrain preview")
        picture("preview")
        report["document_restore"]=require(json.loads(lib.restore_document_preview_json()),"document restore")
        report["terrain_restore"]=require(json.loads(lib.restore_landscape_preview_json()),"terrain restore")
        restored=exported("restored")
        if canonical(restored)!=canonical(baseline):
            raise ValueError("restored complete document differs from baseline")
        if paths!={sid:a.get_path_name() for sid,a in by_id.items()}:
            raise ValueError("actor identities changed")
        report.update(status="complete",restored_document_identical=True,actor_paths_unchanged=True)
    except Exception as exc:
        report.update(status="failed",error=str(exc)); raise
    finally:
        try:
            report["final_document_restore"]=require(json.loads(lib.restore_document_preview_json()),"final document restore")
        finally:
            try:
                report["final_terrain_restore"]=require(json.loads(lib.restore_landscape_preview_json()),"final terrain restore")
            finally:
                try:
                    report["content_integrity"]=require_unchanged(before,snapshot(content))
                except Exception as exc:
                    report.update(status="failed",content_error=str(exc)); raise
                finally:
                    checkpoint()
    uc.report(NAME,dict(report=str(root/"report.json"),status=report["status"],content_integrity=report["content_integrity"]))


if __name__=="__main__": main(sys.argv)
