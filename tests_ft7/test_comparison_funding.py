import unittest
ROWS=[];PROBES=[];BOUNDARIES=[];COSTS=[]


class ComparisonFundingTests(unittest.TestCase):
    def test_exact_real_panel(self):
        self.assertEqual(len(ROWS),4);self.assertEqual({(r['setting'],r['record']) for r in ROWS},
            {(s,r) for s in ('canonical','workflow') for r in ('complete','restored')})
        self.assertTrue(all(r['passed'] for r in ROWS))
    def test_current_wallet_and_floor(self):
        for r in ROWS:
            self.assertEqual(r['energy'],r['time'])
            self.assertEqual(r['energy_deficit'],max(0,r['assignments']-r['energy']))
            if r['setting']=='workflow':self.assertEqual(r['status'],'insufficient_lower_bound');self.assertGreater(r['energy_deficit'],0)
            else:self.assertEqual(r['status'],'exact_quote_required')
    def test_boundary_cases(self):
        self.assertEqual(len(BOUNDARIES),6)
        for b in BOUNDARIES:
            r=b['result'];short=b['energy']<b['assignments'] or b['time']<b['assignments']
            self.assertEqual(r['status'],'insufficient_lower_bound' if short else 'exact_quote_required')
            self.assertEqual(r['energy_deficit'],max(0,b['assignments']-b['energy']))
            self.assertEqual(r['time_deficit'],max(0,b['assignments']-b['time']))
    def test_forgery_rejection(self):
        self.assertEqual(len(PROBES),29);self.assertTrue(all(p['rejected'] for p in PROBES))
        for s in ('canonical','workflow'):self.assertEqual(len([p for p in PROBES if p['setting']==s]),12)
    def test_never_grants_affordability(self):
        for r in ROWS+[b['result'] for b in BOUNDARIES]:
            self.assertIs(r['may_launch'],False);self.assertIs(r['exact_quote'],False);self.assertNotEqual(r['status'],'affordable')
    def test_inherited_cost_floor(self):
        self.assertEqual(len(COSTS),2);self.assertTrue(all(c['exact_expressions'] and c['rejected_floor']==c['successful_constant_floor']==1 for c in COSTS))
