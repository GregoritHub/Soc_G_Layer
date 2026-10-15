import gc
import gzip
import hashlib
import json
import os
from pathlib import Path
import unittest
from hle_unified import codec
from hle_unified.selection_records import dumps, loads
from hle_unified.selection_execution import SelectionEngine
from hle_unified.workflow_selection_execution import WorkflowFinalSelectionEngine
from full_theory.social_live_outcome import SocialLiveOutcome
from full_theory.social_live_outcome_audit import audit_social_live_outcome


def engine_type(setting):
    return SelectionEngine if setting=='canonical' else WorkflowFinalSelectionEngine


def read_record(path):
    with gzip.open(path,'rt',encoding='ascii') as stream:
        return codec.loads(stream.read())


def source(setting, case='partial-movement'):
    key=setting+'/'+case
    root=Path(os.environ['FT7_LIVE_NATIVE']);bound=Path(os.environ['FT7_LIVE_BINDINGS'])
    row=next(x for x in json.loads((root/'record_index.json').read_text()) if x['key']==key)
    br=next(x for x in json.loads((bound/'record_index.json').read_text()) if x['key']==key)
    for folder,item in ((root,row),(bound,br)):
        if hashlib.sha256((folder/item['file']).read_bytes()).hexdigest()!=item['sha256']:
            raise ValueError('input saved identity differs')
    k,txs,s,n=read_record(root/row['file'])
    bk,ih,sh,b=read_record(bound/br['file'])
    if (k,bk,ih,sh)!=(key,key,row['sha256'],hashlib.sha256(s.encode()).hexdigest()):
        raise ValueError('exact paired source required')
    e=engine_type(setting).restore(n)
    if tuple(e.world.journal())!=txs:raise ValueError('raw/native journal differs')
    return e,s,b


def raw(setting,stage):
    return read_record(Path(os.environ['FT7_LIVE_OUTPUT'])/'records'/(setting+'-'+stage+'.json.gz'))


class SocialLiveOutcomeTests(unittest.TestCase):
    def test_exact_original_prefixes(self):
        for setting in ('canonical','workflow'):
            old,s,b=source(setting);_,native,wrapper=raw(setting,'complete');d=loads(wrapper)
            now=engine_type(setting).restore(native)
            self.assertEqual(tuple(now.world.journal())[:len(old.world.journal())],tuple(old.world.journal()))
            for key in ('reserve','history'):
                a=loads(loads(b)[key]);z=loads(d[key])
                self.assertEqual(z['events'][:len(a['events'])],a['events'])
            del old,s,b,now,d,native,wrapper;gc.collect()

    def _pending(self,stage,phase):
        for setting in ('canonical','workflow'):
            _,native,wrapper=raw(setting,stage);d=loads(wrapper)
            self.assertEqual(d['status'],'pending');self.assertEqual(loads(d['cycle'])['phase'],phase)
            self.assertEqual(d['history'],d['history_prefix']);self.assertEqual(d['reserve'],d['reserve_prefix'])
            self.assertEqual(d['pending_start'],d['start']);self.assertEqual(d['windows'],[])
            self.assertIsNone(d['completion'])
            del native,wrapper,d;gc.collect()

    def test_partial_movement_no_credit(self):self._pending('movement-partial','route')
    def test_movement_complete_no_credit(self):self._pending('movement-complete','consumer')
    def test_partial_consumer_no_credit(self):self._pending('consumer-partial','consumer')

    def test_completion_paid_and_once(self):
        for setting in ('canonical','workflow'):
            _,native,wrapper=raw(setting,'complete');d=loads(wrapper);c=loads(d['cycle'])
            self.assertEqual(d['status'],'complete');self.assertEqual(loads(d['reserve'])['balance'],0)
            self.assertEqual(len(loads(d['reserve'])['events'])-len(loads(d['reserve_prefix'])['events']),1)
            self.assertGreater(sum(x['debit']['energy'] for x in d['events']),0)
            self.assertTrue(d['windows']);self.assertIsNotNone(c['terminal']['settlement'])
            for window in d['windows']:
                self.assertGreaterEqual(window['start'],d['start'])
                self.assertTrue(all(x['tag']=='independent' for x in window['event']['classifications']))
            del native,wrapper,d,c;gc.collect()

    def test_both_exact_restarts(self):
        for setting in ('canonical','workflow'):
            for split in ('movement','consumer'):
                a=raw(setting,'complete');b=raw(setting,'restart-'+split+'-final')
                self.assertEqual(a[1:],b[1:]);del a,b;gc.collect()

    def test_terminal_idempotence(self):
        old,s,b=source('canonical');_,native,wrapper=raw('canonical','complete')
        e=engine_type('canonical').restore(native);p=SocialLiveOutcome.restore(wrapper,e,old,s,b)
        p.step(e);p.step(e)
        self.assertEqual(e.checkpoint(),native);self.assertEqual(p.checkpoint(e),wrapper)

    def test_deferred_debt_unchanged(self):
        for setting in ('canonical','workflow'):
            old,s,b=source(setting,'harder');_,native,wrapper=raw(setting,'deferred');d=loads(wrapper)
            e=engine_type(setting).restore(native);p=SocialLiveOutcome.restore(wrapper,e,old,s,b)
            self.assertEqual(d['status'],'deferred');self.assertEqual(d['events'],[])
            self.assertEqual(d['reserve'],loads(b)['reserve']);self.assertEqual(d['history'],loads(b)['history'])
            self.assertEqual(loads(b)['reserve_bindings'][-1]['admission']['preparation'],1)
            p.step(e);self.assertEqual(e.checkpoint(),native);self.assertEqual(p.checkpoint(e),wrapper)
            del old,s,b,e,p,d,native,wrapper;gc.collect()

    def test_forged_credit_and_boundary_rejected(self):
        old,s,b=source('canonical');_,native,wrapper=raw('canonical','consumer-partial')
        e=engine_type('canonical').restore(native)
        d=loads(wrapper);d['pending_start']+=1
        with self.assertRaises(ValueError):audit_social_live_outcome(e,old,s,b,dumps(d))
        d=loads(wrapper);d['completion']={'kind':'completion'}
        with self.assertRaises(ValueError):audit_social_live_outcome(e,old,s,b,dumps(d))

    def test_wrong_pair_and_old_history_rejected(self):
        old,s,b=source('canonical');_,native,wrapper=raw('canonical','consumer-partial')
        e=engine_type('canonical').restore(native);_,final,_=raw('canonical','complete')
        with self.assertRaises(ValueError):SocialLiveOutcome.restore(wrapper,engine_type('canonical').restore(final),old,s,b)
        d=loads(wrapper);h=loads(d['history']);h['scores']['se']=7;d['history']=dumps(h)
        with self.assertRaises(ValueError):audit_social_live_outcome(e,old,s,b,dumps(d))
