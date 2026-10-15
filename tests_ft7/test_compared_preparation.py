import gc,os
from pathlib import Path
import unittest
from hle_unified.selection_records import loads,dumps
from full_theory.compared_preparation import ComparedSocialPreparation
from full_theory.compared_preparation_audit import audit_compared_preparation
from tests_ft7.test_social_live_outcome import read_record,engine_type
from tests_ft7.test_owned_paid_comparison import paid_type

def saved(setting,case):
    return read_record(Path(os.environ['FT7_COMPARED_PREPARATION_OUTPUT'])/'records'/(setting+'-'+case+'.json.gz'))

def objects(row):
    setting=row[0].split('/')[0]
    return (paid_type(setting).restore(row[8]),paid_type(setting).restore(row[5]),
            engine_type(setting).restore(row[1]))

def audit(row,text=None):
    e,c,o=objects(row)
    return audit_compared_preparation(e,c,o,row[2],row[3],row[4],row[6],row[7],row[9] if text is None else text)

class ComparedPreparationTests(unittest.TestCase):
    def test_exact_prefixes(self):
        for setting in ('canonical','workflow'):
            r=saved(setting,'complete');d=loads(r[9]);b=loads(r[3])
            self.assertEqual(d['history_prefix'],b['history']);self.assertEqual(d['reserve'],b['reserve'])
            self.assertTrue(audit(r)['comparison_prefix_exact']);del r,d,b;gc.collect()

    def test_partial_has_no_credit(self):
        for setting in ('canonical','workflow'):
            r=saved(setting,'partial');d=loads(r[9])
            self.assertEqual(d['receipts'],[]);self.assertEqual(d['history'],loads(r[3])['history'])
            self.assertEqual(d['events'][-1]['debit'],dict(energy=1,time=1))
            self.assertEqual(d['events'][-1]['remaining'],1);self.assertFalse(d['execution_authorized'])
            self.assertFalse(d['history_choice']);del r,d;gc.collect()

    def test_complete_exact_separate_costs(self):
        for setting,cost in (('canonical',63),('workflow',54)):
            r=saved(setting,'complete');a=audit(r);d=loads(r[9])
            self.assertEqual(a['native_cost'],dict(energy=2,time=2))
            self.assertEqual(a['comparison_cost'],dict(energy=cost,time=cost))
            self.assertEqual((a['bound'],a['remaining']),(1,0))
            old=loads(d['history_prefix']);now=loads(d['history'])
            self.assertEqual(now['scores'],old['scores']);self.assertEqual(now['native_counts'],old['native_counts'])
            self.assertEqual(now['events'][:len(old['events'])],old['events'])
            self.assertEqual(len(now['events']),len(old['events'])+1);del r,a,d;gc.collect()

    def test_restart_exact(self):
        for setting in ('canonical','workflow'):
            a=saved(setting,'complete');b=saved(setting,'restarted')
            self.assertEqual(a[1:],b[1:]);del a,b;gc.collect()

    def test_terminal_idempotent(self):
        r=saved('canonical','complete');e,c,o=objects(r)
        p=ComparedSocialPreparation.restore(r[9],e,c,o,r[2],r[3],r[4],r[6],r[7])
        p.step(e,work_limit=1);p.step(e,work_limit=99)
        self.assertEqual(e.checkpoint(),r[8]);self.assertEqual(p.checkpoint(e),r[9])

    def test_unsettled_comparison_rejected(self):
        for setting in ('canonical','workflow'):
            r=read_record(Path(os.environ['FT7_COMPARED_PREPARATION_INPUT'])/'records'/(setting+'-ready.json.gz'))
            e=paid_type(setting).restore(r[5]);o=engine_type(setting).restore(r[1])
            with self.assertRaises(ValueError):ComparedSocialPreparation(e,o,r[2],r[3],r[4],r[6],r[7])
            self.assertEqual(e.checkpoint(),r[5]);del r,e,o;gc.collect()

    def test_existing_work_rejected(self):
        r=saved('workflow','partial');e,c,o=objects(r)
        with self.assertRaises(ValueError):ComparedSocialPreparation(e,o,r[2],r[3],r[4],r[6],r[7])
        self.assertEqual(e.checkpoint(),r[8])

    def test_wrong_comparison_pair_rejected(self):
        r=saved('canonical','complete');e,c,o=objects(r)
        wrong=paid_type('canonical').from_native(r[1])
        with self.assertRaises(ValueError):
            audit_compared_preparation(e,wrong,o,r[2],r[3],r[4],r[6],r[7],r[9])

    def test_forged_receipt_rejected(self):
        r=saved('canonical','partial');d=loads(r[9])
        d['receipts']=loads(saved('canonical','complete')[9])['receipts']
        with self.assertRaises(ValueError):audit(r,dumps(d))

    def test_forged_history_rejected(self):
        r=saved('workflow','partial');d=loads(r[9])
        d['history']=loads(saved('workflow','complete')[9])['history']
        with self.assertRaises(ValueError):audit(r,dumps(d))
