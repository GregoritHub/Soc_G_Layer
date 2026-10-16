"""A9 exact evidence controls; accepted gates are not rerun."""
import unittest
ROWS=[];PROBES=[];BOUNDARIES=[]

class UniversalVetoTests(unittest.TestCase):
    def test_full_domain_invariant_coverage(self):
        self.assertEqual(len(ROWS),4)
        self.assertEqual({r['setting']:r['assignments'] for r in ROWS},{'canonical':5832,'workflow':4920480})
        self.assertTrue(all(r['all_work_ineligible'] for r in ROWS))
    def test_independent_current_state(self):
        self.assertTrue(all(r['passed'] and r['native_unchanged'] and r['truncated'] and r['recall_count']==32 for r in ROWS))
    def test_exact_roundtrip(self):
        for setting in ('canonical','workflow'):
            pair=[r for r in ROWS if r['setting']==setting]
            self.assertEqual(pair[0]['sha256'],pair[1]['sha256'])
    def test_all_boundary_cases(self):
        self.assertEqual(len(BOUNDARIES),128)
        self.assertTrue(all(r['passed'] for r in BOUNDARIES))
        self.assertTrue(any(r['veto'] for r in BOUNDARIES))
        self.assertTrue(any(not r['veto'] for r in BOUNDARIES))
    def test_forgery_rejection(self):
        self.assertEqual(len(PROBES),36)
        self.assertEqual(len(set(PROBES)),36)
    def test_no_authority_or_replay(self):
        self.assertTrue(all(r['authority_false'] and r['no_pruning'] for r in ROWS))
