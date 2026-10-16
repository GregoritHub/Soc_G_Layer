"""Exact saved A12E1 gate; context is supplied by the bounded evaluator."""
import unittest
CONTEXT={}
class PostProcessingDomainTests(unittest.TestCase):
    def test_all_thirty_exact_input_bindings(self):
        self.assertEqual(len(CONTEXT['rows']),30);self.assertTrue(all(x['passed'] for x in CONTEXT['rows']))
        self.assertEqual({(x['setting'],x['mask']) for x in CONTEXT['rows']},{(s,m) for s in ('canonical','workflow') for m in range(1,16)})
    def test_complete_current_windows_and_role_proofs(self):
        self.assertTrue(all(x['windows']==(1 if x['setting']=='canonical' else 3) for x in CONTEXT['rows']))
        self.assertTrue(all(all(n>0 for n in x['role_sizes'].values()) for x in CONTEXT['rows']))
    def test_factorized_request_bijection(self):
        self.assertEqual(len(CONTEXT['indices']),30);self.assertTrue(all(x['exact'] and x['checked']>0 for x in CONTEXT['indices']))
        self.assertTrue(all(x['exact'] for x in CONTEXT['algebra']))
    def test_unchanged_oldest_task_and_prefixes(self):
        self.assertTrue(all(x['oldest_task_exact'] and x['prefixes_exact'] for x in CONTEXT['rows']))
    def test_stale_missing_and_forged_evidence_rejected(self):
        self.assertGreaterEqual(sum(x['rejected'] for x in CONTEXT['probes'] if x['setting']=='canonical'),16)
        self.assertGreaterEqual(sum(x['rejected'] for x in CONTEXT['probes'] if x['setting']=='workflow'),16)
    def test_zero_native_work_and_exact_saved_reports(self):
        self.assertTrue(all(x['backup_exact'] and x['typed_exact'] for x in CONTEXT['identities']))
        self.assertTrue(all(not x['native_work'] and not x['engine_restored'] for x in CONTEXT['rows']))
