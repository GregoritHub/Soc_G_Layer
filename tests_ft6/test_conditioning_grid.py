from copy import deepcopy
from dataclasses import replace
from hashlib import sha256
import json
from pathlib import Path
import unittest

from hle_unified.particulars import Selector
from hle_unified import codec
from hle_unified.material import attrs
from hle_unified.selection_execution import SelectionEngine
from hle_unified.selection_records import dumps, loads
from tests_c6 import fixtures as c6
from tests_u4.fixtures import show

from full_theory.conditioning_feedback import compensation_episode
from full_theory.conditioning_grid import HISTORIES, POLICIES, run_matched_grid
from full_theory.conditioning_grid_audit import audit_conditioning_grid
from full_theory.retention import Demand
from full_theory.route_policy import IntegratedRoutePolicy
from full_theory.route_policy_audit import audit_route_policy
from full_theory.use_history import UseHistoryLedger, classifications_for
from full_theory.use_history_audit import audit_use_history


ROOT = Path(__file__).resolve().parents[1]


def _finish(engine, request):
    demand = Demand("canonical", request.context, request.cue, request.target,
                    requirements=("experience", "norms"))
    controller = IntegratedRoutePolicy()
    for _ in range(32):
        event = controller.step(engine, request, demand, work_limit=1000000)
        if event["phase"] in ("complete", "deferred", "failed", "cancelled", "rejected"):
            break
    checkpoint = controller.checkpoint(engine)
    transactions = tuple(engine.world.journal())
    route = audit_route_policy(transactions, engine.access.checkpoint(), checkpoint,
                               engine.checkpoint())
    if event["phase"] != "complete" or event["selected"] != "n" or not route["passed"]:
        raise AssertionError("native n route did not complete and audit")
    episode = compensation_episode(transactions, checkpoint, request.actor, request.key)
    return transactions, checkpoint, episode


def _base(cell):
    action = "Identify" if cell == "N" else "Understand"
    engine, request = c6.fixture(action, "accumulation", tim="eii")
    if cell == "H":
        for index in range(9):
            selector = Selector("ft63extra" + str(index), "name", ("label",))
            show(engine, request.actor, request.target, key="ft63-extra-" + str(index),
                 selectors=(selector,))
    return engine, request


def _history_inputs(training_engine, training_request):
    baseline = tuple(training_engine.world.journal())
    snapshots = []
    prior = baseline
    for turn in range(1, 7):
        request = replace(training_request, key="ft63-training-" + str(turn))
        current, _, _ = _finish(training_engine, request)
        snapshots.append((prior, current))
        prior = current
    return baseline, snapshots, prior


def _schedule(actor, policy, baseline, snapshots, final, tag):
    ledger = UseHistoryLedger(actor, policy, baseline)
    for turn, (before, after) in enumerate(snapshots, 1):
        if tag == "no-use":
            ledger.observe(baseline, turn, ())
        else:
            outcome = dict(status="failed" if tag == "failed" else "succeeded",
                supported=tag == "supported", rehearsal=False,
                demand_id="ft63-training-" + str(turn), route_id="ft63-training-" + str(turn))
            rows = classifications_for(before, after, actor, turn,
                                       "failed" if tag == "failed" else
                                       "supported" if tag == "supported" else "independent",
                                       outcome)
            ledger.observe(after, turn, rows)
    post_training = ledger.checkpoint()
    idle_transactions = baseline if tag == "no-use" else final
    for turn in range(7, 11):
        ledger.observe(idle_transactions, turn, ())
    post_idle = ledger.checkpoint()
    return (post_training,) * 10 + (post_idle,) * 2


class ConditioningGridTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.fixture_path = ROOT / "contracts/ft/FT6_3a_Fixtures_v1.json"
        cls.fixture = json.loads(cls.fixture_path.read_text())
        cls.fixture_digest = sha256(cls.fixture_path.read_bytes()).hexdigest()
        cls.bases = {}
        cls.preflights = {}
        for cell in ("N", "H"):
            engine, request = _base(cell)
            cls.bases[cell] = (engine.checkpoint(), request)
            probe = replace(request, key="ft63-preflight-" + cell)
            transactions, checkpoint, episode = _finish(
                SelectionEngine.restore(engine.checkpoint()), probe)
            cls.preflights[cell] = (transactions, checkpoint, episode)
        training_engine, training_request = _base("H")
        baseline, snapshots, final = _history_inputs(training_engine, training_request)
        actor = training_request.actor
        cls.histories = {}
        cls.removed = {}
        for policy in POLICIES:
            cls.histories[policy + "|independent-use"] = _schedule(
                actor, policy, baseline, snapshots, final, "independent-use")
            for history in ("no-use", "fixed-bias"):
                cls.histories[policy + "|" + history] = _schedule(
                    actor, policy, baseline, snapshots, final, "no-use")
            cls.histories[policy + "|supported-use"] = _schedule(
                actor, policy, baseline, snapshots, final, "supported")
            cls.histories[policy + "|failed-use"] = _schedule(
                actor, policy, baseline, snapshots, final, "failed")
            cls.removed[policy] = _schedule(actor, policy, baseline, snapshots, final, "no-use")
        cls.evidence = {}

        def execute(run_id, chosen):
            cell = "H" if chosen["request_key"].endswith(":H") else "N"
            engine_checkpoint, base_request = cls.bases[cell]
            engine = SelectionEngine.restore(engine_checkpoint)
            request = replace(base_request, key=chosen["request_key"])
            transactions, checkpoint, episode = _finish(engine, request)
            cls.evidence[run_id] = (transactions, checkpoint, episode)
            return dict(run_id=run_id, candidate_identity=chosen["identity"],
                request_key=chosen["request_key"], native_time=55, extra_energy=0,
                means="n", dcnh_cell=episode["dcnh_cell"],
                actual_elements=episode["actual_elements"], paid=True, completed=True,
                route_audit=True,
                journal_sha256=sha256(codec.dumps(transactions).encode()).hexdigest(),
                route_checkpoint_sha256=sha256(checkpoint.encode()).hexdigest())

        cls.report = run_matched_grid(cls.fixture, cls.histories, cls.removed, execute)
        cls.audit = audit_conditioning_grid(cls.report, cls.fixture, cls.histories,
                                            cls.removed, cls.evidence)

    def test_factorial_has_exact_three_by_five_by_twelve_identity_domain(self):
        self.assertEqual((len(self.report["primary"]), len(self.report["controls"])), (180, 48))
        self.assertEqual(len({r["run_id"] for r in self.report["primary"]}), 180)

    def test_fixture_hashes_and_candidate_ties_are_frozen_before_history(self):
        registered = (ROOT / "contracts/ft/FT6_3a_Fixtures_v1.sha256").read_text().split()[0]
        self.assertEqual(self.fixture_digest, registered)
        self.assertTrue(all(len(r["choice"]["tie"]) == 2 and r["choice"]["prefeedback"] == (2, 55, 0)
                            for r in self.report["primary"]))

    def test_all_candidates_are_preflighted_by_actual_paid_native_completion(self):
        for cell, (transactions, checkpoint, episode) in self.preflights.items():
            reference = episode["traversal"]["movement"]
            movement = [version for transaction in transactions for version in transaction.versions
                        if version.ref == reference]
            self.assertEqual((episode["dcnh_cell"], attrs(movement[0])["required"]), (cell, 55))
            self.assertEqual(tuple(episode["actual_elements"]),
                             tuple(self.fixture["alternatives"][cell]["actual_elements"]))

    def test_independent_supported_failed_and_no_use_histories_reconstruct_exactly(self):
        for checkpoints in self.histories.values():
            for checkpoint in {checkpoints[0], checkpoints[-1]}:
                self.assertTrue(audit_use_history(checkpoint)["passed"])
        trained = loads(self.histories["success-v1|independent-use"][0])["scores"]
        self.assertGreater(sum(trained.values()), 0)
        for history in ("no-use", "supported-use", "failed-use"):
            self.assertEqual(sum(loads(self.histories["success-v1|" + history][0])["scores"].values()), 0)

    def test_primary_grid_executes_all_180_cells_without_scheduled_success(self):
        self.assertEqual(len(self.evidence), 228)
        self.assertTrue(all(r["execution"]["completed"] and r["execution"]["paid"]
                            for r in self.report["primary"]))

    def test_every_chosen_request_binds_to_its_actual_paid_element_multiset(self):
        for row in self.report["primary"] + self.report["controls"]:
            self.assertEqual(sorted(row["choice"]["chosen"]["elements"]),
                             sorted(row["execution"]["actual_elements"]))

    def test_null_policy_matches_feedback_off_for_each_fixed_candidate_set(self):
        rows = [r for r in self.report["primary"] if r["policy"] == "null"]
        self.assertTrue(all(not r["choice"]["feedback_active"] for r in rows))
        self.assertTrue(all(r["choice"]["chosen_feedback_score"] == 0 for r in rows))

    def test_history_removal_and_feedback_off_are_exact_one_factor_controls(self):
        trained = [r for r in self.report["primary"] if r["policy"] != "null"
                   and r["history"] == "independent-use"]
        control = {(r["kind"], r["policy"], r["demand_id"]): r for r in self.report["controls"]}
        for row in trained:
            for kind in ("history-removal", "feedback-off"):
                other = control[(kind, row["policy"], row["demand_id"])]
                self.assertEqual(row["choice"]["prefeedback"], other["choice"]["prefeedback"])
                self.assertNotEqual(row["choice"]["chosen"]["identity"],
                                    other["choice"]["chosen"]["identity"])

    def test_fixed_bias_is_score_independent_and_prospectively_identified(self):
        rows = [r for r in self.report["primary"] if r["history"] == "fixed-bias"]
        self.assertTrue(all(not r["choice"]["feedback_enabled"] for r in rows))
        self.assertTrue(all(r["choice"]["chosen"]["identity"] == "a-h-fixed" for r in rows))

    def test_held_out_occupancy_counts_only_completed_paid_n_episodes(self):
        self.assertTrue(all(sum(s["held_out_occupancy"]["counts"].values()) == 6
                            for s in self.report["summaries"]))
        self.assertTrue(all(r["execution"]["means"] == "n" for r in self.report["primary"]))

    def test_changed_schedule_applies_exact_four_turn_decay_before_c4(self):
        before = loads(self.histories["success-decay-v1|independent-use"][9])
        after = loads(self.histories["success-decay-v1|independent-use"][10])
        self.assertEqual(after["turn"] - before["turn"], 4)
        self.assertLess(sum(after["scores"].values()), sum(before["scores"].values()))
        for policy in ("null", "success-v1"):
            b = loads(self.histories[policy + "|independent-use"][9])
            a = loads(self.histories[policy + "|independent-use"][10])
            self.assertEqual(a["scores"], b["scores"])

    def test_ties_counterexamples_and_non_n_choices_are_preserved(self):
        self.assertTrue(any(s["held_out_occupancy"]["cell"] == "N" for s in self.report["summaries"]))
        self.assertTrue(any(s["held_out_occupancy"]["cell"] == "H" for s in self.report["summaries"]))
        bad = deepcopy(self.report)
        bad["primary"][0]["execution"]["paid"] = False
        with self.assertRaises(ValueError):
            audit_conditioning_grid(bad, self.fixture, self.histories, self.removed, self.evidence)

    def test_independent_auditor_reconstructs_full_grid_and_control_contrasts(self):
        self.assertTrue(self.audit["passed"])
        self.assertGreaterEqual(self.audit["discriminating"], 12)

    def test_ft6_2_and_all_predecessor_method_identity_remain_exact(self):
        from tools.evaluate_ft6_2 import predecessor_expected
        from tools.evaluate_ft6_1 import FT4_ROWS
        protocol = json.loads((ROOT / "contracts/ft/FT6_2_Protocol_v1.json").read_text())
        expected = sorted(predecessor_expected() + [
            "tests_ft6.test_conditioning_feedback.ConditioningFeedbackTests." + method
            for method in protocol["registered_tests"]])
        modules = ["tests_ft6.test_conditioning_feedback", "tests_ft6.test_use_history",
            "tests_ft5.test_reserve_grid", "tests_ft5.test_reserve_recovery",
            "tests_ft5.test_reserve_cycle", "tests_ft5.test_reserve_candidates",
            "tests_ft5.test_native_reserve", "tests_ft5.test_reserve"]
        modules += ["tests_ft4." + module for _, module, _ in FT4_ROWS]
        suite = unittest.defaultTestLoader.loadTestsFromNames(modules)
        def ids(value):
            for item in value:
                if isinstance(item, unittest.TestSuite):
                    yield from ids(item)
                else:
                    yield item.id()
        actual = sorted(ids(suite))
        self.assertEqual(actual, expected)
        self.assertEqual(len(actual), 241)
