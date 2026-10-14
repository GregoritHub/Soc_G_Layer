from copy import deepcopy
import inspect
import unittest

from hle.model_a import fields as seat_fields
from hle_unified.selection_records import dumps, loads
from tests_c6 import fixtures as c6
from tests_workflow_selection import fixtures as ws
from tests_ft4.test_demands import state

from full_theory.autonomous_cycle import AutonomousCycleController
from full_theory.autonomous_cycle_audit import audit_autonomous_cycle
from full_theory.retention import Demand


def fixture(setting="canonical", tim="iee", requirements=("experience",)):
    if setting == "canonical":
        engine, supplied = c6.fixture("Understand", "accumulation", tim=tim)
    else:
        engine, supplied, _ = ws.fixture("Contemplate", "accumulation", tim=tim)
    demand = Demand(setting, supplied.context, supplied.cue, supplied.target,
                    requirements=requirements)
    return engine, supplied.actor, demand


def finish(setting="canonical", tim="iee", requirements=("experience",), limit=1000000):
    engine, actor, demand = fixture(setting, tim, requirements)
    controller = AutonomousCycleController()
    for _ in range(64):
        row = controller.step(engine, actor, state(), demand, work_limit=limit)
        if controller.terminal is not None:
            break
    else:
        raise AssertionError("bounded autonomous cycle did not stop")
    report = audit_autonomous_cycle(engine.world.journal(), engine.access.checkpoint(),
        controller.checkpoint(engine), engine.checkpoint())
    return engine, controller, demand, row, report


