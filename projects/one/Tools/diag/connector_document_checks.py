"""Complete-document checks for combined connector and interior-bend additions."""
import copy
import numpy as np
from streetscape import io_json
from streetscape.spline import JunctionPlan
from streetscape.build import build_all,junction_audit
from streetscape.road import junction_boundary
from streetscape.edge import build_junction_corners
from streetscape.mesh import MeshBuffer
from diag.road_body_quality import mapped_top_stats,body_regressions
from diag.corner_quality_audit import pavement_top_stats
from diag.polygon_boundary_quality import boundary_quality,cross


def preserved_source(original,candidate):
    if candidate['junctions'][:len(original['junctions'])]!=original['junctions']:
        raise ValueError('existing junction payload changed')
    additions=candidate['junctions'][len(original['junctions']):]
    if not additions or any(j.get('kind') not in ('connector','bend') for j in additions):raise ValueError('only appended connector/bend additions are supported')
    restored=copy.deepcopy(candidate);restored['junctions']=copy.deepcopy(original['junctions'])
    before={d['id']:d for d in original['splines']};after={d['id']:d for d in restored['splines']};changed=set()
    if before.keys()!=after.keys():raise ValueError('definition coverage changed')
    for j in additions:
        for end in j['ends']:
            sid=end['spline_id'];field='junction_'+end['end'];changed.add(sid)
            if j['kind']=='bend':continue
            if before[sid].get(field) is not None or after[sid].get(field)!=j['id']:raise ValueError('connector end binding not preserved')
            if field in before[sid]:after[sid][field]=before[sid][field]
            else:after[sid].pop(field)
    if restored!=original:raise ValueError('source payload changed beyond appended joins and connector bindings')
    return additions,changed


def body_metrics(site,plan,built):
    rows={}
    for d in site.splines:
        res=built[d.id]
        if d.profile_ids.road is None:rows[d.id]=dict(status='without_road_profile');continue
        if res.road is None:raise ValueError('missing required body road mesh: '+d.id)
        groups=('ballast','rail:left','rail:right') if res.spline.kind=='rail' else ('road',)
        parts={group:mapped_top_stats(res.road,group) for group in groups}
        if any(not part['surface_triangles'] for part in parts.values()):raise ValueError('empty active body surface: '+d.id)
        for side in (-1,1):parts['pavement_'+str(side)]=mapped_top_stats(res.edge.get(side) or MeshBuffer(),'pavement')
        rows[d.id]=dict(status='fold_review' if any(p['folded_triangles'] for p in parts.values()) else 'passed',parts=parts)
    return rows


def junction_meshes(build):
    result={}
    for sid,res in build.items():
        for part,mesh in res.buffers().items():
            for group in mesh.group_names:
                if group.startswith(('junction:','corner_')):result[(sid,part,group)]=mesh.v[mesh.f[mesh.group_mask_tris(exact=group)]]
    return result


def preserved_vertex_displacement(before,after):
    """Absolute 1 nm position gate; topology/attributes are checked separately.

    Adding a mandatory trim station can change floating point elevation sums at
    an existing end by picometres. Never use relative tolerance at national-grid
    scale, and report these arrays separately from byte-exact geometry reuse.
    """
    a,b=np.asarray(before),np.asarray(after)
    if a.shape!=b.shape or a.ndim<2 or a.shape[-1]!=3 or not np.isfinite(a).all() or not np.isfinite(b).all():
        raise ValueError('preserved vertex coverage or finite coordinates differ')
    if np.array_equal(a,b):return 0.
    maximum=float(np.linalg.norm((a-b).reshape(-1,3),axis=1).max(initial=0.))
    if maximum>1e-9:raise ValueError('preserved vertex moved more than 1 nm: '+str(maximum))
    return maximum


