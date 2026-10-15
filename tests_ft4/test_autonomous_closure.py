from copy import deepcopy
from dataclasses import replace
import inspect
import unittest

from hle_unified.records import (Account, Composition, Moment, ObjectRef, ObjectVersion,
                                 Occurrence, Procedure, Role)
from hle_unified.selection_records import dumps, loads
from tests_c5 import fixtures as f
from tests_ft3.test_retention import content, use

from full_theory.autonomous_closure import AutonomousClosureController
from full_theory.autonomous_closure_audit import audit_autonomous_closure
from full_theory.autonomous_cycle import AutonomousCycleController
from full_theory.content import ContentBridge
from tests_ft4.test_autonomous_cycle import finish, fixture


def install_shell_opportunities(engine):
    dev = f.dev
    if dev.TRIGGER.identity not in engine.world._heads:
        objects = (
            f.definition(dev.TRIGGER, "Entrusted performance affordance"),
            f.definition(dev.OTHER_TRIGGER, "Other affordance"),
            ObjectVersion(dev.GROUP, f.WRITER, "Group", (Role.COLLECTIVE,),
                (Composition((f.ALICE, f.BOB), "workshop"),)),
            ObjectVersion(dev.MEMORY, f.WRITER, "Memory", (Role.CLAIM,),
                (Account(f.SAW, (), Moment(0, 0), f.ALICE),),
                occurrence=Occurrence.REMEMBERED_CLAIM),
            ObjectVersion(dev.POSSIBILITY, f.WRITER, "Possibility", (Role.CLAIM,),
                (Account(f.SAW, (), Moment(0, 0), f.ALICE),),
                occurrence=Occurrence.HYPOTHETICAL),
            ObjectVersion(dev.ACTION, f.WRITER, "Plan", (Role.PROCEDURE,),
                (Procedure(("target",), (), (), ()),)))
        engine.declare("ft43b1-anchors", objects)
        for ref in (*dev.TARGETS.values(), dev.TRIGGER, dev.OTHER_TRIGGER,
                    ObjectRef(f.EVE, 1), f.SAW2):
            if ref not in engine.access._known_refs(f.ALICE):
                f.show(engine, f.ALICE, ref)
        engine.configure_patterns("ft43b1-pattern-policy", f.PatternPolicy(f.ALICE, generate=True))


def add_episode(engine, bridge, demand, kept, key, *, shell=True):
    use(engine, bridge, demand.family, kept, key + "-use")
    if shell:
        source = f.dev.supply8(engine, key + "-facts", target=demand.target)
        f.dev.meet(engine, key + "-shell", source, target=demand.target)


def closure_case(setting="canonical", episodes=2, changed=False):
    engine, cycle, demand, _, _ = finish(setting)
    install_shell_opportunities(engine)
    controller = AutonomousClosureController(cycle, engine, cycle.actor, demand)
    bridge = ContentBridge(engine)
    first = content(engine, bridge, setting, demand.target, "closure-a")
    add_episode(engine, bridge, demand, first, "closure-1")
    second = content(engine, bridge, setting, demand.target, "closure-b") if changed else first
    if episodes > 1:
        add_episode(engine, bridge, demand, second, "closure-2")
    rows = [controller.step(engine) for _ in range(episodes)]
    report = audit_autonomous_closure(engine.world.journal(), engine.access.checkpoint(),
        controller.checkpoint(engine), cycle.checkpoint(engine), engine.checkpoint())
    return engine, cycle, demand, controller, rows, report


