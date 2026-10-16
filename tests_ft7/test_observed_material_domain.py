"""Exact new A4 saved-evidence methods; no accepted engine method replay."""
import unittest

RESULTS=[]
PROBES=[]
CONTROLS=[]


class ObservedMaterialDomainTests(unittest.TestCase):
    def test_exact_records_and_staging(self):
        self.assertEqual({(r['setting'],r['record']) for r in RESULTS},
            {(s,n) for s in ('canonical','workflow') for n in ('before','inspect-partial','read-partial','complete','restarted','cancelled')})
        self.assertEqual(len(RESULTS),12)
        for r in RESULTS:
            settled=r['record'] in ('complete','restarted')
            self.assertIs(r['settled'],settled)
            if not settled:
                self.assertEqual(r['observations'],0);self.assertEqual(r['alternatives'],{})

    def test_independent_reconstruction(self):
        self.assertTrue(RESULTS)
        self.assertTrue(all(r['passed'] for r in RESULTS))
        for r in RESULTS:
            if r['settled']:
                self.assertEqual(r['observations'],8 if r['setting']=='canonical' else 10)
                self.assertGreater(r['foreign_observations'],0)

    def test_revision_policy_and_provenance(self):
        self.assertTrue(all(r['revision_policy_exact'] for r in RESULTS))
        for r in RESULTS:
            if r['settled']:
                self.assertEqual(r['revision2'],3)
                self.assertTrue(all(n>1 for n in r['alternatives'].values()))

    def test_no_authority_or_mutation(self):
        self.assertTrue(RESULTS)
        self.assertTrue(all(r['unchanged'] and r['native_work']==0 for r in RESULTS))
        self.assertEqual(sum(p['name']=='output_authority' and p['rejected'] for p in PROBES),2)

    def test_restart_and_permutation(self):
        for setting in ('canonical','workflow'):
            rows={r['record']:r for r in RESULTS if r['setting']==setting}
            self.assertEqual(rows['complete']['projection_sha256'],rows['restarted']['projection_sha256'])
        self.assertEqual({(c['setting'],c['name']) for c in CONTROLS},
            {(s,n) for s in ('canonical','workflow') for n in ('permutation','bool_quantity','removed_read','changed_target')})
        self.assertEqual(len(CONTROLS),8);self.assertTrue(all(c['passed'] for c in CONTROLS))

    def test_adversarial_bindings_and_output(self):
        names=('refresh_actor','refresh_extra','native_pair','view_pair','unknown_setting','output_authority',
               'output_reference','output_evidence','output_missing_observation','output_extra')
        self.assertEqual({(p['setting'],p['name']) for p in PROBES},{(s,n) for s in ('canonical','workflow') for n in names})
        self.assertEqual(len(PROBES),20);self.assertTrue(all(p['rejected'] for p in PROBES))
