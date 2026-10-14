from copy import deepcopy
from pathlib import Path
import inspect,json,unittest
from hle_unified.selection_records import dumps,loads
from hle_unified.material import attrs
from hle_unified.development_values import attrs as devattrs
from tests_ft7.training_fixtures import training_opportunity
from full_theory.social_training import SocialTrainingController
from full_theory.social_training_audit import audit_social_training

ROOT=Path(__file__).resolve().parents[1]

def finish(e,c):
    for _ in range(24-len(c.events)):
        c.step(e,work_limit=1000000)
        if c.terminal is not None:break
    if c.terminal is None:raise AssertionError('training exceeded bounded horizon')


class SocialTrainingTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.witnesses={};cls.restarts={};cls.bases={}
        for setting in ('canonical','workflow'):
            for mode in ('independent','supported','missing-content','missing-correction'):
                e,p,d=training_opportunity(setting,mode);c=SocialTrainingController(e,p)
                cls.bases[setting,mode]=(type(e),e.checkpoint(),c.checkpoint(e))
                finish(e,c);cls.witnesses[setting+'/'+mode]=(e,c)
            typ,native,wrapper=cls.bases[setting,'independent']
            e=typ.restore(native);c=SocialTrainingController.restore(wrapper,e)
            c.step(e,work_limit=1000000);c.step(e,work_limit=1)
            cls.witnesses[setting+'/partial-response']=(e,c)
            for split in ('partial-response','partial-practice'):
                e=typ.restore(native);c=SocialTrainingController.restore(wrapper,e)
                c.step(e,work_limit=1000000)
                while c.phase!=('respond' if split=='partial-response' else 'practice'):
                    c.step(e,work_limit=1000000)
                c.step(e,work_limit=1);partial_native=e.checkpoint();partial_wrapper=c.checkpoint(e)
                other=typ.restore(partial_native);restored=SocialTrainingController.restore(partial_wrapper,other)
                while c.terminal is None:
                    a=c.step(e,work_limit=1000000);b=restored.step(other,work_limit=1000000)
                    if a!=b:raise AssertionError('partial restart trace differs')
                cls.restarts[setting+'/'+split]=(e,c,other,restored,partial_native,partial_wrapper)

    def test_fixed_panel(self):
        self.assertEqual(set(self.witnesses),{s+'/'+m for s in ('canonical','workflow') for m in ('independent','supported','missing-content','missing-correction','partial-response')})
        self.assertEqual(len(self.restarts),4)

    def test_no_supplied_success_or_training_recipe(self):
        self.assertEqual(tuple(inspect.signature(SocialTrainingController.step).parameters),('self','e','work_limit'))
        self.assertEqual(tuple(inspect.signature(SocialTrainingController.__init__).parameters),('self','engine','peer_cycle'))

    def test_owned_discovery_scope_and_order(self):
        for s in ('canonical','workflow'):
            e,c=self.witnesses[s+'/independent'];plan=c.plan
            self.assertEqual(len({r['target'].identity for r in plan['episodes']}),2)
            self.assertTrue(audit_social_training(e,c.checkpoint(e))['passed'])
            self.assertTrue(all(attrs(e.world.resolve(r['source_operation']))['actor']==c.actor for r in plan['episodes']))

    def test_two_actual_paid_independent_responses(self):
        for s in ('canonical','workflow'):
            e,c=self.witnesses[s+'/independent']
            rows=[r for r in c.events if r['phase_before']=='respond' and r['work']['status']=='succeeded']
            self.assertEqual(len(rows),2)
            for row in rows:
                job=e.job_status(c.actor,row['request']['fields']['key']);response=devattrs(e.world.resolve(job['development']))
                self.assertTrue(response['completed_demand']);self.assertFalse(response['supported'])
                self.assertEqual(job['spent'],job['required']);self.assertGreater(job['spent'],0)

    def test_content_use_follows_response_precedes_practice(self):
        for s in ('canonical','workflow'):
            e,c=self.witnesses[s+'/independent']
            for i in (0,1):
                rows={r['phase_before']:attrs(e.world.resolve(r['work']['operation'])) for r in c.events if r['work'] and r['request']['fields']['key'].split(':')[-2]==str(i)}
                self.assertLessEqual(rows['respond']['finished_tick'],rows['content']['started_tick'])
                self.assertLessEqual(rows['content']['finished_tick'],rows['practice']['started_tick'])
                self.assertEqual(rows['content']['source.0'],c.plan['episodes'][i]['source'])

    def test_observation_paid_and_practice_bound(self):
        for s in ('canonical','workflow'):
            e,c=self.witnesses[s+'/independent'];a=audit_social_training(e,c.checkpoint(e))
            self.assertEqual((a['episodes'],a['paid_observations'],a['content_uses']),(2,2,2))

    def test_capacity_from_distinct_independent_examples(self):
        for s in ('canonical','workflow'):
            e,c=self.witnesses[s+'/independent'];self.assertEqual(c.phase,'complete');cap=devattrs(e.world.resolve(c.capacity))
            self.assertEqual(cap['max_load'],1);self.assertEqual(len(set(cap['examples'])),2)
            self.assertTrue(all(devattrs(e.world.resolve(p))['independent'] for p in cap['examples']))

    def test_supported_control_matched_main_cost_no_capacity(self):
        for s in ('canonical','workflow'):
            e,a=self.witnesses[s+'/independent'];f,b=self.witnesses[s+'/supported']
            self.assertEqual(b.phase,'unqualified');self.assertIsNone(b.capacity)
            for phase in ('respond','content'):
                cost=lambda engine,c:sum(attrs(engine.world.resolve(r['work']['operation']))['spent'] for r in c.events if r['phase_before']==phase)
                self.assertEqual(cost(e,a),cost(f,b))
            self.assertEqual(audit_social_training(f,b.checkpoint(f))['independent_practices'],0)

    def test_missing_content_honest_deferral(self):
        for s in ('canonical','workflow'):
            e,c=self.witnesses[s+'/missing-content'];self.assertEqual(c.phase,'deferred');self.assertFalse(c.bridge.events);self.assertIsNone(c.capacity)

    def test_missing_correction_no_independent_capacity(self):
        for s in ('canonical','workflow'):
            e,c=self.witnesses[s+'/missing-correction'];self.assertEqual(c.phase,'unqualified');self.assertIsNone(c.capacity)
            self.assertEqual(audit_social_training(e,c.checkpoint(e))['independent_practices'],0)

    def test_partial_work_no_output_credit(self):
        for s in ('canonical','workflow'):
            e,c=self.witnesses[s+'/partial-response'];self.assertEqual(c.phase,'respond');self.assertEqual(c.index,0)
            r=e.job_status(c.actor,c.events[-1]['request']['fields']['key']);self.assertEqual(r['spent'],1);self.assertIsNone(r.get('result'));self.assertIsNone(c.capacity)

    def test_exact_partial_restart(self):
        for e,c,other,restored,_,_ in self.restarts.values():
            self.assertEqual(c.phase,'complete');self.assertEqual(e.checkpoint(),other.checkpoint());self.assertEqual(c.checkpoint(e),restored.checkpoint(other))

    def test_adversarial_record_links_rejected(self):
        for s in ('canonical','workflow'):
            e,c=self.witnesses[s+'/independent'];original=loads(c.checkpoint(e))
            for fault in ('source','owner','capacity','episode','prefix'):
                d=deepcopy(original)
                if fault=='source':d['plan']['episodes'][0]['source']=d['plan']['episodes'][1]['source']
                elif fault=='owner':d['actor']=loads(d['prefix_peer'])['peer']
                elif fault=='capacity':d['capacity']=d['plan']['pattern']
                elif fault=='episode':d['events'][2]['episode_index']=1
                else:d['prefix_count']-=1
                with self.assertRaises(ValueError):audit_social_training(e,dumps(d))

    def test_supported_prefix_and_identity_preservation(self):
        from tools.evaluate_ft6_3b import predecessor_identities,ids
        all_ids=predecessor_identities()
        for mod,cl,p in (('tests_ft6.test_conditioning_release','ConditioningReleaseTests','FT6_3b'),('tests_ft7.test_packet_channel','PacketChannelTests','FT7_1a'),('tests_ft7.test_social_cycle','SocialCycleTests','FT7_1b1'),('tests_ft7.test_peer_cycle','PeerCycleTests','FT7_1b2a')):
            protocol=json.loads((ROOT/'contracts/ft'/(p+'_Protocol_v1.json')).read_text())
            actual=sorted(ids(unittest.defaultTestLoader.loadTestsFromName(mod)));expected=sorted(mod+'.'+cl+'.'+m for m in protocol['registered_tests'])
            self.assertEqual(actual,expected);all_ids+=actual
        self.assertEqual(len(all_ids),312)
        for s in ('canonical','workflow'):
            _,c=self.witnesses[s+'/independent'];social=loads(loads(c.prefix_peer)['social'])
            self.assertTrue(all(n==0 for n in loads(social['history'])['scores'].values()))
