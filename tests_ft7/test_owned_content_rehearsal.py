import unittest
ROWS=[];PROBES=[];RESTARTS=[]
class RehearsalTests(unittest.TestCase):
    def test_plan_complete_and_route_free(self):
        self.assertEqual(len(ROWS),10)
        self.assertTrue(all(r['passed'] and 0<r['plan_count']<=32 for r in ROWS))
    def test_exact_paid_native_suffix(self):
        for r in ROWS:
            self.assertTrue(r['prefixes_exact'] and r['cursor_native_only'] and r['no_authority'])
            self.assertEqual(r['energy'],r['time'])
            if r['label']=='complete':self.assertGreater(r['energy'],0);self.assertEqual(len(r['results']),r['plan_count'])
    def test_partial_without_credit(self):
        self.assertEqual([r['energy'] for r in ROWS if r['label']=='before'],[0,0])
        self.assertEqual([r['energy'] for r in ROWS if r['label']=='partial'],[1,1])
        self.assertTrue(all(not r['results'] for r in ROWS if r['label'] in ('before','partial')))
    def test_restart_exact(self):
        self.assertEqual(RESTARTS,[True,True])
    def test_cancel_nonrefundable(self):
        self.assertEqual([r['energy'] for r in ROWS if r['label']=='cancelled'],[1,1])
        self.assertTrue(all(r['phase']=='cancelled' and not r['results'] for r in ROWS if r['label']=='cancelled'))
    def test_forgery_and_pairing_rejected(self):
        self.assertEqual(len(PROBES),16);self.assertEqual(len(set(PROBES)),16)
