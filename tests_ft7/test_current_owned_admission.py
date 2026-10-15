import gc,os
from pathlib import Path
import unittest
from hle_unified.selection_records import loads,dumps
from full_theory.current_owned_admission import current_owned_admission
from full_theory.current_owned_admission_audit import audit_current_owned_admission
from tests_ft7.test_social_live_outcome import read_record,engine_type
from tests_ft7.test_owned_paid_comparison import paid_type

def saved(setting,case):
    return read_record(Path(os.environ['FT7_CURRENT_ADMISSION_OUTPUT'])/'records'/(setting+'-'+case+'.json.gz'))

def audit(row,text=None):
    setting=row[0].split('/')[0]
    old=engine_type(setting).restore(row[1]);e=paid_type(setting).restore(row[5])
    return audit_current_owned_admission(e,old,row[2],row[3],row[4],row[6],row[7] if text is None else text)

class CurrentOwnedAdmissionTests(unittest.TestCase):
    def test_exact_complete_domain(self):
        for setting,count in (('canonical',22),('workflow',14)):
            row=saved(setting,'complete');d=loads(row[7])
            self.assertEqual([x['name'] for x in d['admission']['options']],['retained','ordinary','n','cp','support','defer'])
            self.assertEqual(len(d['candidates']),count*5+1)
            for mean in ('retained','ordinary','n','cp','support'):
                self.assertEqual(sum(x['mean']==mean for x in d['candidates']),count)
            self.assertTrue(audit(row)['passed']);del row,d;gc.collect()

    def test_no_unsettled_admission(self):
        for setting in ('canonical','workflow'):
            for case in ('before','ready'):
                d=loads(saved(setting,case)[7]);self.assertIsNone(d['admission']);self.assertEqual(d['candidates'],[])
                self.assertIsNone(d['nominee']);self.assertFalse(d['comparison_settled']);del d;gc.collect()

    def test_current_wallet_not_old_snapshot(self):
        for setting,cost in (('canonical',63),('workflow',54)):
            row=saved(setting,'complete');d=loads(row[7]);old=loads(row[4])['snapshot']['wallet']
            self.assertEqual(tuple(old[i]-d['current_snapshot']['wallet'][i] for i in (0,1)),(cost,cost))
            self.assertEqual(d['preparation_due'],1)
            for c in d['candidates'][:-1]:
                self.assertEqual(c['preparation_cost'],dict(energy=2,time=2))
                if c['total_estimate'] is not None:
                    for u in ('energy','time'):self.assertEqual(c['total_estimate'][u],c['native_effort_estimate']+c['route_overhead'][u]+2)
            del row,d;gc.collect()

    def test_harder_deferral_preserved(self):
        for setting in ('canonical','workflow'):
            row=saved(setting,'complete');d=loads(row[7])
            self.assertEqual(d['nominee']['mean'],'defer');self.assertEqual(d['admission']['selected']['name'],'defer')
            self.assertTrue(all(not c['eligible'] for c in d['candidates'][:-1]));self.assertFalse(d['history_choice'])
            self.assertFalse(d['execution_authorized']);del row,d;gc.collect()

    def test_restart_exact(self):
        for setting in ('canonical','workflow'):
            a=saved(setting,'complete');b=saved(setting,'restarted');self.assertEqual(a[1:],b[1:]);del a,b;gc.collect()

    def test_native_and_prefixes_unchanged(self):
        for setting in ('canonical','workflow'):
            row=saved(setting,'complete');old=engine_type(setting).restore(row[1]);e=paid_type(setting).restore(row[5])
            self.assertEqual(current_owned_admission(e,old,row[2],row[3],row[4],row[6]),row[7])
            self.assertEqual(e.checkpoint(),row[5]);self.assertEqual(old.checkpoint(),row[1]);del row,old,e;gc.collect()

    def test_omitted_mean_rejected(self):
        row=saved('canonical','complete');d=loads(row[7]);d['candidates']=[c for c in d['candidates'] if c['mean']!='cp']
        with self.assertRaises(ValueError):audit(row,dumps(d))

    def test_preparation_price_forgery_rejected(self):
        row=saved('workflow','complete');d=loads(row[7]);d['candidates'][0]['preparation_cost']['energy']=0
        with self.assertRaises(ValueError):audit(row,dumps(d))

    def test_priority_forgery_rejected(self):
        row=saved('canonical','complete');d=loads(row[7]);d['candidates'][0]['priority']=4
        with self.assertRaises(ValueError):audit(row,dumps(d))

    def test_false_authority_rejected(self):
        row=saved('workflow','complete');d=loads(row[7]);d['execution_authorized']=True
        with self.assertRaises(ValueError):audit(row,dumps(d))
