from copy import deepcopy
import unittest

from hle import model_a
from hle_unified.material import attrs
from hle_unified.selection_records import dumps, loads
from tests_c3 import fixtures as ca
from tests_c7_workflow import fixtures as wf

from full_theory.content import ContentBridge
from full_theory.native_reserve import NativeReserveBinding
from full_theory.native_reserve_audit import audit_native_reserve
from full_theory.reserve import ReserveLedger


def preparation_case(setting="canonical", *, bind=2, policy="load-v1"):
    fixture = ca if setting == "canonical" else wf
    engine = ca.setup_c3() if setting == "canonical" else wf.setup_workflow()
    ledger = ReserveLedger(ca.ALICE, policy, initial=4)
    native = NativeReserveBinding(engine, ledger)
    native.admit(engine, "demand", 6)
    for index in range(2):
        fixture.cell(engine, "Express", "accumulation",
                     key="prep-" + str(index), consumer=False)
    result = None
    if bind:
        result = native.bind_preparation(engine, "demand",
                                         tuple("prep-" + str(i) for i in range(bind)))
    return engine, ledger, native, result


def uptake_case(setting="canonical", *, policy="load-v1", partial=False):
    fixture = ca if setting == "canonical" else wf
    engine = ca.setup_c3(tim="lie") if setting == "canonical" else wf.setup_workflow(tim="lie")
    fixture.cell(engine, "Share", "accumulation", key="source", consumer=False)
    bridge = ContentBridge(engine)
    output = engine.job_status(ca.ALICE, "source")["public.0"]
    bridge.emit("packet", ca.ALICE, "source", ca.ALICE, output)
    ledger = ReserveLedger(ca.ALICE, policy, initial=0, tokens=("token", "other"))
    native = NativeReserveBinding(engine, ledger)
    uptake = bridge.receive("packet", ca.ALICE, quantum=1 if partial else 1000000)
    return engine, bridge, ledger, native, uptake


