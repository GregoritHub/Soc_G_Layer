from copy import deepcopy
from dataclasses import replace
import unittest
from hle_unified.selection_records import fields_of, dumps, loads
from full_theory.route_execution import NativeRouteController
from full_theory.route_execution_audit import audit_native_turns
from tests_ft4.test_controller import prepared
from tests_ft4.test_route_means import budgeted_request, RouteNamedRequest
from tests_ft4.test_demands import withdraw
from tests_c3 import fixtures as ca
from tests_c6 import fixtures as c6


def run(setting):
    engine,_,request,_=prepared(setting);controller=NativeRouteController()
    for _ in range(16):
        event=controller.step(engine,request,work_limit=1000000)
        if event['state'] in ('movement_complete','deferred','failed','cancelled','native_rejected'):break
    if event['state']!='movement_complete':raise AssertionError(event)
    report=audit_native_turns(engine.world.journal(),engine.access.checkpoint(),
                             controller.checkpoint(engine),engine.checkpoint())
    return engine,controller,request,report


class NativeTurnTests(unittest.TestCase):
    def test_native_launch_and_paid_completion_both_settings(self):
        for setting in ('canonical','workflow'):
            e,c,r,report=run(setting)
            self.assertTrue(report['passed']);self.assertGreater(report['debits']['time'],0)
            self.assertFalse(any(x['completion_claim'] for x in c.events))
            self.assertEqual(e.job_status(r.actor,r.key+':movement')['status'],'succeeded')

    def test_comparison_must_finish_before_child_exists(self):
        for setting in ('canonical','workflow'):
            e,_,r,_=prepared(setting);c=NativeRouteController();row=c.step(e,r,work_limit=1)
            self.assertEqual(row['debit'],dict(energy=1,time=1))
            self.assertNotIn((r.actor,r.key+':movement'),e._jobs)
            self.assertEqual(e.job_status(r.actor,r.key)['status'],'partial')
            self.assertTrue(audit_native_turns(e.world.journal(),e.access.checkpoint(),c.checkpoint(e),e.checkpoint())['passed'])

    def test_exact_partial_restart_both_settings(self):
        for setting in ('canonical','workflow'):
            for split in (1,2):
                e,_,r,_=prepared(setting);c=NativeRouteController()
                for _ in range(split):c.step(e,r,work_limit=1)
                other=type(e).restore(e.checkpoint());restored=NativeRouteController.restore(c.checkpoint(e),other)
                for _ in range(16):
                    a=c.step(e,r,work_limit=1000000);b=restored.step(other,r,work_limit=1000000)
                    self.assertEqual(a,b)
                    if a['state']=='movement_complete':break
                self.assertEqual(e.checkpoint(),other.checkpoint())
                self.assertEqual(c.checkpoint(e),restored.checkpoint(other))

    def test_unaffordable_work_stays_visible_without_minting(self):
        e,r=budgeted_request();c=NativeRouteController();a=c.step(e,r,work_limit=1000000)
        self.assertEqual(a['debit']['energy'],1);self.assertNotIn((r.actor,r.key+':movement'),e._jobs)
        before=e.checkpoint();b=c.step(e,r,work_limit=1000000)
        self.assertEqual(b['state'],'exhausted');self.assertEqual(b['debit'],dict(energy=0,time=0))
        self.assertEqual(before,e.checkpoint())
        self.assertTrue(audit_native_turns(e.world.journal(),e.access.checkpoint(),c.checkpoint(e),e.checkpoint())['passed'])

    def test_cancelled_child_preserves_spending(self):
        e,_,r,_=prepared('workflow');c=NativeRouteController();c.step(e,r,work_limit=1000000)
        c.step(e,r,work_limit=1);child=r.key+':movement';paid=e.wallet(r.actor)
        e.cancel('external-cancel',r.actor,child);before=e.checkpoint()
        row=c.step(e,r,work_limit=1000000)
        self.assertEqual(row['state'],'cancelled');self.assertEqual(paid,e.wallet(r.actor));self.assertEqual(before,e.checkpoint())
        self.assertTrue(audit_native_turns(e.world.journal(),e.access.checkpoint(),c.checkpoint(e),e.checkpoint())['passed'])

    def test_repeated_terminal_turn_cannot_duplicate_child(self):
        e,c,r,_=run('canonical');before=e.checkpoint();count=len(e._jobs)
        for _ in range(3):self.assertEqual(c.step(e,r)['state'],'movement_complete')
        self.assertEqual(before,e.checkpoint());self.assertEqual(count,len(e._jobs))

    def test_withdrawn_demand_is_not_launched(self):
        e,_,r,_=prepared('canonical');withdraw(e,r.demand);before=e.checkpoint()
        with self.assertRaises(ValueError):NativeRouteController().step(e,r)
        self.assertEqual(before,e.checkpoint())

    def test_foreign_and_route_named_requests_rejected(self):
        e,_,r,_=prepared('canonical');c=NativeRouteController();before=e.checkpoint()
        for invalid in (replace(r,actor=ca.BOB),RouteNamedRequest(**fields_of(r))):
            with self.assertRaises(ValueError):c.step(e,invalid)
        self.assertEqual(before,e.checkpoint());self.assertFalse(c.events)

    def test_busy_actor_does_not_advance_unrelated_work(self):
        e,_,r,_=prepared('canonical');e.start('unrelated:start',replace(r,key='unrelated'))
        before=e.checkpoint();c=NativeRouteController();row=c.step(e,r)
        self.assertEqual(row['state'],'busy_actor');self.assertEqual(before,e.checkpoint())
        self.assertFalse(c.attempts)

    def test_checkpoint_rejects_different_native_state(self):
        e,_,r,_=prepared('canonical');c=NativeRouteController();c.step(e,r)
        checkpoint=c.checkpoint(e);c.step(e,r)
        with self.assertRaises(ValueError):NativeRouteController.restore(checkpoint,e)
        with self.assertRaises(ValueError):c.step(e,replace(r,alternatives=1))

    def test_auditor_rejects_forged_payment_child_and_completion(self):
        e,c,r,_=run('workflow');original=loads(c.checkpoint(e))
        for field,value in (('debit',dict(energy=0,time=0)),('job','unrelated'),('completion_claim',True)):
            forged=deepcopy(original);forged['events'][0][field]=value
            with self.assertRaises(ValueError):audit_native_turns(e.world.journal(),e.access.checkpoint(),dumps(forged),e.checkpoint())

    def test_native_deferral_remains_distinct_from_success(self):
        e,_,r,_=prepared('canonical')
        # This condition demand has no owned condition operands or acquired repair.
        demand=c6.need(e,'unavailable-condition',(10,0,0,0),False,'condition',False)
        r=replace(r,key='unavailable',demand=demand);c=NativeRouteController()
        row=c.step(e,r,work_limit=1000000)
        self.assertEqual(row['state'],'deferred');self.assertFalse(row['completion_claim'])
        self.assertNotIn((r.actor,r.key+':movement'),e._jobs)
        self.assertTrue(audit_native_turns(e.world.journal(),e.access.checkpoint(),c.checkpoint(e),e.checkpoint())['passed'])
