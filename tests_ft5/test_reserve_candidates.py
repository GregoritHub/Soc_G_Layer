from copy import deepcopy
from dataclasses import replace
import inspect
import unittest

from hle_unified.selection_records import dumps, loads
from tests_c3 import fixtures as ca
from tests_c7_workflow import fixtures as wf
from tests_ft4.test_controller import prepared
from tests_ft4.test_route_policy import demand as route_demand

from full_theory.native_reserve import NativeReserveBinding
from full_theory.reserve import ReserveLedger
from full_theory.reserve_candidates import ReserveCandidateController
from full_theory.reserve_candidates_audit import audit_reserve_candidates


def candidate_case(setting="canonical", policy="load-v1", initial=0, load=1):
    engine, _, request, _ = prepared(setting)
    demand = replace(route_demand(setting, request), load=load)
    binding = NativeReserveBinding(engine, ReserveLedger(request.actor, policy, initial=initial))
    controller = ReserveCandidateController(engine, binding)
    row = controller.step(engine, request, demand, work_limit=1)
    return engine, request, demand, controller, row


def pay_preparation(setting, engine, controller):
    if setting == "canonical":
        ca.inspect(engine, key="reserve-preparation")
    else:
        wf.observe(engine, key="reserve-preparation")
    return controller.bind_preparation(engine, ("reserve-preparation",))


