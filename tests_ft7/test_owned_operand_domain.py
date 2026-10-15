import gc,os
from pathlib import Path
import unittest
from hle_unified.selection_records import dumps,loads
from full_theory.owned_operand_domain import owned_operand_domain
from full_theory.owned_operand_domain_audit import audit_owned_operand_domain
from tests_ft7.test_social_live_outcome import read_record,engine_type
from tests_ft7.test_owned_paid_comparison import paid_type


def saved(setting,case):
    return read_record(Path(os.environ['FT7_OPERAND_OUTPUT'])/'records'/(setting+'-'+case+'.json.gz'))


def audit(row,text=None):
    old=engine_type(row[0].split('/')[0]).restore(row[1])
    e=paid_type(row[0].split('/')[0]).restore(row[5])
    return audit_owned_operand_domain(e,old,row[2],row[3],row[4],row[6] if text is None else text)


class OwnedOperandDomainTests(unittest.TestCase):
    def test_exact_cell_and_examined_domain(self):
        for setting,n in (('canonical',33),('workflow',32)):
            row=saved(setting,'complete');out=loads(row[6]);original=loads(row[4])
            self.assertEqual([x['cell'] for x in out['cells']],list(range(n)))
            self.assertEqual(sum(len(x['options']) for x in out['cells']),sum(x['examined'] for x in original['candidates']))
            self.assertTrue(audit(row)['passed']);del row,out,original;gc.collect()

    def test_original_nominees_unchanged(self):
        for setting in ('canonical','workflow'):
            row=saved(setting,'complete');d=loads(row[4]);out=loads(row[6]);winner=d['native_nominee']
            proposals=[o['proposal'] for c in out['cells'] for o in c['options']]
            self.assertIn({k:v for k,v in winner.items() if k not in ('examined','deferred')},proposals)
            self.assertFalse(out['history_choice']);self.assertFalse(out['td5_admitted']);del row,d,out;gc.collect()

    def test_no_early_expansion(self):
        for setting in ('canonical','workflow'):
            for case in ('before','partial','ready','cancelled'):
                row=saved(setting,case);d=loads(row[6]);self.assertEqual(d['cells'],[])
                self.assertFalse(d['comparison_settled']);self.assertFalse(d['complete_within_paid_bound'])
                del row,d;gc.collect()

    def test_paid_pair_required(self):
        row=saved('canonical','complete');other=saved('canonical','partial')
        old=engine_type('canonical').restore(row[1]);e=paid_type('canonical').restore(other[5])
        with self.assertRaises(ValueError):audit_owned_operand_domain(e,old,row[2],row[3],row[4],row[6])

    def test_exact_saved_roundtrip(self):
        for setting in ('canonical','workflow'):
            a=saved(setting,'complete');b=saved(setting,'restarted')
            self.assertEqual(a[1:],b[1:]);self.assertEqual(loads(dumps(loads(a[6]))),loads(a[6]))
            del a,b;gc.collect()

    def test_native_and_ledgers_unchanged(self):
        for setting in ('canonical','workflow'):
            row=saved(setting,'complete');old=engine_type(setting).restore(row[1]);e=paid_type(setting).restore(row[5])
            self.assertEqual(owned_operand_domain(e,old,row[2],row[3],row[4]),row[6])
            self.assertEqual(e.checkpoint(),row[5]);self.assertEqual(old.checkpoint(),row[1])
            del row,old,e;gc.collect()

    def test_omitted_bundle_rejected(self):
        row=saved('canonical','complete');d=loads(row[6]);c=next(c for c in d['cells'] if c['options'])
        c['options'].pop()
        with self.assertRaises(ValueError):audit(row,dumps(d))

    def test_forged_effort_rejected(self):
        row=saved('workflow','complete');d=loads(row[6]);c=next(c for c in d['cells'] if c['options'])
        c['options'][0]['proposal']['effort']+=1
        with self.assertRaises(ValueError):audit(row,dumps(d))

    def test_reordered_cells_rejected(self):
        row=saved('workflow','complete');d=loads(row[6]);d['cells'].reverse()
        with self.assertRaises(ValueError):audit(row,dumps(d))

    def test_false_execution_authority_rejected(self):
        row=saved('canonical','complete');d=loads(row[6]);d['execution_authorized']=True
        with self.assertRaises(ValueError):audit(row,dumps(d))
