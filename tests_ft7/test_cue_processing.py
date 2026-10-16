"""Saved actual native records; no completed paid job replay."""
import copy,gzip,json,unittest
from hle_unified import codec
from hle_unified.selection_records import loads,dumps
from full_theory.cue_comparison import CueCanonicalEngine,CueWorkflowEngine
from full_theory.cue_processing import CueProcessing
from full_theory.cue_processing_audit import audit
CONTEXT={};PROBES=[]
def read(p):return codec.loads(gzip.decompress(p.read_bytes()).decode())
class CueProcessingTests(unittest.TestCase):
    def test_complete_domain(self):
        for s in ('canonical','workflow'):
            a=CONTEXT['audits'][s+'-complete'];self.assertTrue(a['passed']);self.assertEqual((a['phase'],a['targets'],a['completed']),('complete',3,3));self.assertGreater(a['spent'],0);self.assertEqual(a['energy'],a['time']);self.assertEqual(len(a['intents']),3)
    def test_partial_ready(self):
        for s in ('canonical','workflow'):
            for stage in ('before','partial','ready'):
                a=CONTEXT['audits'][s+'-'+stage];self.assertEqual(a['completed'],0);self.assertEqual(a['phase'],'active')
            self.assertEqual(CONTEXT['audits'][s+'-before']['spent'],0);self.assertEqual(CONTEXT['audits'][s+'-partial']['spent'],1);self.assertGreater(CONTEXT['audits'][s+'-ready']['spent'],1)
            b=loads(CONTEXT['rows'][s+'-ready'][3]);self.assertEqual(b['results'],[]);self.assertEqual(b['events'][-1]['status'],'ready')
    def test_restart_exact(self):
        for s in ('canonical','workflow'):self.assertEqual(CONTEXT['rows'][s+'-restarted'][2:],CONTEXT['rows'][s+'-complete'][2:])
    def test_cancel_no_refund(self):
        for s in ('canonical','workflow'):
            a=CONTEXT['audits'][s+'-cancelled'];self.assertEqual((a['phase'],a['spent'],a['completed']),('cancelled',1,0));self.assertEqual(a['intents'],[])
    def test_scope_prefixes(self):
        for a in CONTEXT['audits'].values():
            self.assertTrue(a['source_prefix_exact']);self.assertTrue(a['reserve_history_unchanged'])
            for k in ('comparison_paid','execution_authorized','history_choice','clearance_claim','skill_acquired'):self.assertFalse(a[k])
    def test_wrong_input_rejected(self):
        for s,cls in (('canonical',CueCanonicalEngine),('workflow',CueWorkflowEngine)):
            source=read(CONTEXT['inputs']/CONTEXT['protocol']['inputs'][s]['file']);old=cls.restore(source[3]);bad=loads(source[4]);bad['fresh_demand']['cue']=bad['fresh_demand']['target']
            with self.assertRaises(ValueError):CueProcessing(old,dumps(bad))
            PROBES.append(dict(setting=s,field='wrong_source_windows',rejected=True))
            complete=CONTEXT['rows'][s+'-complete'];e=cls.restore(complete[2])
            with self.assertRaises(ValueError):CueProcessing(e,source[4])
            PROBES.append(dict(setting=s,field='changed_native_pair',rejected=True))
    def test_forgery_rejected(self):
        for s,cls in (('canonical',CueCanonicalEngine),('workflow',CueWorkflowEngine)):
            source=read(CONTEXT['inputs']/CONTEXT['protocol']['inputs'][s]['file']);old=cls.restore(source[3]);row=CONTEXT['rows'][s+'-complete'];e=cls.restore(row[2]);d=loads(row[3])
            changes={'plan':(), 'source_native_sha256':'0'*64,'source_windows_sha256':'0'*64,'expected_native_sha256':'0'*64,'controller_prefix':'{}','reserve':'{}','history':'{}','results':[],'index':0,'comparison_paid':True,'execution_authorized':True,'history_choice':True,'independent_credit':True,'clearance_claim':True,'skill_acquired':True}
            for k,v in changes.items():
                forged=copy.deepcopy(d);forged[k]=v
                with self.assertRaises(ValueError):audit(e,old,source[4],dumps(forged))
                PROBES.append(dict(setting=s,field=k,rejected=True))
            for k in ('debit','cursor_after','item'):
                forged=copy.deepcopy(d)
                if k=='debit':forged['events'][0]['debit']['energy']+=1
                elif k=='item':forged['events'][0]['item']+=1
                else:forged['events'][0]['cursor_after']='forged'
                with self.assertRaises(ValueError):audit(e,old,source[4],dumps(forged))
                PROBES.append(dict(setting=s,field=k,rejected=True))
    def test_terminal_idempotence(self):
        for s in ('canonical','workflow'):self.assertTrue(json.loads((CONTEXT['out']/'jobs'/('generate-'+s+'.outcome.json')).read_text())['result']['terminal_idempotence'])