class ReserveCandidateTests(unittest.TestCase):
    def test_three_policies_have_separate_exact_candidate_state(self):
        observed = {}
        for policy in ("null", "load-v1", "grade-load-v1"):
            engine, request, demand, controller, row = candidate_case(policy=policy)
            observed[policy] = (row["policy"], row["preparation_required"], row["selected_candidate"])
        self.assertEqual(observed["null"], ("null", 0, "ordinary"))
        self.assertEqual(observed["load-v1"], ("load-v1", 1, "preparation"))
        self.assertEqual(observed["grade-load-v1"], ("grade-load-v1", 1, "preparation"))

    def test_null_and_ample_reserve_delegate_without_preparation(self):
        for policy, initial in (("null", 0), ("load-v1", 1), ("grade-load-v1", 1)):
            engine, request, demand, controller, row = candidate_case(policy=policy, initial=initial)
            self.assertEqual(row["preparation_remaining"], 0)
            self.assertEqual(row["selected_candidate"], "ordinary")
            self.assertIsNotNone(row["route_event"])

    def test_scarce_reserve_selects_preparation_and_preserves_all_routes(self):
        engine, request, demand, controller, row = candidate_case()
        self.assertEqual((row["phase"], row["selected_candidate"]), ("preparation", "preparation"))
        self.assertEqual(tuple(option["name"] for option in row["route_options"]),
            ("retained", "ordinary", "n", "cp", "support", "defer"))
        self.assertEqual(row["provisional_native_selection"]["name"], "ordinary")

    def test_zero_reserve_never_marks_a_route_forbidden(self):
        engine, request, demand, controller, row = candidate_case(initial=0, load=8)
        self.assertEqual(row["preparation_required"], 8)
        self.assertTrue(any(option["eligible"] for option in row["route_options"]))
        self.assertFalse(any("forbidden" in option for option in row["route_options"]))
        self.assertEqual(row["provisional_native_selection"]["name"], "ordinary")

    def test_paid_preparation_changes_readiness_then_native_route_launches(self):
        for setting in ("canonical", "workflow"):
            engine, request, demand, controller, first = candidate_case(setting)
            paid = pay_preparation(setting, engine, controller)
            self.assertTrue(paid["complete"])
            second = controller.step(engine, request, demand, work_limit=1)
            self.assertEqual(second["preparation_remaining"], 0)
            self.assertNotEqual(second["selected_candidate"], "preparation")
            self.assertIsNotNone(second["route_event"])

    def test_preparation_term_is_separate_from_native_overhead_and_wallet_price(self):
        engine, request, demand, controller, row = candidate_case()
        wallet = deepcopy(engine.wallet(request.actor)); checkpoint = engine.checkpoint()
        again = controller.step(engine, request, demand, work_limit=1)
        self.assertEqual((engine.checkpoint(), engine.wallet(request.actor)), (checkpoint, wallet))
        self.assertEqual(again["reserve_preparation_units"], 1)
        self.assertEqual(again["native_overhead"], row["provisional_native_selection"]["overhead"])
        self.assertNotIn("reserve", again["native_overhead"])

    def test_canonical_and_workflow_route_priority_remain_native_owned(self):
        for setting in ("canonical", "workflow"):
            engine, request, demand, controller, first = candidate_case(setting)
            self.assertEqual(first["provisional_native_selection"]["name"], "ordinary")
            pay_preparation(setting, engine, controller)
            ready = controller.step(engine, request, demand, work_limit=1)
            self.assertEqual(ready["selected_candidate"], "ordinary")
            self.assertEqual(controller.route_policy.attempts[0]["selected"]["name"], "ordinary")

    def test_step_accepts_no_route_recipe_target_seat_or_success_input(self):
        parameters = tuple(inspect.signature(ReserveCandidateController.step).parameters)
        for forbidden in ("route", "recipe", "target_seat", "preparation", "reserve_result", "success"):
            self.assertNotIn(forbidden, parameters)

    def test_checkpoint_continuation_is_exact(self):
        engine, request, demand, controller, row = candidate_case("workflow")
        restored = ReserveCandidateController.restore(controller.checkpoint(engine), engine)
        left = controller.step(engine, request, demand, work_limit=1)
        right = restored.step(engine, request, demand, work_limit=1)
        self.assertEqual(left, right)
        self.assertEqual(controller.checkpoint(engine), restored.checkpoint(engine))

    def test_independent_auditor_reconstructs_candidate_transitions(self):
        for setting in ("canonical", "workflow"):
            engine, request, demand, controller, row = candidate_case(setting)
            report = audit_reserve_candidates(engine, controller.checkpoint(engine))
            self.assertTrue(report["passed"])
            self.assertEqual(report["preparation_events"], 1)
            pay_preparation(setting, engine, controller)
            controller.step(engine, request, demand, work_limit=1)
            report = audit_reserve_candidates(engine, controller.checkpoint(engine))
            self.assertEqual(report["delegated_events"], 1)

    def test_independent_auditor_rejects_forged_policy_readiness_and_routes(self):
        engine, request, demand, controller, row = candidate_case()
        original = loads(controller.checkpoint(engine))
        mutations = []
        forged = deepcopy(original); forged["events"][0]["policy"] = "null"; mutations.append(forged)
        forged = deepcopy(original); forged["events"][0]["preparation_remaining"] = 0; mutations.append(forged)
        forged = deepcopy(original); forged["events"][0]["route_options"][1]["name"] = "forged"; mutations.append(forged)
        for value in mutations:
            with self.assertRaises(ValueError):
                audit_reserve_candidates(engine, dumps(value))

    def test_ft5_2a_and_all_predecessor_method_identity_remain_exact(self):
        modules = ("tests_ft5.test_native_reserve", "tests_ft5.test_reserve",
            "tests_ft4.test_demands", "tests_ft4.test_requests", "tests_ft4.test_controller",
            "tests_ft4.test_route_means", "tests_ft4.test_route_execution", "tests_ft4.test_orientation",
            "tests_ft4.test_route_policy", "tests_ft4.test_opposition", "tests_ft4.test_autonomous_cycle",
            "tests_ft4.test_autonomous_closure", "tests_ft4.test_autonomous_capability",
            "tests_ft4.test_autonomous_reuse")
        identities = []
        for name in modules:
            stack = list(unittest.defaultTestLoader.loadTestsFromName(name))
            while stack:
                item = stack.pop()
                if isinstance(item, unittest.TestSuite): stack.extend(list(item))
                else: identities.append(item.id())
        self.assertEqual((len(identities), len(set(identities))), (159, 159))
