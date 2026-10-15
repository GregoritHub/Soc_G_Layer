import unittest

from tests_c3 import fixtures as ca
from tests_c6 import fixtures as c6
from tests_c2 import fixtures as c2
from tests_workflow_selection import fixtures as ws
from hle_unified.selection_execution import SelectionEngine
from hle_unified.operation_records import OperationRequest
from hle_unified.store import next_version

from full_theory.demand_controller import IntegratedDemandController
from full_theory.fulfillment_audit import audit_fulfillment
from full_theory.historical import HistoricalController
from tests_ft4.test_demands import state, withdraw


def prepared(setting):
    if setting == "canonical":
        engine, _ = c6.fixture("Understand", "accumulation")
        extra = None
    else:
        engine, _, extra = ws.fixture("Contemplate", "accumulation")
    controller = IntegratedDemandController()
    request, _ = controller.cycle(engine, ca.ALICE, state())
    if request is None:
        raise AssertionError("positive fixture did not form a native request")
    return engine, controller, request, extra


def moved(setting):
    engine, controller, request, extra = prepared(setting)
    if setting == "canonical":
        engine, decision = c6.finish_selection(engine, request)
    else:
        decision = ws.finish(engine, request)
    if decision["status"] != "launched":
        raise AssertionError(decision)
    movement_key = request.key + ":movement"
    movement = engine.job_status(ca.ALICE, movement_key)
    if movement["status"] != "succeeded":
        raise AssertionError(movement)
    return engine, controller, request, extra, movement_key, movement.get("binding") or movement["result"]


def completed(setting):
    engine, controller, request, extra, movement_key, output = moved(setting)
    consumer_key = movement_key + "-consumer"
    if setting == "canonical":
        native = engine._movement_inputs[engine._jobs[ca.ALICE, movement_key].identity][0]
        c6.downstream(engine, native, "Understand", "accumulation")
        consumer_key = movement_key + "-later"
    else:
        ws.consume(engine, request, extra)
    demand_key = next(iter(controller.ledger.demands))
    event = controller.settle(engine, demand_key, request.key, movement_key, consumer_key)
    report = audit_fulfillment(engine.world.journal(), engine.access.checkpoint(), controller.checkpoint())
    return engine, controller, request, event, report


