from copy import deepcopy
from dataclasses import replace
import inspect
import unittest

from hle_unified import model_g
from hle_unified.selection_records import dumps, loads
from tests_c3 import fixtures as ca
from tests_c6 import fixtures as c6
from tests_c7_workflow import fixtures as wf
from tests_ft4.test_autonomous_cycle import fixture as autonomous_fixture
from tests_ft4.test_demands import state

from full_theory.reserve import ReserveLedger
from full_theory.reserve_cycle import ReserveAutonomousController
from full_theory.reserve_cycle_audit import audit_reserve_cycle
from full_theory.retention import Demand


def cycle_case(setting="canonical", policy="load-v1", initial=4, load=1,
               tim="iee", requirements=("experience",)):
    engine, actor, demand = autonomous_fixture(setting, tim, requirements)
    demand = replace(demand, load=load)
    controller = ReserveAutonomousController(
        engine, ReserveLedger(actor, policy, initial=initial))
    return engine, demand, controller


def finish_case(setting="canonical", policy="load-v1", initial=4, load=1,
                tim="iee", requirements=("experience",), limit=1000000):
    engine, demand, controller = cycle_case(
        setting, policy, initial, load, tim, requirements)
    for _ in range(64):
        row = controller.step(engine, state(), demand, work_limit=limit)
        if controller.terminal is not None:
            break
    else:
        raise AssertionError("bounded autonomous reserve cycle did not stop")
    report = audit_reserve_cycle(engine, controller.checkpoint(engine))
    return engine, demand, controller, row, report


def support_case():
    engine, supplied = c6.fixture("Educate", "accumulation", tim="eii")
    demand = Demand("canonical", supplied.context, supplied.cue, supplied.target,
        requirements=("experience", "norms", "situation", "time"), load=1,
        support_allowed=(supplied.peer,))
    controller = ReserveAutonomousController(
        engine, ReserveLedger(supplied.actor, "load-v1", initial=4))
    for _ in range(64):
        row = controller.step(engine, state(), demand, work_limit=1000000)
        if controller.terminal is not None:
            break
    return engine, demand, controller, row, audit_reserve_cycle(
        engine, controller.checkpoint(engine))


def start_interrupt(policy="load-v1", initial=4):
    engine, demand, controller = cycle_case(policy=policy, initial=initial)
    controller.step(engine, state(), demand, work_limit=1)
    controller.step(engine, state(), demand, work_limit=1)
    return engine, demand, controller


