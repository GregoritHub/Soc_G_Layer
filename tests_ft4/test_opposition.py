from copy import deepcopy
from dataclasses import replace
import unittest

from hle.development_structure import portage
from hle.model_a import fields as seat_fields
from hle_unified.material import attrs
from hle_unified.operations import address
from hle_unified.selection_records import dumps, loads

from full_theory.opposition import OBLIGATION, OppositionRouteController
from full_theory.opposition_audit import audit_opposition
from full_theory.orientation import PaidOrientation
from full_theory.retention import Demand
from full_theory.route_execution import NativeRouteController
from tests_ft4.test_controller import prepared
from tests_ft4.test_route_means import budgeted_request


TERMINAL = ("complete", "deferred", "failed", "cancelled", "rejected")


def opposed_demand(setting, request, requirements=("experience",), obligation=OBLIGATION):
    return Demand(setting, request.context, request.cue, request.target,
                  requirements=requirements, obligations=(obligation,))


def finish_opposition(setting):
    engine, _, request, _ = prepared(setting)
    demand = opposed_demand(setting, request)
    controller = OppositionRouteController()
    for _ in range(48):
        row = controller.step(engine, request, demand, work_limit=1000000)
        if row["phase"] in TERMINAL:
            break
    else:
        raise AssertionError("bounded opposition did not stop")
    report = audit_opposition(engine.world.journal(), engine.access.checkpoint(),
                              controller.checkpoint(engine), engine.checkpoint())
    return engine, controller, request, demand, row, report


