from copy import deepcopy
from dataclasses import replace
import unittest

from hle_unified.selection_records import SelectionRequest, dumps, loads
from hle_unified.selection_execution import SelectionEngine
from hle_unified.operations import address
from hle_unified.material import attrs
from tests_c3 import fixtures as ca
from tests_c5 import fixtures as f
from tests_c6 import fixtures as c6
from tests_workflow_selection import fixtures as ws
from tests_ft4.test_controller import prepared
from tests_ft4.test_route_means import budgeted_request
from tests_ft3.test_retention import content, exposure, use

from full_theory.content import ContentBridge
from full_theory.retention import Demand, RetentionLedger
from full_theory.route_policy import IntegratedRoutePolicy
from full_theory.route_policy_audit import audit_route_policy


def demand(setting, request, requirements=("experience",), support=()):
    return Demand(setting,request.context,request.cue,request.target,
                  requirements=requirements,support_allowed=support)


def finish(engine, request, required, *, retention=None, keys=(), limit=1000000):
    controller=IntegratedRoutePolicy()
    for _ in range(32):
        row=controller.step(engine,request,required,retention=retention,
                            certificate_keys=keys,work_limit=limit)
        if row["phase"] in ("complete","deferred","failed","cancelled","rejected"):break
    else:raise AssertionError("bounded route policy did not stop")
    report=audit_route_policy(engine.world.journal(),engine.access.checkpoint(),
                              controller.checkpoint(engine),engine.checkpoint())
    return controller,row,report


def retained_fixture():
    engine=f.setup(engine_type=SelectionEngine);bridge=ContentBridge(engine)
    ledger=RetentionLedger(bridge);retained_demand=Demand("canonical",f.ROOM,f.CUE5,f.SAW)
    pattern=f.dev.generated(engine)
    for i,target in enumerate((f.SAW,f.SAW2,f.KIT,f.STOCK)):
        f.dev.release8(engine,"local-"+str(i),pattern,target)
    kept=content(engine,bridge,"canonical",f.SAW,"first")
    exposure(engine,bridge,ledger,retained_demand,kept,"close-1")
    exposure(engine,bridge,ledger,retained_demand,kept,"close-2")
    uses=[]
    for i,targets in enumerate(((f.SAW,f.KIT),(f.SAW2,f.STOCK))):
        event=f.dev.respond8(engine,"task-"+str(i),pattern,targets)
        current=kept if i==0 else content(engine,bridge,"canonical",f.SAW2,"second")
        key="training-use-"+str(i);use(engine,bridge,"canonical",current,key);uses.append(key)
        f.dev.practice8(engine,"practice-"+str(i),pattern,event)
    f.dev.reorganize8(engine,"organize-practice",pattern)
    capacity=engine._capacities[pattern.ref]["ref"]
    ledger.certify("guarded",f.ALICE,retained_demand,capacity,tuple(uses))
    c6.dev.supply8(engine,"neutral");native=c6.prepare(engine,"Understand","accumulation",key="available")
    for obj in (c6.SAW,c6.KIT,c6.STOCK,c6.SUPPLY):c6.expose(engine,c6.ALICE,engine.world.head(obj.identity).ref)
    owned=c6.need(engine,"route-need",(0,0,0,10),False,"quantity",False)
    request=SelectionRequest("route",c6.ALICE,c6.ROOM,c6.CUE5,c6.SAW,owned,
        stock=c6.SUPPLY,tool=c6.KIT,repair_stock=c6.STOCK,procedure=c6.REPAIR,
        peer=c6.BOB,group=native.group)
    return engine,request,retained_demand,ledger


