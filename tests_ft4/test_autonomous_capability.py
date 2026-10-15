from copy import deepcopy
from dataclasses import replace
import inspect
import unittest

from hle_unified.selection_records import dumps, loads
from hle_unified.shell_records import Effect
from tests_c5 import fixtures as f
from tests_ft3.test_retention import content, use

from full_theory.autonomous_capability import AutonomousCapabilityController
from full_theory.autonomous_capability_audit import audit_autonomous_capability
from full_theory.autonomous_closure import AutonomousClosureController
from full_theory.content import ContentBridge
from tests_ft4.test_autonomous_closure import closure_case


def add_training(engine, demand, *, unrelated=False):
    pattern = engine._patterns[f.dev.inject(engine, Effect("approval"), key="cap-pattern")]
    for i, target in enumerate((f.SAW, f.SAW2, f.KIT, f.STOCK)):
        f.dev.release8(engine, "cap-local-" + str(i), pattern, target)
    bridge = ContentBridge(engine)
    uses = []
    for i, targets in enumerate(((f.SAW, f.KIT), (f.SAW2, f.STOCK))):
        event = f.dev.respond8(engine, "cap-task-" + str(i), pattern, targets)
        target = f.BORROWED if unrelated else targets[0]
        current = content(engine, bridge, demand.family, target, "cap-content-" + str(i))
        key = "cap-use-" + str(i)
        use(engine, bridge, demand.family, current, key)
        uses.append(key)
        f.dev.practice8(engine, "cap-practice-" + str(i), pattern, event)
    f.dev.reorganize8(engine, "cap-organize", pattern)
    return pattern, tuple(uses)


def capability_case(setting="canonical"):
    engine, cycle, demand, closure, _, _ = closure_case(setting)
    controller = AutonomousCapabilityController(closure, engine)
    add_training(engine, demand)
    row = controller.step(engine)
    report = audit_autonomous_capability(engine.world.journal(), engine.access.checkpoint(),
        controller.checkpoint(engine), closure.checkpoint(engine), cycle.checkpoint(engine),
        engine.checkpoint())
    return engine, cycle, demand, closure, controller, row, report


