import gc,json,os
from pathlib import Path
import unittest
from hle_unified.selection_records import loads
from full_theory.owned_paid_comparison import (PaidCanonicalComparisonEngine,
    PaidWorkflowComparisonEngine, PaidComparisonRequest, step_owned_comparison)
from full_theory.owned_paid_comparison_audit import audit_owned_paid_comparison
from tests_ft7.test_social_live_outcome import read_record,engine_type

def paid_type(setting):
    return PaidCanonicalComparisonEngine if setting=='canonical' else PaidWorkflowComparisonEngine

def saved(setting,case):
    return read_record(Path(os.environ['FT7_PAID_COMPARISON_OUTPUT'])/'records'/(setting+'-'+case+'.json.gz'))

def restored(setting,case):
    row=saved(setting,case)
    return row,paid_type(setting).restore(row[5])

def request_for(engine):
    (actor,key),(r,*_)=next(iter(engine._ft_comparisons.items()))
    return PaidComparisonRequest(key,r)

class OwnedPaidComparisonTests(unittest.TestCase):
    def test_exact_paid_extents(self):
        for setting,cost in (('canonical',63),('workflow',54)):
            row,e=restored(setting,'complete');r=request_for(e);d=e.job_status(r.request.actor,r.key)
            self.assertEqual((d['required'],d['completed'],d['spent']),(cost,cost,cost))
            self.assertEqual(e.comparison_result(r.request.actor,r.key)['comparison_required'],cost)
            del row,e;gc.collect()

    def test_no_early_result(self):
        for setting in ('canonical','workflow'):
            for case,status in (('partial','partial'),('ready','ready')):
                row,e=restored(setting,case);r=request_for(e)
                self.assertEqual(e.job_status(r.request.actor,r.key)['status'],status)
                self.assertIsNone(e.comparison_result(r.request.actor,r.key))
                del row,e;gc.collect()

    def test_complete_result_no_movement(self):
        for setting in ('canonical','workflow'):
            row,e=restored(setting,'complete');r=request_for(e);result=e.comparison_result(r.request.actor,r.key)
            self.assertFalse(result['execution_authorized']);self.assertTrue(result['comparison_paid'])
            self.assertEqual(result['candidates'],loads(row[4])['candidates'])
            old=engine_type(setting).restore(row[1]);suffix=tuple(e.world.journal())[len(tuple(old.world.journal())):]
            self.assertFalse(any(v.ref.identity.namespace in ('c5.movement','c6.decision','c7ws.decision') for t in suffix for v in t.versions))
            self.assertEqual(e._cursors,old._cursors)
            del row,e,old;gc.collect()

    def test_exact_partial_restart(self):
        for setting in ('canonical','workflow'):
            self.assertEqual(saved(setting,'complete')[5],saved(setting,'restarted')[5])

    def test_terminal_idempotence(self):
        for setting in ('canonical','workflow'):
            for case in ('complete','cancelled'):
                row,e=restored(setting,case);r=request_for(e);before=e.checkpoint()
                step_owned_comparison(e,r);step_owned_comparison(e,r)
                self.assertEqual(e.checkpoint(),before);del row,e,before;gc.collect()

    def test_cancel_no_refund_or_result(self):
        for setting in ('canonical','workflow'):
            row,e=restored(setting,'cancelled');r=request_for(e)
            self.assertEqual(e.job_status(r.request.actor,r.key)['spent'],1)
            self.assertIsNone(e.comparison_result(r.request.actor,r.key))
            old=engine_type(setting).restore(row[1])
            self.assertEqual({u:old.wallet(r.request.actor)[u]-e.wallet(r.request.actor)[u] for u in ('energy','time')},dict(energy=1,time=1))
            del row,e,old;gc.collect()

    def test_source_and_ledgers_unchanged(self):
        for setting in ('canonical','workflow'):
            before=saved(setting,'before')
            for case in ('partial','ready','complete','restarted','cancelled'):
                row=saved(setting,case);self.assertEqual(row[1:5],before[1:5])
            del before,row;gc.collect()

    def test_independent_saved_audit(self):
        for setting in ('canonical','workflow'):
            row,e=restored(setting,'complete');old=engine_type(setting).restore(row[1])
            self.assertTrue(audit_owned_paid_comparison(e,old,row[2],row[3],row[4])['passed'])
            del row,e,old;gc.collect()

    def test_forged_extent_rejected(self):
        from dataclasses import replace
        from types import SimpleNamespace
        from hle_unified.material import attrs,attributes
        row,e=restored('canonical','complete');old=engine_type('canonical').restore(row[1]);txs=list(e.world.journal())
        first=len(tuple(old.world.journal()));tx=txs[first];versions=[]
        for v in tx.versions:
            d=attrs(v)
            if d.get('ftpc'):d['required']-=1;v=replace(v,attributes=attributes(d))
            versions.append(v)
        txs[first]=replace(tx,versions=tuple(versions))
        forged=SimpleNamespace(world=SimpleNamespace(journal=lambda:tuple(txs)),access=e.access)
        with self.assertRaises(ValueError):audit_owned_paid_comparison(forged,old,row[2],row[3],row[4])

    def test_foreign_result_rejected(self):
        for setting in ('canonical','workflow'):
            row,e=restored(setting,'complete');r=request_for(e)
            foreign=next(a for a in e._profiles if a!=r.request.actor)
            with self.assertRaises(ValueError):e.comparison_result(foreign,r.key)
            del row,e;gc.collect()