class AutonomousCycleTests(unittest.TestCase):
    def test_autonomous_cycle_settles_canonical_and_workflow_demands(self):
        for setting in ("canonical", "workflow"):
            engine, controller, demand, row, report = finish(setting)
            self.assertEqual(controller.phase, "complete")
            self.assertEqual(report["settled"], 1)
            self.assertEqual(row["reason"], "settled_after_paid_consumption")

    def test_controller_forms_request_and_selects_route_without_recipe_input(self):
        parameters = inspect.signature(AutonomousCycleController.step).parameters
        for forbidden in ("request", "recipe", "route", "consumer_key", "target_seat", "success"):
            self.assertNotIn(forbidden, parameters)
        engine, controller, demand, row, report = finish()
        formed = controller.events[0]["request"]
        self.assertTrue(formed["key"].startswith("ft-request:"))
        self.assertEqual(controller.route_policy.attempts[0]["selected"]["name"], "ordinary")

    def test_paid_consumer_uses_exact_movement_output_and_scope(self):
        for setting in ("canonical", "workflow"):
            engine, controller, demand, row, report = finish(setting)
            traversal = controller.route_policy.attempts[0]["traversal"]
            consumer = engine.job_status(controller.actor, controller.consumer_key)
            self.assertIn(traversal["movement_output"], consumer.values())
            self.assertEqual((consumer["context"], consumer.get("content_target", consumer.get("target"))),
                             (demand.context, demand.target))
            self.assertEqual(consumer["status"], "succeeded")
            self.assertGreaterEqual(consumer["spent"], consumer["required"])

    def test_unavailable_route_defers_and_keeps_demand_visible(self):
        all_facets = ("experience", "norms", "situation", "time")
        engine, controller, demand, row, report = finish("canonical", "eii", all_facets)
        self.assertEqual(controller.phase, "deferred")
        admitted = next(iter(controller.demand_controller.effective_demands().values()))
        self.assertEqual(admitted["status"], "pending")
        self.assertEqual(report["settled"], 0)
        self.assertEqual(controller.route_policy.attempts[0]["selected"]["name"], "defer")

    def test_conflicting_demands_follow_owned_admission_order(self):
        engine, actor, demand = fixture()
        c6.need(engine, "zzz-second", weights=(0, 10, 0, 0))
        controller = AutonomousCycleController()
        controller.step(engine, actor, state(), demand, work_limit=1)
        event = controller.demand_controller.events[0]
        scan = controller.demand_controller.ledger.events[0]
        self.assertEqual(len(scan["admitted"]), 2)
        self.assertEqual(event["request"]["selected"], sorted(scan["admitted"])[0])
        self.assertEqual(sum(x["status"] == "pending" for x in scan["demands"].values()), 2)

    def test_route_alternatives_and_reasons_are_preserved(self):
        engine, controller, demand, row, report = finish()
        options = controller.route_policy.attempts[0]["options"]
        self.assertEqual(tuple(x["name"] for x in options),
            ("retained", "ordinary", "n", "cp", "support", "defer"))
        self.assertTrue(all(x["reason"] for x in options))

    def test_partial_work_keeps_demand_pending_and_debits_visible(self):
        engine, actor, demand = fixture()
        controller = AutonomousCycleController()
        before = dict(engine.wallet(actor))
        controller.step(engine, actor, state(), demand, work_limit=1)
        controller.step(engine, actor, state(), demand, work_limit=1)
        after = engine.wallet(actor)
        admitted = next(iter(controller.demand_controller.effective_demands().values()))
        self.assertEqual(admitted["status"], "pending")
        self.assertFalse(controller.demand_controller.outcomes)
        self.assertTrue(after["energy"] < before["energy"] or after["time"] < before["time"])

    def test_checkpoint_continuation_is_exact(self):
        engine, actor, demand = fixture("workflow")
        controller = AutonomousCycleController()
        controller.step(engine, actor, state(), demand, work_limit=1)
        other = type(engine).restore(engine.checkpoint())
        restored = AutonomousCycleController.restore(controller.checkpoint(engine), other)
        for _ in range(64):
            a = controller.step(engine, actor, state(), demand, work_limit=1)
            b = restored.step(other, actor, state(), demand, work_limit=1)
            self.assertEqual(a, b)
            if controller.terminal is not None:
                break
        self.assertEqual(engine.checkpoint(), other.checkpoint())
        self.assertEqual(controller.checkpoint(engine), restored.checkpoint(other))

    def test_duplicate_terminal_step_is_idempotent(self):
        engine, controller, demand, row, report = finish()
        before = (engine.checkpoint(), controller.checkpoint(engine), len(controller.events))
        again = controller.step(engine, controller.actor, state(), demand, work_limit=1)
        self.assertEqual(row, again)
        self.assertEqual(before, (engine.checkpoint(), controller.checkpoint(engine), len(controller.events)))

    def test_tim_and_seat_dimensionality_are_unchanged(self):
        engine, controller, demand, row, report = finish("canonical", "ese",
            ("experience", "norms", "situation", "time"))
        traversal = controller.route_policy.attempts[0]["traversal"]
        self.assertFalse(traversal["dimensionality_changed"])
        self.assertEqual(traversal["origin_dimension"], seat_fields(traversal["origin_seat"])["dimensionality"])
        self.assertEqual(traversal["target_dimension"], seat_fields(traversal["target_seat"])["dimensionality"])
        self.assertEqual(engine.job_status(controller.actor, controller.request.key + ":movement")["tim"], "ese")

    def test_independent_auditor_rejects_forged_links_payments_and_scope(self):
        engine, controller, demand, row, report = finish("workflow")
        original = loads(controller.checkpoint(engine))
        for mutation in ("consumer", "movement", "output"):
            forged = deepcopy(original)
            terminal = forged["terminal"]
            if mutation == "consumer":
                terminal["settlement"]["consumer_key"] = "forged"
            elif mutation == "movement":
                terminal["settlement"]["movement_key"] = "forged"
            else:
                terminal["consumer"]["inputs"] = (demand.cue,)
            forged["events"][-1] = terminal
            with self.assertRaises(ValueError):
                audit_autonomous_cycle(engine.world.journal(), engine.access.checkpoint(),
                    dumps(forged), engine.checkpoint())

    def test_all_predecessor_method_identities_remain_exact(self):
        modules = (
            "tests_ft4.test_demands", "tests_ft4.test_requests", "tests_ft4.test_controller",
            "tests_ft4.test_route_means", "tests_ft4.test_route_execution",
            "tests_ft4.test_orientation", "tests_ft4.test_route_policy",
            "tests_ft4.test_opposition")
        loader = unittest.defaultTestLoader
        identities = []
        for name in modules:
            suite = loader.loadTestsFromName(name)
            stack = list(suite)
            while stack:
                item = stack.pop()
                if isinstance(item, unittest.TestSuite):
                    stack.extend(list(item))
                else:
                    identities.append(item.id())
        self.assertEqual(len(identities), 83)
        self.assertEqual(len(identities), len(set(identities)))