class RoutePolicyTests(unittest.TestCase):
    def test_priority_matrix_selects_ordinary_n_cp_and_defer(self):
        cases=[]
        e,_,r,_=prepared("canonical");cases.append((e,r,demand("canonical",r),"ordinary"))
        e,r=c6.fixture("Understand","accumulation",tim="eii")
        cases.append((e,r,demand("canonical",r,("experience","norms")),"n"))
        e,r=c6.fixture("Understand","accumulation",tim="ese")
        cases.append((e,r,demand("canonical",r,("experience","norms","situation","time")),"cp"))
        e,r=c6.fixture("Understand","accumulation",tim="eii");r=replace(r,peer=None,group=None)
        cases.append((e,r,demand("canonical",r,("experience","norms","situation","time")),"defer"))
        for engine,request,required,expected in cases:
            controller=IntegratedRoutePolicy();row=controller.step(engine,request,required,work_limit=1)
            self.assertEqual(row["selected"],expected)
            self.assertEqual(controller.attempts[0]["selected"]["name"],expected)

    def test_retained_capacity_precedes_structural_route_without_changing_dimension(self):
        e,r,d,l=retained_fixture();c,row,report=finish(e,r,d,retention=l,keys=("guarded",))
        self.assertEqual(row["selected"],"retained");self.assertEqual(report["retained"],1)
        t=c.attempts[0]["traversal"]
        self.assertEqual(t["origin_seat"],t["target_seat"]);self.assertFalse(t["dimensionality_changed"])

    def test_removing_retained_evidence_changes_the_route(self):
        e,r,d,l=retained_fixture();checkpoint=e.checkpoint();removed=type(e).restore(checkpoint)
        a=IntegratedRoutePolicy();a.step(e,r,d,retention=l,certificate_keys=("guarded",))
        b=IntegratedRoutePolicy();b.step(removed,r,d)
        self.assertEqual(a.attempts[0]["selected"]["name"],"retained")
        self.assertEqual(b.attempts[0]["selected"]["name"],"ordinary")
        self.assertEqual(a.attempts[0]["origin_dimension"],b.attempts[0]["origin_dimension"])

    def test_cp_requires_paid_orientation_before_traversal(self):
        e,r=c6.fixture("Understand","accumulation",tim="ese")
        d=demand("canonical",r,("experience","norms","situation","time"));c=IntegratedRoutePolicy()
        first=c.step(e,r,d,work_limit=1)
        self.assertEqual(first["phase"],"orientation");self.assertIsNone(first["traversal"])
        self.assertNotIn((r.actor,r.key),e._jobs)
        second=c.step(e,r,d,work_limit=1)
        self.assertEqual(second["phase"],"native");self.assertIsNotNone(c.attempts[0]["orientation_ticket"])
        self.assertNotIn((r.actor,r.key+":movement"),e._jobs)
        for _ in range(16):
            row=c.step(e,r,d,work_limit=1000000)
            if row["phase"]=="complete":break
        self.assertIsNotNone(row["traversal"])
        self.assertTrue(audit_route_policy(e.world.journal(),e.access.checkpoint(),c.checkpoint(e),e.checkpoint())["passed"])

    def test_each_cp_traversal_links_its_exact_fee_and_native_work(self):
        for setting in ("canonical","workflow"):
            if setting=="canonical":e,r=c6.fixture("Understand","accumulation",tim="ese")
            else:e,r,_=ws.fixture("Commune","accumulation",tim="ile")
            d=demand(setting,r,("experience","norms","situation","time"));c,row,report=finish(e,r,d)
            t=row["traversal"];self.assertEqual(t["means"],"cp")
            self.assertEqual(t["orientation"]["job"],r.key+":cp-orientation")
            self.assertEqual(t["movement"],e._jobs[r.actor,r.key+":movement"])
            self.assertEqual(report["cp"],1)

    def test_native_launch_and_relay_completion_both_settings(self):
        for setting in ("canonical","workflow"):
            e,_,r,_=prepared(setting);d=demand(setting,r);c,row,report=finish(e,r,d)
            self.assertEqual(row["phase"],"complete");self.assertTrue(report["passed"])
            self.assertEqual(row["traversal"]["movement"],e._jobs[r.actor,r.key+":movement"])
            self.assertTrue(row["traversal"]["content_processed"])

    def test_exact_consent_support_both_settings(self):
        for setting in ("canonical","workflow"):
            if setting=="canonical":e,r=c6.fixture("Educate","accumulation",tim="eii")
            else:e,r,_=ws.fixture("Commune","accumulation",tim="eii")
            d=demand(setting,r,("experience","norms","situation","time"),(r.peer,))
            c,row,report=finish(e,r,d)
            self.assertEqual(row["selected"],"support");self.assertTrue(row["traversal"]["supported"])
            self.assertEqual(report["supports"],1)

    def test_nonconsent_foreign_and_unallowed_support_are_rejected(self):
        e,r=c6.fixture("Educate","accumulation",tim="eii")
        required=("experience","norms","situation","time")
        for support in ((),(ca.EVE,)):
            other=type(e).restore(e.checkpoint());c=IntegratedRoutePolicy()
            row=c.step(other,r,demand("canonical",r,required,support),work_limit=1)
            self.assertEqual(row["selected"],"defer")
        allowed=demand("canonical",r,required,(r.peer,));c=IntegratedRoutePolicy();c.step(e,r,allowed)
        forged=loads(c.checkpoint(e));forged["attempts"][0]["support"]["data"]["consent"]=False
        with self.assertRaises(ValueError):audit_route_policy(e.world.journal(),e.access.checkpoint(),dumps(forged),e.checkpoint())

    def test_native_deferral_never_records_a_relay_traversal(self):
        e,_,r,_=prepared("canonical")
        unavailable=c6.need(e,"unavailable-condition",(10,0,0,0),False,"condition",False)
        r=replace(r,key="unavailable",demand=unavailable);d=demand("canonical",r)
        c,row,report=finish(e,r,d)
        self.assertEqual(row["phase"],"deferred");self.assertIsNone(row["traversal"])
        self.assertEqual(report["traversals"],0)

    def test_partial_checkpoint_continues_exactly(self):
        e,r=c6.fixture("Understand","accumulation",tim="ese")
        d=demand("canonical",r,("experience","norms","situation","time"));c=IntegratedRoutePolicy();c.step(e,r,d)
        other=type(e).restore(e.checkpoint());restored=IntegratedRoutePolicy.restore(c.checkpoint(e),other)
        for _ in range(20):
            a=c.step(e,r,d,work_limit=1);b=restored.step(other,r,d,work_limit=1)
            self.assertEqual(a,b)
            if a["phase"] in ("complete","deferred","failed","rejected"):break
        self.assertEqual(e.checkpoint(),other.checkpoint());self.assertEqual(c.checkpoint(e),restored.checkpoint(other))

    def test_independent_auditor_rejects_forged_priority_support_fee_and_traversal(self):
        e,r=c6.fixture("Understand","accumulation",tim="ese")
        d=demand("canonical",r,("experience","norms","situation","time"));c,row,_=finish(e,r,d)
        original=loads(c.checkpoint(e))
        for path,value in (("priority",True),("fee",None),("target",original["attempts"][0]["origin_seat"])):
            forged=deepcopy(original);a=forged["attempts"][0]
            if path=="priority":a["options"][0]["eligible"]=True
            elif path=="fee":a["traversal"]["orientation"]=None
            else:a["traversal"]["target_seat"]=value
            with self.assertRaises(ValueError):audit_route_policy(e.world.journal(),e.access.checkpoint(),dumps(forged),e.checkpoint())