def check_complete_document(original,candidate,terrain):
    additions,changed=preserved_source(original,candidate)
    sites=[io_json.site_from_dict(raw) for raw in (original,candidate)];plans=[JunctionPlan(site) for site in sites];builds=[]
    for label,site,plan in zip(('source','candidate'),sites,plans):
        if terrain is not None and (site.origin.E,site.origin.N)!=(terrain.origin_E,terrain.origin_N):raise ValueError('document/terrain registration differs')
        try:builds.append(build_all(site,terrain,plan=plan))
        except ValueError as exc:raise ValueError(label+' full build failed: '+str(exc)) from exc
    before,after=[body_metrics(site,plan,built) for site,plan,built in zip(sites,plans,builds)]
    regressions={sid:body_regressions(before[sid],after[sid]) for sid in before};regressions={sid:r for sid,r in regressions.items() if r}
    if regressions:raise ValueError('combined body regressions: '+str(regressions))
    unchanged=set(before)-changed;arrays=0;roundoff_arrays=0;roundoff_bodies=0;maximum_displacement=0.
    for sid in unchanged:
        if before[sid]!=after[sid]:raise ValueError('untouched body metrics changed: '+sid)
        a,b=[build[sid].buffers() for build in builds]
        if a.keys()!=b.keys():raise ValueError('untouched buffer coverage changed: '+sid)
        body_roundoff=False
        for part in a:
            for attribute in ('v','f','vs','vd','vh','mat','grp'):
                av,bv=getattr(a[part],attribute),getattr(b[part],attribute)
                if attribute=='v':
                    displacement=preserved_vertex_displacement(av,bv);maximum_displacement=max(maximum_displacement,displacement)
                    if displacement:roundoff_arrays+=1;body_roundoff=True
                    else:arrays+=1
                else:
                    if not np.array_equal(av,bv):raise ValueError('untouched mesh changed: '+sid+':'+part+':'+attribute)
                    arrays+=1
            if a[part].group_names!=b[part].group_names or a[part].material_names!=b[part].material_names:raise ValueError('untouched mesh semantics changed')
        roundoff_bodies+=int(body_roundoff)
    old,new=[junction_meshes(build) for build in builds]
    roundoff_junction_groups=0
    for group,vertices in old.items():
        if group not in new:raise ValueError('existing junction geometry missing: '+str(group))
        displacement=preserved_vertex_displacement(vertices,new[group]);maximum_displacement=max(maximum_displacement,displacement)
        roundoff_junction_groups+=int(displacement>0.)
    plan=plans[1];splines={sid:res.spline for sid,res in builds[1].items()};new_rows=[]
    for j in additions:
        jid=j['id'];boundary=junction_boundary(plan,jid,splines)
        if boundary is None:raise ValueError('combined connector is not planned: '+jid)
        simple=boundary_quality(boundary[0][:,:2]);q=boundary[0][:,:2]-np.array([j['x'],j['y']]);signed=cross(q,np.roll(q,-1,axis=0))*.5
        overlap=float(max(0.,abs(signed).sum()-abs(signed.sum())))
        edge=MeshBuffer();corners=build_junction_corners(plan,jid,splines,edge);pavement=pavement_top_stats(edge)
        if not simple['simple'] or overlap>1e-4 or corners['skipped_incompatible'] or pavement['inverted_top_triangles'] or pavement['folded_top_triangles'] or any(np.min(c[4].b[:,2])<=0 for c in boundary[2]):raise ValueError('combined connector shape failed: '+jid)
        # Keep a large inherited gap elsewhere from masking a new local gap.
        selected=copy.copy(plan);selected.arms={jid:plan.arms[jid]};seams=junction_audit(selected,builds[1])
        if seams['patches']!=1 or seams['worst_patch_gap_m']>1e-9 or seams['worst_corner_gap_m']>1e-9 or seams['corners_skipped_incompatible']:raise ValueError('combined connector finished seam failed: '+jid)
        new_rows.append(dict(id=jid,kind=j['kind'],boundary=simple,patch_overlap_area_m2=overlap,pavement=pavement,finished_mesh_seams=seams))
    from collections import Counter
    return dict(status='complete_document_geometry_verified',definitions=len(before),additions=len(additions),changed_bodies=len(changed),
        before_body_totals=dict(Counter(r['status'] for r in before.values())),after_body_totals=dict(Counter(r['status'] for r in after.values())),
        untouched_bodies_exact=len(unchanged)-roundoff_bodies,untouched_mesh_arrays_exact=arrays,existing_junction_mesh_groups_exact=len(old)-roundoff_junction_groups,
        untouched_bodies_with_roundoff=roundoff_bodies,untouched_mesh_arrays_with_roundoff=roundoff_arrays,existing_junction_mesh_groups_with_roundoff=roundoff_junction_groups,
        maximum_preserved_vertex_displacement_m=maximum_displacement,preserved_position_absolute_tolerance_m=1e-9,
        new_connectors=[row for row in new_rows if row['kind']=='connector'],
        new_bends=[row for row in new_rows if row['kind']=='bend'],source_payload_preserved=True,body_regressions=0)
