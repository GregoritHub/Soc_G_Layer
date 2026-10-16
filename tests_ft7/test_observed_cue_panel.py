import unittest
from hle_unified.selection_records import loads,dumps
from hle_unified.self_content import decode
from full_theory.observed_cue_panel import build
from full_theory.observed_cue_panel_audit import audit
CONTEXT={}

class ObservedCuePanelTests(unittest.TestCase):
    def test_complete_panel(self):
        for n,s,b,k,r in CONTEXT['rows']:
            d=loads(r);self.assertEqual(dumps(d),r);self.assertTrue(audit(n,s,b,k,r)['passed'])
            self.assertEqual([(x['cue'],x['mask']) for x in d['rows']],[(c,m) for c in d['cues'] for m in range(1,16)])
    def test_exact_payload_and_prefixes(self):
        for n,s,b,k,r in CONTEXT['rows']:
            d=loads(r);self.assertEqual(d['history'],loads(b)['history']);self.assertEqual(d['controller_prefix'],loads(s)['demand_controller'])
            key='weights' if k=='canonical' else 'priorities';base=None
            for row in d['rows']:
                payload=decode(row['payload']);self.assertEqual(payload.pop(key),tuple(10*((row['mask']>>i)&1) for i in range(4)))
                if base is None:base=payload
                self.assertEqual(payload,base)
    def test_all_authority_false(self):
        for *_,r in CONTEXT['rows']:
            d=loads(r)
            for k in ('intake_paid','comparison_paid','execution_authorized','td5_admitted','history_choice'):self.assertIs(d[k],False)
            self.assertTrue(all(x['intake_paid'] is False for x in d['rows']))
    def test_history_partition(self):
        for *_,r in CONTEXT['rows']:
            d=loads(r);self.assertEqual(sum(x['historical_only'] for x in d['rows']),15)
            self.assertTrue(all(x['historical_only']==(x['cue']==d['original_cue']) for x in d['rows']))
    def test_input_mismatch_rejected(self):
        for n,s,b,k,r in CONTEXT['rows']:
            for values in ((n+' ',s,b),(n,s+' ',b),(n,s,b+' ')):
                with self.assertRaises(ValueError):build(*values,k)
                with self.assertRaises(ValueError):audit(*values,k,r)
    def test_report_forgery_rejected(self):
        for n,s,b,k,r in CONTEXT['rows']:
            d=loads(r)
            for key,value in [('rows',d['rows'][:-1]),('cues',()),('fulfilled_needs',()),('cue_evidence',()),('intake_paid',True),('history_choice',True),('controller_prefix','{}')]:
                altered=dict(d);altered[key]=value
                with self.assertRaises(ValueError):audit(n,s,b,k,dumps(altered))
                CONTEXT['probes']+=1
