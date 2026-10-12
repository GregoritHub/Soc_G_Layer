from copy import deepcopy
from dataclasses import dataclass, replace
import unittest

from hle.development_structure import lap, portage
from hle.model_a import TYPES, element_at, fields as seat_fields, position_of
from hle_unified.selection_execution import SelectionEngine
from hle_unified.selection_records import SelectionRequest, fields_of
from tests_c3 import fixtures as ca
from tests_c6 import fixtures as c6
from tests_u8 import fixtures as dev

from full_theory.route_means import inventory_route_means
from full_theory.route_means_audit import audit_route_means
from tests_ft4.test_controller import prepared
from tests_ft4.test_demands import withdraw


@dataclass(frozen=True)
class RouteNamedRequest(SelectionRequest):
    route: str = "n"


def budgeted_request(budget=87):
    def factory(world, law):
        return SelectionEngine(world, law)
    engine = c6.setup_c3("iee", budget=budget, engine_type=factory, shared=False)
    objects = (c6.definition(dev.TRIGGER, "Entrusted performance affordance"),
        c6.definition(dev.OTHER_TRIGGER, "Other affordance"),
        c6.ObjectVersion(dev.GROUP,c6.WRITER,"Group",(c6.Role.COLLECTIVE,),
            (c6.Composition((c6.ALICE,c6.BOB),"workshop"),)),
        c6.ObjectVersion(dev.MEMORY,c6.WRITER,"Memory",(c6.Role.CLAIM,),
            (c6.Account(c6.SAW,(),c6.Moment(0,0),c6.ALICE),),occurrence=c6.Occurrence.REMEMBERED_CLAIM),
        c6.ObjectVersion(dev.POSSIBILITY,c6.WRITER,"Possibility",(c6.Role.CLAIM,),
            (c6.Account(c6.SAW,(),c6.Moment(0,0),c6.ALICE),),occurrence=c6.Occurrence.HYPOTHETICAL),
        c6.ObjectVersion(dev.ACTION,c6.WRITER,"Plan",(c6.Role.PROCEDURE,),
            (c6.Procedure(("target",),(),(),()),)))
    engine.declare("c5-anchors", objects)
    for ref in (*dev.TARGETS.values(),dev.TRIGGER,dev.OTHER_TRIGGER,c6.ObjectRef(c6.EVE,1),c6.SAW2):
        if ref not in engine.access._known_refs(c6.ALICE):
            c6.show(engine,c6.ALICE,ref)
    engine.configure_patterns("c5-policy",c6.PatternPolicy(c6.ALICE,generate=False))
    dev.supply8(engine,"neutral")
    source = c6.prepare(engine,"Understand","accumulation",key="available")
    for ref in (c6.SAW,c6.KIT,c6.STOCK,c6.SUPPLY):
        c6.expose(engine,c6.ALICE,engine.world.head(ref.identity).ref)
    weights=tuple(10 if i==c6.NAMES.index("Understand")%4 else 0 for i in range(4))
    demand=c6.need(engine,"owned-need",weights,False,"quantity",False)
    request=c6.SelectionRequest("automatic",c6.ALICE,c6.ROOM,c6.CUE5,c6.SAW,demand,
        stock=c6.SUPPLY,tool=c6.KIT,repair_stock=c6.STOCK,procedure=c6.REPAIR,
        peer=c6.BOB,group=source.group)
    return engine,request