class AutonomousCapabilityTests(unittest.TestCase):
    def test_discovers_and_certifies_owned_capability_in_both_settings(self):
        for setting in ("canonical", "workflow"):
            engine, _, demand, _, controller, row, report = capability_case(setting)
            self.assertEqual(controller.phase, "certified")
            self.assertTrue(row["certified"] and report["certified"])
            self.assertEqual(report["certificates"], 1)
            self.assertEqual(controller.ledger.applicable(
                controller.certificate_key, controller.actor, demand)[0], True)

    def test_discovery_accepts_no_capacity_use_or_success_input(self):
        parameters = tuple(inspect.signature(AutonomousCapabilityController.step).parameters)
        self.assertEqual(parameters, ("self", "engine", "scan_limit"))
        for forbidden in ("capacity", "practice", "content_use", "candidate", "route", "success"):
            self.assertNotIn(forbidden, parameters)

    def test_honest_closure_must_precede_certification(self):
        engine, cycle, demand, _, _, _ = closure_case(episodes=1)
        open_controller = AutonomousClosureController(cycle, engine, cycle.actor, demand)
        with self.assertRaises(ValueError):
            AutonomousCapabilityController(open_controller, engine)

    def test_supported_duplicate_and_insufficient_training_stay_open(self):
        engine, _, demand, closure, _, _ = closure_case()
        controller = AutonomousCapabilityController(closure, engine)
        row = controller.step(engine)
        self.assertEqual(row["kind"], "capability_wait")
        self.assertEqual(controller.phase, "open")
        pattern = engine._patterns[f.dev.inject(engine, Effect("approval"), key="short-pattern")]
        for i, target in enumerate((f.SAW, f.KIT)):
            f.dev.release8(engine, "short-local-" + str(i), pattern, target)
        event = f.dev.respond8(engine, "short-task", pattern, (f.SAW, f.KIT))
        bridge = ContentBridge(engine)
        current = content(engine, bridge, demand.family, f.SAW, "short-content")
        use(engine, bridge, demand.family, current, "short-use")
        f.dev.practice8(engine, "short-practice", pattern, event)
        with self.assertRaises(ValueError):
            f.dev.reorganize8(engine, "short-organize", pattern)
        self.assertEqual(controller.step(engine)["kind"], "capability_wait")

    def test_candidate_order_is_committed_and_stable(self):
        engine, _, _, _, controller, row, _ = capability_case()
        before = row["candidates"]
        engine._capacities = dict(reversed(tuple(engine._capacities.items())))
        engine._jobs = dict(reversed(tuple(engine._jobs.items())))
        again = controller.step(engine)
        self.assertEqual(again["candidates"], before)

    def test_wrong_scope_and_unrelated_content_use_are_rejected(self):
        engine, _, demand, closure, _, _ = closure_case()
        controller = AutonomousCapabilityController(closure, engine)
        add_training(engine, demand, unrelated=True)
        row = controller.step(engine)
        self.assertEqual(row["kind"], "capability_wait")
        self.assertEqual(controller.phase, "open")

    def test_certificate_is_applicable_only_inside_trained_bounds(self):
        _, _, demand, _, controller, _, _ = capability_case()
        within = replace(demand, load=2)
        outside = replace(demand, load=3)
        self.assertTrue(controller.ledger.applicable(
            controller.certificate_key, controller.actor, within)[0])
        self.assertEqual(controller.ledger.applicable(
            controller.certificate_key, controller.actor, outside)[1],
            "outside_trained_demand_bounds")

    def test_removing_recall_or_revoking_evidence_preserves_closure_history(self):
        _, _, demand, _, controller, _, _ = capability_case()
        before = deepcopy(controller.ledger.history)
        wrong = replace(demand, cue=f.CUE)
        self.assertFalse(controller.ledger.applicable(
            controller.certificate_key, controller.actor, wrong)[0])
        controller.ledger.revoke(controller.certificate_key,
                                 "independent episode evidence withdrawn")
        self.assertEqual(controller.ledger.applicable(
            controller.certificate_key, controller.actor, demand),
            (False, "revoked_evidence"))
        self.assertEqual(controller.ledger.history, before)

    def test_checkpoint_continuation_is_exact(self):
        engine, _, _, closure, controller, row, _ = capability_case("workflow")
        restored = AutonomousCapabilityController.restore(
            controller.checkpoint(engine), closure, engine)
        self.assertEqual(restored.step(engine), row)
        self.assertEqual(restored.checkpoint(engine), controller.checkpoint(engine))

    def test_independent_auditor_rejects_forged_capacity_use_order_and_claim(self):
        engine, cycle, _, closure, controller, _, _ = capability_case()
        original = loads(controller.checkpoint(engine))
        for mutation in ("capacity", "use", "order", "claim"):
            forged = deepcopy(original)
            event = forged["events"][-1]
            if mutation == "capacity":
                event["selected"]["capacity_ref"] = event["selected"]["content_use_refs"][0]
            elif mutation == "use":
                event["selected"]["content_use_refs"] = tuple(reversed(
                    event["selected"]["content_use_refs"]))
            elif mutation == "order":
                event["selected"]["order"] = (0, "", ())
            else:
                forged["retention_events"][-1]["material_competence"] = True
            with self.assertRaises(ValueError):
                audit_autonomous_capability(engine.world.journal(), engine.access.checkpoint(),
                    dumps(forged), closure.checkpoint(engine), cycle.checkpoint(engine),
                    engine.checkpoint())

    def test_all_ft4_3b1_and_predecessor_method_identities_remain_exact(self):
        modules = (
            "tests_ft4.test_demands", "tests_ft4.test_requests", "tests_ft4.test_controller",
            "tests_ft4.test_route_means", "tests_ft4.test_route_execution",
            "tests_ft4.test_orientation", "tests_ft4.test_route_policy",
            "tests_ft4.test_opposition", "tests_ft4.test_autonomous_cycle",
            "tests_ft4.test_autonomous_closure")
        identities = []
        for name in modules:
            stack = list(unittest.defaultTestLoader.loadTestsFromName(name))
            while stack:
                item = stack.pop()
                if isinstance(item, unittest.TestSuite):
                    stack.extend(list(item))
                else:
                    identities.append(item.id())
        self.assertEqual(len(identities), 107)
        self.assertEqual(len(identities), len(set(identities)))
