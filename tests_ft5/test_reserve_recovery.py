from copy import deepcopy
from dataclasses import replace
import inspect
import unittest

from hle_unified import model_g
from hle_unified.selection_records import dumps, loads
from tests_c3 import fixtures as ca
from tests_c7_workflow import fixtures as wf
from tests_ft4.test_autonomous_cycle import fixture as autonomous_fixture
from tests_ft4.test_demands import state
from tests_ft5.test_reserve_cycle import finish_case, support_case

from full_theory.content import ContentBridge
from full_theory.reserve import ReserveLedger
from full_theory.reserve_cycle import ReserveAutonomousController
from full_theory.reserve_cycle_audit import audit_reserve_cycle


def paid_uptake(engine, actor, setting="canonical", *, receive=True, partial=False,
                packet="recovery-packet"):
    fixture = ca if setting == "canonical" else wf
    fixture.cell(engine, "Share", "accumulation", key=packet + ":source",
                 consumer=False)
    bridge = ContentBridge(engine)
    output = engine.job_status(actor, packet + ":source")["public.0"]
    bridge.emit(packet, actor, packet + ":source", actor, output)
    if not receive:
        receipt = None
    elif partial:
        receipt = bridge.receive(packet, actor, quantum=1)
        if receipt is not None:
            raise AssertionError("partial uptake unexpectedly completed")
        engine.cancel("cancel-partial:" + packet, actor, "ft:read:" + packet)
    else:
        receipt = bridge.receive(packet, actor, quantum=1000000)
    return bridge, receipt


def interrupted_case(setting="canonical", policy="load-v1", initial=2, load=2,
                     tim="lie", *, uptake=True, partial_uptake=False):
    engine, actor, demand = autonomous_fixture(setting, tim, ("experience",))
    demand = replace(demand, load=load)
    bridge, receipt = paid_uptake(engine, actor, setting, receive=uptake,
                                  partial=partial_uptake)
    controller = ReserveAutonomousController(engine, ReserveLedger(
        actor, policy, initial=initial, tokens=("recovery-token", "other-token")))
    controller.step(engine, state(), demand, work_limit=1)
    controller.step(engine, state(), demand, work_limit=1)
    controller.interrupt(engine)
    return engine, demand, controller, bridge, receipt


def recovered_case(setting="canonical", policy="load-v1", initial=2, load=2,
                   *, finish=True):
    engine, demand, controller, bridge, receipt = interrupted_case(
        setting, policy, initial, load)
    recovery = controller.replenish(
        engine, bridge, "recovery-token", "recovery-packet")
    restart = controller.restart(engine)
    row = restart
    if finish:
        for _ in range(64):
            row = controller.step(engine, state(), demand, work_limit=1000000)
            if controller.terminal is not None:
                break
        else:
            raise AssertionError("recovered autonomous cycle did not stop")
    return engine, demand, controller, bridge, receipt, recovery, restart, row


