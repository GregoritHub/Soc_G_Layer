import gc, os, unittest
from pathlib import Path
from copy import deepcopy
from hle_unified.selection_records import dumps,loads
from tools.evaluate_ft7_1b2b3b2b2b2b2b2b1c import context,saved,protocol,read
from full_theory.current_window_capacity import current_window_capacity
from full_theory.current_window_capacity_audit import audit_current_window_capacity

class CurrentWindowCapacityTests(unittest.TestCase):
    def test_exact_full_panel(self):
        for key in protocol()['saved_records']:
            out=loads(saved(key)[2]);stage=read(Path(os.environ['FT7_CAPACITY_OUTPUT'])/'stages'/(key.replace('/','-')+'.json'))
            self.assertTrue(stage['passed']);self.assertTrue(stage['independent_audit']['passed'])
            expected=510 if key.startswith('workflow/') else 1
            self.assertEqual(len(out['windows']),expected if out['comparison_settled'] else 0)
            self.assertEqual(len(out['means']),6 if out['comparison_settled'] else 0)

    def test_lifecycle_withholds_capacity(self):
        for setting in ('canonical','workflow'):
            for name in ('before','partial','ready','cancelled'):
                d=loads(saved(setting+'/'+name)[2]);self.assertFalse(d['comparison_settled'])
                self.assertIsNone(d['required']);self.assertIsNone(d['preparation']);self.assertIsNone(d['inventory'])
                self.assertEqual((d['windows'],d['means'],d['retained']),((),(),()))

    def test_restart_exact(self):
        for setting in ('canonical','workflow'):
            self.assertEqual(saved(setting+'/mask-1')[2],saved(setting+'/restarted')[2])

    def test_current_wallet_and_preparation(self):
        for setting,wallet in (('canonical',197913),('workflow',175815)):
            for mask in range(1,16):
                d=loads(saved(setting+'/mask-'+str(mask))[2]);p=d['preparation']
                self.assertEqual(d['inventory']['wallet'],dict(energy=wallet,time=wallet))
                self.assertEqual(p['units'],max(0,p['load']-p['reserve']))
                self.assertEqual((p['energy'],p['time']),(2*p['units'],)*2)
                self.assertEqual((p['intake_credit'],p['comparison_credit']),(0,0));self.assertIsNone(p['receipt'])
                self.assertFalse(p['admitted']);self.assertEqual(p['task'],d['inventory']['request']['demand'])

    def test_exact_scope_and_window_factorization(self):
        for setting in ('canonical','workflow'):
            ctx=context(setting+'/mask-1');d=loads(saved(setting+'/mask-1')[2]);w=loads(ctx[-1]);s=loads(ctx[3])
            self.assertEqual(d['required'],s['required'])
            self.assertEqual([x['name'] for x in d['means']],['retained','ordinary','n','cp','support','defer'])
            self.assertFalse(d['means'][4]['eligible'])
            for n,fields in enumerate(w['requests']):
                from hashlib import sha256
                self.assertEqual(d['windows'][n],dict(ordinal=n,request_sha256=sha256(dumps(fields).encode()).hexdigest()))
            for mode in ('requirements','window','role'):
                bad=deepcopy(d)
                if mode=='requirements':bad['required']['load']+=1
                elif mode=='window':bad['windows']=bad['windows'][:-1]
                else:bad['inventory']['request']['peer']=bad['actor']
                with self.assertRaises(ValueError):audit_current_window_capacity(*ctx,dumps(bad))
            del ctx;gc.collect()

    def test_independent_capacity_and_authority_forgery(self):
        for setting in ('canonical','workflow'):
            ctx=context(setting+'/mask-1');d=loads(saved(setting+'/mask-1')[2])
            for field in ('execution_authorized','td5_admitted','history_choice','full_operand_cost_domain','prefixes_mutated'):
                bad=deepcopy(d);bad[field]=True
                with self.assertRaises(ValueError):audit_current_window_capacity(*ctx,dumps(bad))
            for mode in ('capacity','wallet','credit','history','reserve','selected'):
                bad=deepcopy(d)
                if mode=='capacity':bad['means'][0]['eligible']=not bad['means'][0]['eligible']
                elif mode=='wallet':bad['inventory']['wallet']['energy']+=1
                elif mode=='credit':bad['preparation']['intake_credit']=1
                elif mode=='history':bad['history_prefix_sha256']='0'*64
                elif mode=='reserve':bad['reserve_prefix_sha256']='0'*64
                else:bad['selected']='retained'
                with self.assertRaises(ValueError):audit_current_window_capacity(*ctx,dumps(bad))
            del ctx;gc.collect()

    def test_source_and_native_pairing_rejected(self):
        for setting in ('canonical','workflow'):
            ctx=context(setting+'/mask-1');before=ctx[0].checkpoint()
            for mode in ('source','windows','cursor'):
                wrong=list(ctx)
                if mode=='source':wrong[3]+=' '
                elif mode=='windows':
                    w=loads(wrong[-1]);w['requests']=w['requests'][:-1];wrong[-1]=dumps(w)
                else:
                    saved_cursor=deepcopy(ctx[0]._cursors);actor=loads(ctx[3])['actor'];ctx[0]._cursors[actor]='not-an-element'
                try:
                    with self.assertRaises(ValueError):current_window_capacity(*wrong)
                finally:
                    if mode=='cursor':ctx[0]._cursors=saved_cursor
                self.assertEqual(ctx[0].checkpoint(),before)
            del ctx;gc.collect()

    def test_old_prefixes_and_no_mutation(self):
        for setting in ('canonical','workflow'):
            ctx=context(setting+'/mask-1');before=tuple(x.checkpoint() for x in ctx[:3]);strings=ctx[3:]
            actual=current_window_capacity(*ctx)
            self.assertEqual(actual,saved(setting+'/mask-1')[2]);audit_current_window_capacity(*ctx,actual)
            self.assertEqual(tuple(x.checkpoint() for x in ctx[:3]),before);self.assertEqual(ctx[3:],strings)
            del ctx;gc.collect()
