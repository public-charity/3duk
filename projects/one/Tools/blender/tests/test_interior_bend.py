import copy,json,sys,unittest
from pathlib import Path
import numpy as np
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
import synthetic as syn
from streetscape import io_json
from streetscape.spline import Spline,JunctionPlan
from streetscape.build import build_all,junction_audit


class InteriorBendTests(unittest.TestCase):
    def fixture(self):
        raw=syn.load_fixture('straight_100');sid=raw['splines'][0]['id'];raw['junctions']=[]
        candidate=copy.deepcopy(raw);candidate['junctions']=[dict(id='bend:test',kind='bend',x=50.,y=0.,corner_handle_frac=.65,
            ends=[dict(spline_id=sid,end='end',station_m=44.),dict(spline_id=sid,end='start',station_m=58.)])]
        return raw,candidate,sid

    def build(self,raw):
        site=io_json.site_from_dict(raw);plan=JunctionPlan(site);result=build_all(site,syn.terrain_for(raw),plan=plan)
        return site,plan,result

    def test_serialized_bend_keeps_one_definition_and_original_spline_distances(self):
        source,candidate,sid=self.fixture();a=self.build(source)[2][sid];site,plan,result=self.build(candidate);b=result[sid]
        self.assertEqual(set(result),{sid});self.assertEqual(a.spline.length,b.spline.length)
        self.assertTrue(np.array_equal(a.spline.s,b.spline.s));self.assertEqual(candidate['splines'],source['splines'])
        self.assertFalse(np.any(b.spline.active&((b.spline.s>44)&(b.spline.s<58))))
        seams=junction_audit(plan,result);self.assertEqual(seams['patches'],1);self.assertEqual(seams['corners'],2)
        self.assertLessEqual(seams['worst_patch_gap_m'],1e-9);self.assertLessEqual(seams['worst_corner_gap_m'],1e-9)
        reparsed=io_json.site_from_dict(site.to_dict());self.assertEqual(reparsed.junctions[0].ends[0].station_m,44.)

    def test_markings_are_clipped_without_restarting_dash_phase(self):
        source,candidate,sid=self.fixture();before=self.build(source)[2][sid].road;after=self.build(candidate)[2][sid].road
        for group in [g for g in before.group_names if g.startswith('marking:')]:
            old_faces=before.f[before.group_mask_tris(exact=group)];new_faces=after.f[after.group_mask_tris(exact=group)]
            old_stations=before.vs[old_faces];new_stations=after.vs[new_faces]
            self.assertTrue(np.all((new_stations.max(axis=1)<=44.+1e-9)|(new_stations.min(axis=1)>=58.-1e-9)))
            keep=(old_stations.max(axis=1)<=44.)|(old_stations.min(axis=1)>=58.)
            old={tuple(row) for row in np.round(before.v[old_faces[keep]].reshape(-1,3),10)}
            new={tuple(row) for row in np.round(after.v[new_faces].reshape(-1,3),10)}
            self.assertTrue(old<=new,group)
        self.assertGreater(len(new_faces),0)

    def test_fence_posts_inside_the_cut_are_removed_and_remote_posts_stay_exact(self):
        source,candidate,sid=self.fixture()
        segment=dict(id='fence',s0_m=20.,s1_m=95.,side='right',edge=dict(barrier=dict(type='chain_link',height_m=1.2,thickness_m=.05,material='chain_link',post_pitch_m=3.)))
        for raw in (source,candidate):raw['splines'][0]['segments']=[copy.deepcopy(segment)]
        before=self.build(source)[2][sid];after=self.build(candidate)[2][sid]
        original=[i for i in before.instances if i.kind=='post_round'];retained=[i for i in original if not 44.<i.position[0]<58.]
        proposed=[i for i in after.instances if i.kind=='post_round'];self.assertLess(len(proposed),len(original));self.assertEqual(len(retained),len(proposed))
        for a,b in zip(retained,proposed):self.assertTrue(np.array_equal(a.transform,b.transform))
        mesh=after.edge[-1];faces=mesh.f[mesh.group_mask_tris(prefix='barrier:')];s=mesh.vs[faces]
        self.assertTrue(np.all((s.max(axis=1)<=44.+1e-9)|(s.min(axis=1)>=58.-1e-9)))

    def test_other_junction_groups_cannot_hide_a_displaced_corner_or_patch(self):
        from streetscape.build import _ring_at, _ring_at_group, _max_nearest
        source, candidate, sid = self.fixture()
        for part, metric in (("road", "worst_patch_gap_m"), ("edge", "worst_corner_gap_m")):
            site, plan, built = self.build(candidate)
            mesh = built[sid].road if part == "road" else built[sid].edge[1]
            fake = copy.deepcopy(mesh)
            if part == "road":
                ids = [i for i, g in enumerate(mesh.group_names) if g == "junction:bend:test"]
                fake.group_names = [g.replace("junction:bend:test", "junction:bend:test_other") for g in fake.group_names]
            else:
                ids = [i for i, g in enumerate(mesh.group_names) if g.startswith("corner_")]
                fake.group_names = [g.replace(":bend:test:", ":bend:test_other:") for g in fake.group_names]
            vertices = np.unique(mesh.f[np.isin(mesh.grp, ids)])
            self.assertGreater(len(vertices), 0)
            mesh.v[vertices, 2] += 2.
            mesh.merge(fake)
            # The old broad selector sees the undamaged impostor and reports no crack.
            impostor = _ring_at_group(mesh, "junction:bend:test" if part == "road" else "corner_")
            ring = _ring_at(built[sid].road if part == "road" else built[sid].edge[1],
                            44., ("road", "skirt_") if part == "road" else ("kerb", "pavement"))
            self.assertLessEqual(_max_nearest(ring, impostor), 1e-9)
            self.assertGreater(junction_audit(plan, built)[metric], 1.9)

    def test_malformed_ports_and_endpoint_rebinding_are_schema_errors(self):
        source,candidate,sid=self.fixture()
        for mode in ('two_ids','duplicate_ends','missing_station','nan','boolean','legacy_station','trim_radius','node','endpoint_binding','steps_flag'):
            raw=copy.deepcopy(candidate);j=raw['junctions'][0]
            if mode=='two_ids':j['ends'][1]['spline_id']='missing'
            elif mode=='duplicate_ends':j['ends'][1]['end']='end'
            elif mode=='missing_station':j['ends'][1].pop('station_m')
            elif mode=='nan':j['ends'][1]['station_m']=float('nan')
            elif mode=='boolean':j['ends'][1]['station_m']=True
            elif mode=='legacy_station':j['kind']='disc'
            elif mode=='trim_radius':j['trim_radius_m']=6.
            elif mode=='node':j['y']=.01
            elif mode=='steps_flag':raw['splines'][0]['flags']={'steps':True}
            elif mode=='endpoint_binding':raw['splines'][0]['junction_start']=j['id']
            with self.subTest(mode=mode):self.assertTrue(io_json.validate_structure(raw))

    def test_overlapping_out_of_range_or_wrong_control_intervals_fail_to_build(self):
        source,candidate,sid=self.fixture()
        for mode in ('overlap','outside','wrong_control','short_head','short_tail','existing_end_trim'):
            raw=copy.deepcopy(candidate);j=raw['junctions'][0]
            if mode=='overlap':other=copy.deepcopy(j);other['id']='bend:other';raw['junctions'].append(other)
            elif mode=='outside':j['ends'][1]['station_m']=101.
            elif mode=='wrong_control':j['ends'][0]['station_m']=25.;j['ends'][1]['station_m']=35.
            elif mode=='short_head':j['ends'][0]['station_m']=.5
            elif mode=='short_tail':j['ends'][0]['station_m']=40.;j['ends'][1]['station_m']=99.5
            with self.subTest(mode=mode),self.assertRaises(ValueError):
                if mode=='existing_end_trim':
                    site=io_json.site_from_dict(raw);Spline(site.spline(sid),site,syn.terrain_for(raw),trim=(45.,0.))
                else:JunctionPlan(io_json.site_from_dict(raw))


if __name__=='__main__':unittest.main()
