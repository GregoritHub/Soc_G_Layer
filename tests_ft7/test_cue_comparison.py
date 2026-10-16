"""Saved-record gates; never regenerates completed primary paid work."""
import copy,gzip,json,unittest
from dataclasses import replace
from types import SimpleNamespace
from hle_unified import codec
from hle_unified.selection_records import loads,dumps
from hle_unified.material import attrs,attributes
from hle_unified.selection_execution import SelectionEngine
from hle_unified.workflow_selection_execution import WorkflowFinalSelectionEngine
from full_theory.cue_comparison import cue_windows,CueCanonicalEngine,CueWorkflowEngine
from full_theory.cue_comparison_audit import audit,audit_windows
CONTEXT={};PROBES=[]
def read(p):return codec.loads(gzip.decompress(p.read_bytes()).decode())
class CueComparisonTests(unittest.TestCase):
    def test_complete_panel(self):
        for s in ('canonical','workflow'):
            for m in range(1,16):
                n=f'{s}-{m:02d}-complete';a=CONTEXT['audits'][n]
                self.assertEqual(a['status'],'succeeded');self.assertEqual(a['spent'],a['required']);self.assertGreater(a['required'],0);self.assertEqual(a['receipts'],1);self.assertTrue(a['passed'])
    def test_partial_ready_receipts(self):
        for s in ('canonical','workflow'):
            for stage in ('before','partial','ready'):
                a=CONTEXT['audits'][f'{s}-01-{stage}'];self.assertEqual(a['receipts'],0)
                self.assertEqual(a['spent'],0 if stage=='before' else 1 if stage=='partial' else a['required'])
            self.assertEqual(CONTEXT['audits'][f'{s}-01-ready']['status'],'ready')
    def test_exact_restart(self):
        for s in ('canonical','workflow'):
            self.assertEqual(CONTEXT['rows'][f'{s}-01-restarted'][3:],CONTEXT['rows'][f'{s}-01-complete'][3:])
    def test_cancellation_debits(self):
        for s in ('canonical','workflow'):
            a=CONTEXT['audits'][f'{s}-01-cancelled'];self.assertEqual((a['status'],a['spent'],a['receipts']),('cancelled',1,0))
    def test_prefixes_recall_scope(self):
        for n,a in CONTEXT['audits'].items():
            self.assertTrue(a['source_prefix_exact']);self.assertTrue(a['reserve_history_unchanged']);self.assertFalse(a['execution_authorized']);self.assertFalse(a['td5_admitted']);self.assertFalse(a['history_choice'])
            w=loads(CONTEXT['rows'][n][4]);self.assertEqual(w['recall']['limit'],32);self.assertEqual(w['recall']['task_visited'],w['fresh_demand']['binding'] in w['recall']['visited']);self.assertFalse(w['full_future_role_domain'])
    def test_wrong_input_domain_rejected(self):
        for s in ('canonical','workflow'):
            native=read(CONTEXT['inputs']/CONTEXT['protocol']['inputs'][f'{s}-01-complete']['file']);old=(SelectionEngine if s=='canonical' else WorkflowFinalSelectionEngine).restore(native[3]);bad=loads(native[4]);bad['mask']=2
            with self.assertRaises(ValueError):cue_windows(old,dumps(bad))
            PROBES.append(dict(setting=s,field='wrong_input_mask',rejected=True))
            other=read(CONTEXT['inputs']/CONTEXT['protocol']['inputs'][f'{s}-02-complete']['file'])
            with self.assertRaises(ValueError):cue_windows(old,other[4])
            PROBES.append(dict(setting=s,field='wrong_native_intake_pair',rejected=True))
    def test_forgery_rejected(self):
        class Proxy:
            def __init__(self,base,**overrides):self.base=base;self.overrides=overrides
            def __getattr__(self,k):return self.overrides[k] if k in self.overrides else getattr(self.base,k)
        for s in ('canonical','workflow'):
            native=read(CONTEXT['inputs']/CONTEXT['protocol']['inputs'][f'{s}-01-complete']['file']);old=(SelectionEngine if s=='canonical' else WorkflowFinalSelectionEngine).restore(native[3]);row=CONTEXT['rows'][f'{s}-01-complete'];engine=(CueCanonicalEngine if s=='canonical' else CueWorkflowEngine).restore(row[3]);w=loads(row[4])
            changes={'requests':[], 'native_sha256':'0'*64,'intake_sha256':'0'*64,'fresh_demand':{},'controller_prefix':'{}','content_inventory':(), 'recall':{},'execution_authorized':True,'comparison_paid':True,'td5_admitted':True,'history_choice':True,'full_future_role_domain':True}
            if s=='canonical':changes.pop('content_inventory')
            for k,v in changes.items():
                forged=copy.deepcopy(w);forged[k]=v
                with self.assertRaises(ValueError):audit_windows(old,native[4],dumps(forged))
                PROBES.append(dict(setting=s,field=k,rejected=True))
            forged=copy.deepcopy(w);forged['requests'][0]['stock']=w['fresh_demand']['binding']
            with self.assertRaises(ValueError):audit_windows(old,native[4],dumps(forged))
            PROBES.append(dict(setting=s,field='foreign_operand',rejected=True))
            original=tuple(engine.world.journal());start=len(tuple(old.world.journal()))
            for what in ('required','spent','policy','nominee'):
                txs=list(original);target=start if what!='nominee' else len(txs)-1;versions=list(txs[target].versions);changed=False
                for j,v in enumerate(versions):
                    d=attrs(v)
                    if what=='nominee' and v.ref.identity.namespace=='ftwc.result':
                        p=loads(d['payload']);p['windows'][0]['nominee']=999;d['payload']=dumps(p)
                    elif what in ('required','spent') and d.get('ftwc'):d[what]+=1
                    elif what=='policy' and d.get('ftwc'):d['policy']='forged'
                    else:continue
                    versions[j]=replace(v,attributes=attributes(d));changed=True;break
                self.assertTrue(changed);txs[target]=replace(txs[target],versions=tuple(versions));fake=Proxy(engine,world=Proxy(engine.world,journal=lambda:tuple(txs)))
                with self.assertRaises(ValueError):audit(fake,old,native[4],row[4])
                PROBES.append(dict(setting=s,field='native_'+what,rejected=True))
    def test_terminal_idempotence(self):
        for s in ('canonical','workflow'):
            for m in range(1,16):self.assertTrue(json.loads((CONTEXT['out']/'jobs'/f'generate-{s}-{m:02d}.outcome.json').read_text())['result']['terminal_idempotence'])
