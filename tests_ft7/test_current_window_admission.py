import unittest,gc
from copy import deepcopy
from hle_unified.selection_records import dumps,loads
from tools.evaluate_ft7_current_window_admission import protocol,context,saved,capacity_row
from full_theory.current_window_admission import current_window_admission
from full_theory.current_window_admission_audit import audit_current_window_admission

class CurrentWindowAdmissionTests(unittest.TestCase):
    def test_exact_full_panel(self):
        for key in protocol()['saved_records']:
            d=loads(saved(key)[2]);settled=d['comparison_settled']
            self.assertEqual(len(d['windows']),(510 if key.startswith('workflow/') else 1) if settled else 0)
            self.assertEqual(d['complete_within_paid_bound'],settled)
            self.assertFalse(d['execution_authorized']);self.assertFalse(d['td5_admitted']);self.assertFalse(d['history_choice'])
            if settled:self.assertEqual(d['nominee']['mean'],'defer')
    def test_lifecycle_withholds_domain(self):
        for setting in ('canonical','workflow'):
            for name in ('before','partial','ready','cancelled'):
                d=loads(saved(setting+'/'+name)[2]);self.assertEqual((d['windows'],d['candidates']),((),()))
                self.assertIsNone(d['nominee']);self.assertIsNone(d['current_wallet']);self.assertIsNone(d['preparation'])
    def test_restart_exact(self):
        for setting in ('canonical','workflow'):self.assertEqual(saved(setting+'/mask-1')[2],saved(setting+'/restarted')[2])
    def test_every_cost_and_priority_join(self):
        for setting,wallet in (('canonical',197913),('workflow',175815)):
            for mask in range(1,16):
                key=setting+'/mask-'+str(mask);d=loads(saved(key)[2]);cap=loads(capacity_row(key)[2])
                self.assertEqual(d['current_wallet'],dict(energy=wallet,time=wallet))
                operands=sum(len(c['options']) for w in d['windows'] for c in w['cells'])
                self.assertEqual(len(d['candidates']),5*operands+1)
                self.assertEqual(len({r['identity'] for r in d['candidates']}),len(d['candidates']))
                for r in d['candidates'][:-1]:
                    m=cap['means'][r['priority']];self.assertEqual(r['mean'],m['name'])
                    for u in ('energy','time'):
                        self.assertEqual(r['total_estimate'][u],r['native_effort_estimate']+m['overhead'][u]+cap['preparation'][u])
                self.assertEqual(d['candidates'][-1]['total_estimate'],dict(energy=0,time=0))
    def test_window_operand_cost_forgery_rejected(self):
        for setting in ('canonical','workflow'):
            ctx=context(setting+'/mask-1');d=loads(saved(setting+'/mask-1')[2])
            for mode in ('window','operand','cost','authority','nominee'):
                bad=deepcopy(d)
                if mode=='window':bad['windows']=bad['windows'][:-1]
                elif mode=='operand':bad['candidates']=bad['candidates'][1:]
                elif mode=='cost':bad['candidates'][0]['total_estimate']['energy']+=1
                elif mode=='authority':bad['execution_authorized']=True
                else:bad['nominee']=bad['candidates'][0]
                with self.assertRaises(ValueError):audit_current_window_admission(*ctx,dumps(bad))
            del ctx;gc.collect()
    def test_capacity_and_input_pairing_rejected(self):
        for setting in ('canonical','workflow'):
            ctx=list(context(setting+'/mask-1'));d=loads(ctx[-1]);d['inventory']['wallet']['energy']+=1;ctx[-1]=dumps(d)
            with self.assertRaises(ValueError):current_window_admission(*ctx)
            del ctx;gc.collect()
    def test_old_nominees_and_bounded_cells(self):
        for key in protocol()['saved_records']:
            d=loads(saved(key)[2])
            for window in d['windows']:
                if window['rejection'] is not None:continue
                self.assertEqual([c['cell'] for c in window['cells']],list(range(33 if key.startswith('canonical/') else 32)))
                for c in window['cells']:
                    self.assertEqual(c['examined'],len(c['options']));self.assertLessEqual(c['examined'],64)
                    self.assertEqual((c['examined'],c['deferred']),(c['paid_nominee']['examined'],c['paid_nominee']['deferred']))
                    self.assertEqual([o['ordinal'] for o in c['options']],list(range(c['examined'])))
    def test_native_and_prefixes_unchanged(self):
        for setting in ('canonical','workflow'):
            ctx=context(setting+'/mask-1');before=tuple(e.checkpoint() for e in ctx[:3]);strings=ctx[3:]
            text=current_window_admission(*ctx);self.assertEqual(text,saved(setting+'/mask-1')[2])
            audit_current_window_admission(*ctx,text)
            self.assertEqual(tuple(e.checkpoint() for e in ctx[:3]),before);self.assertEqual(ctx[3:],strings)
            del ctx;gc.collect()
