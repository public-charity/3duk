"""Create a source-hashed, bounded terrain finish candidate around named road edges.

All nearby road/path/pavement surfaces constrain clearance. Named outer bases
must contact ground within one height encoding unit; other outer bases retain
their existing contact within 5 mm. Surface clearance tapers at skirt bases.
Only a sparse candidate is written under Saved, never a production raster.
"""
import argparse
import json
from pathlib import Path
import sys
import time
import numpy as np
TOOLS=Path(__file__).resolve().parents[1]; REPO=TOOLS.parents[2]
sys.path[:0]=[str(TOOLS),str(TOOLS/'blender')]
from phase1_qc import atomic_json,content_identity,sha256
from streetscape import io_json
from streetscape.spline import Spline,JunctionPlan
from streetscape.terrain import Heightfield
from streetscape.road import build_road,build_junction_patch,junction_boundary
from streetscape.edge import build_edge,build_junction_corners
from streetscape.mesh import MeshBuffer
from diag.driving_surface_audit import top_triangles,in_bounds
from diag.junction_contact_candidate import ribbon_bottom_segments,bottom_segments
from diag.terrain_edge_contact import constraint_points,compare_segments
from diag.terrain_finish import minimum_adjustment,apply_adjustments,bounded_triangles
from diag.terrain_contact import exact_penetration
from diag.bridge_crossing_audit import highest_triangle_z


