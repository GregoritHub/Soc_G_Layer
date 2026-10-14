from copy import deepcopy
from pathlib import Path
import inspect,json,unittest
from hle_unified.selection_records import dumps,loads
from hle_unified.material import attrs
from hle_unified.shell_records import Effect
from tests_c5 import fixtures as f
from tests_ft7.training_fixtures import training_opportunity
from tests_ft7.test_social_training import finish as finish_training
from full_theory.social_closure import SocialClosureController
from full_theory.social_closure_audit import audit_social_closure

ROOT=Path(__file__).resolve().parents[1]

def finish(e,c,interrupt=False):
    for _ in range(12-len(c.events)):
        c.step(e,work_limit=1000000,interrupted=interrupt and c.phase=='expose' and c.index==0)
        if c.terminal is not None:return
    raise AssertionError('closure exceeded registered horizon')


class SocialClosureTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.witnesses={};cls.restarts={};cls.bases={}
        for setting in ('canonical','workflow'):
            for mode in ('independent','supported','missing-correction'):
                e,t,d=training_opportunity(setting,mode);finish_training(e,t)
                c=SocialClosureController(e,t)
                cls.bases[setting,mode]=(type(e),e.checkpoint(),c.checkpoint(e))
                finish(e,c);cls.witnesses[setting+'/'+mode]=(e,c)
            typ,native,wrapper=cls.bases[setting,'independent']
            for mode in ('missing-shell','active-shell','interrupted','partial-use'):
                e=typ.restore(native);c=SocialClosureController.restore(wrapper,e)
                if mode=='missing-shell':f.dev.supply8(e,'closure-incomplete',target=c.demand.target,safe=None)
                if mode=='active-shell':f.dev.inject(e,Effect('forecast'),key='closure-forecast')
                if mode=='partial-use':c.step(e,work_limit=1000000);c.step(e,work_limit=1)
                else:finish(e,c,interrupt=mode=='interrupted')
                cls.witnesses[setting+'/'+mode]=(e,c)
            for split in ('partial-use','partial-shell'):
                e=typ.restore(native);c=SocialClosureController.restore(wrapper,e)
                c.step(e,work_limit=1000000)
                if split=='partial-shell':c.step(e,work_limit=1000000)
                c.step(e,work_limit=1);pn=e.checkpoint();pw=c.checkpoint(e)
                other=typ.restore(pn);restored=SocialClosureController.restore(pw,other)
                while c.terminal is None:
                    if c.step(e,work_limit=1000000)!=restored.step(other,work_limit=1000000):
                        raise AssertionError('restart trace differs')
                cls.restarts[setting+'/'+split]=(e,c,other,restored,pn,pw)

    def test_exact_panel(self):
        self.assertEqual(set(self.witnesses),{s+'/'+m for s in ('canonical','workflow') for m in ('independent','supported','missing-correction','missing-shell','active-shell','interrupted','partial-use')})
        self.assertEqual(len(self.restarts),4)

    def test_no_supplied_evidence_or_success(self):
        self.assertEqual(tuple(inspect.signature(SocialClosureController.__init__).parameters),('self','engine','training'))
        self.assertEqual(tuple(inspect.signature(SocialClosureController.step).parameters),('self','engine','work_limit','interrupted'))

    def test_paid_stable_return_and_two_exposures(self):
        for s in ('canonical','workflow'):
            e,c=self.witnesses[s+'/independent'];rows=c.ledger.events[:2]
            self.assertEqual([r['hold'] for r in rows],[1,2]);self.assertEqual(rows[0]['kept'],rows[1]['kept'])
            self.assertNotEqual(rows[0]['consumer'],rows[1]['consumer'])
            self.assertTrue(all(r['returned'] and r['paid_use'] and r['shell']['clear'] and r['shell']['evaluated'] for r in rows))
            self.assertTrue(audit_social_closure(e,c.checkpoint(e))['passed'])

    def test_certificates_bound_to_independent_training(self):
        for s in ('canonical','workflow'):
            e,c=self.witnesses[s+'/independent'];self.assertEqual(c.phase,'certified')
            cert=c.ledger.certificates[c.certificate_key]
            self.assertEqual(cert['native_capacity'],loads(c.training_checkpoint)['capacity'])
            self.assertEqual(cert['scope']['load'],1);self.assertFalse(cert['material_competence'])
            self.assertTrue(c.ledger.applicable(c.certificate_key,c.actor,c.demand)[0])

    def test_supported_closure_is_not_capability(self):
        for s in ('canonical','workflow'):
            e,c=self.witnesses[s+'/supported'];self.assertEqual(c.phase,'closed');self.assertFalse(c.ledger.certificates)
            self.assertTrue(c.ledger.events[-1]['closed'])
            e2,c2=self.witnesses[s+'/independent']
            costs=lambda engine,x:[attrs(engine.world.resolve(r['work']['operation']))['spent'] for r in x.events if r['phase_before']=='use']
            self.assertEqual(costs(e,c),costs(e2,c2))

    def test_missing_correction_no_certificate(self):
        for s in ('canonical','workflow'):
            e,c=self.witnesses[s+'/missing-correction'];self.assertEqual(c.phase,'open')
            self.assertFalse(c.ledger.certificates);self.assertTrue(all(not r['closed'] for r in c.ledger.events))

    def test_missing_and_active_shell_not_clear(self):
        for s in ('canonical','workflow'):
            for m in ('missing-shell','active-shell'):
                e,c=self.witnesses[s+'/'+m];self.assertEqual(c.phase,'open')
                self.assertTrue(all(not r['shell']['clear'] for r in c.ledger.events))
                self.assertFalse(c.ledger.certificates)

    def test_interruption_resets_window(self):
        for s in ('canonical','workflow'):
            e,c=self.witnesses[s+'/interrupted'];self.assertEqual([r['hold'] for r in c.ledger.events],[0,1])
            self.assertEqual(c.phase,'open');self.assertFalse(c.ledger.certificates)

    def test_partial_work_no_closure_credit(self):
        for s in ('canonical','workflow'):
            e,c=self.witnesses[s+'/partial-use'];self.assertEqual(c.phase,'use')
            self.assertFalse(c.ledger.events);self.assertIsNone(c.events[-1]['work']['output'])
            self.assertEqual(e.job_status(c.actor,c.events[-1]['work']['key'])['spent'],1)

    def test_exact_partial_restarts(self):
        for e,c,other,restored,_,_ in self.restarts.values():
            self.assertEqual(c.phase,'certified');self.assertEqual(e.checkpoint(),other.checkpoint())
            self.assertEqual(c.checkpoint(e),restored.checkpoint(other))

    def test_forged_scope_return_and_certificate_rejected(self):
        for s in ('canonical','workflow'):
            e,c=self.witnesses[s+'/independent'];original=loads(c.checkpoint(e))
            for fault in ('scope','return','certificate','closure','prefix','owner'):
                d=deepcopy(original)
                if fault=='scope':d['demand']['load']=2
                elif fault=='return':d['plan']['return_refs']=()
                elif fault=='certificate':d['ledger']['certificates'][d['certificate_key']]['scope']['load']=8
                elif fault=='closure':d['events'][3]['exposure']['closed']=True
                elif fault=='prefix':d['prefix_count']-=1
                else:d['actor']=f.BOB
                with self.assertRaises(ValueError):audit_social_closure(e,dumps(d))

    def test_predecessor_identities_and_scope_boundaries(self):
        from tools.evaluate_ft6_3b import predecessor_identities,ids
        all_ids=predecessor_identities()
        for mod,cl,p in (('tests_ft6.test_conditioning_release','ConditioningReleaseTests','FT6_3b'),('tests_ft7.test_packet_channel','PacketChannelTests','FT7_1a'),('tests_ft7.test_social_cycle','SocialCycleTests','FT7_1b1'),('tests_ft7.test_peer_cycle','PeerCycleTests','FT7_1b2a'),('tests_ft7.test_social_training','SocialTrainingTests','FT7_1b2b1')):
            protocol=json.loads((ROOT/'contracts/ft'/(p+'_Protocol_v1.json')).read_text())
            actual=sorted(ids(unittest.defaultTestLoader.loadTestsFromName(mod)))
            self.assertEqual(actual,sorted(mod+'.'+cl+'.'+m for m in protocol['registered_tests']));all_ids+=actual
        self.assertEqual(len(all_ids),326)
        for s in ('canonical','workflow'):
            _,c=self.witnesses[s+'/independent'];self.assertEqual(c.demand.record(),dict(loads(c.training_checkpoint)['scope'],target=loads(c.training_checkpoint)['plan']['episodes'][0]['target']))