class RouteMeansTests(unittest.TestCase):
    def test_both_native_request_settings_are_accepted(self):
        for setting in ("canonical","workflow"):
            engine, _, request, _ = prepared(setting)
            row=inventory_route_means(engine,request)
            self.assertTrue(audit_route_means(engine.world.journal(),row)["passed"])
            self.assertEqual(row["setting"],setting)

    def test_all_types_and_seats_match_reference_geometry(self):
        count=0
        for tim in TYPES:
            engine,_=c6.fixture("Understand","accumulation",tim=tim)
            from full_theory.demand_controller import IntegratedDemandController
            from tests_ft4.test_demands import state
            controller=IntegratedDemandController();request,_=controller.cycle(engine,ca.ALICE,state())
            for seat in range(1,9):
                engine._cursors[ca.ALICE]=element_at(tim,seat);before=engine.checkpoint()
                row=inventory_route_means(engine,request);options={x["name"]:x for x in row["options"]}
                self.assertEqual((options["ordinary"]["target_seat"],options["n"]["target_seat"],options["cp"]["target_seat"]),
                    (lap(seat),portage(seat,"n"),portage(seat,"cp")))
                self.assertEqual(before,engine.checkpoint());count+=1
        self.assertEqual(count,128)

    def test_n_has_zero_overhead_but_keeps_content_cost_separate(self):
        engine,_,request,_=prepared("canonical");row=inventory_route_means(engine,request)
        n=row["options"][1]
        self.assertEqual(n["overhead"],dict(energy=0,time=0))
        self.assertTrue(n["content_cost_separate"])
        self.assertIn("native_content_unpriced_here",n["reason"])

    def test_cp_costs_exact_orientation_read(self):
        engine,_,request,_=prepared("workflow");row=inventory_route_means(engine,request);cp=row["options"][2]
        self.assertEqual(cp["overhead"],dict(energy=2,time=2))
        self.assertEqual(cp["orientation_read"],request.key+":cp-orientation")

    def test_cp_preserves_accepting_and_flips_ring(self):
        engine,_,request,_=prepared("canonical");cp=inventory_route_means(engine,request)["options"][2]
        self.assertEqual(cp["origin_fields"]["accepting"],cp["target_fields"]["accepting"])
        self.assertNotEqual(cp["origin_fields"]["ring"],cp["target_fields"]["ring"])

    def test_cp_conjugates_lap_to_reverse_orientation(self):
        engine,_,request,_=prepared("canonical");cp=inventory_route_means(engine,request)["options"][2]
        self.assertEqual(cp["conjugated_lap"],cp["reverse_lap"])

    def test_unaffordable_cp_remains_visible_and_ineligible(self):
        engine,request=budgeted_request();self.assertEqual(engine.wallet(ca.ALICE)["energy"],1)
        row=inventory_route_means(engine,request);cp=row["options"][2]
        self.assertFalse(cp["eligible"]);self.assertEqual(cp["reason"],"insufficient_wallet_for_orientation_read")
        self.assertTrue(audit_route_means(engine.world.journal(),row)["passed"])

    def test_inventory_never_selects_or_mutates_native_state(self):
        for setting in ("canonical","workflow"):
            engine,_,request,_=prepared(setting);before=engine.checkpoint()
            row=inventory_route_means(engine,request)
            self.assertEqual(before,engine.checkpoint());self.assertIsNone(row["selected"])
            self.assertFalse(row["completion_claim"]);self.assertTrue(all(not x["completion_claim"] for x in row["options"]))

    def test_stale_foreign_and_route_named_requests_are_rejected(self):
        engine,controller,request,_=prepared("canonical")
        with self.assertRaises(ValueError):inventory_route_means(engine,replace(request,actor=ca.BOB))
        with self.assertRaises(ValueError):inventory_route_means(engine,RouteNamedRequest(**fields_of(request),route="n"))
        demand=next(iter(controller.ledger.demands.values()));withdraw(engine,demand["binding"])
        with self.assertRaises(ValueError):inventory_route_means(engine,request)

    def test_independent_auditor_rejects_tampered_geometry_cost_and_scope(self):
        engine,_,request,_=prepared("workflow");row=inventory_route_means(engine,request)
        forged=deepcopy(row);forged["options"][2]["target_seat"]=forged["active_seat"]
        with self.assertRaises(ValueError):audit_route_means(engine.world.journal(),forged)
        forged=deepcopy(row);forged["options"][2]["overhead"]["energy"]=0
        with self.assertRaises(ValueError):audit_route_means(engine.world.journal(),forged)
        forged=deepcopy(row);forged["demand"]=ca.CUE5
        with self.assertRaises(ValueError):audit_route_means(engine.world.journal(),forged)
