"""New panel tests on saved evidence; accepted v1 tests are not invoked."""
import copy, hashlib, json, unittest
from hle_unified.selection_records import loads,dumps
from full_theory.cue_comparison import CueCanonicalEngine,CueWorkflowEngine
from full_theory.cue_processing import CueProcessing
from full_theory.cue_processing_panel import CueProcessingPanel
from full_theory.cue_processing_panel_audit import audit,domain
from tools.evaluate_ft7_cue_comparison import read
CONTEXT={}; PROBES=[]
def typ(s): return CueCanonicalEngine if s=='canonical' else CueWorkflowEngine
class CueProcessingPanelTests(unittest.TestCase):
    def test_all_thirty_exact_sources(self):
        self.assertEqual(len(CONTEXT['protocol']['inputs']),30)
        for name,entry in CONTEXT['protocol']['inputs'].items():
            p=CONTEXT['inputs']/entry['file']; row=read(p)
            self.assertEqual(hashlib.sha256(p.read_bytes()).hexdigest(),entry['sha256'])
            self.assertEqual((row[0],row[1],row[2]),(name.split('-')[0],int(name.split('-')[1]),'complete'))
            self.assertEqual((hashlib.sha256(row[3].encode()).hexdigest(),hashlib.sha256(row[4].encode()).hexdigest()),(entry['native_sha256'],entry['windows_sha256']))
            if row[1]>1:
                d=loads(CONTEXT['rows'][name+'-complete'][4]); self.assertEqual((d['source_native_sha256'],d['source_windows_sha256'],d['source_mask']),(entry['native_sha256'],entry['windows_sha256'],row[1]))
    def test_all_native_target_domains(self):
        for s in ('canonical','workflow'):
            for m in range(2,16):
                n=f'{s}-{m:02d}-complete'; a=CONTEXT['audits'][n]; d=loads(CONTEXT['rows'][n][4]); source=read(CONTEXT['inputs']/CONTEXT['protocol']['inputs'][f'{s}-{m:02d}']['file']); e=typ(s).restore(source[3]); w=loads(source[4])
                self.assertEqual(d['plan'],domain(e.participant_view(w['actor']),w['actor'],w['fresh_demand']['context']))
                self.assertEqual((a['phase'],a['completed'],a['targets']),('complete',len(d['plan']),len(d['plan'])))
                self.assertGreater(a['targets'],0); self.assertEqual(len(a['intents']),a['targets'])
                self.assertTrue(all(r['status']=='succeeded' for r in d['results']))
    def test_partial_ready_no_result(self):
        for s in ('canonical','workflow'):
            for stage in ('before','partial','ready'):
                a=CONTEXT['audits'][s+'-02-'+stage]; d=loads(CONTEXT['rows'][s+'-02-'+stage][4]); self.assertEqual((a['completed'],a['phase'],d['results']),(0,'active',[]))
            self.assertEqual(CONTEXT['audits'][s+'-02-before']['spent'],0); self.assertEqual(CONTEXT['audits'][s+'-02-partial']['spent'],1)
            self.assertEqual(loads(CONTEXT['rows'][s+'-02-ready'][4])['events'][-1]['status'],'ready')
    def test_new_v2_restarts_and_cancellations(self):
        for s in ('canonical','workflow'):
            self.assertEqual(CONTEXT['rows'][s+'-02-restarted'][3:],CONTEXT['rows'][s+'-02-complete'][3:])
            a=CONTEXT['audits'][s+'-02-cancelled']; self.assertEqual((a['phase'],a['spent'],a['completed'],a['intents']),('cancelled',1,0,[]))
    def test_twelve_legacy_records_exact(self):
        self.assertEqual(len(CONTEXT['legacy']),12)
        for n,e in CONTEXT['protocol']['retained_a12d_records'].items():
            for sub,file,key in [('records',e['file'],'raw_sha256'),('audits',n+'.json','audit_sha256'),('jobs','audit-'+n+'.outcome.json','audit_outcome_sha256')]:
                self.assertEqual(hashlib.sha256((CONTEXT['out']/'legacy'/sub/file).read_bytes()).hexdigest(),e[key])
            self.assertEqual(len(read(CONTEXT['out']/'legacy/records'/e['file'])),4)
    def test_prefixes_native_payments_no_authority(self):
        for n,a in CONTEXT['audits'].items():
            d=loads(CONTEXT['rows'][n][4]); self.assertTrue(a['source_prefix_exact']); self.assertTrue(a['reserve_history_unchanged']); self.assertEqual(a['energy'],a['time'])
            self.assertEqual(a['spent'],sum(x['debit']['energy'] for x in d['events']))
            for k in ('comparison_paid','execution_authorized','td5_admitted','history_choice','independent_credit','clearance_claim','skill_acquired'): self.assertIs(d[k],False)
    def test_wrong_inputs_and_saved_forgeries(self):
        for s in ('canonical','workflow'):
            cls=typ(s); source=read(CONTEXT['inputs']/CONTEXT['protocol']['inputs'][s+'-02']['file']); old=cls.restore(source[3]); row=CONTEXT['rows'][s+'-02-complete']; e=cls.restore(row[3]); d=loads(row[4])
            one=read(CONTEXT['inputs']/CONTEXT['protocol']['inputs'][s+'-01']['file'])
            for native,windows in [(one[3],one[4]),(source[3],one[4]),(row[3],source[4])]:
                with self.assertRaises(ValueError): CueProcessingPanel(cls.restore(native),windows)
                PROBES.append(dict(setting=s,field='wrong_or_completed_input',rejected=True))
            changes={'source_mask':1,'version':'ft-owned-cue-processing-a12d-v1','plan':(),'source_native_sha256':'0'*64,'source_windows_sha256':'0'*64,'expected_native_sha256':'0'*64,'controller_prefix':'{}','reserve':'{}','history':'{}','results':[],'index':0,'comparison_paid':True,'execution_authorized':True,'td5_admitted':True,'history_choice':True,'independent_credit':True,'clearance_claim':True,'skill_acquired':True}
            for k,v in changes.items():
                forged=copy.deepcopy(d); forged[k]=v
                with self.assertRaises(ValueError): audit(e,old,source[4],dumps(forged))
                PROBES.append(dict(setting=s,field=k,rejected=True))
            for k in ('debit','cursor_after','item'):
                forged=copy.deepcopy(d)
                if k=='debit': forged['events'][0]['debit']['energy']+=1
                elif k=='item': forged['events'][0]['item']+=1
                else: forged['events'][0]['cursor_after']='forged'
                with self.assertRaises(ValueError): audit(e,old,source[4],dumps(forged))
                PROBES.append(dict(setting=s,field=k,rejected=True))
    def test_frozen_sources_and_terminal_idempotence(self):
        for name,h in CONTEXT['freeze'].items(): self.assertEqual(hashlib.sha256((CONTEXT['root']/name).read_bytes()).hexdigest(),h)
        for method in ('step','key','checkpoint'): self.assertIs(getattr(CueProcessingPanel,method),getattr(CueProcessing,method))
        jobs=[f'generate-{s}-{m:02d}' for s in ('canonical','workflow') for m in range(2,16)]+[f'control-{s}-02-{c}' for s in ('canonical','workflow') for c in ('restarted','cancelled')]
        for job in jobs: self.assertTrue(json.loads((CONTEXT['out']/'jobs'/(job+'.outcome.json')).read_text())['result']['terminal_idempotence'])
