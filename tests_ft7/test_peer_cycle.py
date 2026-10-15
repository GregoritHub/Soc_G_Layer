from copy import deepcopy
from pathlib import Path
import inspect,json,unittest
from hle_unified.selection_records import dumps,loads
from tests_c3 import fixtures as ca
from tests_ft4.test_demands import state
from tests_ft7.peer_fixtures import opportunity
from full_theory.peer_cycle import AutonomousPeerCycle
from full_theory.peer_cycle_audit import audit_peer_cycle

ROOT=Path(__file__).resolve().parents[1]


def finish(e,c,d,available=None):
    for _ in range(40-c.turn):
        c.step(e,state(),d,available=c.channel.participants if available is None else available,work_limit=1000000)
        if c.terminal is not None:break


class PeerCycleTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.bases={};cls.witnesses={};cls.restarts={}
        for setting in ('canonical','workflow'):
            for variant,kw in (('consented',{}),('nonconsent',{'consent':False}),('no-stance',{'stance':False}),('no-offer',{'offer':False})):
                e,d=opportunity(setting,**kw);cls.bases[setting,variant]=(type(e),e.checkpoint(),d)
            for mode in ('consented','nonconsent','no-offer','no-stance','peer-withdrawn','partial-peer','recipient-withdrawn'):
                typ,native,d=cls.bases[setting,mode if mode in ('nonconsent','no-offer','no-stance') else 'consented']
                e=typ.restore(native);c=AutonomousPeerCycle(e,ca.ALICE,ca.BOB,setting);wallets={a:dict(e.wallet(a)) for a in c.channel.participants}
                if mode=='partial-peer':
                    for limit in (1000000,1000000,1):c.step(e,state(),d,available=c.channel.participants,work_limit=limit)
                    finish(e,c,d,(ca.ALICE,))
                elif mode=='recipient-withdrawn':
                    for _ in range(3):c.step(e,state(),d,available=c.channel.participants,work_limit=1000000)
                    finish(e,c,d,(ca.BOB,))
                else:finish(e,c,d,(ca.ALICE,) if mode=='peer-withdrawn' else None)
                cls.witnesses[setting+'/'+mode]=(e,c,d,wallets)
            for split in ('partial-peer','partial-recipient'):
                typ,native,d=cls.bases[setting,'consented'];e=typ.restore(native);c=AutonomousPeerCycle(e,ca.ALICE,ca.BOB,setting)
                for limit in ((1000000,1000000,1) if split=='partial-peer' else (1000000,1000000,1000000,1)):
                    c.step(e,state(),d,available=c.channel.participants,work_limit=limit)
                other=typ.restore(e.checkpoint());restored=AutonomousPeerCycle.restore(c.checkpoint(e),other)
                partial=loads(c.checkpoint(e));partial_native=e.checkpoint()
                for _ in range(40-c.turn):
                    a=c.step(e,state(),d,available=c.channel.participants,work_limit=1000000)
                    b=restored.step(other,state(),d,available=restored.channel.participants,work_limit=1000000)
                    if a!=b:raise AssertionError('peer split trace differs')
                    if c.terminal is not None:break
                cls.restarts[setting+'/'+split]=(e,c,other,restored,partial_native,dumps(partial))

    def test_exact_panel(self):
        self.assertEqual(set(self.witnesses),{s+'/'+m for s in ('canonical','workflow') for m in ('consented','nonconsent','no-offer','no-stance','peer-withdrawn','partial-peer','recipient-withdrawn')})
        self.assertEqual(len(self.restarts),4)

    def test_no_supplied_peer_recipe_or_output(self):
        self.assertFalse(set(inspect.signature(AutonomousPeerCycle.step).parameters)&{'request','recipe','route','reply','success','answer','certificate'})
        self.assertFalse(set(inspect.signature(AutonomousPeerCycle.__init__).parameters)&{'offer','request','recipe','reply','operation_key'})
        for setting in ('canonical','workflow'):
            typ,native,d=self.bases[setting,'consented'];e=typ.restore(native)
            self.assertFalse(any(a==ca.BOB and k.startswith('ft-peer-reply:') for a,k in e._jobs))

    def test_paid_offer_to_peer_owned_request(self):
        for s in ('canonical','workflow'):
            e,c,_,_=self.witnesses[s+'/consented'];self.assertEqual(c.phase,'complete')
            self.assertIn('peer-offer',c.channel.bridge.receipts)
            self.assertEqual(c.request.actor,ca.BOB);self.assertEqual(c.request.inputs[0],c.offer['output'])
            self.assertEqual(c.request.inputs[1].identity.key,'peer-owned-stance')
            self.assertTrue(audit_peer_cycle(e,c.checkpoint(e))['paid_reply'])

    def test_reply_is_paid_and_uses_exact_offer_and_stance(self):
        for s in ('canonical','workflow'):
            e,c,_,_=self.witnesses[s+'/consented'];job=e.job_status(ca.BOB,c.request.key)
            self.assertEqual(job['status'],'succeeded');self.assertEqual(job['spent'],job['required']);self.assertGreater(job['spent'],0)
            self.assertEqual(tuple(v for k,v in sorted(job.items()) if k.startswith('source.')),c.request.inputs)
            self.assertEqual(job['public.0'],c.reply)

    def test_recipient_later_use_consumes_generated_reply(self):
        for s in ('canonical','workflow'):
            e,c,_,_=self.witnesses[s+'/consented'];link=c.social.terminal['causal_link'];self.assertEqual(link['source'],c.reply)
            job=e.job_status(ca.ALICE,link['consumer_key']);self.assertEqual(job['status'],'succeeded')
            self.assertEqual(job['spent'],job['required']);self.assertGreater(job['spent'],0)
            self.assertIn(link['movement_output'],tuple(v for k,v in job.items() if k.startswith('input.')))

    def test_nonconsent_changes_outcome_at_matched_peer_cost(self):
        for s in ('canonical','workflow'):
            e,a,_,_=self.witnesses[s+'/consented'];f,b,_,_=self.witnesses[s+'/nonconsent']
            self.assertEqual(e.job_status(ca.BOB,a.request.key)['spent'],f.job_status(ca.BOB,b.request.key)['spent'])
            self.assertEqual(a.phase,'complete');self.assertEqual(b.phase,'deferred');self.assertFalse(b.social.terminal['causal_link'])

    def test_missing_offer_grants_no_peer_work(self):
        for s in ('canonical','workflow'):
            e,c,_,w=self.witnesses[s+'/no-offer'];self.assertEqual(c.phase,'deferred');self.assertIsNone(c.offer)
            self.assertFalse(c.production.events);self.assertIsNone(c.social);self.assertEqual(dict(e.wallet(ca.BOB)),w[ca.BOB])

    def test_missing_stance_is_honest_deferral(self):
        for s in ('canonical','workflow'):
            e,c,_,_=self.witnesses[s+'/no-stance'];self.assertEqual(c.phase,'deferred');self.assertIsNone(c.request)
            self.assertFalse(c.production.events);self.assertIn('peer-offer',c.channel.bridge.receipts);self.assertIsNone(c.social)

    def test_peer_withdrawal_grants_no_uptake(self):
        for s in ('canonical','workflow'):
            e,c,_,w=self.witnesses[s+'/peer-withdrawn'];self.assertEqual(c.phase,'uptake');self.assertEqual(c.turn,40)
            self.assertFalse(c.channel.bridge.receipts);self.assertFalse(c.production.events);self.assertEqual(dict(e.wallet(ca.BOB)),w[ca.BOB])

    def test_partial_reply_has_no_public_output_or_receiver_cycle(self):
        for s in ('canonical','workflow'):
            e,c,_,_=self.witnesses[s+'/partial-peer'];self.assertEqual(c.phase,'peer')
            job=e.job_status(ca.BOB,c.request.key);self.assertEqual(job['spent'],1);self.assertNotIn('public.0',job)
            self.assertIsNone(c.reply);self.assertIsNone(c.social)

    def test_recipient_withdrawal_keeps_reply_pending(self):
        for s in ('canonical','workflow'):
            e,c,_,_=self.witnesses[s+'/recipient-withdrawn'];self.assertEqual(c.phase,'recipient');self.assertIsNotNone(c.reply)
            self.assertFalse(c.social.channel.bridge.receipts);self.assertFalse(c.social.cycle.events)

    def test_exact_restart_during_peer_and_recipient_work(self):
        for e,c,other,restored,_,_ in self.restarts.values():
            self.assertEqual(c.phase,'complete');self.assertEqual(e.checkpoint(),other.checkpoint());self.assertEqual(c.checkpoint(e),restored.checkpoint(other))

    def test_forged_request_receipt_or_source_rejected(self):
        for s in ('canonical','workflow'):
            e,c,_,_=self.witnesses[s+'/consented'];original=loads(c.checkpoint(e))
            for fault in ('request','receipt','source'):
                forged=deepcopy(original)
                if fault=='request':forged['request']['inputs']=tuple(reversed(forged['request']['inputs']))
                elif fault=='receipt':
                    ch=loads(forged['channel']);ch['bridge']['receipts']['peer-offer']['receipt']=forged['offer']['operation'];forged['channel']=dumps(ch)
                else:forged['reply']=forged['offer']['output']
                with self.assertRaises(ValueError):audit_peer_cycle(e,dumps(forged))

    def test_supported_history_and_reserve_remain_exact(self):
        for s in ('canonical','workflow'):
            e,c,_,_=self.witnesses[s+'/consented'];self.assertEqual(c.social.cycle.candidates.binding.ledger.balance,3)
            self.assertTrue(all(v==0 for v in c.social.history.scores.values()));self.assertFalse(audit_peer_cycle(e,c.checkpoint(e))['independent_capability'])

    def test_predecessor_identities_exact(self):
        from tools.evaluate_ft6_3b import predecessor_identities,ids
        earlier=predecessor_identities()
        for mod,cls,protocol in (('tests_ft6.test_conditioning_release','ConditioningReleaseTests','FT6_3b'),('tests_ft7.test_packet_channel','PacketChannelTests','FT7_1a'),('tests_ft7.test_social_cycle','SocialCycleTests','FT7_1b1')):
            p=json.loads((ROOT/'contracts/ft'/(protocol+'_Protocol_v1.json')).read_text())
            expected=sorted(mod+'.'+cls+'.'+m for m in p['registered_tests']);actual=sorted(ids(unittest.defaultTestLoader.loadTestsFromName(mod)))
            self.assertEqual(actual,expected);earlier+=actual
        self.assertEqual(len(earlier),297)
