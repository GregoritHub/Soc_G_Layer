from copy import deepcopy
from dataclasses import replace
import inspect
import unittest

from hle.model_a import fields as seat_fields
from hle_unified.material import attrs, attributes
from hle_unified.operation_records import OperationRequest
from hle_unified.selection_records import dumps, loads
from hle_unified.store import next_version
from tests_c3 import fixtures as ca

from full_theory.autonomous_reuse import AutonomousReuseController
from full_theory.autonomous_reuse_audit import audit_autonomous_reuse
from tests_ft4.test_autonomous_capability import capability_case
from tests_ft4.test_demands import need, state, withdraw
from tests_ft4.test_opposition import finish_opposition


TERMINAL = ("complete", "deferred", "failed", "cancelled", "rejected")


def later_need(engine, cycle, setting, key="later-need", weights=(0, 0, 0, 10)):
    old_ref = next(iter(cycle.demand_controller.ledger.demands.values()))["binding"]
    old = engine.world.resolve(old_ref)
    active_endorsement = attrs(old)["endorsement"]
    target = cycle.request.target
    view = engine.participant_view(cycle.actor)
    prior = view._bindings[old_ref]
    if setting == "workflow":
        current = [row for row in view.snapshot.bindings
                   if len(row.content) == 1 and row.content[0].relation == "c7w.data"
                   and row.target == target]
        if len(current) > 8:
            local = [row for row in current if row.ref.identity.namespace == "workshop"]
            withdraw(engine, min(local, key=lambda row: dumps(row.ref)).ref)
    evidence = prior.particulars
    facets = old.facets
    withdrawn_ref = withdraw(engine, old_ref)
    withdrawn = engine.world.resolve(withdrawn_ref)
    new = next_version(withdrawn, facets=facets, attributes=attributes(
        {**attrs(withdrawn), "endorsement": active_endorsement,
         "meaning": "Post-certification unresolved task " + key}))
    engine.declare("declare:" + key, (new,))
    ca.perform(engine, OperationRequest("bind:" + key, cycle.actor, "bind",
        cycle.request.context, binding=new.ref, evidence=evidence), limit=100000)
    return new.ref, target


def finish_reuse(setting="canonical", *, revoke=False, required=None):
    engine, cycle, demand, _, capability, _, _ = capability_case(setting)
    controller = AutonomousReuseController(capability, engine)
    if revoke:
        controller.ledger.revoke(controller.certificate_key, "matched evidence ablation")
    _, target = later_need(engine, cycle, setting)
    required = replace(demand, target=target) if required is None else required
    for _ in range(64):
        row = controller.step(engine, state(), required, work_limit=1000000)
        if controller.terminal is not None:
            break
    else:
        raise AssertionError("bounded autonomous reuse did not stop")
    report = audit_autonomous_reuse(engine.world.journal(), engine.access.checkpoint(),
        controller.checkpoint(engine), engine.checkpoint())
    return engine, cycle, required, controller, row, report


