from copy import deepcopy
from dataclasses import replace
import unittest

from hle_unified.selection_execution import SelectionEngine
from hle_unified.workflow_selection_execution import WorkflowSelectionEngine
from tests_c6 import fixtures as c6
from tests_u8 import fixtures as dev
from tests_workflow_selection import fixtures as ws

from full_theory.reserve_grid import (BUDGETS, GRID_CELL_COUNT, cell_identity,
    demand_relation, grid_axes, no_easier, run_grid_cell, select_release_policy)
from full_theory.reserve_grid_audit import audit_complete_grid, audit_grid_cell
from full_theory.retention import Demand


def _engine_factory(engine_type, model):
    def factory(world, law):
        if model == "legacy-r4":
            return engine_type(world, law)
        return engine_type.create(world, law, resource_model=model)
    return factory


def _canonical_request(model, budget):
    engine = c6.setup_c3("iee", budget=budget,
        engine_type=_engine_factory(SelectionEngine, model), shared=False)
    objects = (c6.definition(dev.TRIGGER, "Entrusted performance affordance"),
        c6.definition(dev.OTHER_TRIGGER, "Other affordance"),
        c6.ObjectVersion(dev.GROUP, c6.WRITER, "Group", (c6.Role.COLLECTIVE,),
            (c6.Composition((c6.ALICE, c6.BOB), "workshop"),)),
        c6.ObjectVersion(dev.MEMORY, c6.WRITER, "Memory", (c6.Role.CLAIM,),
            (c6.Account(c6.SAW, (), c6.Moment(0, 0), c6.ALICE),),
            occurrence=c6.Occurrence.REMEMBERED_CLAIM),
        c6.ObjectVersion(dev.POSSIBILITY, c6.WRITER, "Possibility", (c6.Role.CLAIM,),
            (c6.Account(c6.SAW, (), c6.Moment(0, 0), c6.ALICE),),
            occurrence=c6.Occurrence.HYPOTHETICAL),
        c6.ObjectVersion(dev.ACTION, c6.WRITER, "Plan", (c6.Role.PROCEDURE,),
            (c6.Procedure(("target",), (), (), ()),)))
    engine.declare("c5-anchors", objects)
    for ref in (*dev.TARGETS.values(), dev.TRIGGER, dev.OTHER_TRIGGER,
                c6.ObjectRef(c6.EVE, 1), c6.SAW2):
        if ref not in engine.access._known_refs(c6.ALICE):
            c6.show(engine, c6.ALICE, ref)
    engine.configure_patterns("c5-policy", c6.PatternPolicy(c6.ALICE, generate=False))
    dev.supply8(engine, "neutral")
    source = c6.prepare(engine, "Understand", "accumulation", key="available")
    for ref in (c6.SAW, c6.KIT, c6.STOCK, c6.SUPPLY):
        c6.expose(engine, c6.ALICE, engine.world.head(ref.identity).ref)
    weights = tuple(10 if index == c6.NAMES.index("Understand") % 4 else 0
                    for index in range(4))
    owned = c6.need(engine, "owned-need", weights, False, "quantity", False)
    request = c6.SelectionRequest("automatic", c6.ALICE, c6.ROOM, c6.CUE5,
        c6.SAW, owned, stock=c6.SUPPLY, tool=c6.KIT, repair_stock=c6.STOCK,
        procedure=c6.REPAIR, peer=c6.BOB, group=source.group)
    return engine, request


def native_case(setting, model, budget_class, load):
    budget = BUDGETS[budget_class][setting]
    if setting == "canonical":
        engine, request = _canonical_request(model, budget)
    else:
        engine, request, _ = ws.fixture("Contemplate", "accumulation",
            engine_type=_engine_factory(WorkflowSelectionEngine, model), budget=budget)
    demand = Demand(setting, request.context, request.cue, request.target, load=load)
    return engine, request, demand


def run_axes(axes):
    engine, request, demand = native_case(axes["setting"], axes["wallet_model"],
                                           axes["budget_class"], axes["load"])
    cell = run_grid_cell(engine, request, demand, axes)
    return cell, audit_grid_cell(engine, cell)


def complete_grid():
    reports = []
    for axes in grid_axes():
        _, report = run_axes(axes)
        reports.append(report)
    return reports


