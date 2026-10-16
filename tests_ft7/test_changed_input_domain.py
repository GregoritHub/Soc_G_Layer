"""Six exact new A6 assertions over independently reconstructed saved outputs."""
import unittest

ROWS=[];PROBES=[];INDICES=[];PREFIXES=[];ALGEBRA=[]


class ChangedInputDomainTests(unittest.TestCase):
    def test_exact_saved_panel(self):
        self.assertEqual({(r['setting'],r['record']) for r in ROWS},
            {(s,k) for s in ('canonical','workflow') for k in ('complete','restored')})
        self.assertEqual(len(ROWS),4);self.assertTrue(all(r['passed'] for r in ROWS))

    def test_complete_factorization(self):
        from math import prod
        for r in ROWS:
            self.assertEqual(r['assignments'],r['windows']*prod(r['role_sizes'].values()))
            self.assertEqual(r['windows'],1 if r['setting']=='canonical' else 510)
            self.assertTrue(all(n>=1 for n in r['role_sizes'].values()))

    def test_index_bijection(self):
        self.assertEqual(len(INDICES),2);self.assertTrue(all(x['all_factor_values'] and x['checked']>1 for x in INDICES))
        self.assertEqual(len(ALGEBRA),6);self.assertTrue(all(x['exact'] for x in ALGEBRA))
        self.assertEqual(len([p for p in PROBES if p['setting']=='algebra']),6)

    def test_current_owned_evidence(self):
        self.assertEqual(len(PREFIXES),2);self.assertTrue(all(p['exact'] and p['bindings']>0 and p['receipts']>0 for p in PREFIXES))
        self.assertTrue(all(r['oldest_task_exact'] and r['controller_prefix_exact'] for r in ROWS))
        self.assertEqual({r['setting']:r['observations'] for r in ROWS},{'canonical':8,'workflow':10})

    def test_forgery_rejection(self):
        for setting in ('canonical','workflow'):
            ps=[p for p in PROBES if p['setting']==setting]
            self.assertEqual(len(ps),20);self.assertEqual(len({p['name'] for p in ps}),20)
            self.assertTrue(all(p['rejected'] for p in ps))

    def test_no_native_authority(self):
        for r in ROWS:
            for k in ('comparison_paid','execution_authorized','td5_admitted','history_choice'):self.assertIs(r[k],False)
