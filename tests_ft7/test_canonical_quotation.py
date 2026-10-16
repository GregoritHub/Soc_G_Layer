"""A8 whole-domain evidence controls; no inherited test-body execution."""
import unittest

REPORT={}; ROWS=[]; RAW={}


class CanonicalQuotationTests(unittest.TestCase):
    def test_complete_ordinal_coverage(self):
        self.assertEqual([r['ordinal'] for r in ROWS],list(range(5832)))
        self.assertEqual(len({r['request_sha256'] for r in ROWS}),5832)
        self.assertGreaterEqual(REPORT['request_mapping_samples'],29)

    def test_all_independent_rows(self):
        self.assertEqual(REPORT['independent_rows'],5832)
        self.assertEqual(REPORT['native_view_calls'],5832)
        self.assertEqual(len(REPORT['records']),2)
        self.assertTrue(all(r['passed'] for r in REPORT['records']))
        self.assertTrue(all(r['required']>=1 and (len(r['examined'])==33 if r['rejection'] is None else r['required']==1) for r in ROWS))

    def test_native_immutable(self):
        self.assertTrue(REPORT['native_unchanged'] and REPORT['audit_native_unchanged'])
        self.assertEqual([REPORT[k] for k in ('native_work_calls','engine_restore_calls','accepted_stage_replays')],[0,0,0])
        self.assertEqual(REPORT['prior_identities'],493)

    def test_exact_aggregate_funding(self):
        total=sum(r['required'] for r in ROWS)
        self.assertEqual(RAW['required_energy'],total);self.assertEqual(RAW['required_time'],total)
        self.assertEqual(RAW['energy_deficit'],max(0,total-RAW['energy']))
        self.assertEqual(RAW['time_deficit'],max(0,total-RAW['time']))
        self.assertEqual(RAW['status'],'insufficient_exact_quote' if total>min(RAW['energy'],RAW['time']) else 'affordable_quote_only')
        self.assertEqual(sum(REPORT['cost_histogram'].values()),5832)

    def test_forgery_rejection(self):
        self.assertEqual(len(REPORT['forgery_rejections']),21)
        self.assertEqual(len(set(REPORT['forgery_rejections'])),21)

    def test_authority_and_roundtrip(self):
        self.assertTrue(RAW['exact_quote'])
        self.assertTrue(all(RAW[k] is False for k in ('may_launch','comparison_paid','execution_authorized','td5_admitted','history_choice','parent_accepted')))
        self.assertEqual(REPORT['records'][0]['payload_sha256'],REPORT['records'][1]['payload_sha256'])
        self.assertEqual(REPORT['records'][0]['sha256'],REPORT['records'][1]['sha256'])