class AutonomousReuseTests(unittest.TestCase):
    def test_later_autonomous_demand_selects_retained_route_in_both_settings(self):
        for setting in ("canonical", "workflow"):
            _, _, _, controller, row, report = finish_reuse(setting)
            self.assertEqual(controller.phase, "complete")
            self.assertEqual(controller.route_policy.attempts[0]["selected"]["name"], "retained")
            self.assertTrue(report["retained"])
            self.assertEqual(row["reason"], "settled_after_applicable_retained_choice")

    def test_reuse_step_accepts_no_request_route_certificate_or_success_input(self):
        parameters = tuple(inspect.signature(AutonomousReuseController.step).parameters)
        self.assertEqual(parameters, ("self", "engine", "historical_state", "demand", "work_limit"))
        for forbidden in ("request", "route", "certificate", "candidate", "success", "answer"):
            self.assertNotIn(forbidden, parameters)

    def test_later_route_consumes_actual_output_and_settles(self):
        for setting in ("canonical", "workflow"):
            engine, _, _, controller, row, report = finish_reuse(setting)
            traversal = controller.route_policy.attempts[0]["traversal"]
            settlement = row["settlement"]
            consumer = engine.job_status(controller.actor, controller.consumer_key)
            self.assertEqual(settlement["movement_output"], traversal["movement_output"])
            self.assertIn(traversal["movement_output"], consumer.values())
            self.assertEqual(report["fulfillment"]["fulfilled"], 1)

    def test_matched_certificate_revocation_removes_only_choice_effect(self):
        live = finish_reuse("canonical")
        removed = finish_reuse("canonical", revoke=True)
        left, right = live[3], removed[3]
        self.assertEqual(left.route_policy.attempts[0]["selected"]["name"], "retained")
        self.assertEqual(right.route_policy.attempts[0]["selected"]["name"], "ordinary")
        self.assertEqual(left.ledger.history, right.ledger.history)
        self.assertEqual(live[5]["revoked"], False)
        self.assertEqual(removed[5]["revoked"], True)
        self.assertEqual(left.route_policy.attempts[0]["origin_dimension"],
                         right.route_policy.attempts[0]["origin_dimension"])

    def test_unavailable_support_is_logged_and_never_fabricates_success(self):
        _, _, _, controller, _, report = finish_reuse()
        options = {row["name"]: row for row in controller.route_policy.attempts[0]["options"]}
        self.assertFalse(options["support"]["eligible"])
        self.assertEqual(options["support"]["reason"], "no_exact_allowed_consent")
        self.assertEqual(controller.route_policy.attempts[0]["selected"]["name"], "retained")
        self.assertEqual(report["fulfillment"]["fulfilled"], 1)

    def test_harder_demand_defers_and_remains_visible(self):
        engine, cycle, demand, _, capability, _, _ = capability_case("canonical")
        controller = AutonomousReuseController(capability, engine)
        later_need(engine, cycle, "canonical")
        harder = replace(demand, requirements=("experience", "norms", "situation", "time"),
                         load=8, support_allowed=())
        first = controller.step(engine, state(), harder, work_limit=1)
        self.assertEqual(first["kind"], "scan")
        controller.step(engine, state(), harder, work_limit=1)
        attempt = controller.route_policy.attempts[0]
        retained = next(row for row in attempt["options"] if row["name"] == "retained")
        self.assertFalse(retained["eligible"])
        self.assertEqual(retained["reason"], "no_applicable_capacity")
        admitted = next(iter(controller.demand_controller.effective_demands().values()))
        self.assertEqual(admitted["status"], "pending")

    def test_conflicting_later_demands_follow_owned_order(self):
        engine, cycle, demand, _, capability, _, _ = capability_case()
        controller = AutonomousReuseController(capability, engine)
        later_need(engine, cycle, "canonical", key="z-later", weights=(0, 10, 0, 0))
        need(engine, "canonical", key="a-later", weights=(10, 0, 0, 0))
        controller.step(engine, state(), demand, work_limit=1)
        scan = controller.demand_controller.ledger.events[0]
        self.assertEqual(len(scan["admitted"]), 2)
        self.assertEqual(controller.demand_controller.events[0]["request"]["selected"],
                         sorted(scan["admitted"])[0])

    def test_opposition_common_gate_remains_exact_and_paid(self):
        for setting in ("canonical", "workflow"):
            _, controller, _, _, row, report = finish_opposition(setting)
            self.assertEqual(row["phase"], "complete")
            self.assertEqual(tuple(leg["move"] for leg in controller.attempts[0]["legs"]),
                             ("cp", "n"))
            self.assertEqual(report["native"]["attempts"], 2)
            self.assertEqual((report["orientation"]["paid_energy"],
                              report["orientation"]["paid_time"]), (2, 2))

    def test_checkpoint_continuation_is_exact(self):
        engine, cycle, demand, _, capability, _, _ = capability_case("workflow")
        controller = AutonomousReuseController(capability, engine)
        _, target = later_need(engine, cycle, "workflow")
        demand = replace(demand, target=target)
        controller.step(engine, state(), demand, work_limit=1)
        other = type(engine).restore(engine.checkpoint())
        restored = AutonomousReuseController.restore(controller.checkpoint(engine), other)
        for _ in range(64):
            left = controller.step(engine, state(), demand, work_limit=1)
            right = restored.step(other, state(), demand, work_limit=1)
            self.assertEqual(left, right)
            if controller.terminal is not None:
                break
        self.assertEqual(engine.checkpoint(), other.checkpoint())
        self.assertEqual(controller.checkpoint(engine), restored.checkpoint(other))

    def test_independent_auditor_rejects_forged_certificate_route_and_settlement(self):
        engine, _, _, controller, _, _ = finish_reuse()
        original = loads(controller.checkpoint(engine))
        for mutation in ("certificate", "route", "settlement"):
            forged = deepcopy(original)
            if mutation == "certificate":
                forged["certificate_key"] = "forged"
            elif mutation == "route":
                route = loads(forged["route_policy"])
                route["attempts"][0]["selected"]["certificate"] = "forged"
                forged["route_policy"] = dumps(route)
            else:
                forged["terminal"]["settlement"]["consumer_key"] = "forged"
                forged["events"][-1] = forged["terminal"]
            with self.assertRaises(ValueError):
                audit_autonomous_reuse(engine.world.journal(), engine.access.checkpoint(),
                    dumps(forged), engine.checkpoint())

    def test_final_ft4_common_invariants_hold_both_settings(self):
        for setting in ("canonical", "workflow"):
            engine, _, _, controller, _, report = finish_reuse(setting)
            attempt = controller.route_policy.attempts[0]
            traversal = attempt["traversal"]
            certificate = controller.ledger.certificates[controller.certificate_key]
            self.assertFalse(certificate["material_competence"])
            self.assertFalse(traversal["dimensionality_changed"])
            self.assertEqual(traversal["origin_dimension"],
                             seat_fields(traversal["origin_seat"])["dimensionality"])
            self.assertEqual(report["phase"], "complete")

    def test_all_ft4_3b2a_and_predecessor_identities_remain_exact(self):
        modules = (
            "tests_ft4.test_demands", "tests_ft4.test_requests", "tests_ft4.test_controller",
            "tests_ft4.test_route_means", "tests_ft4.test_route_execution",
            "tests_ft4.test_orientation", "tests_ft4.test_route_policy",
            "tests_ft4.test_opposition", "tests_ft4.test_autonomous_cycle",
            "tests_ft4.test_autonomous_closure", "tests_ft4.test_autonomous_capability")
        identities = []
        for name in modules:
            stack = list(unittest.defaultTestLoader.loadTestsFromName(name))
            while stack:
                item = stack.pop()
                if isinstance(item, unittest.TestSuite):
                    stack.extend(list(item))
                else:
                    identities.append(item.id())
        self.assertEqual(len(identities), 118)
        self.assertEqual(len(identities), len(set(identities)))
