"""Exact aggregate checks for the bounded A12E2 evaluation."""
import unittest


SUMMARY = None


class CurrentDomainQuotationTests(unittest.TestCase):
    def test_all_thirty_exact_quote_bindings(self):
        self.assertEqual(SUMMARY["records"], 30)
        self.assertEqual(SUMMARY["audits"], 30)
        self.assertEqual(set(SUMMARY["settings"]), {"canonical", "workflow"})

    def test_complete_ordered_request_rows(self):
        self.assertEqual(SUMMARY["canonical_assignments"], [1728] * 15)
        self.assertEqual(SUMMARY["workflow_assignments"], [12384] * 15)
        self.assertEqual(SUMMARY["ordered_reports"], 30)

    def test_exact_native_cost_formula(self):
        self.assertTrue(SUMMARY["all_formula_exact"])
        self.assertEqual(SUMMARY["native_view_calls"], 211680)
        self.assertEqual(SUMMARY["audit_view_calls"], 211680)

    def test_exact_wallet_affordability(self):
        self.assertEqual(SUMMARY["affordable"] + SUMMARY["insufficient"], 30)
        self.assertTrue(SUMMARY["wallets_exact"])

    def test_read_only_native_state(self):
        self.assertEqual(SUMMARY["native_work_calls"], 0)
        self.assertEqual(SUMMARY["accepted_stage_replays"], 0)
        self.assertTrue(SUMMARY["native_states_unchanged"])

    def test_forgery_and_truncation_rejected(self):
        self.assertGreaterEqual(SUMMARY["forgery_rejections"]["canonical"], 16)
        self.assertGreaterEqual(SUMMARY["forgery_rejections"]["workflow"], 16)
        self.assertTrue(SUMMARY["truncation_rejected"])


