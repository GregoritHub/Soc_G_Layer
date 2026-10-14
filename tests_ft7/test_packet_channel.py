from copy import deepcopy
from pathlib import Path
import json
import unittest

from hle_unified.selection_records import dumps, loads
from hle import model_a
from hle.relations import landing_position
from tests_c3 import fixtures as ca
from tests_c7_workflow import fixtures as wf
from full_theory.packet_channel import PacketChannel
from full_theory.packet_channel_audit import audit_packet_channel

ROOT = Path(__file__).resolve().parents[1]


class PacketChannelTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.bases={};cls.witnesses={};cls.restarts={}
        for setting in ("canonical","workflow"):
            if setting=="canonical":
                e=ca.setup_c3();ca.cell_c2(e,"Commune","expenditure",prefix="public",consumer=False)
            else:
                e=wf.setup_workflow();wf.cell(e,"Share","expenditure",key="public",consumer=False)
            public=e.job_status(ca.ALICE,"public")["public.0"]
            cls.bases[setting]=(type(e),e.checkpoint(),public)
            for mode in ("self","peer","withdrawn","missing-uptake"):
                engine,channel=cls.channel(setting,ca.ALICE if mode=="self" else ca.BOB)
                before=dict(engine.wallet(ca.ALICE if mode=="self" else ca.BOB))
                channel.emit("packet",ca.ALICE,"public",ca.ALICE if mode=="self" else ca.BOB,public)
                if mode=="missing-uptake":
                    for _ in range(8):channel.step(available=(),work_limit=1000000)
                elif mode=="withdrawn":
                    for _ in range(8):channel.step(available=(ca.ALICE,),work_limit=1000000)
                else:
                    channel.step(available=channel.participants,work_limit=1000000)
                audit=audit_packet_channel(tuple(engine.world.journal()),channel.checkpoint(),engine.checkpoint())
                cls.witnesses[setting+"/"+mode]=(engine,channel,before,audit)
            engine,channel=cls.channel(setting)
            channel.emit("partial",ca.ALICE,"public",ca.BOB,public)
            channel.step(available=channel.participants,work_limit=1)
            other=type(engine).restore(engine.checkpoint())
            restored=PacketChannel.restore(channel.checkpoint(),other)
            for _ in range(8):
                a=channel.step(available=channel.participants,work_limit=1000000)
                b=restored.step(available=restored.participants,work_limit=1000000)
                if a!=b:raise AssertionError("partial channel restart trace differs")
                if channel.queue["partial"]["status"]=="delivered":break
            cls.restarts[setting]=(engine,channel,other,restored)

    @classmethod
    def channel(cls,setting,receiver=ca.BOB):
        engine_type,checkpoint,_=cls.bases[setting]
        e=engine_type.restore(checkpoint)
        return e,PacketChannel(e,(ca.ALICE,) if receiver==ca.ALICE else (ca.ALICE,receiver))

    def test_same_bridge_rules_deliver_self_and_peer_in_both_settings(self):
        for setting in ("canonical","workflow"):
            for mode in ("self","peer"):
                _,channel,_,audit=self.witnesses[setting+"/"+mode]
                self.assertEqual(channel.queue["packet"]["status"],"delivered")
                self.assertEqual(audit["paid_uptakes"],1)

    def test_receiver_seat_and_relation_landing_reconstruct_without_capability(self):
        for e,channel,_,audit in self.witnesses.values():
            event=channel.events[0]
            self.assertEqual(event["receiver_seat"],event["relation_landing"])
            self.assertTrue(audit["independent"])
            self.assertNotIn("capability",loads(channel.checkpoint()))

    def test_peer_uptake_consumes_actual_native_paid_read(self):
        for setting in ("canonical","workflow"):
            e,channel,before,_=self.witnesses[setting+"/peer"]
            self.assertLess(e.wallet(ca.BOB)["energy"],before["energy"])
            self.assertLess(e.wallet(ca.BOB)["time"],before["time"])
            self.assertEqual(channel.bridge.receipts["packet"]["source"],self.bases[setting][2])

    def test_emission_grants_no_receiver_access_or_receipt(self):
        for setting in ("canonical","workflow"):
            e,channel=self.channel(setting);public=self.bases[setting][2]
            channel.emit("only-emitted",ca.ALICE,"public",ca.BOB,public)
            self.assertFalse(channel.bridge.receipts)
            self.assertFalse(e.participant_view(ca.BOB).resolve(public))
            self.assertEqual(channel.turn,0)

    def test_partial_read_grants_no_kept_content(self):
        for setting in ("canonical","workflow"):
            e,channel=self.channel(setting)
            channel.emit("partial",ca.ALICE,"public",ca.BOB,self.bases[setting][2])
            channel.step(available=channel.participants,work_limit=1)
            self.assertEqual(channel.queue["partial"]["status"],"partial")
            self.assertFalse(channel.bridge.kept)
            self.assertFalse(channel.bridge.receipts)
            self.assertTrue(audit_packet_channel(tuple(e.world.journal()),channel.checkpoint(),e.checkpoint())["passed"])

    def test_withdrawn_receiver_preserves_pending_packet_without_debit(self):
        for setting in ("canonical","workflow"):
            e,channel,before,audit=self.witnesses[setting+"/withdrawn"]
            self.assertEqual(dict(e.wallet(ca.BOB)),before)
            self.assertEqual(audit["pending"],1)
            self.assertEqual(channel.queue["packet"]["status"],"queued")

    def test_missing_uptake_never_counts_as_completed_knowledge(self):
        for setting in ("canonical","workflow"):
            e,channel,before,audit=self.witnesses[setting+"/missing-uptake"]
            self.assertEqual(audit["paid_uptakes"],0)
            self.assertEqual(channel.turn,8)
            self.assertEqual(dict(e.wallet(ca.BOB)),before)
            self.assertFalse(channel.bridge.charge)

    def test_duplicate_delivery_is_idempotent_and_duplicate_emit_rejected(self):
        e,original,_,_=self.witnesses["canonical/peer"]
        other=type(e).restore(e.checkpoint());channel=PacketChannel.restore(original.checkpoint(),other)
        before=other.checkpoint()
        row=channel.step(available=channel.participants,work_limit=1000000)
        self.assertEqual(row["ready"],())
        self.assertEqual(other.checkpoint(),before)
        with self.assertRaises(ValueError):channel.emit("packet",ca.ALICE,"public",ca.BOB,self.bases["canonical"][2])

    def test_wrong_receiver_and_private_cross_owner_content_are_rejected(self):
        e,channel=self.channel("canonical")
        with self.assertRaises(ValueError):channel.emit("wrong",ca.ALICE,"public",ca.EVE,self.bases["canonical"][2])
        private=ca.cell(e,"Understand","accumulation",key="private",consumer=False)["result"]
        with self.assertRaises(ValueError):channel.emit("private",ca.ALICE,"private",ca.BOB,private)
        channel.emit("private-self",ca.ALICE,"private",ca.ALICE,private)
        d=loads(channel.checkpoint())
        d["queue"][0]["receiver"]=ca.BOB
        d["events"][0]["queue"]["receiver"]=ca.BOB
        for packet in (d["events"][0]["packet"],d["bridge"]["packets"]["private-self"],d["bridge"]["events"][0]["packet"]):
            packet["receiver"]=ca.BOB
        d["events"][0]["receiver_seat"]=model_a.position_of(channel.bridge.tim(ca.BOB),d["events"][0]["packet"]["aspect"])
        d["events"][0]["relation_landing"]=landing_position(channel.bridge.tim(ca.ALICE),d["events"][0]["sender_seat"],channel.bridge.tim(ca.BOB))
        with self.assertRaisesRegex(ValueError,"private own realization"):
            audit_packet_channel(tuple(e.world.journal()),dumps(d),e.checkpoint())

    def test_next_turn_delivery_and_stable_queue_order(self):
        e,channel=self.channel("canonical");public=self.bases["canonical"][2]
        channel.emit("z-first",ca.ALICE,"public",ca.BOB,public)
        channel.emit("a-second",ca.ALICE,"public",ca.BOB,public)
        other=type(e).restore(e.checkpoint());restored=PacketChannel.restore(channel.checkpoint(),other)
        restored.queue=dict(reversed(tuple(restored.queue.items())))
        a=channel.step(available=channel.participants,work_limit=1000000)
        b=restored.step(available=restored.participants,work_limit=1000000)
        self.assertEqual(a,b)
        self.assertEqual(a["turn"],1)
        self.assertEqual(a["ready"],("z-first","a-second"))
        self.assertEqual(channel.checkpoint(),restored.checkpoint())
        self.assertTrue(audit_packet_channel(tuple(e.world.journal()),channel.checkpoint(),e.checkpoint())["passed"])
        self.__class__.permutation=(e,channel)

    def test_partial_restart_matches_exact_uninterrupted_native_state(self):
        for engine,channel,other,restored in self.restarts.values():
            self.assertEqual(engine.checkpoint(),other.checkpoint())
            self.assertEqual(channel.checkpoint(),restored.checkpoint())
            self.assertEqual(channel.queue["partial"]["status"],"delivered")

    def test_foreign_native_checkpoint_is_rejected(self):
        e,channel=self.channel("canonical")
        channel.emit("packet",ca.ALICE,"public",ca.BOB,self.bases["canonical"][2])
        saved=channel.checkpoint()
        channel.step(available=channel.participants,work_limit=1)
        with self.assertRaises(ValueError):PacketChannel.restore(saved,e)

    def test_independent_auditor_rejects_forged_packet_receipt_and_clock(self):
        e,channel,_,_=self.witnesses["workflow/peer"]
        original=loads(channel.checkpoint())
        for fault in ("packet","receipt","clock"):
            d=deepcopy(original)
            if fault=="packet":d["bridge"]["packets"]["packet"]["aspect"]="ti"
            elif fault=="receipt":d["bridge"]["receipts"]["packet"]["receipt"]=self.bases["workflow"][2]
            else:d["events"][-1]["turn"]+=1
            with self.assertRaises(ValueError):audit_packet_channel(tuple(e.world.journal()),dumps(d),e.checkpoint())

    def test_all_267_predecessor_method_identities_remain_exact(self):
        from tools.evaluate_ft6_3b import predecessor_identities
        earlier=predecessor_identities()
        protocol=json.loads((ROOT/"contracts/ft/FT6_3b_Protocol_v1.json").read_text())
        expected=sorted("tests_ft6.test_conditioning_release.ConditioningReleaseTests."+m for m in protocol["registered_tests"])
        suite=unittest.defaultTestLoader.loadTestsFromName("tests_ft6.test_conditioning_release")
        from tools.evaluate_ft6_3b import ids
        self.assertEqual(sorted(ids(suite)),expected)
        self.assertEqual(len(earlier+expected),267)
