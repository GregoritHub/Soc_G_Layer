import gc,gzip,os,unittest
from pathlib import Path
from hashlib import sha256
from hle_unified import codec
from hle_unified.selection_records import loads,dumps
from full_theory.fresh_task_comparison import prepare_fresh_comparison
from full_theory.fresh_task_comparison_audit import audit_fresh_domain
from full_theory.owned_paid_comparison import step_owned_comparison
from tests_ft7.test_social_live_outcome import engine_type
from tests_ft7.test_owned_paid_comparison import paid_type,request_for
from tools.evaluate_ft7_1b2b3b2b2b2b2b2b1 import input_row,original_row

def saved(setting,stage):
    with gzip.open(Path(os.environ['FT7_FRESH_COMPARISON_OUTPUT'])/'records'/(setting+'-'+stage+'.json.gz'),'rt') as f:return codec.loads(f.read())

class FreshTaskComparisonTests(unittest.TestCase):
    def test_full_fixed_panel(self):
        for setting in ('canonical','workflow'):
            for mask in range(1,16):
                row=saved(setting,'mask-'+str(mask));d=loads(row[2]);i=loads(input_row(setting,'mask-'+str(mask))[2])
                self.assertEqual(d['request']['demand'],i['task'])
                self.assertEqual(d['fresh_demand']['binding'],i['task'])
                self.assertEqual(d['formation']['selected'],dumps((d['actor'],i['task'])))
                self.assertEqual([x['cell'] for x in d['candidates']],list(range(33 if setting=='canonical' else 32)))
                self.assertTrue(all(d['request'][k] is None for k in ('stock','tool','peer','group') if k in d['request']))

    def test_actual_payment_and_receipts(self):
        for setting in ('canonical','workflow'):
            for mask in range(1,16):
                row=saved(setting,'mask-'+str(mask));d=loads(row[2]);e=paid_type(setting).restore(row[1]);r=request_for(e)
                status=e.job_status(r.request.actor,r.key);result=e.comparison_result(r.request.actor,r.key)
                self.assertEqual((status['required'],status['spent'],status['completed']),(d['comparison_required'],)*3)
                self.assertEqual(status['status'],'succeeded');self.assertTrue(result['comparison_paid'])
                self.assertEqual(result['candidates'],d['candidates']);self.assertEqual(result['native_nominee'],d['native_nominee'])
                old=engine_type(setting).restore(input_row(setting,'mask-'+str(mask))[1])
                self.assertEqual({u:old.wallet(d['actor'])[u]-e.wallet(d['actor'])[u] for u in ('energy','time')},dict(energy=d['comparison_required'],time=d['comparison_required']))
                del old,e,row;gc.collect()

    def test_partial_and_ready_no_result(self):
        for setting in ('canonical','workflow'):
            for stage in ('before','partial','ready'):
                row=saved(setting,stage);d=loads(row[2]);e=paid_type(setting).restore(row[1])
                key='ft-owned-comparison:fresh:'+d['intake_sha256'][:24]
                if stage=='before':
                    self.assertNotIn((d['actor'],key),e._jobs)
                    with self.assertRaises(ValueError):e.comparison_result(d['actor'],key)
                else:
                    self.assertIsNone(e.comparison_result(d['actor'],key))
                    self.assertEqual(e.job_status(d['actor'],key)['status'],stage)
                del row,e;gc.collect()

    def test_exact_restart_and_terminal(self):
        for setting in ('canonical','workflow'):
            self.assertEqual(saved(setting,'mask-1')[1:],saved(setting,'restarted')[1:])
            for stage in ('mask-1','cancelled'):
                row=saved(setting,stage);e=paid_type(setting).restore(row[1]);r=request_for(e)
                step_owned_comparison(e,r);step_owned_comparison(e,r)
                self.assertEqual(e.checkpoint(),row[1]);del row,e;gc.collect()

    def test_cancellation_no_refund(self):
        for setting in ('canonical','workflow'):
            row=saved(setting,'cancelled');e=paid_type(setting).restore(row[1]);r=request_for(e)
            status=e.job_status(r.request.actor,r.key)
            self.assertEqual((status['status'],status['spent']),('cancelled',1))
            self.assertIsNone(e.comparison_result(r.request.actor,r.key))
            old=engine_type(setting).restore(input_row(setting,'mask-1')[1])
            self.assertEqual({u:old.wallet(r.request.actor)[u]-e.wallet(r.request.actor)[u] for u in ('energy','time')},dict(energy=1,time=1))
            del old,e,row;gc.collect()

    def test_incomplete_intake_rejected(self):
        for setting in ('canonical','workflow'):
            original=original_row(setting);old=engine_type(setting).restore(original[1])
            for stage in ('before','read-partial','read-complete','bind-partial'):
                row=input_row(setting,stage);e=engine_type(setting).restore(row[1]);before=e.checkpoint()
                with self.assertRaises(ValueError):prepare_fresh_comparison(e,old,original[2],original[3],row[2])
                self.assertEqual(e.checkpoint(),before);del e,row;gc.collect()
            del old,original;gc.collect()

    def test_forged_domain_rejected(self):
        for setting in ('canonical','workflow'):
            original=original_row(setting);old=engine_type(setting).restore(original[1]);row=input_row(setting,'mask-1')
            e=engine_type(setting).restore(row[1]);domain=saved(setting,'mask-1')[2]
            for field,value in (('comparison_required',0),('source_sha256','0'*64),('native_nominee',{})):
                d=loads(domain);d[field]=value
                with self.assertRaises(ValueError):audit_fresh_domain(e,old,original[2],original[3],row[2],dumps(d))
            d=loads(domain);d['request']['demand']=loads(original[2])['task'] if 'task' in loads(original[2]) else None
            with self.assertRaises(ValueError):audit_fresh_domain(e,old,original[2],original[3],row[2],dumps(d))
            for field,value in (('receipt',None),('source_sha256','0'*64)):
                i=loads(row[2]);i[field]=value;before=e.checkpoint()
                with self.assertRaises(ValueError):prepare_fresh_comparison(e,old,original[2],original[3],dumps(i))
                self.assertEqual(e.checkpoint(),before)
            with self.assertRaises(ValueError):prepare_fresh_comparison(e,old,original[2],original[3]+' ',row[2])
            del old,e,row,original;gc.collect()

    def test_immutable_prefix_and_scope(self):
        for setting in ('canonical','workflow'):
            original=original_row(setting)
            for mask in range(1,16):
                row=saved(setting,'mask-'+str(mask));d=loads(row[2]);intake=input_row(setting,'mask-'+str(mask))
                self.assertEqual(d['controller_prefix'],loads(original[2])['demand_controller'])
                self.assertEqual(d['intake_sha256'],sha256(intake[2].encode()).hexdigest())
                self.assertFalse(any(d[k] for k in ('comparison_paid','execution_authorized','td5_admitted','history_choice')))
            row=saved(setting,'mask-15');e=paid_type(setting).restore(row[1]);old=engine_type(setting).restore(input_row(setting,'mask-15')[1])
            self.assertEqual(tuple(e.world.journal())[:len(old.world.journal())],tuple(old.world.journal()))
            self.assertEqual(e._cursors,old._cursors)
            del e,old,row;gc.collect()
