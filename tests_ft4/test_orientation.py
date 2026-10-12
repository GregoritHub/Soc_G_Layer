from copy import deepcopy
from dataclasses import replace
import unittest
from hle_unified.selection_records import dumps, loads
from full_theory.orientation import PaidOrientation
from full_theory.orientation_audit import audit_orientation
from tests_ft4.test_controller import prepared
from tests_ft4.test_route_means import budgeted_request
from tests_ft4.test_demands import withdraw
from tests_c3 import fixtures as ca


def run(setting):
    e,_,r,_=prepared(setting);c=PaidOrientation();row=c.step(e,r,work_limit=2)
    if row['ticket'] is None:raise AssertionError(row)
    report=audit_orientation(e.world.journal(),e.access.checkpoint(),c.checkpoint(e),e.checkpoint())
    return e,c,r,report


class OrientationTests(unittest.TestCase):
    def test_exact_paid_read_both_settings(self):
        for setting in ('canonical','workflow'):
            e,c,r,report=run(setting)
            self.assertTrue(report['passed']);self.assertEqual(report['paid_time'],2);self.assertEqual(report['paid_energy'],2)
            self.assertEqual(c.events[-1]['ticket']['demand'],r.demand)
            self.assertEqual(e.job_status(r.actor,r.key+':cp-orientation')['input.0'],r.demand)

    def test_partial_read_never_grants_orientation(self):
        for setting in ('canonical','workflow'):
            e,_,r,_=prepared(setting);c=PaidOrientation();row=c.step(e,r,work_limit=1)
            self.assertIsNone(row['ticket']);self.assertEqual(row['debit'],dict(energy=1,time=1))
            report=audit_orientation(e.world.journal(),e.access.checkpoint(),c.checkpoint(e),e.checkpoint())
            self.assertEqual(report['ticket_observations'],0)

    def test_repeated_poll_never_charges_twice(self):
        e,c,r,_=run('canonical');before=e.checkpoint()
        for _ in range(3):
            row=c.step(e,r,work_limit=2);self.assertEqual(row['debit'],dict(energy=0,time=0));self.assertIsNotNone(row['ticket'])
        self.assertEqual(before,e.checkpoint())
        report=audit_orientation(e.world.journal(),e.access.checkpoint(),c.checkpoint(e),e.checkpoint())
        self.assertEqual(report['paid_energy'],2)

    def test_partial_checkpoint_continues_exactly(self):
        for setting in ('canonical','workflow'):
            e,_,r,_=prepared(setting);c=PaidOrientation();c.step(e,r)
            other=type(e).restore(e.checkpoint());restored=PaidOrientation.restore(c.checkpoint(e),other)
            self.assertEqual(c.step(e,r),restored.step(other,r))
            self.assertEqual(e.checkpoint(),other.checkpoint());self.assertEqual(c.checkpoint(e),restored.checkpoint(other))

    def test_unaffordable_orientation_rejected_before_mutation(self):
        e,r=budgeted_request();before=e.checkpoint();c=PaidOrientation()
        with self.assertRaises(ValueError):c.step(e,r)
        self.assertEqual(before,e.checkpoint());self.assertFalse(c.events);self.assertFalse(c.attempts)

    def test_foreign_stale_and_busy_requests_rejected(self):
        e,_,r,_=prepared('canonical');c=PaidOrientation()
        with self.assertRaises(ValueError):c.step(e,replace(r,actor=ca.BOB))
        e.start('busy:start',replace(r,key='other'));before=e.checkpoint()
        with self.assertRaises(ValueError):c.step(e,r)
        self.assertEqual(before,e.checkpoint());e.cancel('busy:cancel',r.actor,'other')
        withdraw(e,r.demand);before=e.checkpoint()
        with self.assertRaises(ValueError):c.step(e,r)
        self.assertEqual(before,e.checkpoint())

    def test_cancelled_read_never_grants_orientation(self):
        e,_,r,_=prepared('workflow');c=PaidOrientation();c.step(e,r)
        e.cancel('read:cancel',r.actor,r.key+':cp-orientation');before=e.checkpoint()
        row=c.step(e,r);self.assertIsNone(row['ticket']);self.assertEqual(row['status'],'cancelled');self.assertEqual(before,e.checkpoint())
        report=audit_orientation(e.world.journal(),e.access.checkpoint(),c.checkpoint(e),e.checkpoint())
        self.assertEqual(report['paid_energy'],1)

    def test_withdrawn_need_invalidates_completed_ticket(self):
        e,c,r,_=run('canonical');withdraw(e,r.demand)
        self.assertIsNone(c.ticket(e,r));row=c.step(e,r)
        self.assertIsNone(row['ticket']);self.assertEqual(row['debit'],dict(energy=0,time=0))
        self.assertTrue(audit_orientation(e.world.journal(),e.access.checkpoint(),c.checkpoint(e),e.checkpoint())['passed'])

    def test_ticket_does_not_move_cursor_or_grant_capacity(self):
        for setting in ('canonical','workflow'):
            e,_,r,_=prepared(setting);cursor=e._cursors.copy();profiles=e._profiles.copy();capacities=e.development_view(r.actor)['capacities']
            c=PaidOrientation();row=c.step(e,r,work_limit=2)
            self.assertFalse(row['ticket']['traversal_claim']);self.assertFalse(row['ticket']['completion_claim'])
            self.assertEqual(cursor,e._cursors);self.assertEqual(profiles,e._profiles)
            self.assertEqual(capacities,e.development_view(r.actor)['capacities'])
            # Once native work actually leaves the priced origin, the old fee
            # cannot authorize a differently oriented traversal.
            from full_theory.route_execution import NativeRouteController
            turn=NativeRouteController()
            for _ in range(4):
                event=turn.step(e,r,work_limit=1000000)
                if event['state']=='movement_complete':break
            if e._cursors[r.actor]!=cursor[r.actor]:
                self.assertIsNone(c.ticket(e,r));self.assertIsNone(c.step(e,r)['ticket'])
                self.assertTrue(audit_orientation(e.world.journal(),e.access.checkpoint(),c.checkpoint(e),e.checkpoint())['passed'])

    def test_auditor_rejects_forged_cost_source_receipt_and_geometry(self):
        e,c,r,_=run('workflow');original=loads(c.checkpoint(e))
        for target,field,value in [('ticket','energy',0),('ticket','operation',r.demand),('attempt','payload','fake'),('attempt','target_seat',original['attempts'][0]['origin_seat'])]:
            forged=deepcopy(original)
            (forged['events'][0]['ticket'] if target=='ticket' else forged['attempts'][0])[field]=value
            with self.assertRaises(ValueError):audit_orientation(e.world.journal(),e.access.checkpoint(),dumps(forged),e.checkpoint())