class ReserveGridTests(unittest.TestCase):
    def test_partial_order_reports_equivalent_harder_easier_and_incomparable(self):
        _, request, base = native_case("canonical", "legacy-r4", "ample", 1)
        harder = replace(base, requirements=("experience", "norms"),
            obligations=("participate", "account"), alternatives=("I", "IT"),
            load=2, deadline=999)
        crossed = replace(base, requirements=("experience", "norms"), deadline=1000,
                          support_allowed=("peer",))
        self.assertEqual(demand_relation(base, base), "equivalent")
        self.assertEqual(demand_relation(harder, base), "harder")
        self.assertEqual(demand_relation(base, harder), "easier")
        self.assertEqual(demand_relation(crossed, base), "incomparable")

    def test_changed_target_is_incomparable_even_when_other_coordinates_match(self):
        _, _, base = native_case("canonical", "legacy-r4", "ample", 1)
        changed = replace(base, target=c6.SAW2)
        self.assertEqual((demand_relation(base, changed), demand_relation(changed, base)),
                         ("incomparable", "incomparable"))

    def test_partial_order_is_reflexive_antisymmetric_and_transitive(self):
        _, _, base = native_case("canonical", "legacy-r4", "ample", 1)
        middle = replace(base, requirements=("experience", "norms"), load=2)
        hard = replace(middle, obligations=("participate", "account"),
                       alternatives=("I", "IT"), load=4, deadline=999)
        rows = (base, middle, hard)
        self.assertTrue(all(no_easier(row, row) for row in rows))
        self.assertTrue(no_easier(hard, middle) and no_easier(middle, base)
                        and no_easier(hard, base))
        for left in rows:
            for right in rows:
                if no_easier(left, right) and no_easier(right, left):
                    self.assertEqual(left.record(), right.record())

    def test_grid_axes_are_exact_and_have_432_unique_cells(self):
        rows = grid_axes()
        self.assertEqual((len(rows), len({cell_identity(row) for row in rows})),
                         (GRID_CELL_COUNT, GRID_CELL_COUNT))
        self.assertEqual({tuple(row) for row in rows}, {(
            "setting", "policy", "initial_reserve", "load", "token_inventory",
            "wallet_model", "budget_class")})

    def test_each_grid_cell_uses_actual_declared_wallet_model_and_budget(self):
        for setting in ("canonical", "workflow"):
            for model in ("legacy-r4", "grade-v1"):
                for budget_class in ("ample", "scarce"):
                    axes = dict(setting=setting, policy="null", initial_reserve=4,
                        load=1, token_inventory=0, wallet_model=model,
                        budget_class=budget_class)
                    cell, report = run_axes(axes)
                    self.assertTrue(report["passed"])
                    self.assertEqual(cell["wallet_before"]["initial_energy"],
                                     BUDGETS[budget_class][setting])

    def test_grid_preparation_is_exact_and_never_hides_native_routes(self):
        for policy, initial, load, expected in (("null", 0, 4, 0),
                ("load-v1", 0, 4, 4), ("grade-load-v1", 4, 4, 0)):
            axes = dict(setting="canonical", policy=policy, initial_reserve=initial,
                load=load, token_inventory=0, wallet_model="legacy-r4",
                budget_class="ample")
            cell, report = run_axes(axes)
            self.assertEqual(report["preparation"], expected)
            self.assertEqual(len(cell["candidate_event"]["route_options"]), 6)

    def test_token_inventory_without_paid_uptake_causes_no_balance_or_route_change(self):
        rows = []
        for tokens in (0, 2):
            axes = dict(setting="workflow", policy="load-v1", initial_reserve=4,
                load=2, token_inventory=tokens, wallet_model="grade-v1",
                budget_class="ample")
            _, report = run_axes(axes)
            rows.append((report["preparation"], report["phase"],
                         report["selected_candidate"], report["reserve_balance"],
                         report["wallet_delta"]))
        self.assertEqual(rows[0], rows[1])

    def test_ample_and_scarce_budget_results_are_reported_without_retuning(self):
        reports = {}
        for budget_class in ("ample", "scarce"):
            axes = dict(setting="canonical", policy="null", initial_reserve=4,
                load=1, token_inventory=0, wallet_model="legacy-r4",
                budget_class=budget_class)
            _, reports[budget_class] = run_axes(axes)
        self.assertEqual(reports["ample"]["axes"]["budget_class"], "ample")
        self.assertEqual(reports["scarce"]["axes"]["budget_class"], "scarce")
        self.assertNotEqual(reports["ample"]["wallet_delta"],
                            reports["scarce"]["wallet_delta"])

    def test_independent_auditor_reconstructs_every_grid_cell(self):
        reports = complete_grid()
        self.assertEqual(audit_complete_grid(reports),
                         {"passed": True, "cells": 432, "token_pairs": 216})

    def test_independent_auditor_rejects_forged_axis_order_and_preparation(self):
        axes = dict(setting="canonical", policy="load-v1", initial_reserve=0,
            load=1, token_inventory=0, wallet_model="legacy-r4", budget_class="ample")
        engine, request, demand = native_case("canonical", "legacy-r4", "ample", 1)
        cell = run_grid_cell(engine, request, demand, axes)
        forged = deepcopy(cell)
        forged["axes"] = dict(reversed(tuple(forged["axes"].items())))
        with self.assertRaises(ValueError):
            audit_grid_cell(engine, forged)
        forged = deepcopy(cell)
        forged["candidate_event"]["preparation_required"] = 0
        with self.assertRaises(ValueError):
            audit_grid_cell(engine, forged)

    def test_release_election_selects_load_v1_only_after_complete_invariants(self):
        reports = [{"passed": True, "cell_id": cell_identity(axes)} for axes in grid_axes()]
        decision = select_release_policy(reports)
        self.assertEqual((decision["status"], decision["selected"]),
                         ("selected", "load-v1"))

    def test_release_election_holds_on_missing_failed_or_duplicate_cells(self):
        reports = [{"passed": True, "cell_id": cell_identity(axes)} for axes in grid_axes()]
        self.assertEqual(select_release_policy(reports[:-1])["status"], "held")
        failed = deepcopy(reports); failed[0]["passed"] = False
        self.assertEqual(select_release_policy(failed)["status"], "held")
        duplicate = deepcopy(reports); duplicate[-1] = deepcopy(duplicate[0])
        self.assertEqual(select_release_policy(duplicate)["status"], "held")
        self.assertEqual(select_release_policy(reports,
            paid_recovery_predecessor=False)["status"], "held")

    def test_ft5_3a_and_all_predecessor_method_identity_remain_exact(self):
        modules = ("tests_ft5.test_reserve_recovery", "tests_ft5.test_reserve_cycle",
            "tests_ft5.test_reserve_candidates", "tests_ft5.test_native_reserve",
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
        self.assertEqual((len(identities), len(set(identities))), (202, 202))