class ReserveRecoveryTests(unittest.TestCase):
    def test_paid_uptake_restarts_same_pending_demand_in_both_settings(self):
        for setting in ("canonical", "workflow"):
            engine, demand, controller, bridge, receipt, recovery, restart, row = recovered_case(setting)
            self.assertEqual(controller.phase, "complete")
            self.assertEqual(tuple(effect["kind"] for effect in controller.effects),
                             ("interruption", "replenishment", "completion"))
            self.assertTrue(audit_reserve_cycle(engine, controller.checkpoint(engine))["passed"])

    def test_sustained_interruption_replenishment_completion_arithmetic(self):
        engine, demand, controller, bridge, receipt, recovery, restart, row = recovered_case()
        events = [event for event in controller.candidates.binding.ledger.events
                  if event["kind"] != "admission"]
        self.assertEqual(tuple(event["kind"] for event in events),
                         ("interruption", "replenishment", "completion"))
        self.assertEqual(tuple((event["balance_before"], event["delta"],
                                event["balance_after"]) for event in events),
                         ((2, -1, 1), (1, 2, 3), (3, -2, 1)))

    def test_restart_requires_new_post_interruption_paid_replenishment(self):
        engine, demand, controller, bridge, receipt = interrupted_case()
        with self.assertRaises(ValueError):
            controller.restart(engine)
        self.assertEqual(controller.phase, "interrupted")

    def test_partial_or_wrong_seat_uptake_cannot_recover(self):
        engine, demand, controller, bridge, receipt = interrupted_case(partial_uptake=True)
        self.assertIsNone(receipt)
        with self.assertRaises(ValueError):
            controller.replenish(engine, bridge, "recovery-token", "recovery-packet")
        engine, demand, controller, bridge, receipt = interrupted_case(tim="iee")
        with self.assertRaises(ValueError):
            controller.replenish(engine, bridge, "recovery-token", "recovery-packet")

    def test_restart_preserves_request_reserve_id_and_native_attempt(self):
        engine, demand, controller, bridge, receipt = interrupted_case()
        request = deepcopy(controller.request)
        reserve_id = controller._reserve_id()
        attempt = deepcopy(controller.candidates.route_policy._attempt(controller.request))
        controller.replenish(engine, bridge, "recovery-token", "recovery-packet")
        controller.restart(engine)
        self.assertEqual(controller.request, request)
        self.assertEqual(controller._reserve_id(), reserve_id)
        self.assertEqual(controller.candidates.route_policy._attempt(controller.request), attempt)
        self.assertEqual(len(controller.candidates.binding.ledger.demands), 1)

    def test_external_support_completion_remains_distinct_and_cheaper_at_load_two(self):
        supported = support_case()[2].effects[0]
        independent = finish_case(load=2)[2].effects[0]
        self.assertEqual((supported["completion_kind"], supported["reserve_event"]["delta"]),
                         ("supported", -1))
        self.assertEqual((independent["completion_kind"], independent["reserve_event"]["delta"]),
                         ("independent", -2))

    def test_null_policy_records_recovery_without_minting_reserve(self):
        engine, demand, controller, bridge, receipt, recovery, restart, row = recovered_case(
            policy="null", initial=0)
        changes = [event["delta"] for event in controller.candidates.binding.ledger.events
                   if event["kind"] in ("interruption", "replenishment", "completion")]
        self.assertEqual(changes, [0, 0, 0])
        self.assertEqual(controller.candidates.binding.ledger.balance, 0)

    def test_grade_policy_uses_realized_grade_after_restart(self):
        engine, demand, controller, bridge, receipt, recovery, restart, row = recovered_case(
            policy="grade-load-v1")
        completion = controller.effects[-1]
        self.assertEqual(completion["last_paid_grade"],
                         model_g.grade(completion["traversal"]["target_seat"]))
        self.assertEqual(completion["reserve_event"]["last_paid_grade"],
                         completion["last_paid_grade"])

    def test_finite_token_packet_receipt_and_second_restart_cannot_form_free_loop(self):
        engine, demand, controller, bridge, receipt = interrupted_case()
        controller.replenish(engine, bridge, "recovery-token", "recovery-packet")
        controller.restart(engine)
        with self.assertRaises(ValueError):
            controller.restart(engine)
        with self.assertRaises(ValueError):
            controller.candidates.binding.replenish_from_uptake(
                engine, bridge, "other-token", "recovery-packet")

    def test_recovery_does_not_reprice_or_double_charge_native_work(self):
        engine, demand, controller, bridge, receipt = interrupted_case()
        job = deepcopy(engine.job_status(controller.actor, "ft:read:recovery-packet"))
        native = engine.checkpoint()
        controller.replenish(engine, bridge, "recovery-token", "recovery-packet")
        self.assertEqual((engine.checkpoint(), engine.job_status(
            controller.actor, "ft:read:recovery-packet")), (native, job))
        controller.restart(engine)
        self.assertEqual(engine.checkpoint(), native)

    def test_checkpoint_continuation_is_exact_across_recovery_and_restart(self):
        engine, demand, controller, bridge, receipt = interrupted_case("workflow")
        controller.replenish(engine, bridge, "recovery-token", "recovery-packet")
        other = type(engine).restore(engine.checkpoint())
        restored = ReserveAutonomousController.restore(controller.checkpoint(engine), other)
        self.assertEqual(controller.restart(engine), restored.restart(other))
        for _ in range(64):
            left = controller.step(engine, state(), demand, work_limit=1000000)
            right = restored.step(other, state(), demand, work_limit=1000000)
            self.assertEqual(left, right)
            if controller.terminal is not None:
                break
        self.assertEqual(engine.checkpoint(), other.checkpoint())
        self.assertEqual(controller.checkpoint(engine), restored.checkpoint(other))

    def test_public_recovery_inputs_cannot_supply_route_grade_support_or_success(self):
        for method in (ReserveAutonomousController.replenish,
                       ReserveAutonomousController.restart):
            parameters = tuple(inspect.signature(method).parameters)
            for forbidden in ("route", "grade", "support", "success", "delta", "balance"):
                self.assertNotIn(forbidden, parameters)

    def test_independent_auditor_reconstructs_paid_recovery_sequence(self):
        for setting in ("canonical", "workflow"):
            engine, demand, controller, bridge, receipt, recovery, restart, row = recovered_case(setting)
            report = audit_reserve_cycle(engine, controller.checkpoint(engine))
            self.assertEqual((report["passed"], report["effects"], report["fulfilled"]),
                             (True, 3, 1))

    def test_independent_auditor_rejects_forged_order_payment_token_and_delta(self):
        engine, demand, controller, bridge, receipt, recovery, restart, row = recovered_case()
        original = loads(controller.checkpoint(engine))
        mutations = []
        forged = deepcopy(original)
        forged["events"][-4], forged["events"][-3] = forged["events"][-3], forged["events"][-4]
        forged["events"][-4]["index"], forged["events"][-3]["index"] = (
            forged["events"][-3]["index"], forged["events"][-4]["index"])
        mutations.append(forged)
        forged = deepcopy(original)
        forged["effects"][0]["paid_jobs"][0]["status"]["spent"] = 0
        mutations.append(forged)
        forged = deepcopy(original)
        forged["effects"][1]["token_id"] = "other-token"
        mutations.append(forged)
        forged = deepcopy(original)
        nested = loads(forged["candidates"])
        binding = loads(nested["binding"])
        reserve = loads(binding["reserve"])
        reserve["events"][-2]["delta"] = 1
        binding["reserve"] = dumps(reserve)
        nested["binding"] = dumps(binding)
        forged["candidates"] = dumps(nested)
        mutations.append(forged)
        for value in mutations:
            with self.assertRaises(ValueError):
                audit_reserve_cycle(engine, dumps(value))

    def test_interrupted_demand_remains_visible_until_later_settlement(self):
        engine, demand, controller, bridge, receipt = interrupted_case()
        admitted = next(iter(controller.demand_controller.effective_demands().values()))
        self.assertEqual(admitted["status"], "pending")
        engine, demand, controller, bridge, receipt, recovery, restart, row = recovered_case()
        admitted = next(iter(controller.demand_controller.effective_demands().values()))
        self.assertEqual(admitted["status"], "fulfilled")

    def test_ft5_2b2_and_all_predecessor_method_identity_remain_exact(self):
        modules = ("tests_ft5.test_reserve_cycle", "tests_ft5.test_reserve_candidates",
            "tests_ft5.test_native_reserve", "tests_ft5.test_reserve",
            "tests_ft4.test_demands", "tests_ft4.test_requests", "tests_ft4.test_controller",
            "tests_ft4.test_route_means", "tests_ft4.test_route_execution",
            "tests_ft4.test_orientation", "tests_ft4.test_route_policy",
            "tests_ft4.test_opposition", "tests_ft4.test_autonomous_cycle",
            "tests_ft4.test_autonomous_closure", "tests_ft4.test_autonomous_capability",
            "tests_ft4.test_autonomous_reuse")
        identities = []
        for name in modules:
            stack = list(unittest.defaultTestLoader.loadTestsFromName(name))
            while stack:
                item = stack.pop()
                if isinstance(item, unittest.TestSuite):
                    stack.extend(list(item))
                else:
                    identities.append(item.id())
        self.assertEqual((len(identities), len(set(identities))), (186, 186))
