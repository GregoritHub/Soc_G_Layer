from copy import deepcopy
from pathlib import Path
import inspect
import json
import unittest

from hle_unified.material import attrs
from hle_unified.selection_execution import SelectionEngine
from hle_unified.workflow_selection_execution import WorkflowSelectionEngine
from hle_unified.selection_records import dumps, loads
from hle_unified.self_content import encode
from tests_c3 import fixtures as ca
from tests_c6 import fixtures as c6
from tests_c7_workflow import fixtures as wf
from tests_ft4.test_demands import state
from full_theory.retention import Demand
from full_theory.social_cycle import SocialSupportCycle
from full_theory.social_cycle_audit import audit_social_cycle

ROOT=Path(__file__).resolve().parents[1]


def peer_opportunity(setting, consent=True):
    """Supplied lawful opportunities; final reply is deliberately unreceived."""
    if setting=="canonical":
        e=c6.setup(tim="eii",engine_type=SelectionEngine)
        c6.dev.supply8(e,"neutral")
        source=ca.model(e,"social-model")
        group=ca.join(e,ca.group(e,"social-group"),key="social-join")["ref"]
        for actor in (ca.ALICE,ca.BOB):ca.expose_group(e,actor,group)
        offer=ca.work(e,ca.req(e,"social-offer","offer-system-v1",(source,),peer=ca.BOB,group=group,demand=1))
        offer=e.job_status(ca.ALICE,"social-offer")["public.0"]
        for actor in (ca.ALICE,ca.BOB):ca.expose(e,actor,offer)
        own=ca.seed_intent(e,"social-peer-stance",cap=2,consent=consent,actor=ca.BOB)
        ca.work(e,ca.req(e,"social-reply","reply-v1",(offer,own),actor=ca.BOB,peer=ca.ALICE,group=group))
        target=ca.SAW
        for obj in (c6.SAW,c6.KIT,c6.STOCK,c6.SUPPLY):c6.expose(e,ca.ALICE,e.world.head(obj.identity).ref)
        c6.need(e,"social-owned-need",weights=(0,0,10,0),collective=True)
    else:
        e=wf.setup_workflow(tim="eii",engine_type=WorkflowSelectionEngine)
        source=wf.model(e,"social-model")
        group=ca.join(e,ca.group(e,"social-group"),key="social-join")["ref"]
        for actor in (ca.ALICE,ca.BOB):ca.expose_group(e,actor,group)
        rows=wf.data(e,source)["tasks"]
        stance=wf.authored(e,"social-offer-stance",rows,kind="stance")
        wf.work(e,wf.request(e,"social-offer","offer-system",None,(source,stance),peer=ca.BOB,
            group=group,completed=(rows[0][0],),clock=1))
        offer=e.job_status(ca.ALICE,"social-offer")["public.0"]
        for actor in (ca.ALICE,ca.BOB):wf.expose(e,actor,offer)
        own=wf.authored(e,"social-peer-stance",rows,actor=ca.BOB,kind="stance",consent=consent)
        wf.work(e,wf.request(e,"social-reply","reply",None,(offer,own),actor=ca.BOB,peer=ca.ALICE,group=group))
        target=wf.DEVICE
        ca.seed(e,"social-owned-need",encode(dict(kind="workflow_need",priorities=(0,0,10,0),externalize=False)),
                target=target,relation="c7ws.need")
    reply=e.job_status(ca.BOB,"social-reply")["public.0"]
    if e.participant_view(ca.ALICE).resolve(reply):
        raise AssertionError("fixture must not supply receiver uptake")
    demand=Demand(setting,ca.ROOM,ca.CUE5,target,requirements=("experience","norms","situation","time"),
                  load=1,support_allowed=(ca.BOB,))
    return e,reply,demand


def finish(engine, controller, demand, mode="consented"):
    for _ in range(32):
        available=() if mode in ("withdrawn","partial-uptake") else controller.channel.participants
        row=controller.step(engine,state(),demand,available=available,work_limit=1000000)
        if controller.terminal is not None:break
    return row


class SocialCycleTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.bases={};cls.witnesses={};cls.restarts={}
        for setting in ("canonical","workflow"):
            for consent in (True,False):
                engine,reply,demand=peer_opportunity(setting,consent)
                cls.bases[setting,consent]=(type(engine),engine.checkpoint(),reply,demand)
            for mode in ("consented","nonconsent","no-packet","withdrawn","partial-uptake"):
                typ,checkpoint,reply,demand=cls.bases[setting,mode!="nonconsent"]
                engine=typ.restore(checkpoint);controller=SocialSupportCycle(engine,ca.ALICE,(ca.ALICE,ca.BOB))
                before=dict(engine.wallet(ca.ALICE))
                if mode!="no-packet":controller.queue_reply(ca.BOB,"social-reply",reply)
                if mode=="partial-uptake":
                    controller.step(engine,state(),demand,available=controller.channel.participants,work_limit=1)
                    for _ in range(31):controller.step(engine,state(),demand,available=(),work_limit=1000000)
                else:finish(engine,controller,demand,mode)
                cls.witnesses[setting+"/"+mode]=(engine,controller,demand,before,None)
                audit=audit_social_cycle(engine,controller.checkpoint(engine))
                cls.witnesses[setting+"/"+mode]=(engine,controller,demand,before,audit)
            typ,checkpoint,reply,demand=cls.bases[setting,True]
            engine=typ.restore(checkpoint);controller=SocialSupportCycle(engine,ca.ALICE,(ca.ALICE,ca.BOB))
            controller.queue_reply(ca.BOB,"social-reply",reply)
            controller.step(engine,state(),demand,available=controller.channel.participants,work_limit=1)
            other=typ.restore(engine.checkpoint());restored=SocialSupportCycle.restore(controller.checkpoint(engine),other)
            for _ in range(32):
                a=controller.step(engine,state(),demand,available=controller.channel.participants,work_limit=1000000)
                b=restored.step(other,state(),demand,available=restored.channel.participants,work_limit=1000000)
                if a!=b:raise AssertionError("partial social restart trace differs")
                if controller.terminal is not None:break
            cls.restarts[setting]=(engine,controller,other,restored)

    def test_exact_ten_scenario_domain_and_two_restart_records(self):
        protocol=json.loads((ROOT/"contracts/ft/FT7_1b1_Protocol_v1.json").read_text())
        self.assertEqual(set(self.witnesses),set(protocol["fixed_panel"]["scenario_ids"]))
        self.assertEqual(set(self.restarts),{"canonical","workflow"})

    def test_paid_peer_packet_enables_owned_support_choice_in_both_settings(self):
        for setting in ("canonical","workflow"):
            e,c,_,_,audit=self.witnesses[setting+"/consented"]
            self.assertEqual(c.phase,"complete")
            self.assertTrue(audit["supported"])
            self.assertEqual(c.cycle.candidates.route_policy.attempts[0]["selected"]["name"],"support")

    def test_owned_need_forms_request_without_supplied_recipe_or_success(self):
        parameters=inspect.signature(SocialSupportCycle.step).parameters
        self.assertFalse(set(parameters)&{"request","route","recipe","success","answer","certificate"})
        for setting in ("canonical","workflow"):
            c=self.witnesses[setting+"/consented"][1]
            self.assertTrue(c.cycle.request.key.startswith("ft-request:"))
            self.assertTrue(c.cycle.demand_controller.events[0]["request"]["request"])

    def test_exact_reply_is_actual_selected_native_operand(self):
        for setting in ("canonical","workflow"):
            e,c,_,_,_=self.witnesses[setting+"/consented"]
            link=c.terminal["causal_link"];job=e.job_status(c.actor,c.cycle.request.key+":movement")
            self.assertIn(link["source"],tuple(v for k,v in job.items() if k.startswith("input.")))
            self.assertEqual(link["source"],c.channel.bridge.receipts[c.packet_key]["source"])

    def test_paid_consumer_uses_selected_movement_output_and_same_scope(self):
        for setting in ("canonical","workflow"):
            e,c,d,_,_=self.witnesses[setting+"/consented"]
            consumer=e.job_status(c.actor,c.cycle.consumer_key)
            self.assertEqual(consumer["status"],"succeeded")
            self.assertGreaterEqual(consumer["spent"],consumer["required"])
            self.assertIn(c.terminal["causal_link"]["movement_output"],tuple(v for k,v in consumer.items() if k.startswith("input.")))
            self.assertEqual((consumer["context"],consumer.get("content_target",consumer.get("target"))),(d.context,d.target))

    def test_nonconsent_changes_choice_at_fixed_sender_main_cost(self):
        for setting in ("canonical","workflow"):
            a=self.witnesses[setting+"/consented"];b=self.witnesses[setting+"/nonconsent"]
            self.assertEqual(a[0].job_status(ca.BOB,"social-reply")["spent"],b[0].job_status(ca.BOB,"social-reply")["spent"])
            self.assertEqual(b[1].phase,"deferred")
            self.assertFalse(b[4]["supported"])
            self.assertEqual(b[1].cycle.candidates.route_policy.attempts[0]["selected"]["name"],"defer")

    def test_no_packet_has_no_owned_support_and_preserves_deferred_need(self):
        for setting in ("canonical","workflow"):
            e,c,_,_,audit=self.witnesses[setting+"/no-packet"]
            self.assertEqual(c.phase,"deferred")
            self.assertEqual(audit["paid_uptakes"],0)
            self.assertTrue(all(d["status"]=="pending" for d in c.cycle.demand_controller.effective_demands().values()))

    def test_withdrawal_keeps_packet_pending_and_never_launches_route(self):
        for setting in ("canonical","workflow"):
            e,c,_,before,_=self.witnesses[setting+"/withdrawn"]
            self.assertEqual(c.phase,"intake");self.assertEqual(c.turn,32)
            self.assertEqual(dict(e.wallet(c.actor)),before)
            self.assertEqual(c.cycle.events,[])
            self.assertEqual(c.channel.queue[c.packet_key]["status"],"queued")

    def test_partial_uptake_grants_no_content_or_completion_credit(self):
        for setting in ("canonical","workflow"):
            _,c,_,_,_=self.witnesses[setting+"/partial-uptake"]
            self.assertFalse(c.channel.bridge.kept);self.assertFalse(c.channel.bridge.receipts)
            self.assertEqual(c.cycle.events,[]);self.assertEqual(c.history.event_count,0)
            self.assertEqual(c.channel.queue[c.packet_key]["status"],"partial")

    def test_supported_settlement_debits_load_v1_once(self):
        for setting in ("canonical","workflow"):
            c=self.witnesses[setting+"/consented"][1]
            self.assertEqual(c.cycle.candidates.binding.ledger.balance,3)
            self.assertEqual(c.cycle.effects[0]["reserve_event"]["delta"],-1)
            self.assertEqual(c.cycle.effects[0]["completion_kind"],"supported")

    def test_success_v1_supported_history_grants_zero_independent_credit(self):
        for setting in ("canonical","workflow"):
            c=self.witnesses[setting+"/consented"][1]
            self.assertEqual(c.history.policy,"success-v1")
            self.assertGreater(sum(row["supported"] for row in c.history.tag_totals.values()),0)
            self.assertEqual(sum(c.history.scores.values()),0)
            self.assertTrue(all(row["tag"]=="supported" for row in c.history.events[0]["classifications"]))

    def test_duplicate_terminal_step_is_idempotent(self):
        for setting in ("canonical","workflow"):
            e,c,d,_,_=self.witnesses[setting+"/consented"]
            before=(e.checkpoint(),c.checkpoint(e))
            self.assertEqual(c.step(e,state(),d,available=c.channel.participants,work_limit=1),c.terminal)
            self.assertEqual((e.checkpoint(),c.checkpoint(e)),before)

    def test_partial_restart_is_exact_in_both_settings(self):
        for e,c,other,restored in self.restarts.values():
            self.assertEqual(e.checkpoint(),other.checkpoint())
            self.assertEqual(c.checkpoint(e),restored.checkpoint(other))
            self.assertEqual(c.phase,"complete")

    def test_forged_support_receipt_operand_or_history_is_rejected(self):
        for setting in ("canonical","workflow"):
            e,c,_,_,_=self.witnesses[setting+"/consented"]
            original=loads(c.checkpoint(e))
            for fault in ("receipt","operand","history"):
                d=deepcopy(original)
                if fault=="receipt":d["terminal"]["causal_link"]["uptake_receipt"]=d["terminal"]["causal_link"]["peer_operation"]
                elif fault=="operand":d["terminal"]["causal_link"]["source"]=ca.CUE5
                else:
                    h=loads(d["history"]);h["scores"]["ne"]=8;d["history"]=dumps(h)
                if fault!="history":d["events"][-1]=d["terminal"]
                with self.assertRaises(ValueError):audit_social_cycle(e,dumps(d))

    def test_no_certificate_or_permanent_history_is_minted(self):
        for _,c,_,_,audit in self.witnesses.values():
            self.assertNotIn("certificates",loads(c.checkpoint(c.channel.bridge.engine)))
            if c.terminal and c.terminal["causal_link"]:
                self.assertFalse(c.terminal["causal_link"]["independent_capability"])

    def test_all_281_predecessor_method_identities_remain_exact(self):
        from tools.evaluate_ft6_3b import predecessor_identities,ids
        earlier=predecessor_identities()
        for name,cls,protocol in (("tests_ft6.test_conditioning_release","ConditioningReleaseTests","FT6_3b"),
                                  ("tests_ft7.test_packet_channel","PacketChannelTests","FT7_1a")):
            p=json.loads((ROOT/"contracts/ft"/(protocol+"_Protocol_v1.json")).read_text())
            expected=sorted(name+"."+cls+"."+m for m in p["registered_tests"])
            actual=sorted(ids(unittest.defaultTestLoader.loadTestsFromName(name)))
            self.assertEqual(actual,expected);earlier+=expected
        self.assertEqual(len(earlier),281)
