from copy import deepcopy
from dataclasses import replace
import json
from pathlib import Path
import unittest

from hle_unified.selection_records import dumps, loads
from tests_c6 import fixtures as c6

from full_theory.conditioning_feedback import (bind_choice, choose_candidate,
    compensation_episode, measured_occupancy)
from full_theory.conditioning_feedback_audit import (audit_binding, audit_choice,
    audit_episode, audit_occupancy)
from full_theory.retention import Demand
from full_theory.route_policy import IntegratedRoutePolicy
from full_theory.use_history import UseHistoryLedger, classifications_for


def outcome(route):
    return dict(status="succeeded", supported=False, rehearsal=False,
                demand_id="ft6.2-demand", route_id=route)


def candidate(actor, identity, key, elements, *, eligible=True, priority=2,
              native_time=10, extra_energy=0):
    return dict(identity=identity, actor=actor, request_key=key, eligible=eligible,
        priority=priority, native_time=native_time, extra_energy=extra_energy,
        elements=tuple(elements))


def finish(engine, request, demand):
    controller = IntegratedRoutePolicy()
    for _ in range(32):
        event = controller.step(engine, request, demand, work_limit=1000000)
        if event["phase"] in ("complete", "deferred", "failed", "cancelled", "rejected"):
            break
    else:
        raise AssertionError("bounded n route did not stop")
    if event["phase"] != "complete" or event["selected"] != "n":
        raise AssertionError("fixture did not complete actual n traffic")
    return controller


def method_ids(suite):
    for item in suite:
        if isinstance(item, unittest.TestSuite):
            yield from method_ids(item)
        else:
            yield item.id()


class ConditioningFeedbackTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        engine, request = c6.fixture("Understand", "accumulation", tim="eii")
        required = Demand("canonical", request.context, request.cue, request.target,
            requirements=("experience", "norms"))
        actor = request.actor

        first_request = replace(request, key="ft62-training-n")
        first = finish(engine, first_request, required)
        first_checkpoint = first.checkpoint(engine)
        all_transactions = tuple(engine.world.journal())
        first_episode = compensation_episode(
            all_transactions, first_checkpoint, actor, first_request.key)
        baseline = all_transactions[:first_episode["journal_window"][0]]
        rows = classifications_for(baseline, all_transactions, actor, 1,
                                   "independent", outcome(first_request.key))
        history = UseHistoryLedger(actor, "success-v1", baseline)
        history.observe(all_transactions, 1, rows)
        history_checkpoint = history.checkpoint()
        actual = first_episode["actual_elements"]
        alternative_element = next(element for element, score in history.scores.items()
                                   if score == 0)
        chosen_request = replace(request, key="ft62-chosen-n")
        candidates = (
            candidate(actor, "a-stable-untrained", "ft62-unused-n",
                      (alternative_element,) * len(actual)),
            candidate(actor, "z-history-trained", chosen_request.key, actual),
        )
        choice = choose_candidate(candidates, history_checkpoint)
        second = finish(engine, chosen_request, required)
        second_checkpoint = second.checkpoint(engine)
        transactions = tuple(engine.world.journal())
        binding = bind_choice(choice, transactions, second_checkpoint)

        episodes = [first_episode, compensation_episode(
            transactions, second_checkpoint, actor, chosen_request.key)]
        checkpoints = [(all_transactions, first_checkpoint),
                       (transactions, second_checkpoint)]
        for index in range(2, 6):
            current = replace(request, key=f"ft62-repeat-n-{index}")
            controller = finish(engine, current, required)
            current_transactions = tuple(engine.world.journal())
            checkpoint = controller.checkpoint(engine)
            episodes.append(compensation_episode(
                current_transactions, checkpoint, actor, current.key))
            checkpoints.append((current_transactions, checkpoint))

        null = UseHistoryLedger(actor, "null", baseline)
        null.observe(all_transactions, 1, rows)
        cls.actor = actor
        cls.history_checkpoint = history_checkpoint
        cls.null_checkpoint = null.checkpoint()
        cls.candidates = candidates
        cls.choice = choice
        cls.binding = binding
        cls.binding_transactions = transactions
        cls.binding_checkpoint = second_checkpoint
        cls.episodes = tuple(episodes)
        cls.checkpoints = tuple(checkpoints)

    def test_candidate_domain_and_actor_history_identity_are_exact(self):
        bad = deepcopy(self.candidates[0]); bad["actor"] = "foreign"
        with self.assertRaises(ValueError):
            choose_candidate((bad,), self.history_checkpoint)
        bad = deepcopy(self.candidates[0]); bad["priority"] = True
        with self.assertRaises(ValueError):
            choose_candidate((bad,), self.history_checkpoint)
        bad = deepcopy(self.candidates[0]); bad["elements"] = ()
        with self.assertRaises(ValueError):
            choose_candidate((bad,), self.history_checkpoint)

    def test_ineligible_priority_and_cost_coordinates_precede_feedback(self):
        trained = deepcopy(self.candidates[1])
        preferred = deepcopy(self.candidates[0]); preferred["identity"] = "cost-winner"
        for field in ("priority", "native_time", "extra_energy"):
            left, right = deepcopy(preferred), deepcopy(trained)
            right[field] = left[field] + 1
            self.assertEqual(choose_candidate((left, right), self.history_checkpoint)["chosen"], left)
        ineligible = deepcopy(trained); ineligible["eligible"] = False
        self.assertEqual(choose_candidate((preferred, ineligible), self.history_checkpoint)["chosen"], preferred)

    def test_non_null_feedback_breaks_only_exact_pre_feedback_ties(self):
        self.assertEqual(self.choice["chosen"]["identity"], "z-history-trained")
        self.assertGreater(self.choice["chosen_feedback_score"], 0)
        self.assertEqual(len({tuple(row["candidate"][field] for field in
            ("priority", "native_time", "extra_energy")) for row in self.choice["tie"]}), 1)

    def test_null_and_feedback_off_preserve_stable_identity_choice(self):
        null = choose_candidate(self.candidates, self.null_checkpoint)
        off = choose_candidate(self.candidates, self.history_checkpoint, feedback=False)
        self.assertEqual((null["chosen"]["identity"], off["chosen"]["identity"]),
                         ("a-stable-untrained", "a-stable-untrained"))
        self.assertFalse(null["feedback_active"] or off["feedback_active"])

    def test_repeated_element_sequence_scores_count_with_multiplicity(self):
        rows = deepcopy(self.candidates)
        trained = next(element for element in rows[1]["elements"])
        rows[0]["elements"] = (trained,)
        rows[1]["elements"] = (trained, trained)
        result = choose_candidate(rows, self.history_checkpoint)
        self.assertEqual(result["chosen"], rows[1])
        self.assertEqual(result["chosen_feedback_score"],
                         2 * loads(self.history_checkpoint)["scores"][trained])

    def test_choice_binding_requires_matching_actual_paid_completion(self):
        self.assertEqual(self.binding["choice"], self.choice["chosen"])
        self.assertEqual(self.binding["actual_elements"], self.choice["chosen"]["elements"])
        forged = deepcopy(self.choice); forged["chosen"]["elements"] = ("se",)
        with self.assertRaises(ValueError):
            bind_choice(forged, self.binding_transactions, self.binding_checkpoint)

    def test_actual_repeated_n_routes_create_paid_compensation_episodes(self):
        self.assertEqual(len(self.episodes), 6)
        self.assertTrue(all(row["actual_elements"] and row["traversal"]["means"] == "n"
                            for row in self.episodes))
        self.assertEqual(len({row["request_key"] for row in self.episodes}), 6)

    def test_n_episode_rejects_counter_label_partial_or_unpaid_traffic(self):
        transactions, checkpoint = self.checkpoints[0]
        data = loads(checkpoint); data["attempts"][0]["selected"]["name"] = "ordinary"
        with self.assertRaises(ValueError):
            compensation_episode(transactions, dumps(data), self.actor,
                                 self.episodes[0]["request_key"])
        partial = transactions[:self.episodes[0]["journal_window"][0]]
        with self.assertRaises(ValueError):
            compensation_episode(partial, checkpoint, self.actor,
                                 self.episodes[0]["request_key"])
        forged = loads(checkpoint); forged["attempts"][0]["status"] = "native"
        with self.assertRaises(ValueError):
            compensation_episode(transactions, dumps(forged), self.actor,
                                 self.episodes[0]["request_key"])

    def test_dcnh_cell_is_derived_from_inherited_n_pair_geometry(self):
        for row in self.episodes:
            self.assertEqual(tuple(sorted((row["origin_seat"], row["target_seat"]))), row["n_pair"])
            self.assertIn(row["dcnh_cell"], "DCNH")
            self.assertFalse(row["completion_claim"])

    def test_latest_six_occupancy_requires_unique_four_of_six(self):
        result = measured_occupancy(self.episodes)
        self.assertEqual((result["status"], result["cell"]),
                         ("unique", self.episodes[-1]["dcnh_cell"]))
        self.assertEqual(result["counts"][result["cell"]], 6)

    def test_ties_and_fewer_than_six_episodes_remain_explicit(self):
        self.assertEqual(measured_occupancy(self.episodes[:5])["status"], "insufficient")
        tied = []
        for index, cell in enumerate("DCDCHN"):
            row = deepcopy(self.episodes[index]); row["dcnh_cell"] = cell; tied.append(row)
        result = measured_occupancy(tied)
        self.assertEqual((result["status"], result["cell"]), ("tie", None))

    def test_independent_auditor_reconstructs_choices_and_episodes(self):
        self.assertTrue(audit_choice(self.choice, self.history_checkpoint)["passed"])
        self.assertTrue(audit_binding(self.choice, self.binding_transactions,
                                      self.binding_checkpoint, self.binding)["passed"])
        for episode, (transactions, checkpoint) in zip(self.episodes, self.checkpoints):
            self.assertTrue(audit_episode(transactions, checkpoint, episode)["passed"])
        occupancy = measured_occupancy(self.episodes)
        self.assertTrue(audit_occupancy(self.episodes, occupancy)["passed"])
        forged = deepcopy(self.choice); forged["chosen_feedback_score"] += 1
        with self.assertRaises(ValueError): audit_choice(forged, self.history_checkpoint)

    def test_ft6_1_and_all_predecessor_method_identity_remain_exact(self):
        from tools.evaluate_ft6_1 import FT4_ROWS, predecessor_expected
        modules = ["tests_ft5.test_reserve_grid", "tests_ft5.test_reserve_recovery",
            "tests_ft5.test_reserve_cycle", "tests_ft5.test_reserve_candidates",
            "tests_ft5.test_native_reserve", "tests_ft5.test_reserve"]
        modules += ["tests_ft4." + module for _, module, _ in FT4_ROWS]
        predecessor = sorted(method_ids(unittest.defaultTestLoader.loadTestsFromNames(modules)))
        self.assertEqual(predecessor, predecessor_expected())
        protocol = json.loads(Path("contracts/ft/FT6_1_Protocol_v1.json").read_text())
        expected = sorted("tests_ft6.test_use_history.UseHistoryTests." + method
                          for method in protocol["registered_tests"])
        actual = sorted(method_ids(unittest.defaultTestLoader.loadTestsFromName(
            "tests_ft6.test_use_history")))
        self.assertEqual(actual, expected)
        self.assertEqual(len(predecessor) + len(actual), 228)
