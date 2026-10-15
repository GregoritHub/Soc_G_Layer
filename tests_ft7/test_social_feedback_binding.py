import gc,gzip,json,os,unittest
from pathlib import Path
from hle_unified import codec
from hle_unified.selection_records import dumps,loads
from hle_unified.selection_execution import SelectionEngine
from hle_unified.workflow_selection_execution import WorkflowFinalSelectionEngine
from full_theory.social_feedback_binding import SocialPostUseBinding
from full_theory.social_feedback_binding_audit import audit_social_feedback_binding


def saved(key):
    root=Path(os.environ['FT7_POST_USE_INPUT'])
    row=next(x for x in json.loads((root/'record_index.json').read_text()) if x['key']==key)
    with gzip.open(root/row['file'],'rt',encoding='ascii') as f:k,txs,source,native=codec.loads(f.read())
    e=(SelectionEngine if key.startswith('canonical/') else WorkflowFinalSelectionEngine).restore(native)
    if k!=key or tuple(e.world.journal())!=txs:raise ValueError('saved native source differs')
    return e,source


class SocialFeedbackBindingTests(unittest.TestCase):
    def test_exact_immutable_social_prefix(self):
        e,s=saved('canonical/live');native=e.checkpoint();b=SocialPostUseBinding(e,s);r=loads(b.checkpoint())
        old=loads(r['history_prefix']);now=loads(r['history'])
        self.assertEqual(old['scores'],dict.fromkeys(old['scores'],0));self.assertEqual(now['events'][:len(old['events'])],old['events'])
        self.assertEqual(e.checkpoint(),native)
        self.assertTrue(audit_social_feedback_binding(e,s,b.checkpoint())['source_prefix_exact'])

    def test_two_independent_practices_bind_debits(self):
        e,s=saved('canonical/live');b=SocialPostUseBinding(e,s);r=loads(b.checkpoint())
        self.assertEqual(loads(r['reserve_prefix'])['balance'],3)
        self.assertEqual([x['completion']['balance_after'] for x in r['reserve_bindings']], [2,1,0])
        self.assertEqual([x['tag'] for x in r['windows']],['rehearsal','independent','independent','rehearsal','independent'])
        self.assertTrue(any(loads(r['history'])['scores'].values()))

    def test_strict_deferral_grants_no_later_credit(self):
        e,s=saved('canonical/revoked');b=SocialPostUseBinding(e,s);r=loads(b.checkpoint())
        self.assertEqual(loads(r['reserve'])['balance'],1);self.assertIsNone(r['reserve_bindings'][-1]['completion'])
        later=[x for x in r['windows'] if x['kind']=='later-use']
        self.assertTrue(all(not any(x['event']['credit_delta'].values()) for x in later))
        self.assertFalse(audit_social_feedback_binding(e,s,b.checkpoint())['later_completed'])

    def test_harder_deferral_preserves_preparation_debt(self):
        e,s=saved('canonical/harder');b=SocialPostUseBinding(e,s);r=loads(b.checkpoint())
        self.assertEqual(r['reserve_bindings'][-1]['admission']['preparation'],1)
        self.assertIsNone(r['reserve_bindings'][-1]['completion']);self.assertEqual(loads(r['reserve'])['balance'],1)

    def test_partial_consumer_has_no_completion_debit(self):
        e,s=saved('canonical/partial-consumer/restart-partial');b=SocialPostUseBinding(e,s);r=loads(b.checkpoint())
        self.assertIsNone(r['reserve_bindings'][-1]['completion']);self.assertEqual(loads(r['reserve'])['balance'],1)
        self.assertTrue(all(not any(x['event']['credit_delta'].values()) for x in r['windows'] if x['kind']=='later-use'))

    def test_both_settings_roundtrip(self):
        for setting in ('canonical','workflow'):
            e,s=saved(setting+'/lower-live');b=SocialPostUseBinding(e,s);text=b.checkpoint()
            self.assertEqual(SocialPostUseBinding.restore(text,e,s).checkpoint(),text)
            del e,s,b;gc.collect()

    def test_forged_history_rejected(self):
        e,s=saved('canonical/live');b=SocialPostUseBinding(e,s);r=loads(b.checkpoint());h=loads(r['history'])
        h['scores']['fe']=(h['scores']['fe']+1)%9;r['history']=dumps(h)
        with self.assertRaises(ValueError):audit_social_feedback_binding(e,s,dumps(r))

    def test_forged_reserve_rejected(self):
        e,s=saved('canonical/live');b=SocialPostUseBinding(e,s);r=loads(b.checkpoint());r['reserve_bindings'][-1]['completion']=None
        with self.assertRaises(ValueError):audit_social_feedback_binding(e,s,dumps(r))
