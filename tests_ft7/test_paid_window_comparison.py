import gc,gzip,json,os,unittest
from pathlib import Path
from dataclasses import replace
from unittest.mock import patch
from hle_unified import codec
from hle_unified.selection_records import loads,dumps
from hle_unified.material import attrs,attributes
from hle_unified.operations import address,record
from full_theory.paid_window_comparison import prepare_window_comparison,step_window_comparison,digest
from full_theory.paid_window_comparison_audit import audit_paid_windows
from tests_ft7.test_social_live_outcome import engine_type
from tools.evaluate_ft7_1b2b3b2b2b2b2b2b1b import input_row,original_row,paid_type,domain_row

def saved(setting,stage):
    with gzip.open(Path(os.environ['FT7_WINDOW_OUTPUT'])/'records'/(setting+'-'+stage+'.json.gz'),'rt') as f:return codec.loads(f.read())

def inputs(setting):
    original=original_row(setting);intake=input_row(setting,'mask-1')
    return engine_type(setting).restore(intake[1]),engine_type(setting).restore(original[1]),original,intake

def request_for(e):
    return next(command[2] for command,_ in (e._pool.get(t) for t in e._events)
        if command[0]=='start' and type(command[2]).__name__=='WindowComparisonRequest')

class PaidWindowComparisonTests(unittest.TestCase):
    def test_exact_full_panel(self):
        audits=json.loads((Path(os.environ['FT7_WINDOW_OUTPUT'])/'decoded_audits.json').read_text())
        self.assertEqual(len(audits),40)
        for setting,count in (('canonical',1),('workflow',510)):
            for mask in range(1,16):
                row=saved(setting,'mask-'+str(mask));domain=domain_row(setting,mask)
                self.assertEqual(row[2],domain[2]);self.assertEqual(len(loads(row[2])['requests']),count)
                a=audits[setting+'/mask-'+str(mask)]
                self.assertEqual(a['windows'],count);self.assertTrue(a['passed'])

    def test_full_native_payment(self):
        for setting in ('canonical','workflow'):
            for mask in range(1,16):
                row=saved(setting,'mask-'+str(mask));e=paid_type(setting).restore(row[1]);r=request_for(e)
                actor=loads(row[2])['actor'];result=e.window_result(actor,r.key);status=e.job_status(actor,r.key)
                required=sum(x['required'] for x in result['windows'])
                self.assertGreater(required,0);self.assertEqual(result['required'],required)
                self.assertEqual((status['required'],status['spent'],status['completed']),(required,)*3)
                self.assertEqual(status['status'],'succeeded')
                old=engine_type(setting).restore(input_row(setting,'mask-'+str(mask))[1])
                self.assertEqual({u:old.wallet(actor)[u]-e.wallet(actor)[u] for u in ('energy','time')},dict(energy=required,time=required))
                del old,e,row;gc.collect()

    def test_no_early_receipt(self):
        for setting in ('canonical','workflow'):
            for stage in ('before','partial','ready','cancelled'):
                row=saved(setting,stage);e=paid_type(setting).restore(row[1]);d=loads(row[2])
                key='ft-window-comparison:'+digest(row[2])
                if stage=='before':
                    self.assertNotIn((d['actor'],key),e._jobs)
                    with self.assertRaises(ValueError):e.window_result(d['actor'],key)
                else:self.assertIsNone(e.window_result(d['actor'],key))
                self.assertFalse(any(v.ref.identity.namespace=='ftwc.result' for tx in e.world.journal() for v in tx.versions))
                del e,row;gc.collect()

    def test_exact_partial_restart(self):
        for setting in ('canonical','workflow'):
            self.assertEqual(saved(setting,'mask-1')[1:],saved(setting,'restarted')[1:])

    def test_cancel_and_terminal_idempotence(self):
        for setting in ('canonical','workflow'):
            for stage in ('mask-1','cancelled'):
                row=saved(setting,stage);e=paid_type(setting).restore(row[1]);r=request_for(e);actor=loads(row[2])['actor']
                if stage=='cancelled':
                    self.assertEqual(e.job_status(actor,r.key)['spent'],1)
                    old=engine_type(setting).restore(input_row(setting,'mask-1')[1])
                    self.assertEqual({u:old.wallet(actor)[u]-e.wallet(actor)[u] for u in ('energy','time')},dict(energy=1,time=1))
                    del old
                step_window_comparison(e,r);step_window_comparison(e,r)
                self.assertEqual(e.checkpoint(),row[1]);del e,row;gc.collect()

    def test_forged_source_and_domain_rejected(self):
        for setting in ('canonical','workflow'):
            native,old,original,intake=inputs(setting);domain=domain_row(setting,1)[2]
            evidence=(original[1],original[2],original[3],intake[2]);before=native.checkpoint()
            for field,value in (('requests',[]),('native_sha256','0'*64),('comparison_paid',True)):
                d=loads(domain);d[field]=value
                with self.assertRaises(ValueError):prepare_window_comparison(native,dumps(d),evidence)
                self.assertEqual(native.checkpoint(),before)
            wrong=list(evidence);wrong[2]+=' '
            with self.assertRaises(ValueError):prepare_window_comparison(native,domain,tuple(wrong))
            for stage in ('before','read-partial','read-complete','bind-partial'):
                incomplete=input_row(setting,stage);bad=engine_type(setting).restore(incomplete[1])
                with self.assertRaises(ValueError):prepare_window_comparison(bad,domain,(*evidence[:3],incomplete[2]))
                self.assertEqual(bad.checkpoint(),incomplete[1]);del bad
            del native,old,original,intake;gc.collect()

    def test_protected_result_and_forged_extent(self):
        for setting in ('canonical','workflow'):
            native,old,original,intake=inputs(setting);domain=domain_row(setting,1)[2]
            e,r=prepare_window_comparison(native,domain,(original[1],original[2],original[3],intake[2]))
            actor=loads(domain)['actor'];before=e.checkpoint();ref=address('ftwc.result',actor,r.key)
            with self.assertRaises(ValueError):e.declare('forged-window-result',(record(ref,'Forged result',dict(payload='fake')),))
            self.assertEqual(e.checkpoint(),before)
            e=paid_type(setting).restore(saved(setting,'mask-1')[1])
            for mode in ('extent','authority'):
                txs=list(e.world.journal());versions=list(txs[-1].versions)
                for i,v in enumerate(versions):
                    data=attrs(v)
                    if mode=='extent' and data.get('ftwc'):
                        versions[i]=replace(v,attributes=attributes(dict(data,required=0)))
                    if mode=='authority' and v.ref.identity.namespace=='ftwc.result':
                        payload=loads(data['payload']);payload['execution_authorized']=True
                        versions[i]=replace(v,attributes=attributes(dict(data,payload=dumps(payload))))
                txs[-1]=replace(txs[-1],versions=tuple(versions))
                with patch.object(e.world,'journal',return_value=tuple(txs)):
                    with self.assertRaises(ValueError):audit_paid_windows(e,native,old,original[2],original[3],intake[2],domain)
            del native,old,original,intake,e;gc.collect()

    def test_no_admission_or_history_authority(self):
        for setting in ('canonical','workflow'):
            original=original_row(setting)
            for mask in range(1,16):
                row=saved(setting,'mask-'+str(mask));d=loads(row[2])
                self.assertEqual(d['controller_prefix'],loads(original[2])['demand_controller'])
                self.assertEqual(d['receipt_scope'],'intake_only')
                e=paid_type(setting).restore(row[1]);r=request_for(e);result=e.window_result(d['actor'],r.key)
                self.assertTrue(result['comparison_paid'])
                self.assertFalse(any(result[k] for k in ('execution_authorized','td5_admitted','history_choice')))
                self.assertEqual([x['ordinal'] for x in result['windows']],list(range(len(d['requests']))))
                old=engine_type(setting).restore(input_row(setting,'mask-'+str(mask))[1])
                self.assertEqual(tuple(e.world.journal())[:len(old.world.journal())],tuple(old.world.journal()))
                self.assertEqual(e._cursors,old._cursors)
                del e,old,row;gc.collect()