class ReserveCycleTests(unittest.TestCase):
    def test_three_policies_settle_actual_autonomous_completion(self):
        cases = (("null", 0), ("load-v1", 4), ("grade-load-v1", 4))
        for policy, initial in cases:
            for setting in ("canonical", "workflow"):
                engine, demand, controller, row, report = finish_case(
                    setting, policy, initial)
                self.assertEqual((controller.phase, report["effects"]), ("complete", 1))
                self.assertEqual(controller.effects[0]["kind"], "completion")
                self.assertEqual(controller.candidates.binding.ledger.policy, policy)

    def test_load_v1_independent_completion_debits_exact_load_once(self):
        engine, demand, controller, row, report = finish_case(load=2)
        event = controller.effects[0]["reserve_event"]
        self.assertEqual((event["delta"], event["balance_after"]), (-2, 2))
        before = controller.checkpoint(engine)
        self.assertEqual(controller.step(engine, state(), demand), row)
        self.assertEqual(controller.checkpoint(engine), before)

    def test_grade_load_v1_uses_actual_last_paid_seat_grade(self):
        engine, demand, controller, row, report = finish_case(
            policy="grade-load-v1", load=2)
        effect = controller.effects[0]
        grade = model_g.grade(effect["traversal"]["target_seat"])
        expected = -min(4, max(1, demand.load + 1 - grade))
        self.assertEqual(effect["last_paid_grade"], grade)
        self.assertEqual(effect["reserve_event"]["delta"], expected)

    def test_consented_support_is_the_only_supported_completion(self):
        engine, demand, controller, row, report = support_case()
        effect = controller.effects[0]
        self.assertEqual((effect["selected"], effect["supported"],
                          effect["completion_kind"]), ("support", True, "supported"))
        self.assertEqual(effect["reserve_event"]["delta"], -1)
        independent = finish_case()[2].effects[0]
        self.assertEqual((independent["supported"], independent["completion_kind"]),
                         (False, "independent"))

    def test_deferred_and_partial_cycles_do_not_complete_or_debit(self):
        engine, demand, controller, row, report = finish_case(
            tim="eii", requirements=("experience", "norms", "situation", "time"))
        self.assertEqual((controller.phase, controller.effects), ("deferred", []))
        self.assertEqual(controller.candidates.binding.ledger.balance, 4)
        engine, demand, controller = cycle_case()
        controller.step(engine, state(), demand, work_limit=1)
        controller.step(engine, state(), demand, work_limit=1)
        self.assertIsNone(controller.terminal)
        self.assertEqual((controller.effects, controller.candidates.binding.ledger.balance), ([], 4))

    def test_actual_paid_interruption_debits_once_and_keeps_demand_pending(self):
        engine, demand, controller = start_interrupt()
        row = controller.interrupt(engine)
        self.assertEqual(row["reason"], "interrupted_actual_paid_work")
        effect = controller.effects[0]
        self.assertTrue(effect["paid_jobs"])
        self.assertEqual(effect["reserve_event"]["delta"], -1)
        reserve_id = effect["reserve_id"]
        self.assertEqual(controller.candidates.binding.ledger.demands[reserve_id]["status"], "pending")
        before = controller.checkpoint(engine)
        self.assertEqual(controller.interrupt(engine), row)
        self.assertEqual(controller.checkpoint(engine), before)

    def test_unpaid_or_preparation_only_interruption_is_rejected(self):
        engine, demand, controller = cycle_case()
        controller.step(engine, state(), demand, work_limit=1)
        with self.assertRaises(ValueError):
            controller.interrupt(engine)
        engine, demand, controller = cycle_case(initial=0)
        controller.step(engine, state(), demand, work_limit=1)
        controller.step(engine, state(), demand, work_limit=1)
        self.assertEqual(controller.candidates.events[-1]["phase"], "preparation")
        with self.assertRaises(ValueError):
            controller.interrupt(engine)

    def test_zero_reserve_preserves_route_visibility_and_bounds(self):
        engine, demand, controller = cycle_case(initial=0, load=8)
        controller.step(engine, state(), demand)
        controller.step(engine, state(), demand)
        event = controller.candidates.events[-1]
        self.assertEqual(controller.candidates.binding.ledger.balance, 0)
        self.assertEqual(tuple(row["name"] for row in event["route_options"]),
            ("retained", "ordinary", "n", "cp", "support", "defer"))
        self.assertFalse(any("forbidden" in row for row in event["route_options"]))

    def test_paid_preparation_to_route_to_settlement_runs_both_settings(self):
        for setting in ("canonical", "workflow"):
            engine, demand, controller = cycle_case(setting, initial=0)
            controller.step(engine, state(), demand)
            controller.step(engine, state(), demand)
            if setting == "canonical":
                ca.inspect(engine, key="reserve-cycle-preparation")
            else:
                wf.observe(engine, key="reserve-cycle-preparation")
            bound = controller.bind_preparation(engine, ("reserve-cycle-preparation",))
            self.assertTrue(bound["complete"])
            for _ in range(64):
                row = controller.step(engine, state(), demand, work_limit=1000000)
                if controller.terminal is not None:
                    break
            self.assertEqual(controller.phase, "complete")
            self.assertEqual(controller.effects[0]["reserve_event"]["balance_after"], 0)
            self.assertTrue(audit_reserve_cycle(engine, controller.checkpoint(engine))["passed"])

    def test_reserve_effect_never_reprices_or_double_charges_native_work(self):
        engine, demand, controller, row, report = finish_case(load=2)
        effect = controller.effects[0]
        self.assertEqual(effect["native_before"], effect["native_after"])
        candidate = controller.candidates.events[-1]
        self.assertNotIn("reserve", candidate["native_overhead"])
        self.assertEqual(candidate["reserve_preparation_units"], 0)

    def test_public_inputs_cannot_supply_route_support_grade_or_success(self):
        step = tuple(inspect.signature(ReserveAutonomousController.step).parameters)
        interrupt = tuple(inspect.signature(ReserveAutonomousController.interrupt).parameters)
        for forbidden in ("request", "route", "recipe", "support", "grade",
                          "completion_kind", "success", "reserve_result"):
            self.assertNotIn(forbidden, step)
            self.assertNotIn(forbidden, interrupt)

    def test_checkpoint_continuation_is_exact(self):
        engine, demand, controller = cycle_case("workflow", policy="grade-load-v1")
        controller.step(engine, state(), demand, work_limit=1)
        other = type(engine).restore(engine.checkpoint())
        restored = ReserveAutonomousController.restore(controller.checkpoint(engine), other)
        for _ in range(64):
            left = controller.step(engine, state(), demand, work_limit=1000000)
            right = restored.step(other, state(), demand, work_limit=1000000)
            self.assertEqual(left, right)
            if controller.terminal is not None:
                break
        self.assertEqual(engine.checkpoint(), other.checkpoint())
        self.assertEqual(controller.checkpoint(engine), restored.checkpoint(other))

    def test_independent_auditor_reconstructs_completion_and_interruption(self):
        for setting in ("canonical", "workflow"):
            engine, demand, controller, row, report = finish_case(setting)
            self.assertTrue(report["passed"])
            self.assertEqual((report["phase"], report["effects"]), ("complete", 1))
        engine, demand, controller = start_interrupt()
        controller.interrupt(engine)
        report = audit_reserve_cycle(engine, controller.checkpoint(engine))
        self.assertEqual((report["phase"], report["effects"], report["fulfilled"]),
                         ("interrupted", 1, 0))

    def test_independent_auditor_rejects_forged_kind_grade_payment_and_delta(self):
        engine, demand, controller, row, report = finish_case(policy="grade-load-v1")
        original = loads(controller.checkpoint(engine))
        forged = deepcopy(original)
        forged["effects"][0]["completion_kind"] = "supported"
        forged["terminal"]["effect"] = forged["effects"][0]
        forged["events"][-1] = forged["terminal"]
        with self.assertRaises(ValueError):
            audit_reserve_cycle(engine, dumps(forged))
        forged = deepcopy(original)
        forged["effects"][0]["last_paid_grade"] = 0
        forged["terminal"]["effect"] = forged["effects"][0]
        forged["events"][-1] = forged["terminal"]
        with self.assertRaises(ValueError):
            audit_reserve_cycle(engine, dumps(forged))
        forged = deepcopy(original)
        nested = loads(forged["candidates"])
        binding = loads(nested["binding"])
        reserve = loads(binding["reserve"])
        reserve["events"][-1]["delta"] = 0
        binding["reserve"] = dumps(reserve); nested["binding"] = dumps(binding)
        forged["candidates"] = dumps(nested)
        with self.assertRaises(ValueError):
            audit_reserve_cycle(engine, dumps(forged))
        engine, demand, controller = start_interrupt()
        controller.interrupt(engine)
        forged = loads(controller.checkpoint(engine))
        forged["effects"][0]["paid_jobs"][0]["status"]["spent"] = 0
        forged["terminal"]["effect"] = forged["effects"][0]
        forged["events"][-1] = forged["terminal"]
        with self.assertRaises(ValueError):
            audit_reserve_cycle(engine, dumps(forged))

    def test_ft5_2b1_and_all_predecessor_method_identity_remain_exact(self):
        modules = ("tests_ft5.test_reserve_candidates", "tests_ft5.test_native_reserve",
            "tests_ft5.test_reserve", "tests_ft4.test_demands", "tests_ft4.test_requests",
            "tests_ft4.test_controller", "tests_ft4.test_route_means",
            "tests_ft4.test_route_execution", "tests_ft4.test_orientation",
            "tests_ft4.test_route_policy", "tests_ft4.test_opposition",
            "tests_ft4.test_autonomous_cycle", "tests_ft4.test_autonomous_closure",
            "tests_ft4.test_autonomous_capability", "tests_ft4.test_autonomous_reuse")
        identities = []
        for name in modules:
            stack = list(unittest.defaultTestLoader.loadTestsFromName(name))
            while stack:
                item = stack.pop()
                if isinstance(item, unittest.TestSuite):
                    stack.extend(list(item))
                else:
                    identities.append(item.id())
        self.assertEqual((len(identities), len(set(identities))), (171, 171))