class OppositionTests(unittest.TestCase):
    def test_declared_cp_then_n_opposition_completes_both_settings(self):
        for setting in ("canonical", "workflow"):
            engine, controller, request, _, row, report = finish_opposition(setting)
            attempt = controller.attempts[0]
            self.assertEqual(row["phase"], "complete")
            self.assertEqual(tuple(leg["move"] for leg in attempt["legs"]), ("cp", "n"))
            self.assertEqual(attempt["final_target"], portage(attempt["origin_seat"], "a"))
            self.assertEqual(controller.relay[request.actor], attempt["final_target"])
            self.assertEqual(report["completed"], 1)

    def test_two_native_movements_and_exact_cp_fee_are_paid(self):
        for setting in ("canonical", "workflow"):
            engine, controller, request, _, _, report = finish_opposition(setting)
            self.assertEqual(report["native"]["attempts"], 2)
            self.assertEqual(report["orientation"]["paid_energy"], 2)
            self.assertEqual(report["orientation"]["paid_time"], 2)
            for leg in controller.attempts[0]["legs"]:
                movement = attrs(engine.world.head(address(
                    "u4.operation", request.actor, leg["key"] + ":movement").identity))
                self.assertEqual(movement["status"], "succeeded")
                self.assertEqual(movement["spent"], movement["required"])

    def test_second_leg_cannot_start_before_first_movement_completes(self):
        engine, _, request, _ = prepared("canonical")
        demand = opposed_demand("canonical", request)
        controller = OppositionRouteController()
        second = request.key + ":opposition:1:n"
        for _ in range(20):
            row = controller.step(engine, request, demand, work_limit=1000000)
            if controller.attempts[0]["legs"][0]["traversal"] is not None:
                break
            self.assertNotIn((request.actor, second), engine._jobs)
        self.assertEqual(row["phase"], "between_legs")
        self.assertNotIn((request.actor, second), engine._jobs)
        controller.step(engine, request, demand, work_limit=1)
        self.assertIn((request.actor, second), engine._jobs)

    def test_missing_or_different_constraint_is_rejected(self):
        engine, _, request, _ = prepared("canonical")
        for obligations in (("participate",), ("opposition:n-cp-v1",)):
            demand = Demand("canonical", request.context, request.cue, request.target,
                            obligations=obligations)
            before = engine.checkpoint()
            with self.assertRaises(ValueError):
                OppositionRouteController().step(engine, request, demand)
            self.assertEqual(before, engine.checkpoint())

    def test_intermediate_dimensionality_block_defers_without_native_work(self):
        engine, _, request, _ = prepared("canonical")
        demand = opposed_demand("canonical", request,
            ("experience", "norms", "situation"))
        before = engine.checkpoint()
        controller = OppositionRouteController()
        row = controller.step(engine, request, demand)
        self.assertEqual(row["phase"], "deferred")
        self.assertEqual(controller.attempts[0]["reason"],
                         "intermediate_dimensionality_insufficient")
        self.assertEqual(before, engine.checkpoint())
        self.assertFalse(controller.native.attempts)

    def test_unaffordable_cp_fee_stays_visible_without_native_work(self):
        engine, request = budgeted_request(87)
        demand = opposed_demand("canonical", request)
        before = engine.checkpoint()
        controller = OppositionRouteController()
        row = controller.step(engine, request, demand)
        self.assertEqual(row["phase"], "deferred")
        self.assertEqual(controller.attempts[0]["reason"],
                         "insufficient_wallet_for_orientation_read")
        self.assertEqual(before, engine.checkpoint())
        self.assertFalse(controller.native.attempts)
        self.assertFalse(controller.orientation.attempts)

    def test_first_leg_exhaustion_never_starts_second_leg(self):
        engine, request = budgeted_request(89)
        demand = opposed_demand("canonical", request)
        controller = OppositionRouteController()
        for _ in range(5):
            row = controller.step(engine, request, demand, work_limit=1000000)
        self.assertEqual(engine.wallet(request.actor)["energy"], 0)
        self.assertEqual(row["phase"], "native")
        self.assertIsNone(controller.attempts[0]["legs"][0]["traversal"])
        self.assertNotIn((request.actor, request.key + ":opposition:1:n"), engine._jobs)

    def test_partial_checkpoint_continues_exactly(self):
        engine, _, request, _ = prepared("workflow")
        demand = opposed_demand("workflow", request)
        controller = OppositionRouteController()
        for _ in range(4):
            controller.step(engine, request, demand, work_limit=1)
        other = type(engine).restore(engine.checkpoint())
        restored = OppositionRouteController.restore(controller.checkpoint(engine), other)
        for _ in range(64):
            left = controller.step(engine, request, demand, work_limit=1000000)
            right = restored.step(other, request, demand, work_limit=1000000)
            self.assertEqual(left, right)
            if left["phase"] in TERMINAL:
                break
        self.assertEqual(engine.checkpoint(), other.checkpoint())
        self.assertEqual(controller.checkpoint(engine), restored.checkpoint(other))

    def test_tim_dimensions_and_native_cursor_are_not_rewritten(self):
        for setting in ("canonical", "workflow"):
            engine, _, request, _ = prepared(setting)
            profiles = deepcopy(engine._profiles)
            dimensions = tuple(seat_fields(seat)["dimensionality"] for seat in range(1, 9))
            demand = opposed_demand(setting, request)
            controller = OppositionRouteController()
            for _ in range(48):
                row = controller.step(engine, request, demand, work_limit=1000000)
                if row["phase"] in TERMINAL:
                    break

            control, _, control_request, _ = prepared(setting)
            cp_request = replace(control_request,
                key=control_request.key + ":opposition:0:cp")
            orientation = PaidOrientation()
            self.assertIsNotNone(orientation.step(
                control, cp_request, work_limit=1000000)["ticket"])
            native = NativeRouteController()
            for child in (cp_request, replace(control_request,
                          key=control_request.key + ":opposition:1:n")):
                for _ in range(16):
                    native_row = native.step(control, child, work_limit=1000000)
                    if native_row["state"] == "movement_complete":
                        break
            self.assertEqual(engine.checkpoint(), control.checkpoint())
            self.assertEqual(engine._profiles, profiles)
            self.assertEqual(tuple(seat_fields(seat)["dimensionality"] for seat in range(1, 9)),
                             dimensions)

    def test_independent_auditor_rejects_forged_sequence_payment_link_and_target(self):
        engine, controller, _, _, _, _ = finish_opposition("canonical")
        original = loads(controller.checkpoint(engine))
        for kind in ("sequence", "payment", "link", "target"):
            forged = deepcopy(original)
            attempt = forged["attempts"][0]
            if kind == "sequence":
                attempt["moves"] = ("n", "cp")
            elif kind == "payment":
                attempt["legs"][0]["orientation_ticket"]["energy"] = 0
            elif kind == "link":
                attempt["legs"][1]["traversal"]["movement"] = \
                    attempt["legs"][0]["traversal"]["movement"]
            else:
                attempt["final_target"] = attempt["origin_seat"]
            with self.assertRaises(ValueError):
                audit_opposition(engine.world.journal(), engine.access.checkpoint(),
                                 dumps(forged), engine.checkpoint())