class ControllerTests(unittest.TestCase):
    def test_controller_forms_requests_in_both_settings(self):
        for setting in ("canonical", "workflow"):
            engine, controller, request, _ = prepared(setting)
            self.assertEqual(request.demand, next(iter(controller.ledger.demands.values()))["binding"])
            self.assertEqual(controller.events[0]["request"]["reason"], "ready_for_native_comparison")
            self.assertTrue(audit_fulfillment(engine.world.journal(), engine.access.checkpoint(),
                                              controller.checkpoint())["passed"])

    def test_unscoped_pressure_does_not_create_demand(self):
        engine = ca.setup_c3(engine_type=SelectionEngine)
        controller = IntegratedDemandController()
        request, event = controller.cycle(engine, ca.ALICE, state(pending=True, empty=True))
        self.assertIsNone(request)
        self.assertTrue(event["pressure"]["active"])
        self.assertFalse(controller.ledger.demands)
        self.assertEqual(event["request"]["reason"], "no_current_pending_need")

    def test_actual_paid_consumption_fulfills_both_settings(self):
        for setting in ("canonical", "workflow"):
            engine, controller, request, event, report = completed(setting)
            self.assertEqual(event["outcome"], "fulfilled")
            self.assertEqual(report["fulfilled"], 1)
            self.assertEqual(next(iter(controller.effective_demands().values()))["status"], "fulfilled")
            self.assertLess(engine.wallet(ca.ALICE)["energy"], engine.wallet(ca.ALICE)["initial_energy"])

    def test_selection_or_movement_alone_never_fulfills(self):
        for setting in ("canonical", "workflow"):
            engine, controller, request, _, movement_key, _ = moved(setting)
            key = next(iter(controller.ledger.demands))
            with self.assertRaises((ValueError, KeyError)):
                controller.settle(engine, key, request.key, movement_key, movement_key + "-consumer")
            self.assertFalse(controller.outcomes)
            self.assertEqual(controller.effective_demands()[key]["status"], "pending")

    def test_partial_failed_and_cancelled_work_stays_pending(self):
        engine, controller, request, _, movement_key, output = moved("canonical")
        key = next(iter(controller.ledger.demands)); consumer_key = movement_key + "-consumer"
        current = engine.world.head(c6.SUPPLY.identity).ref
        c6.expose(engine, ca.ALICE, current)
        consumer = c6.req(engine, consumer_key, "use-personal-v1", (output,),
                          stock=current, demand=5)
        engine.start("partial:start", consumer); engine.advance("partial:work", ca.ALICE, consumer_key, 1)
        with self.assertRaises(ValueError):
            controller.settle(engine, key, request.key, movement_key, consumer_key)
        engine.cancel("partial:cancel", ca.ALICE, consumer_key)
        with self.assertRaises(ValueError):
            controller.settle(engine, key, request.key, movement_key, consumer_key)
        failed, failed_controller, failed_request, _, failed_movement, failed_output = moved("canonical")
        failed_key = next(iter(failed_controller.ledger.demands))
        failed_stock = failed.world.head(c6.SUPPLY.identity).ref
        c6.expose(failed, ca.ALICE, failed_stock)
        bad_key = failed_movement + "-failed-consumer"
        bad = c6.req(failed, bad_key, "use-personal-v1", (failed_output,),
                     stock=failed_stock, demand=5)
        failed.start("failed:start", bad); failed.advance("failed:work", ca.ALICE, bad_key, 1000000)
        context = failed.world.resolve(ca.ROOM)
        failed.declare("failed:invalidate", (next_version(context, label="Changed after paid work"),))
        failed.commit("failed:commit", ca.ALICE, bad_key)
        self.assertEqual(failed.job_status(ca.ALICE, bad_key)["status"], "failed")
        with self.assertRaises(ValueError):
            failed_controller.settle(failed, failed_key, failed_request.key, failed_movement, bad_key)
        self.assertFalse(failed_controller.outcomes)

    def test_wrong_actor_context_target_and_output_rejected(self):
        engine, controller, request, _, movement_key, output = moved("canonical")
        key = next(iter(controller.ledger.demands))
        wrong_key = movement_key + "-wrong-target"
        with self.assertRaises(ValueError):
            c2.consume(engine, output, key=wrong_key, target=ca.SAW2)
        native = engine._movement_inputs[engine._jobs[ca.ALICE, movement_key].identity][0]
        c6.downstream(engine, native, "Understand", "accumulation")
        correct_key = movement_key + "-later"
        with self.assertRaises((ValueError, KeyError)):
            controller.settle(engine, key, request.key, "wrong-child", correct_key)
        with self.assertRaises((ValueError, KeyError)):
            controller.settle(engine, key, "wrong-selection", movement_key, correct_key)
        self.assertFalse(controller.outcomes)

    def test_withdrawal_suspends_before_settlement(self):
        engine, controller, request, _, movement_key, output = moved("canonical")
        native = engine._movement_inputs[engine._jobs[ca.ALICE, movement_key].identity][0]
        c6.downstream(engine, native, "Understand", "accumulation")
        consumer_key = movement_key + "-later"
        demand = next(iter(controller.ledger.demands.values()))
        withdraw(engine, demand["binding"])
        controller.cycle(engine, ca.ALICE, state())
        key = next(iter(controller.ledger.demands))
        self.assertEqual(controller.ledger.demands[key]["status"], "suspended")
        with self.assertRaises(ValueError):
            controller.settle(engine, key, request.key, movement_key, consumer_key)

    def test_duplicate_settlement_is_idempotent(self):
        engine, controller, request, event, report = completed("canonical")
        key = next(iter(controller.ledger.demands))
        again = controller.settle(engine, key, request.key, request.key + ":movement",
                                  request.key + ":movement-later")
        self.assertEqual(event, again)
        self.assertEqual(sum(e["kind"] == "settlement" for e in controller.events), 1)

    def test_checkpoint_exact_continuation(self):
        for setting in ("canonical", "workflow"):
            engine, controller, request, _ = prepared(setting)
            other = type(engine).restore(engine.checkpoint())
            restored = IntegratedDemandController.restore(controller.checkpoint())
            a = controller.cycle(engine, ca.ALICE, state())
            b = restored.cycle(other, ca.ALICE, state())
            self.assertEqual(a, b)
            self.assertEqual(engine.checkpoint(), other.checkpoint())
            self.assertEqual(controller.checkpoint(), restored.checkpoint())

    def test_auditor_rejects_forged_child_payment_and_scope(self):
        engine, controller, request, event, report = completed("workflow")
        key = next(iter(controller.outcomes))
        for field, value in (("movement_key", "forged-child"),
                             ("consumer_key", request.key),
                             ("movement_output", ca.CUE5)):
            forged = IntegratedDemandController.restore(controller.checkpoint())
            settlement = next(e for e in forged.events if e["kind"] == "settlement")
            settlement[field] = value
            forged.outcomes[key][field] = value
            with self.assertRaises(ValueError):
                audit_fulfillment(engine.world.journal(), engine.access.checkpoint(), forged.checkpoint())
