"""Exact saved A12B panel/lifecycle controls; never rerun primary intake."""
import unittest
from copy import deepcopy
from hle_unified.selection_records import loads,dumps
from full_theory.cue_task_intake import CueTaskIntake
from full_theory.cue_task_intake_audit import audit_cue_task_intake
CONTEXT={}
class CueTaskIntakeTests(unittest.TestCase):
    def test_complete_panel(self):
        rows=CONTEXT['rows'];self.assertEqual(len(rows),50)
        for s in ('canonical','workflow'):
            for mask in range(1,16):
                d=loads(rows[f'{s}-{mask:02d}-complete'][4]);self.assertEqual(d['mask'],mask);self.assertEqual(d['receipt']['energy'],5);self.assertEqual(d['receipt']['time'],5)
    def test_partial_ready_receipts(self):
        for s in ('canonical','workflow'):
            for stage in ('before','read_partial','read_ready','read_complete','bind_partial','bind_ready'):
                d=loads(CONTEXT['rows'][f'{s}-01-{stage}'][4]);self.assertIsNone(d['receipt']);self.assertFalse(CONTEXT['audits'][f'{s}-01-{stage}']['bound'])
            for stage in ('read_ready','bind_ready'):self.assertEqual(loads(CONTEXT['rows'][f'{s}-01-{stage}'][4])['events'][-1]['status'],'ready')
    def test_exact_restart(self):
        for s in ('canonical','workflow'):
            for stage in ('restart_read','restart_bind'):
                self.assertEqual(CONTEXT['rows'][f'{s}-01-{stage}'][3:5],CONTEXT['rows'][f'{s}-01-complete'][3:5])
    def test_cancellation_debits(self):
        for s in ('canonical','workflow'):
            for stage,cost in (('cancel_read',1),('cancel_bind',3)):
                d=loads(CONTEXT['rows'][f'{s}-01-{stage}'][4]);self.assertTrue(d['cancelled']);self.assertIsNone(d['receipt'])
                self.assertEqual(CONTEXT['audits'][f'{s}-01-{stage}']['native_cost'],dict(energy=cost,time=cost))
    def test_prefixes_and_no_authority(self):
        for name,row in CONTEXT['rows'].items():
            d=loads(row[4]);native,source,binding,panel=CONTEXT['inputs'][row[0]];b=loads(binding)
            self.assertEqual(d['reserve'],b['reserve']);self.assertEqual(d['history'],b['history']);self.assertEqual(d['controller_prefix'],loads(source)['demand_controller'])
            for k in ('comparison_paid','execution_authorized','td5_admitted','history_choice'):self.assertIs(d[k],False)
    def test_historical_and_wrong_input_rejected(self):
        class Snapshot:
            def __init__(self,text):self.text=text
            def checkpoint(self):return self.text
        for s,(native,source,binding,panel) in CONTEXT['inputs'].items():
            bad=loads(panel)
            for row in bad['rows']:row['historical_only']=not row['historical_only']
            with self.assertRaises(ValueError):CueTaskIntake(Snapshot(native),source,binding,dumps(bad),1)
            with self.assertRaises(ValueError):CueTaskIntake(Snapshot(native+' '),source,binding,panel,1)
    def test_saved_forgery_rejected(self):
        class Snapshot:
            def __init__(self,text):self.text=text
            def checkpoint(self):return self.text
        for s,(native,source,binding,panel) in CONTEXT['inputs'].items():
            row=CONTEXT['rows'][f'{s}-01-complete'];d=loads(row[4])
            for key,value in (('version','forged'),('mask',0),('native_sha256','forged'),('source_sha256','forged'),('panel_sha256','forged')):
                bad=deepcopy(d);bad[key]=value
                with self.assertRaises(ValueError):audit_cue_task_intake(Snapshot(row[3]),Snapshot(native),source,binding,panel,dumps(bad))
    def test_terminal_idempotence(self):
        class Snapshot:
            def __init__(self,text):self.text=text
            def checkpoint(self):return self.text
        for s in ('canonical','workflow'):
            for stage in ('complete','cancel_read','cancel_bind'):
                row=CONTEXT['rows'][f'{s}-01-{stage}'];d=loads(row[4]);d.pop('version');d.pop('native_sha256')
                obj=CueTaskIntake.__new__(CueTaskIntake);obj.__dict__.update(d)
                before=obj.checkpoint(Snapshot(row[3]));self.assertEqual(obj.step(Snapshot(row[3])),d['events'][-1]);self.assertEqual(obj.checkpoint(Snapshot(row[3])),before)
