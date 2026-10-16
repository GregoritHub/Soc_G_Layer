"""Checks over exact independently audited actual native records, not simulated stubs."""
import unittest
RESULTS=None


class OwnedMaterialInspectionTests(unittest.TestCase):
    def rows(self):
        self.assertIsNotNone(RESULTS,'run through frozen evaluator with actual native evidence')
        return {(r['setting'],r['record']):r for r in RESULTS}

    def test_exact_two_setting_six_record_panel(self):
        rows=self.rows();self.assertEqual(len(rows),12)
        self.assertEqual({k[1] for k in rows},{'before','inspect-partial','read-partial','complete','restarted','cancelled'})
        self.assertTrue(all(x['passed'] for x in rows.values()))

    def test_actual_native_payment(self):
        rows=self.rows()
        for s in ('canonical','workflow'):
            r=rows[s,'complete'];self.assertGreater(r['receipts'],0)
            self.assertEqual((r['energy'],r['time']),(5*r['receipts'],)*2)
            self.assertEqual(r['inventory'],r['receipts']+r['rejected'])

    def test_partial_work_withholds_owned_observation(self):
        rows=self.rows()
        for s in ('canonical','workflow'):
            self.assertEqual(rows[s,'before']['energy'],0)
            for name,cost in (('inspect-partial',1),('read-partial',4)):
                r=rows[s,name];self.assertEqual(r['receipts'],0);self.assertEqual(r['energy'],cost)

    def test_exact_restart_summary(self):
        rows=self.rows()
        for s in ('canonical','workflow'):
            for k in ('inventory','receipts','rejected','energy','time','phase'):
                self.assertEqual(rows[s,'complete'][k],rows[s,'restarted'][k])

    def test_cancellation_has_no_refund_or_receipt(self):
        rows=self.rows()
        for s in ('canonical','workflow'):
            r=rows[s,'cancelled'];self.assertEqual(r['phase'],'cancelled')
            self.assertEqual((r['energy'],r['time'],r['receipts']),(1,1,0))

    def test_complete_and_rejected_inventory_accounted(self):
        for (s,name),r in self.rows().items():
            self.assertLessEqual(r['inventory'],128)
            if name in ('complete','restarted'):
                self.assertEqual(r['phase'],'complete');self.assertGreater(r['rejected'],0)

if __name__=='__main__':unittest.main()
