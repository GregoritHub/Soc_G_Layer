from copy import deepcopy
import inspect
import unittest

from hle_unified.selection_records import dumps, loads

from full_theory.reserve import (CAPACITY, DEFAULT_INITIAL, POLICIES,
                                 ReserveLedger, independent_loss, preparation)
from full_theory.reserve_audit import audit_reserve


def receipt(actor, token, identity):
    return dict(identity=identity, actor=actor, token_id=token, source="external",
                seat=5, status="succeeded", paid=True)


def populated(policy="load-v1"):
    ledger = ReserveLedger("actor", policy, initial=4, tokens=("t1", "t2"))
    ledger.admit("d1", 2)
    ledger.interrupt("d1", "a1")
    grade = 2 if policy == "grade-load-v1" else None
    ledger.complete("d1", "independent", last_paid_grade=grade)
    ledger.replenish("t1", receipt("actor", "t1", "r1"))
    return ledger


class ReserveTests(unittest.TestCase):
    def test_three_exact_policy_names_and_default_contract_values(self):
        self.assertEqual(POLICIES, ("null", "load-v1", "grade-load-v1"))
        self.assertEqual((DEFAULT_INITIAL, CAPACITY), (4, 8))
        self.assertEqual(inspect.signature(ReserveLedger).parameters["initial"].default, 4)

    def test_reserve_domain_and_inputs_are_exact_integers(self):
        for value in (-1, 9, True, 1.0):
            with self.assertRaises(ValueError):
                ReserveLedger("actor", "load-v1", initial=value)
        ledger = ReserveLedger("actor", "load-v1")
        for value in (-1, True, 1.0):
            with self.assertRaises(ValueError):
                ledger.admit("bad-" + str(value), value)

    def test_admission_records_preparation_without_charging_native_wallet(self):
        ledger = ReserveLedger("actor", "load-v1", initial=1)
        event = ledger.admit("d", 4)
        self.assertEqual((event["preparation"], event["delta"], ledger.balance), (3, 0, 1))
        self.assertNotIn("energy", event); self.assertNotIn("time", event)

    def test_load_v1_independent_completion_uses_exact_loss(self):
        for initial, load, expected in ((4, 2, 2), (1, 4, 1), (4, 0, 1)):
            ledger = ReserveLedger("actor", "load-v1", initial=initial)
            ledger.admit("d", load)
            event = ledger.complete("d", "independent")
            self.assertEqual((-event["delta"], ledger.balance), (expected, initial - expected))

    def test_grade_load_v1_independent_completion_uses_last_paid_grade(self):
        self.assertEqual(independent_loss("grade-load-v1", 4, 4, 0), 4)
        self.assertEqual(independent_loss("grade-load-v1", 4, 4, 3), 2)
        ledger = ReserveLedger("actor", "grade-load-v1", initial=4)
        ledger.admit("d", 4)
        self.assertEqual(ledger.complete("d", "independent", last_paid_grade=3)["delta"], -2)
        with self.assertRaises(ValueError):
            independent_loss("grade-load-v1", 4, 1, True)

    def test_supported_completion_and_interrupt_are_bounded_once(self):
        ledger = ReserveLedger("actor", "load-v1", initial=2)
        ledger.admit("d1", 8); ledger.interrupt("d1", "attempt")
        with self.assertRaises(ValueError):
            ledger.interrupt("d1", "attempt")
        ledger.complete("d1", "supported")
        self.assertEqual(ledger.balance, 0)

    def test_zero_reserve_never_deletes_or_forbids_a_demand(self):
        ledger = ReserveLedger("actor", "load-v1", initial=0)
        event = ledger.admit("d", 4)
        self.assertEqual((event["preparation"], ledger.demands["d"]["status"]), (4, "pending"))
        self.assertFalse(any("route" in row or "forbidden" in row for row in ledger.events))
        ledger.complete("d", "independent")
        self.assertEqual(ledger.balance, 0)

    def test_null_comparator_has_no_preparation_loss_or_gain(self):
        ledger = ReserveLedger("actor", "null", initial=4, tokens=("t",))
        self.assertEqual(ledger.admit("d", 8)["preparation"], 0)
        ledger.interrupt("d", "a")
        ledger.complete("d", "independent")
        ledger.replenish("t", receipt("actor", "t", "r"))
        self.assertEqual(ledger.balance, 4)
        self.assertEqual(ledger.consumed_tokens, set())
        self.assertTrue(all(row["delta"] == 0 for row in ledger.events))

    def test_finite_external_token_identity_prevents_free_replenishment_loop(self):
        ledger = ReserveLedger("actor", "load-v1", initial=0, tokens=("t",))
        ledger.replenish("t", receipt("actor", "t", "r"))
        self.assertEqual(ledger.balance, 2)
        for value in (receipt("actor", "t", "r"), receipt("actor", "t", "r2")):
            with self.assertRaises(ValueError):
                ledger.replenish("t", value)
        with self.assertRaises(ValueError):
            ledger.replenish("foreign", receipt("actor", "foreign", "r3"))

    def test_bounds_apply_at_zero_and_eight_without_refund_or_minting(self):
        empty = ReserveLedger("actor", "load-v1", initial=0)
        empty.admit("d", 1); self.assertEqual(empty.complete("d", "supported")["delta"], 0)
        full = ReserveLedger("actor", "load-v1", initial=8, tokens=("t",))
        event = full.replenish("t", receipt("actor", "t", "r"))
        self.assertEqual((event["delta"], full.balance, full.consumed_tokens), (0, 8, {"t"}))

    def test_demand_and_attempt_identities_cannot_be_reused_or_rewritten(self):
        ledger = ReserveLedger("actor", "load-v1")
        ledger.admit("d", 1); ledger.interrupt("d", "a")
        for call in (lambda: ledger.admit("d", 2), lambda: ledger.interrupt("d", "a")):
            with self.assertRaises(ValueError): call()
        ledger.complete("d", "supported")
        with self.assertRaises(ValueError): ledger.complete("d", "supported")

    def test_checkpoint_continuation_is_exact(self):
        ledger = populated("grade-load-v1")
        restored = ReserveLedger.restore(ledger.checkpoint())
        self.assertEqual(restored.checkpoint(), ledger.checkpoint())
        restored.admit("d2", 4); ledger.admit("d2", 4)
        self.assertEqual(restored.checkpoint(), ledger.checkpoint())

    def test_independent_auditor_reconstructs_every_delta(self):
        for policy in POLICIES:
            ledger = populated(policy)
            report = audit_reserve(ledger.checkpoint())
            self.assertTrue(report["passed"]); self.assertEqual(report["balance"], ledger.balance)

    def test_independent_auditor_rejects_tampered_balance_token_and_formula(self):
        ledger = populated(); data = loads(ledger.checkpoint())
        mutations = []
        a = deepcopy(data); a["events"][1]["balance_after"] += 1; mutations.append(a)
        b = deepcopy(data); b["consumed_tokens"] = (); mutations.append(b)
        c = deepcopy(data); c["events"][0]["preparation"] += 1; mutations.append(c)
        for forged in mutations:
            with self.assertRaises(ValueError): audit_reserve(dumps(forged))

    def test_native_wallet_tim_dimension_and_ft4_state_remain_unchanged(self):
        from tests_ft4.test_autonomous_reuse import finish_reuse
        from full_theory.historical import type_map
        for setting in ("canonical", "workflow"):
            engine, _, _, controller, _, _ = finish_reuse(setting)
            actor = controller.actor
            before = (engine.checkpoint(), controller.checkpoint(engine),
                      deepcopy(engine.wallet(actor)),
                      deepcopy(type_map(controller.ledger.bridge.tim(actor))))
            ledger = ReserveLedger(actor, "load-v1", initial=0, tokens=("t",))
            ledger.admit("reserve-isolation", 4)
            ledger.replenish("t", receipt(actor, "t", "receipt-" + setting))
            after = (engine.checkpoint(), controller.checkpoint(engine),
                     deepcopy(engine.wallet(actor)),
                     deepcopy(type_map(controller.ledger.bridge.tim(actor))))
            self.assertEqual(before, after)

    def test_ft4_common_gate_method_identity_remains_exact(self):
        modules = ("test_demands", "test_requests", "test_controller", "test_route_means",
                   "test_route_execution", "test_orientation", "test_route_policy",
                   "test_opposition", "test_autonomous_cycle", "test_autonomous_closure",
                   "test_autonomous_capability", "test_autonomous_reuse")
        identities = []
        for module in modules:
            stack = list(unittest.defaultTestLoader.loadTestsFromName("tests_ft4." + module))
            while stack:
                item = stack.pop()
                if isinstance(item, unittest.TestSuite): stack.extend(list(item))
                else: identities.append(item.id())
        self.assertEqual((len(identities), len(set(identities))), (130, 130))
