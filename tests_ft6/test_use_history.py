from copy import deepcopy
from dataclasses import replace
import unittest

from hle_unified.conditioning_audit import ELEMENTS, completed_use
from hle_unified.energy_audit import blocks
from hle_unified.material import attrs, attributes
from hle_unified.selection_records import dumps, loads
from tests_energy.fixtures import factory
from tests_workflow_selection.final_fixtures import final_fixture

from full_theory.use_history import (DECAY_IDLE, POLICIES, RECENT_LIMIT, SCORE_CAP,
    TAGS, UseHistoryLedger, _transition, classifications_for, native_snapshot)
from full_theory.use_history_audit import audit_use_history


def outcome(tag, turn=1):
    values = {
        "independent": ("succeeded", False, False),
        "rehearsal": ("succeeded", False, True),
        "supported": ("succeeded", True, False),
        "failed": ("failed", False, False),
    }
    status, supported, rehearsal = values[tag]
    return dict(status=status, supported=supported, rehearsal=rehearsal,
                demand_id=f"demand-{turn}", route_id=f"route-{turn}")


def exact_methods(modules):
    identities = []
    for name in modules:
        stack = list(unittest.defaultTestLoader.loadTestsFromName(name))
        while stack:
            item = stack.pop()
            if isinstance(item, unittest.TestSuite):
                stack.extend(list(item))
            else:
                identities.append(item.id())
    return identities


class UseHistoryTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        engine, request, _ = final_fixture(
            "Contemplate", "accumulation", factory("grade-v1"))
        actor = request.actor
        snapshots = []
        baseline = None
        for index in range(10):
            current = replace(request, key=f"ft6-paid-{index}")
            engine.start(f"ft6-start-{index}", current)
            engine.advance(f"ft6-select-{index}", actor, current.key, 10000)
            engine.commit(f"ft6-select-commit-{index}", actor, current.key)
            key = current.key + ":movement"
            status = engine.job_status(actor, key)
            boundary = next(end for _, end, _, element in blocks(status)
                            if element is not None)
            if baseline is None:
                baseline = tuple(engine.world.journal())
            engine.advance(f"ft6-use-{index}", actor, key, boundary)
            snapshots.append(tuple(engine.world.journal()))
            engine.cancel(f"ft6-cancel-{index}", actor, key)
        cls.actor = actor
        cls.baseline = baseline
        cls.snapshots = tuple(snapshots)

    def rows(self, before, after, turn, tag="independent"):
        return classifications_for(before, after, self.actor, turn, tag,
                                   outcome(tag, turn))

    def test_exact_policy_tag_element_and_state_domains(self):
        self.assertEqual(POLICIES, ("null", "success-v1", "success-decay-v1"))
        self.assertEqual(TAGS, ("independent", "rehearsal", "supported", "failed"))
        self.assertEqual(tuple(ELEMENTS), ("ne", "ni", "se", "si", "te", "ti", "fe", "fi"))
        self.assertEqual((SCORE_CAP, DECAY_IDLE, RECENT_LIMIT), (8, 4, 32))
        for invalid in ("unknown", None, 1):
            with self.assertRaises(ValueError):
                UseHistoryLedger(self.actor, invalid, self.baseline)

    def test_native_snapshot_counts_only_committed_paid_completion(self):
        before = native_snapshot(self.baseline, self.actor)
        after = native_snapshot(self.snapshots[0], self.actor)
        delta = {element: after["counts"][element] - before["counts"][element]
                 for element in ELEMENTS}
        self.assertEqual(sum(delta.values()), 1)
        self.assertEqual(set(delta.values()), {0, 1})
        self.assertNotEqual(before["journal_sha256"], after["journal_sha256"])
        last = self.snapshots[0][-1]
        versions = tuple(v for v in last.versions
                         if attrs(v).get("record_type") != "wallet")
        forged = self.snapshots[0][:-1] + (replace(last, versions=versions),)
        with self.assertRaises(ValueError):
            native_snapshot(forged, self.actor)

    def test_classifications_exactly_exhaust_native_element_deltas(self):
        rows = self.rows(self.baseline, self.snapshots[0], 1)
        ledger = UseHistoryLedger(self.actor, "success-v1", self.baseline)
        event = ledger.observe(self.snapshots[0], 1, rows)
        self.assertEqual(len(event["classifications"]), 1)
        with self.assertRaises(ValueError):
            UseHistoryLedger(self.actor, "success-v1", self.baseline).observe(
                self.snapshots[0], 1, ())
        forged = rows + (deepcopy(rows[0]),)
        with self.assertRaises(ValueError):
            UseHistoryLedger(self.actor, "success-v1", self.baseline).observe(
                self.snapshots[0], 1, forged)

    def test_successful_independent_use_adds_one_only_to_non_null_policies(self):
        rows = self.rows(self.baseline, self.snapshots[0], 1)
        element = rows[0]["element"]
        for policy, expected in (("null", 0), ("success-v1", 1),
                                 ("success-decay-v1", 1)):
            ledger = UseHistoryLedger(self.actor, policy, self.baseline)
            ledger.observe(self.snapshots[0], 1, rows)
            self.assertEqual(ledger.scores[element], expected)

    def test_rehearsal_supported_and_failed_use_never_add_independent_credit(self):
        for tag in ("rehearsal", "supported", "failed"):
            rows = self.rows(self.baseline, self.snapshots[0], 1, tag)
            ledger = UseHistoryLedger(self.actor, "success-v1", self.baseline)
            ledger.observe(self.snapshots[0], 1, rows)
            element = rows[0]["element"]
            self.assertEqual(ledger.scores[element], 0)
            self.assertEqual(ledger.tag_totals[element][tag], 1)

    def test_scores_saturate_at_eight(self):
        ledger = UseHistoryLedger(self.actor, "success-v1", self.baseline)
        prior = self.baseline
        credited = dict.fromkeys(ELEMENTS, 0)
        for turn, current in enumerate(self.snapshots, 1):
            rows = self.rows(prior, current, turn)
            ledger.observe(current, turn, rows)
            for row in rows:
                credited[row["element"]] += 1
            prior = current
        repeated = max(credited, key=credited.get)
        self.assertGreater(credited[repeated], SCORE_CAP)
        self.assertEqual(ledger.scores[repeated], SCORE_CAP)
        scores = dict.fromkeys(ELEMENTS, 0); scores[repeated] = SCORE_CAP
        idle = dict.fromkeys(ELEMENTS, 0)
        totals = {element: dict.fromkeys(TAGS, 0) for element in ELEMENTS}
        rows = (dict(identity="x", element=repeated, tag="independent",
                     outcome=outcome("independent")),)
        result = _transition("success-v1", scores, idle, totals, rows,
                             {element: int(element == repeated) for element in ELEMENTS})
        self.assertEqual(result[0][repeated], SCORE_CAP)

    def test_decay_occurs_after_exact_four_idle_turns_only(self):
        rows = self.rows(self.baseline, self.snapshots[0], 1)
        element = rows[0]["element"]
        ledger = UseHistoryLedger(self.actor, "success-decay-v1", self.baseline)
        ledger.observe(self.snapshots[0], 1, rows)
        for turn in range(2, 5):
            ledger.observe(self.snapshots[0], turn, ())
            self.assertEqual(ledger.scores[element], 1)
        event = ledger.observe(self.snapshots[0], 5, ())
        self.assertEqual((ledger.scores[element], ledger.idle[element],
                          event["decay_delta"][element]), (0, 0, -1))
        for policy in ("null", "success-v1"):
            other = UseHistoryLedger(self.actor, policy, self.baseline)
            other.observe(self.snapshots[0], 1, rows)
            for turn in range(2, 6):
                other.observe(self.snapshots[0], turn, ())
            self.assertEqual(other.scores[element], int(policy == "success-v1"))

    def test_paid_use_resets_idle_and_recovery_is_a_new_independent_credit(self):
        ledger = UseHistoryLedger(self.actor, "success-decay-v1", self.baseline)
        first = self.rows(self.baseline, self.snapshots[1], 1)
        ledger.observe(self.snapshots[1], 1, first)
        recovery_element = self.rows(self.snapshots[1], self.snapshots[2], 6)[0]["element"]
        self.assertEqual(ledger.scores[recovery_element], 1)
        for turn in range(2, 6):
            ledger.observe(self.snapshots[1], turn, ())
        self.assertEqual(ledger.scores[recovery_element], 0)
        rows = self.rows(self.snapshots[1], self.snapshots[2], 6)
        ledger.observe(self.snapshots[2], 6, rows)
        self.assertEqual((ledger.scores[recovery_element], ledger.idle[recovery_element]), (1, 0))

    def test_null_policy_records_evidence_without_feedback(self):
        ledger = UseHistoryLedger(self.actor, "null", self.baseline)
        rows = self.rows(self.baseline, self.snapshots[0], 1)
        ledger.observe(self.snapshots[0], 1, rows)
        self.assertEqual(set(ledger.scores.values()), {0})
        self.assertEqual(sum(sum(row.values()) for row in ledger.tag_totals.values()), len(rows))
        self.assertTrue(audit_use_history(ledger.checkpoint(), self.snapshots[0])["passed"])

    def test_stale_duplicate_reordered_and_skipped_snapshots_are_rejected(self):
        rows = self.rows(self.baseline, self.snapshots[0], 1)
        ledger = UseHistoryLedger(self.actor, "success-v1", self.baseline)
        ledger.observe(self.snapshots[0], 1, rows)
        with self.assertRaises(ValueError): ledger.observe(self.snapshots[0], 1, ())
        with self.assertRaises(ValueError): ledger.observe(self.snapshots[1], 3,
            self.rows(self.snapshots[0], self.snapshots[1], 3))
        with self.assertRaises(ValueError): ledger.observe(self.baseline, 2, ())
        reordered = self.snapshots[1][:-2] + tuple(reversed(self.snapshots[1][-2:]))
        with self.assertRaises(ValueError): ledger.observe(reordered, 2, ())

    def test_recent_window_is_bounded_and_checkpoint_continuation_is_exact(self):
        ledger = UseHistoryLedger(self.actor, "success-v1", self.baseline)
        ledger.observe(self.snapshots[0], 1, self.rows(self.baseline, self.snapshots[0], 1))
        for turn in range(2, 41):
            ledger.observe(self.snapshots[0], turn, ())
        self.assertEqual((len(ledger.events), ledger.base["event_count"]), (RECENT_LIMIT, 8))
        restored = UseHistoryLedger.restore(ledger.checkpoint())
        left = ledger.observe(self.snapshots[0], 41, ())
        right = restored.observe(self.snapshots[0], 41, ())
        self.assertEqual((left, ledger.checkpoint()), (right, restored.checkpoint()))

    def test_independent_auditor_reconstructs_state_and_rejects_tampering(self):
        ledger = UseHistoryLedger(self.actor, "success-decay-v1", self.baseline)
        rows = self.rows(self.baseline, self.snapshots[0], 1)
        ledger.observe(self.snapshots[0], 1, rows)
        ledger.observe(self.snapshots[0], 2, ())
        report = audit_use_history(ledger.checkpoint(), self.snapshots[0])
        self.assertTrue(report["passed"] and report["native_bound"])
        data = loads(ledger.checkpoint())
        data["events"][0]["scores_after"][rows[0]["element"]] += 1
        with self.assertRaises(ValueError): audit_use_history(dumps(data), self.snapshots[0])
        with self.assertRaises(ValueError): audit_use_history(ledger.checkpoint(), self.snapshots[1])

    def test_ft5_and_all_predecessor_method_identity_remain_exact(self):
        modules = (
            "tests_ft5.test_reserve_grid", "tests_ft5.test_reserve_recovery",
            "tests_ft5.test_reserve_cycle", "tests_ft5.test_reserve_candidates",
            "tests_ft5.test_native_reserve", "tests_ft5.test_reserve",
            "tests_ft4.test_demands", "tests_ft4.test_requests",
            "tests_ft4.test_controller", "tests_ft4.test_route_means",
            "tests_ft4.test_route_execution", "tests_ft4.test_orientation",
            "tests_ft4.test_route_policy", "tests_ft4.test_opposition",
            "tests_ft4.test_autonomous_cycle", "tests_ft4.test_autonomous_closure",
            "tests_ft4.test_autonomous_capability", "tests_ft4.test_autonomous_reuse")
        identities = exact_methods(modules)
        self.assertEqual((len(identities), len(set(identities))), (215, 215))
