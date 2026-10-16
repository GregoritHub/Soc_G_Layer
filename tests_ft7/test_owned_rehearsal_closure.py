import unittest
EXTRA=[];ROWS=[]
class ClosureTests(unittest.TestCase):
    def test_narrow_rejection_evidence(self):
        self.assertEqual(len(EXTRA),6);self.assertEqual(len(set(EXTRA)),6)
        self.assertEqual([(r['setting'],r['label']) for r in ROWS if r['rejections']], [('workflow','complete'),('workflow','restored')])
        self.assertTrue(all(r['rejection_debit']==0 for r in ROWS))
        self.assertTrue(all(r['results'][-1]=='rejected' for r in ROWS if r['rejections']))
