import gc
import gzip
import json
import os
from pathlib import Path
import unittest

from hle_unified import codec
from hle_unified.selection_records import dumps, loads
from hle_unified.selection_execution import SelectionEngine
from hle_unified.workflow_selection_execution import WorkflowFinalSelectionEngine
from full_theory.social_preparation import SocialPaidPreparation
from full_theory.social_preparation_audit import audit_social_preparation


def engine_type(setting):
    return SelectionEngine if setting == 'canonical' else WorkflowFinalSelectionEngine


def read_record(path):
    with gzip.open(path, 'rt', encoding='ascii') as f:
        return codec.loads(f.read())


def source(setting):
    root = Path(os.environ['FT7_PREPARATION_NATIVE'])
    bound = Path(os.environ['FT7_PREPARATION_BINDINGS'])
    key = setting + '/harder'
    row = next(x for x in json.loads((root/'record_index.json').read_text()) if x['key'] == key)
    k, txs, wrapper, native = read_record(root/row['file'])
    br = next(x for x in json.loads((bound/'record_index.json').read_text()) if x['key'] == key)
    bk, input_hash, wrapper_hash, binding = read_record(bound/br['file'])
    if (k,bk,input_hash) != (key,key,row['sha256']):
        raise ValueError('exact paired input required')
    return engine_type(setting).restore(native), wrapper, binding


def record(setting, stage):
    root = Path(os.environ['FT7_PREPARATION_OUTPUT'])
    key, native, wrapper = read_record(root/'records'/(setting+'-'+stage+'.json.gz'))
    if key != setting+'/'+stage:
        raise ValueError('saved identity mismatch')
    return engine_type(setting).restore(native), wrapper


class SocialPreparationTests(unittest.TestCase):
    def test_exact_source_prefix(self):
        for setting in ('canonical','workflow'):
            e,s,b = source(setting); now,c = record(setting,'complete');d = loads(c)
            self.assertEqual(tuple(now.world.journal())[:len(e.world.journal())],tuple(e.world.journal()))
            self.assertEqual((d['reserve'],d['history_prefix']),(loads(b)['reserve'],loads(b)['history']))
            self.assertEqual(loads(d['reserve'])['balance'],1)
            del e,s,b,now,c,d;gc.collect()

    def test_partial_work_no_receipt_or_credit(self):
        for setting in ('canonical','workflow'):
            e,c = record(setting,'partial');d = loads(c)
            self.assertEqual(d['receipts'],[]);self.assertEqual(d['history'],d['history_prefix'])
            self.assertEqual(d['events'][-1]['debit'],dict(energy=1,time=1))
            self.assertEqual(d['events'][-1]['remaining'],1)
            del e,c,d;gc.collect()

    def test_complete_exact_native_cost_and_task(self):
        for setting in ('canonical','workflow'):
            e,c = record(setting,'complete');d = loads(c)
            self.assertEqual(len(d['receipts']),d['required']);self.assertEqual(d['required'],1)
            self.assertEqual({u:sum(x['debit'][u] for x in d['events']) for u in ('energy','time')},dict(energy=2,time=2))
            op=e.job_status(d['actor'],d['jobs'][0])
            self.assertEqual((op['required'],op['completed'],op['spent']),(2,2,2))
            self.assertEqual(op['input.0'],d['request']['demand'])
            self.assertEqual(loads(d['history'])['scores'],loads(d['history_prefix'])['scores'])
            del e,c,d;gc.collect()

    def test_restart_exact(self):
        for setting in ('canonical','workflow'):
            root=Path(os.environ['FT7_PREPARATION_OUTPUT'])/'records'
            a=read_record(root/(setting+'-complete.json.gz'))
            b=read_record(root/(setting+'-restarted.json.gz'))
            self.assertEqual(a[1:],b[1:]);del a,b;gc.collect()

    def test_repeated_completion_idempotent(self):
        e,s,b=source('canonical');now,c=record('canonical','complete')
        p=SocialPaidPreparation.restore(c,now,e,s,b);native=now.checkpoint()
        p.step(now);p.step(now)
        self.assertEqual(now.checkpoint(),native);self.assertEqual(p.checkpoint(now),c)

    def test_existing_work_not_adopted(self):
        e,s,b=source('canonical');now,c=record('canonical','partial')
        before=now.checkpoint()
        with self.assertRaises(ValueError):SocialPaidPreparation(now,s,b)
        self.assertEqual(now.checkpoint(),before)

    def test_forged_receipt_and_history_rejected(self):
        e,s,b=source('canonical');now,c=record('canonical','partial');d=loads(c)
        d['receipts']=[dict(job=d['jobs'][0],energy=2,time=2)]
        with self.assertRaises(ValueError):audit_social_preparation(now,e,s,b,dumps(d))
        d=loads(c);h=loads(d['history']);h['scores']['se']=1;d['history']=dumps(h)
        with self.assertRaises(ValueError):audit_social_preparation(now,e,s,b,dumps(d))

    def test_wrong_native_pair_rejected(self):
        e,s,b=source('canonical');now,c=record('canonical','partial');end,unused=record('canonical','complete')
        with self.assertRaises(ValueError):SocialPaidPreparation.restore(c,end,e,s,b)
