from copy import deepcopy
from dataclasses import replace
from pathlib import Path
import inspect,json,unittest
from hle_unified.selection_records import dumps,loads
from hle_unified.material import attrs
from hle_unified.self_content import encode
from hle_unified.operation_records import OperationRequest
from tests_c5 import fixtures as f
from tests_c3 import fixtures as ca
from tests_c7_workflow import fixtures as wf
from tests_ft4.test_demands import state,withdraw
from tests_ft7.training_fixtures import training_opportunity
from tests_ft7.test_social_training import finish as finish_training
from tests_ft7.test_social_closure import finish as finish_closure
from full_theory.social_closure import SocialClosureController
from full_theory.content import ContentBridge
from full_theory.social_reuse import SocialReuseController
from full_theory.social_reuse_audit import audit_social_reuse

ROOT=Path(__file__).resolve().parents[1]

def prepare(setting):
    e,t,_=training_opportunity(setting);finish_training(e,t)
    closed=SocialClosureController(e,t);finish_closure(e,closed)
    c=SocialReuseController(closed,e)
    for _ in range(8):
        c.step(e,state('eii'),work_limit=1000000)
        if c.phase=='scan':break
    if c.phase!='scan':raise AssertionError('unsupported requalification did not certify')
    return e,c

def later(e,c,mode='live'):
    heads={}
    for b in e.participant_view(c.actor).snapshot.bindings:
        if len(b.content)==1 and b.content[0].relation in ('c6.need','c7ws.need'):
            if b.ref.identity not in heads or b.ref.revision>heads[b.ref.identity].ref.revision:heads[b.ref.identity]=b
    for b in heads.values():
        if b.endorsement.value not in ('retracted','disputed'):withdraw(e,b.ref)
    target=f.BORROWED if c.setting=='canonical' else wf.DEVICE
    cue=f.CUE if mode=='wrong-cue' else c.requalification_demand.cue
    f.dev.supply8(e,'later-changed-partner',target=target,partner=f.ObjectRef(f.EVE,1))
    if c.setting=='canonical':
        event=f.perform(e,OperationRequest('later-model-inspect',c.actor,'inspect',f.ROOM,target=ca.SUPPLY,evidence=f.evidence(e,c.actor,ca.SUPPLY)),limit=100000)
        observation=f.receive(e,event,c.actor,'later-model-observation')
        r=replace(ca.req(e,'later-model','organize-accumulation-v1',(observation,)),target=target,cue=cue,evidence=f.evidence(e,c.actor,target))
        ContentBridge(e).execute(r,consumed=(observation,))
        ca.seed(e,'later-owned-intention',encode(dict(kind='intention',cap=2,consent=True)),target=target,cue=cue,relation='c3.data')
        body=dict(kind='need',weights=(10,0,0,0),commit=False,scope='quantity',amount=4,collective=False)
        relation='c6.need'
    else:
        rows=wf.data(e,next(b.ref for b in e.participant_view(c.actor).snapshot.bindings if len(b.content)==1 and b.content[0].relation=='c7w.data' and b.target==target and wf.data(e,b.ref).get('kind')=='system'))['tasks']
        own=wf.authored(e,'later-owned-intention',rows,target=target,kind='stance')
        if mode=='wrong-cue':
            ca.seed(e,'later-wrong-cue-content',encode(dict(kind='stance',tasks=rows,consent=True,hypothetical=False)),target=target,cue=cue,relation='c7w.data')
        body=dict(kind='workflow_need',priorities=(10,0,0,0),externalize=False);relation='c7ws.need'
    ca.seed(e,'later-owned-need',encode(body),target=target,cue=cue,relation=relation)
    if mode=='revoked':c.ledger.revoke(c.certificate_key,'matched independent evidence removal')
    return replace(c.requalification_demand,target=target,cue=cue,load=2 if mode=='harder' else 1)

def finish(e,c,d):
    for _ in range(32-len(c.events)):
        c.step(e,state('eii'),d,work_limit=1000000)
        if c.terminal is not None:return
    raise AssertionError('later reuse exceeded bounded horizon')


class SocialReuseTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.witnesses={};cls.restarts={};cls.bases={}
        for setting in ('canonical','workflow'):
            e,c=prepare(setting);cls.bases[setting]=(type(e),e.checkpoint(),c.checkpoint(e))
            typ,native,wrapper=cls.bases[setting]
            for mode in ('live','revoked','harder','wrong-cue','partial-movement'):
                e=typ.restore(native);c=SocialReuseController.restore(wrapper,e);d=later(e,c,mode)
                if mode=='partial-movement':
                    c.step(e,state('eii'),d,work_limit=1000000)
                    for _ in range(32):
                        c.step(e,state('eii'),d,work_limit=1000000)
                        if (c.actor,c.request.key+':movement') in e._jobs:break
                    else:raise AssertionError('movement never started')
                    c.step(e,state('eii'),d,work_limit=1)
                else:finish(e,c,d)
                cls.witnesses[setting+'/'+mode]=(e,c,d)
            for split in ('partial-movement','partial-consumer'):
                e=typ.restore(native);c=SocialReuseController.restore(wrapper,e);d=later(e,c)
                if split=='partial-movement':
                    c.step(e,state('eii'),d,work_limit=1000000)
                    for _ in range(32):
                        c.step(e,state('eii'),d,work_limit=1000000)
                        if (c.actor,c.request.key+':movement') in e._jobs:break
                    else:raise AssertionError('movement never started')
                    c.step(e,state('eii'),d,work_limit=1)
                else:
                    for _ in range(32):
                        if c.phase=='consumer':break
                        c.step(e,state('eii'),d,work_limit=1000000)
                    else:raise AssertionError('consumer never started')
                    c.step(e,state('eii'),d,work_limit=1)
                pn=e.checkpoint();pw=c.checkpoint(e);other=typ.restore(pn);restored=SocialReuseController.restore(pw,other)
                while c.terminal is None:
                    if c.step(e,state('eii'),d,work_limit=1000000)!=restored.step(other,state('eii'),d,work_limit=1000000):raise AssertionError('reuse restart differs')
                cls.restarts[setting+'/'+split]=(e,c,other,restored,pn,pw)

    def test_exact_panel(self):
        self.assertEqual(set(self.witnesses),{s+'/'+m for s in ('canonical','workflow') for m in ('live','revoked','harder','wrong-cue','partial-movement')})
        self.assertEqual(len(self.restarts),4)

    def test_unsupported_requalification_has_two_fresh_exposures(self):
        for s in ('canonical','workflow'):
            e,c,d=self.witnesses[s+'/live'];rows=[r['exposure'] for r in c.qualification_events if r['exposure']]
            self.assertEqual([r['hold'] for r in rows],[1,2]);self.assertTrue(rows[-1]['closed'])
            old=loads(c.prefix_checkpoint)['ledger']['events'][:2]
            self.assertFalse({r['consumer'] for r in rows}&{r['consumer'] for r in old})
            self.assertTrue(all(r['demand']['support_allowed']==() and r['shell']['clear'] for r in rows))

    def test_new_certificate_has_stricter_support_bound(self):
        for s in ('canonical','workflow'):
            _,c,d=self.witnesses[s+'/live'];new=c.ledger.certificates[c.certificate_key];old=c.ledger.certificates[c.source_certificate_key]
            self.assertEqual(new['scope']['support_allowed'],());self.assertTrue(old['scope']['support_allowed'])
            self.assertEqual(new['native_capacity'],old['native_capacity']);self.assertNotEqual(new['key'],old['key'])

    def test_later_need_is_owned_and_post_certificate(self):
        for s in ('canonical','workflow'):
            e,c,d=self.witnesses[s+'/live'];self.assertNotIn(c.request.demand,c.prior_need_refs)
            self.assertTrue(audit_social_reuse(e,c.checkpoint(e))['passed'])

    def test_novel_target_changed_partner_no_support(self):
        for s in ('canonical','workflow'):
            e,c,d=self.witnesses[s+'/live'];self.assertNotEqual(d.target,c.requalification_demand.target);self.assertEqual(d.support_allowed,())
            trained=loads(loads(c.prefix_checkpoint)['training_checkpoint'])['plan']['episodes']
            self.assertNotIn(d.target,{row['target'] for row in trained})
            from hle_unified.development_policy import opportunity
            self.assertEqual(opportunity(e.participant_view(c.actor),d.target,d.context)[0]['partner'],f.ObjectRef(f.EVE,1))
            options={r['name']:r for r in c.route_policy.attempts[0]['options']};self.assertFalse(options['support']['eligible'])

    def test_retained_choice_paid_movement_consumer_settlement(self):
        for s in ('canonical','workflow'):
            e,c,d=self.witnesses[s+'/live'];self.assertEqual(c.phase,'complete')
            self.assertEqual(c.route_policy.attempts[0]['selected']['name'],'retained')
            movement=e.job_status(c.actor,c.request.key+':movement');consumer=e.job_status(c.actor,c.consumer_key)
            self.assertGreater(movement['spent'],0);self.assertGreater(consumer['spent'],0)
            self.assertEqual(consumer['source.0'],movement.get('binding') or movement.get('result'))

    def test_revocation_changes_choice_at_matched_main_cost(self):
        for s in ('canonical','workflow'):
            e,a,_=self.witnesses[s+'/live'];other,b,_=self.witnesses[s+'/revoked']
            self.assertEqual(a.phase,b.phase);self.assertEqual(b.phase,'complete')
            self.assertEqual(a.route_policy.attempts[0]['selected']['name'],'retained');self.assertNotEqual(b.route_policy.attempts[0]['selected']['name'],'retained')
            for suffix in (':movement',':retained-consumer'):
                self.assertEqual(e.job_status(a.actor,a.request.key+suffix)['spent'],other.job_status(b.actor,b.request.key+suffix)['spent'])
            self.assertEqual(a.ledger.history,b.ledger.history)

    def test_harder_and_wrong_cue_not_applicable(self):
        for s in ('canonical','workflow'):
            for m in ('harder','wrong-cue'):
                e,c,d=self.witnesses[s+'/'+m];self.assertFalse(c.ledger.applicable(c.certificate_key,c.actor,d)[0])
                self.assertTrue(not c.route_policy.attempts or c.route_policy.attempts[0]['selected']['name']!='retained')

    def test_partial_work_and_exact_restarts(self):
        for s in ('canonical','workflow'):
            e,c,d=self.witnesses[s+'/partial-movement'];self.assertNotEqual(c.phase,'complete');self.assertIsNone(c.terminal)
        for e,c,other,restored,_,_ in self.restarts.values():
            self.assertEqual(c.phase,'complete');self.assertEqual(e.checkpoint(),other.checkpoint());self.assertEqual(c.checkpoint(e),restored.checkpoint(other))

    def test_forged_certificate_prefix_and_settlement_rejected(self):
        for s in ('canonical','workflow'):
            e,c,d=self.witnesses[s+'/live'];original=loads(c.checkpoint(e))
            for fault in ('scope','prefix','certificate','consumer'):
                bad=deepcopy(original)
                if fault=='scope':bad['requalification_demand']['load']=2
                elif fault=='prefix':bad['prefix_count']-=1
                elif fault=='certificate':bad['certificate_key']='forged'
                else:bad['terminal']['settlement']['consumer_output']=None
                with self.assertRaises(ValueError):audit_social_reuse(e,dumps(bad))

    def test_predecessor_identities_unchanged(self):
        from tools.evaluate_ft6_3b import predecessor_identities,ids
        all_ids=predecessor_identities()
        for mod,cl,p in (('tests_ft6.test_conditioning_release','ConditioningReleaseTests','FT6_3b'),('tests_ft7.test_packet_channel','PacketChannelTests','FT7_1a'),('tests_ft7.test_social_cycle','SocialCycleTests','FT7_1b1'),('tests_ft7.test_peer_cycle','PeerCycleTests','FT7_1b2a'),('tests_ft7.test_social_training','SocialTrainingTests','FT7_1b2b1'),('tests_ft7.test_social_closure','SocialClosureTests','FT7_1b2b2a')):
            protocol=json.loads((ROOT/'contracts/ft'/(p+'_Protocol_v1.json')).read_text());actual=sorted(ids(unittest.defaultTestLoader.loadTestsFromName(mod)))
            self.assertEqual(actual,sorted(mod+'.'+cl+'.'+m for m in protocol['registered_tests']));all_ids+=actual
        self.assertEqual(len(all_ids),338)

    def test_no_supplied_route_or_success(self):
        self.assertEqual(tuple(inspect.signature(SocialReuseController.__init__).parameters),('self','closure','engine'))
        self.assertEqual(tuple(inspect.signature(SocialReuseController.step).parameters),('self','engine','historical_state','demand','work_limit'))