class AutonomousClosureTests(unittest.TestCase):
    def test_discovers_two_honest_closure_exposures_in_both_settings(self):
        for setting in ("canonical", "workflow"):
            _, _, _, controller, rows, report = closure_case(setting)
            self.assertEqual([row["retention"]["hold"] for row in rows], [1, 2])
            self.assertTrue(controller.phase == "closed" and report["closed"])

    def test_discovery_accepts_no_operation_keys_or_success_flag(self):
        parameters = tuple(inspect.signature(AutonomousClosureController.step).parameters)
        self.assertEqual(parameters, ("self", "engine", "scan_limit", "interrupted"))
        _, _, _, controller, rows, _ = closure_case()
        self.assertNotIn("success", parameters)
        self.assertTrue(all("candidate" in row for row in rows))

    def test_settlement_must_precede_closure_discovery(self):
        engine, actor, demand = fixture()
        with self.assertRaises(ValueError):
            AutonomousClosureController(AutonomousCycleController(), engine, actor, demand)

    def test_exact_owned_scope_and_actor_are_required(self):
        engine, cycle, demand, _, _ = finish()
        with self.assertRaises(ValueError):
            AutonomousClosureController(cycle, engine, f.BOB, demand)
        with self.assertRaises(ValueError):
            AutonomousClosureController(cycle, engine, cycle.actor, replace(demand, target=f.KIT))

    def test_missing_complement_to_native_return_stays_open(self):
        engine, cycle, demand, _, _ = finish()
        install_shell_opportunities(engine)
        controller = AutonomousClosureController(cycle, engine, cycle.actor, demand)
        bridge = ContentBridge(engine)
        output = engine.job_status(cycle.actor, cycle.request.key + ":movement")["binding"]
        kept = {"result": output, "target": demand.target}
        add_episode(engine, bridge, demand, kept, "no-return")
        self.assertEqual(controller.step(engine)["kind"], "closure_wait")
        self.assertEqual(controller.phase, "open")

    def test_missing_or_incomplete_shell_clearance_stays_open(self):
        engine, cycle, demand, _, _ = finish()
        install_shell_opportunities(engine)
        controller = AutonomousClosureController(cycle, engine, cycle.actor, demand)
        bridge = ContentBridge(engine); kept = content(engine, bridge, demand.family, demand.target, "no-shell")
        add_episode(engine, bridge, demand, kept, "no-shell", shell=False)
        self.assertEqual(controller.step(engine)["kind"], "closure_wait")

    def test_changed_content_resets_continuity_window(self):
        _, _, _, controller, rows, report = closure_case(changed=True)
        self.assertEqual([row["retention"]["hold"] for row in rows], [1, 1])
        self.assertFalse(report["closed"]); self.assertEqual(controller.phase, "open")

    def test_interrupted_or_unpaid_work_never_closes(self):
        engine, cycle, demand, _, _ = finish()
        install_shell_opportunities(engine)
        controller = AutonomousClosureController(cycle, engine, cycle.actor, demand)
        bridge = ContentBridge(engine); kept = content(engine, bridge, demand.family, demand.target, "interrupt")
        add_episode(engine, bridge, demand, kept, "interrupt-1")
        add_episode(engine, bridge, demand, kept, "interrupt-2")
        first = controller.step(engine, interrupted=True)
        second = controller.step(engine)
        self.assertEqual((first["retention"]["hold"], second["retention"]["hold"]), (0, 1))
        self.assertEqual(controller.phase, "open")

    def test_candidates_are_scanned_in_committed_chronological_order(self):
        engine, cycle, demand, _, _ = finish()
        install_shell_opportunities(engine)
        controller = AutonomousClosureController(cycle, engine, cycle.actor, demand)
        bridge = ContentBridge(engine); kept = content(engine, bridge, demand.family, demand.target, "ordered")
        add_episode(engine, bridge, demand, kept, "z-first")
        add_episode(engine, bridge, demand, kept, "a-second")
        first = controller.step(engine); second = controller.step(engine)
        self.assertEqual(first["candidate"]["consumer_key"], "z-first-use")
        self.assertEqual(second["candidate"]["consumer_key"], "a-second-use")
        self.assertLessEqual(tuple(first["candidate"]["order"]), tuple(second["candidate"]["order"]))

    def test_checkpoint_continuation_is_exact(self):
        engine, cycle, demand, _, _ = finish()
        install_shell_opportunities(engine)
        original = AutonomousClosureController(cycle, engine, cycle.actor, demand)
        bridge = ContentBridge(engine); kept = content(engine, bridge, demand.family, demand.target, "restart")
        add_episode(engine, bridge, demand, kept, "restart-1")
        add_episode(engine, bridge, demand, kept, "restart-2")
        original.step(engine)
        restored = AutonomousClosureController.restore(original.checkpoint(engine), cycle, engine)
        self.assertEqual(original.step(engine), restored.step(engine))
        self.assertEqual(original.checkpoint(engine), restored.checkpoint(engine))

    def test_independent_auditor_rejects_forged_closure_and_links(self):
        engine, cycle, _, controller, _, _ = closure_case()
        checkpoint = loads(controller.checkpoint(engine))
        for mutation in ("closed", "consumer", "order"):
            forged = deepcopy(checkpoint)
            if mutation == "closed":
                forged["retention_events"][-1]["closed"] = False
            elif mutation == "consumer":
                forged["events"][-1]["candidate"]["consumer_ref"] = forged["events"][0]["candidate"]["consumer_ref"]
            else:
                forged["events"][-1]["candidate"]["order"] = (0, 0, "", "")
            with self.assertRaises(ValueError):
                audit_autonomous_closure(engine.world.journal(), engine.access.checkpoint(),
                    dumps(forged), cycle.checkpoint(engine), engine.checkpoint())

    def test_all_ft4_3a_and_predecessor_method_identities_remain_exact(self):
        modules = (
            "tests_ft4.test_demands", "tests_ft4.test_requests", "tests_ft4.test_controller",
            "tests_ft4.test_route_means", "tests_ft4.test_route_execution",
            "tests_ft4.test_orientation", "tests_ft4.test_route_policy",
            "tests_ft4.test_opposition", "tests_ft4.test_autonomous_cycle")
        identities = []
        for name in modules:
            stack = list(unittest.defaultTestLoader.loadTestsFromName(name))
            while stack:
                item = stack.pop()
                if isinstance(item, unittest.TestSuite):
                    stack.extend(list(item))
                else:
                    identities.append(item.id())
        self.assertEqual(len(identities), 95)
        self.assertEqual(len(identities), len(set(identities)))