def main():
    ap=argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--document',type=Path,required=True)
    ap.add_argument('--landscape',type=Path,required=True)
    ap.add_argument('--bounds',required=True)
    ap.add_argument('--contact-road',action='append',required=True)
    ap.add_argument('--max-contact-gap-m',type=float,help='explicit review target, at most 25 mm; default one encoded height unit')
    ap.add_argument('--out',type=Path,default=TOOLS.parent/'Saved/Phase1/terrain_finish_candidates')
    args=ap.parse_args()
    bounds=np.array(list(map(float,args.bounds.split(','))))
    if bounds.shape!=(4,) or not np.isfinite(bounds).all() or np.any(bounds[2:]-bounds[:2]<=0) or np.any(bounds[2:]-bounds[:2]>64):
        raise ValueError('invalid terrain finish bounds')
    if not args.out.resolve().is_relative_to((TOOLS.parent/'Saved/Phase1').resolve()):
        raise ValueError('finish output must be under Saved/Phase1')
    raw=json.loads(args.document.read_text())
    tile=np.array(raw['_tile']['bounds_local'])
    if np.any(bounds[:2]-32<tile[:2]) or np.any(bounds[2:]+32>tile[2:]):
        raise ValueError('finish neighbourhood needs adjacent documents')
    survey_dir=REPO/'data/thanet/out/unreal/landscape'
    # Contact cannot sensibly target less than one declared height encoding unit.
    manifest=json.loads((args.landscape/'landscape_manifest.json').read_text())
    contact_gap=1./float(manifest['heightmap']['z_encoding']['per_unit'])
    if not 0<contact_gap<=.02:raise ValueError('unsupported terrain encoding for contact finish')
    if args.max_contact_gap_m is not None:
        if not np.isfinite(args.max_contact_gap_m) or not contact_gap<=args.max_contact_gap_m<=.025:
            raise ValueError('explicit contact target must be between one encoding unit and 25 mm')
        contact_gap=args.max_contact_gap_m
    inputs=[args.document,Path(__file__),TOOLS/'phase1_qc.py']
    inputs += [TOOLS/'diag'/f for f in ('terrain_finish.py','terrain_contact.py','driving_surface_audit.py',
        'junction_contact_candidate.py','bridge_crossing_audit.py','terrain_edge_contact.py')]
    inputs += list((TOOLS/'blender/streetscape').glob('*.py'))
    for directory in (survey_dir,args.landscape):
        inputs += [directory/'landscape_manifest.json']+list(directory.glob('hm_*.r16'))+list(directory.glob('clip_*.r8'))
    config=dict(model='bounded_surface_edge_finish',document=str(args.document.resolve()),landscape=str(args.landscape.resolve()),bounds_m=bounds.tolist(),
        contact_roads=args.contact_road,max_cut_m=.5,max_raise_m=.5,clearance_m=.01,edge_gap_m=contact_gap,
        seam_rule='clearance tapers to zero at intentional skirt bases; upper road and pavement retain 10 mm',
        edge_measurement='exact emitted segments at terrain triangle crossings, region boundaries and protected-gap roots')
    identity,hashes=content_identity(inputs,config)
    root=args.out/identity[:20]; root.mkdir(parents=True,exist_ok=True)
    report=dict(status='running',phase1_accepted=False,fingerprint=identity,input_sha256=hashes,config=config,problems=[])
    atomic_json(root/'report.json',report)
    started=time.time()
    try:
        survey=Heightfield.from_landscape_dir(str(survey_dir)); survey.sampling='landscape_triangulated'
        ground=Heightfield.from_landscape_dir(str(args.landscape)); ground.sampling='landscape_triangulated'
        site=io_json.site_from_dict(raw); plan=JunctionPlan(site)
        if (site.origin.E,site.origin.N)!=(survey.origin_E,survey.origin_N) or (site.origin.E,site.origin.N)!=(ground.origin_E,ground.origin_N):
            raise ValueError('finish registration mismatch')
        lo,hi=bounds[:2]-1,bounds[2:]+1
        junctions=[j for j in site.junctions if np.all(np.array([j.x,j.y])+32>=lo) and np.all(np.array([j.x,j.y])-32<=hi)]
        ids={a.spline_id for j in junctions for a in plan.arms.get(j.id,[])}|set(args.contact_road)
        for d in site.splines:
            if d.source.layer not in ('roads','rail'): continue
            p=np.array([[p.x,p.y] for p in d.points])
            if np.all(p.max(axis=0)+32>=lo) and np.all(p.min(axis=0)-32<=hi):ids.add(d.id)
        splines={}; surfaces=[]; edges=[];edge_segments={}
        def add_surface(name,mesh,mask=None,clearance=None):
            faces=mesh.f if mask is None else mesh.f[mask]
            top=mesh.v[faces]
            normal=np.cross(top[:,1]-top[:,0],top[:,2]-top[:,0])
            keep=normal[:,2]>.5*np.linalg.norm(normal,axis=1)
            keep &= np.all(top[:,:,:2].max(axis=1)>=lo,axis=1)&np.all(top[:,:,:2].min(axis=1)<=hi,axis=1)
            top=top[keep]
            if not len(top):return
            limit=top.copy()
            limit[:,:,2]-=.01 if clearance is None else np.asarray(clearance)[faces[keep]]
            surfaces.append((name,top,limit))
        def add_edges(name,points,required=False):
            keep=np.all(points[:,:2]>=lo,axis=1)&np.all(points[:,:2]<=hi,axis=1)
            points=points[keep]
            if not len(points):return
            if required:
                inside=np.all(points[:,:2]>=bounds[:2],axis=1)&np.all(points[:,:2]<=bounds[2:],axis=1)
                add_edges(name+':protected_halo',points[~inside],False)
                points=points[inside]
                if not len(points):return
            baseline=ground.sample(*points[:,:2].T)
            if not np.isfinite(baseline).all():raise ValueError('missing edge ground')
            target=points.copy()
            if not required:target[:,2]=np.minimum(target[:,2],baseline+contact_gap-.005)
            edges.append((name,points,target,required))
        for sid in sorted(ids):
            d=site.spline(sid)
            if d.flags and (d.flags.bridge or d.flags.tunnel):
                report.setdefault('excluded_structures',[]).append(sid);continue
            sp=Spline(d,site,survey,trim=plan.trim_for(sid));splines[sid]=sp
            m,_=build_road(sp)
            # Road skirts and kerb tucks are intentionally buried seam geometry.
            # They must not demand 10 mm clearance below the very contact base.
            add_surface(sid,m,m.group_mask_tris(exact='road') if sp.kind!='rail' else None)
            if sp.kind!='rail':
                for side,group in ((-1,'skirt_right'),(1,'skirt_left')):
                    edge=np.interp(m.vs,sp.s,sp.edge_offset(side)); overlap=np.interp(m.vs,sp.s,sp.overlap_m)
                    clearance=.01*np.clip((edge+overlap-side*m.vd)/np.maximum(overlap,1e-9),0,1)
                    add_surface(sid+':'+group,m,m.group_mask_tris(exact=group),clearance)
            for side in (-1,1):
                m,_=build_edge(sp,side,survey)
                mask=(m.group_mask_tris(exact='kerb')|m.group_mask_tris(exact='pavement'))
                mask &= np.min(m.vh[m.f],axis=1)>=-1e-8
                add_surface(sid+':edge:'+str(side),m,mask)
            segments=ribbon_bottom_segments(sp,(lo,hi));edge_segments[sid]=segments
            add_edges(sid,constraint_points(segments,ground,bounds,gap_roots=(contact_gap-.005,)),sid in args.contact_road)
        for j in junctions:
            if j.id not in plan.arms or any(a.spline_id not in splines for a in plan.arms[j.id]):continue
            m=MeshBuffer()
            if not build_junction_patch(plan,j.id,splines,m)['built']:raise ValueError('junction patch missing')
            # Junction boundary includes full carriageway end rows AND lowered
            # skirt/corner bases. Match their clearance to the incident ribbons.
            _,arm_slices,_=junction_boundary(plan,j.id,splines)
            clearance=np.zeros(len(m.v));clearance[0]=.01
            for a,b in arm_slices:clearance[1+a+1:1+b-1]=.01
            add_surface(j.id,m,clearance=clearance)
            m=MeshBuffer();build_junction_corners(plan,j.id,splines,m)
            add_surface(j.id+':corners',m,np.min(m.vh[m.f],axis=1)>=-1e-8)
            if any(g.startswith('corner_pavement:') for g in m.group_names):
                segments=bottom_segments(m);edge_segments[j.id]=segments
                add_edges(j.id,constraint_points(segments,ground,bounds,gap_roots=(contact_gap-.005,)))
        if set(args.contact_road)-{sid for sid,_,_,required in edges if required}:
            raise ValueError('named road has no measured outer base in rectangle')
        triangles=np.concatenate([top for _,top,_ in surfaces]); limits=np.concatenate([limit for _,_,limit in surfaces])
        targets=np.concatenate([target for _,_,target,_ in edges])
        relaxable=np.concatenate([np.full(len(target),required,dtype=bool) for _,_,target,required in edges])
        report['surface_groups']=len(surfaces);report['edge_groups']=len(edges)
        # Detect an explicit local contradiction before invoking the integer solve.
        # A higher adjacent mesh may visually cover this base; classify separately,
        # never silently count that as ground contact.
        conflicts=[]
        for sid,points,target,required in edges:
            if not required:continue
            inside=np.all(points[:,:2]>=bounds[:2],axis=1)&np.all(points[:,:2]<=bounds[2:],axis=1)
            p=points[inside]
            if not len(p):continue
            for name,top,limit in surfaces:
                z=highest_triangle_z(limit,p[:,:2])
                bad=np.isfinite(z)&(p[:,2]-contact_gap>z+1e-7)
                if bad.any():
                    ix=np.flatnonzero(bad)[np.argmax(p[bad,2]-z[bad])]
                    conflicts.append(dict(edge=sid,surface=name,samples=int(bad.sum()),point_m=p[ix].tolist(),
                        terrain_ceiling_z_m=float(z[ix]),contradiction_m=float(p[ix,2]-z[ix]-contact_gap)))
        report['direct_contact_conflicts']=conflicts
        atomic_json(root/'report.json',report)
        if conflicts:raise ValueError('direct surface/ground-contact conflict: geometry or seam ownership must be resolved')
        changes,stats=minimum_adjustment(limits,ground,bounds,targets,clearance_m=0.,edge_gap_m=contact_gap,
                                         relaxable_edges=relaxable,diagnose_failure=True)
        candidate=apply_adjustments(ground,changes)
        patch=bounded_triangles(triangles,bounds[:2],bounds[2:])
        after=exact_penetration(patch,candidate)
        clearance_check=exact_penetration(bounded_triangles(limits,bounds[:2],bounds[2:]),candidate)
        if clearance_check['max_penetration_m']>1e-7:raise ValueError('finish clearance verification failed')
        edge_rows=[]
        exact_rows=[]
        for sid,segments in edge_segments.items():
            if not len(segments):continue
            exact=compare_segments(segments,ground,candidate)
            exact_rows.append(dict(id=sid,**exact))
            if exact['max_gap_increase_m']>.005+1e-7:raise ValueError('exact edge protection failed: '+sid)
        for sid,points,target,required in edges:
            inside=np.all(points[:,:2]>=bounds[:2],axis=1)&np.all(points[:,:2]<=bounds[2:],axis=1)
            p=points[inside]
            if not len(p):continue
            old=np.maximum(0,p[:,2]-ground.sample(*p[:,:2].T));new=np.maximum(0,p[:,2]-candidate.sample(*p[:,:2].T))
            edge_rows.append(dict(id=sid,required=required,before_max_gap_m=float(old.max()),after_max_gap_m=float(new.max()),
                                  max_gap_increase_m=float((new-old).max())))
            if (required and new.max()>contact_gap+1e-7) or (not required and (new-old).max()>.005+1e-7):
                raise ValueError('finish edge verification failed: '+sid)
        if content_identity(inputs,config)[0]!=identity:raise ValueError('finish inputs changed during run')
        atomic_json(root/'posts.json',dict(status='candidate',fingerprint=identity,posts=[[x,y,z] for (x,y),z in sorted(changes.items())]))
        report.update(status='candidate',stats=stats,surface_after=after,clearance_constraints=clearance_check,
                      edges=edge_rows,exact_edge_protection=exact_rows,posts_sha256=sha256(root/'posts.json'))
    except BaseException as exc:
        report.update(status='failed',error=str(exc))
        if getattr(exc,'diagnostic',None):report['infeasibility_diagnostic']=exc.diagnostic
        raise
    finally:
        report['seconds']=round(time.time()-started,3);atomic_json(root/'report.json',report)
        print(json.dumps({k:v for k,v in report.items() if k!='input_sha256'},indent=2))


if __name__=='__main__':main()