class NativeReserveTests(unittest.TestCase):
    def test_paid_post_admission_preparation_binds_both_settings(self):
        for setting in ("canonical", "workflow"):
            engine, ledger, native, result = preparation_case(setting)
            self.assertEqual((result["required"], result["bound"], result["remaining"]), (2, 2, 0))
            self.assertTrue(result["complete"])
            self.assertEqual(result["demand_status"], "pending")
            self.assertTrue(audit_native_reserve(engine, native.checkpoint(engine))["passed"])

    def test_partial_preparation_stays_visible_and_demand_pending(self):
        engine, ledger, native, result = preparation_case(bind=1)
        self.assertEqual((result["bound"], result["remaining"], result["complete"]), (1, 1, False))
        self.assertEqual(ledger.demands["demand"]["status"], "pending")
        self.assertEqual(audit_native_reserve(engine, native.checkpoint(engine))["complete_preparations"], 0)

    def test_preexisting_foreign_failed_and_unpaid_work_are_rejected(self):
        engine = ca.setup_c3()
        ca.cell(engine, "Express", "accumulation", key="old", consumer=False)
        native = NativeReserveBinding(engine, ReserveLedger(ca.ALICE, "load-v1", initial=0))
        native.admit(engine, "demand", 2)
        with self.assertRaises(ValueError):
            native.bind_preparation(engine, "demand", ("old",))
        with self.assertRaises(ValueError):
            native.bind_preparation(engine, "demand", ("foreign",))
        prepared = ca.cell(engine, "Express", "accumulation", key="partial", prepare_only=True)
        ContentBridge(engine).execute(prepared["request"], quantum=1)
        with self.assertRaises(ValueError):
            native.bind_preparation(engine, "demand", ("partial",))

    def test_native_job_cannot_be_double_bound_or_double_charged(self):
        engine, ledger, native, _ = preparation_case(bind=0)
        before = (engine.checkpoint(), deepcopy(engine.wallet(ca.ALICE)))
        native.bind_preparation(engine, "demand", ("prep-0",))
        self.assertEqual(before, (engine.checkpoint(), deepcopy(engine.wallet(ca.ALICE))))
        with self.assertRaises(ValueError):
            native.bind_preparation(engine, "demand", ("prep-0",))

    def test_actual_paid_a5_uptake_replenishes_both_settings(self):
        for setting in ("canonical", "workflow"):
            engine, bridge, ledger, native, uptake = uptake_case(setting)
            before = engine.checkpoint()
            row = native.replenish_from_uptake(engine, bridge, "token", "packet")
            self.assertEqual(engine.checkpoint(), before)
            self.assertEqual((uptake["seat"], row["native"]["status"]["status"]), (5, "succeeded"))
            self.assertEqual((ledger.balance, row["reserve_event"]["delta"]), (2, 2))

    def test_partial_or_forged_uptake_cannot_replenish(self):
        engine, bridge, ledger, native, uptake = uptake_case(partial=True)
        self.assertIsNone(uptake)
        with self.assertRaises(ValueError):
            native.replenish_from_uptake(engine, bridge, "token", "packet")
        engine, bridge, ledger, native, uptake = uptake_case()
        bridge.receipts["packet"]["seat"] = 4
        with self.assertRaises(ValueError):
            native.replenish_from_uptake(engine, bridge, "token", "packet")

    def test_finite_token_packet_and_native_receipt_reuse_are_rejected(self):
        engine, bridge, ledger, native, uptake = uptake_case()
        native.replenish_from_uptake(engine, bridge, "token", "packet")
        with self.assertRaises(ValueError):
            native.replenish_from_uptake(engine, bridge, "other", "packet")
        with self.assertRaises(ValueError):
            native.replenish_from_uptake(engine, bridge, "token", "packet")

    def test_null_comparator_records_paid_binding_without_reserve_effect(self):
        engine, bridge, ledger, native, uptake = uptake_case(policy="null")
        row = native.replenish_from_uptake(engine, bridge, "token", "packet")
        self.assertEqual((row["reserve_event"]["delta"], ledger.balance), (0, 0))
        self.assertEqual(ledger.consumed_tokens, set())
        self.assertEqual(len(native.replenishment_bindings), 1)

    def test_checkpoint_continuation_is_exact(self):
        engine, bridge, ledger, native, uptake = uptake_case("workflow")
        native.replenish_from_uptake(engine, bridge, "token", "packet")
        restored = NativeReserveBinding.restore(native.checkpoint(engine), engine)
        self.assertEqual(restored.checkpoint(engine), native.checkpoint(engine))

    def test_independent_auditor_reconstructs_native_bindings(self):
        for policy in ("null", "load-v1", "grade-load-v1"):
            engine, bridge, ledger, native, uptake = uptake_case(policy=policy)
            native.replenish_from_uptake(engine, bridge, "token", "packet")
            report = audit_native_reserve(engine, native.checkpoint(engine))
            self.assertTrue(report["passed"])
            self.assertEqual(report["policy"], policy)

    def test_independent_auditor_rejects_forged_payment_order_and_role(self):
        engine, ledger, native, result = preparation_case()
        original = loads(native.checkpoint(engine))
        forged = deepcopy(original)
        forged["preparation_bindings"]["demand"][0]["status"]["spent"] = 0
        with self.assertRaises(ValueError):
            audit_native_reserve(engine, dumps(forged))
        forged = deepcopy(original)
        forged["admissions"]["demand"]["journal_count"] = 10 ** 9
        with self.assertRaises(ValueError):
            audit_native_reserve(engine, dumps(forged))
        engine, bridge, ledger, native, uptake = uptake_case()
        native.replenish_from_uptake(engine, bridge, "token", "packet")
        forged = loads(native.checkpoint(engine))
        forged["replenishment_bindings"][0]["uptake"]["seat"] = 4
        with self.assertRaises(ValueError):
            audit_native_reserve(engine, dumps(forged))

    def test_grade_prices_wallet_tim_dimension_and_ft4_state_are_unchanged(self):
        for setting in ("canonical", "workflow"):
            engine, ledger, native, _ = preparation_case(setting, bind=0, policy="grade-load-v1")
            statuses = [deepcopy(engine.job_status(ca.ALICE, "prep-" + str(i))) for i in range(2)]
            before = (engine.checkpoint(), deepcopy(engine.wallet(ca.ALICE)),
                      attrs(engine.world.resolve(engine._profiles[ca.ALICE]))["tim"])
            native.bind_preparation(engine, "demand", ("prep-0", "prep-1"))
            after = (engine.checkpoint(), deepcopy(engine.wallet(ca.ALICE)),
                     attrs(engine.world.resolve(engine._profiles[ca.ALICE]))["tim"])
            self.assertEqual(before, after)
            self.assertEqual(statuses, [engine.job_status(ca.ALICE, "prep-" + str(i)) for i in range(2)])
            self.assertTrue(all(row["spent"] >= row["required"] > 0 for row in statuses))
            self.assertEqual(model_a.fields(5)["dimensionality"], 1)

    def test_ft5_1_and_ft4_predecessor_method_identity_remains_exact(self):
        modules = ("tests_ft5.test_reserve", "tests_ft4.test_demands", "tests_ft4.test_requests",
            "tests_ft4.test_controller", "tests_ft4.test_route_means", "tests_ft4.test_route_execution",
            "tests_ft4.test_orientation", "tests_ft4.test_route_policy", "tests_ft4.test_opposition",
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
        self.assertEqual((len(identities), len(set(identities))), (146, 146))
