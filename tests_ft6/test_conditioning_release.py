from copy import deepcopy
import unittest

from full_theory.conditioning_release import decide_conditioning_release, occupancy
from full_theory.conditioning_release_audit import audit_release, audit_training

CONTEXT = None


class ConditioningReleaseTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        if CONTEXT is None:
            raise RuntimeError("Run the frozen FT6.3b evaluator with the exact accepted archive")
        cls.c = CONTEXT

    def test_exact_input_and_predecessor_identities(self):
        self.assertTrue(self.c["input_hashes_verified"])
        self.assertTrue(self.c["accepted_source_verified"])
        self.assertEqual(len(self.c["predecessor_ids"]), 255)
        self.assertEqual(len(set(self.c["predecessor_ids"])), 255)

    def test_saved_grid_and_training_reconstruct_independently(self):
        self.assertEqual(self.c["grid_audit"]["executions"], 228)
        self.assertTrue(self.c["grid_audit"]["passed"])
        self.assertTrue(all(x["passed"] for x in self.c["training_audits"]))

    def test_training_matches_all_saved_paid_history_events(self):
        self.assertEqual(len(self.c["training_audits"]), 3)
        self.assertTrue(all(x["paid_history_bound"] and x["episodes"] == 6 for x in self.c["training_audits"]))

    def test_unique_training_pair_persists_on_held_out_schedule(self):
        train = self.c["decision"]["training"]
        self.assertTrue(train["stabilized"])
        self.assertTrue(any(g["held_out_persistence"] for g in self.c["decision"]["policy_gates"].values()))

    def test_causal_controls_remove_choice_effect(self):
        self.assertTrue(all(g["causal"] for g in self.c["decision"]["policy_gates"].values()))
        self.assertTrue(all(len(g["discriminating_demands"]) >= 1 for g in self.c["decision"]["policy_gates"].values()))

    def test_changed_and_fixed_bias_counterexamples_are_preserved(self):
        outcomes = self.c["decision"]["outcomes"]
        self.assertEqual(len(outcomes), 15)
        self.assertTrue(all(len(x["decisions"]) == 12 for x in outcomes))
        self.assertEqual(sum(x["history"] == "fixed-bias" for x in outcomes), 3)
        self.assertTrue(any(x["held_out"]["cell"] != self.c["decision"]["training"]["cell"] for x in outcomes))

    def test_selection_matches_prospective_rule_and_independent_auditor(self):
        self.assertTrue(self.c["release_audit"]["passed"])
        self.assertEqual(self.c["decision"]["selected_policy"], self.c["release_audit"]["selected_policy"])
        d = self.c["decision"]
        expected = ("success-decay-v1" if d["policy_gates"]["success-decay-v1"]["eligible"] and d["decay_distinct_demands"]
                    else "success-v1" if d["policy_gates"]["success-v1"]["eligible"] else "null")
        self.assertEqual(d["selected_policy"], expected)

    def test_synthetic_decay_distinction_selects_decay_without_tuning(self):
        report = deepcopy(self.c["report"])
        for row in report["primary"]:
            if (row["policy"], row["history"], row["demand_id"]) == ("success-decay-v1", "independent-use", "C4"):
                row["choice"]["chosen"]["identity"] = "synthetic-changed-response"
        decision = decide_conditioning_release(report, self.c["episodes"], self.c["grid_audit"])
        self.assertEqual(decision["selected_policy"], "success-decay-v1")
        self.assertEqual(decision["decay_distinct_demands"], ("C4",))
        self.assertTrue(audit_release(report, self.c["episodes"], decision, self.c["grid_audit"])["passed"])

    def test_synthetic_no_causal_effect_holds_behavioral_gate(self):
        report = deepcopy(self.c["report"])
        for row in report["controls"]:
            primary = next(r for r in report["primary"] if r["policy"] == row["policy"]
                           and r["history"] == "independent-use" and r["demand_id"] == row["demand_id"])
            row["choice"]["chosen"]["identity"] = primary["choice"]["chosen"]["identity"]
        decision = decide_conditioning_release(report, self.c["episodes"], self.c["grid_audit"])
        self.assertEqual((decision["selected_policy"], decision["engineering_gate"]), ("null", "held"))
        self.assertTrue(audit_release(report, self.c["episodes"], decision, self.c["grid_audit"])["passed"])

    def test_synthetic_insufficient_and_tied_occupancy_hold_stabilization(self):
        self.assertFalse(occupancy(("H",) * 5)["stabilized"])
        self.assertFalse(occupancy(("H", "N") * 3)["stabilized"])
        episodes = deepcopy(self.c["episodes"])
        for index, episode in enumerate(episodes):
            episode["dcnh_cell"] = "H" if index < 3 else "N"
        decision = decide_conditioning_release(self.c["report"], episodes, self.c["grid_audit"])
        self.assertEqual(decision["engineering_gate"], "held")
        self.assertTrue(audit_release(self.c["report"], episodes, decision, self.c["grid_audit"])["passed"])

    def test_forged_decision_and_unpaid_episode_are_rejected(self):
        decision = deepcopy(self.c["decision"])
        decision["selected_policy"] = "forged"
        with self.assertRaises(ValueError):
            audit_release(self.c["report"], self.c["episodes"], decision, self.c["grid_audit"])
        records = deepcopy(self.c["training"])
        records[0][2]["target_seat"] = records[0][2]["origin_seat"]
        with self.assertRaises(ValueError):
            audit_training(self.c["baseline"], records, self.c["histories"]["success-v1|independent-use"][0])
        report = deepcopy(self.c["report"])
        report["primary"][0]["execution"]["paid"] = False
        with self.assertRaises(ValueError):
            decide_conditioning_release(report, self.c["episodes"], self.c["grid_audit"])

    def test_subtype_and_permanent_history_boundaries_remain_explicit(self):
        self.assertIsNone(self.c["decision"]["subtype_assignment"])
        self.assertFalse(self.c["decision"]["permanent_history_changed"])
        self.assertEqual(self.c["decision"]["full_subtype_claim"], "held pending author interpretation")
