"""Exclusive A12D2 jobs; exact legacy proofs retained, no accepted replay."""
import argparse, gzip, hashlib, json, pathlib, traceback, unittest, zipfile
from datetime import datetime, timezone
from hle_unified import codec
from hle_unified.selection_records import loads
from full_theory.cue_comparison import CueCanonicalEngine, CueWorkflowEngine
from full_theory.cue_processing_panel import CueProcessingPanel
from full_theory.cue_processing_panel_audit import audit
from tools.evaluate_ft7_cue_comparison import write, js, read
ROOT=pathlib.Path(__file__).resolve().parents[1]
PREFIX='contracts/ft/FT7_Cue_Processing_Panel_A12D2_'
def sha(b): return hashlib.sha256(b).hexdigest()
def typ(s): return CueCanonicalEngine if s=='canonical' else CueWorkflowEngine
def names():
    return tuple(f'{s}-{m:02d}-complete' for s in ('canonical','workflow') for m in range(2,16))+tuple(f'{s}-02-{t}' for s in ('canonical','workflow') for t in ('before','partial','ready','restarted','cancelled'))
def persist(out,name,payload,folder):
    data=codec.dumps(payload); raw=gzip.compress(data.encode(),mtime=0)
    path=out/folder/(name+'.json.gz'); write(path,raw); write(out/(folder+'-backup')/path.name,raw)
    if codec.dumps(read(path))!=data: raise ValueError('typed persistence mismatch')
    return path
def save(out,s,m,stage,e,b):
    name=f'{s}-{m:02d}-{stage}'; path=persist(out,name,(s,m,stage,e.checkpoint(),b.checkpoint(e)),'records')
    js(out/'identities'/(name+'.json'),dict(sha256=sha(path.read_bytes()),typed_exact=True,backup_exact=True))
    return name
def durable(out,label,e,b):
    persist(out,label+f'-{len(b.events):03d}',(b.setting,b.source_mask,len(b.events),e.checkpoint(),b.checkpoint(e)),'durable')
def verify_archive(path,entry):
    if sha(path.read_bytes())!=entry['sha256']: raise ValueError('archive identity')
    z=zipfile.ZipFile(path); manifest=json.loads(z.read('SHA256.json'))
    if len(manifest)!=entry['members']: raise ValueError('archive count')
    for n,h in manifest.items():
        if sha(z.read(n))!=h: raise ValueError('archive member '+n)
    return z
def retained(out,protocol):
    reports={}
    for n,entry in protocol['retained_a12d_records'].items():
        raw=(out/'legacy/records'/entry['file']).read_bytes(); ar=(out/'legacy/audits'/(n+'.json')).read_bytes(); closed=(out/'legacy/jobs'/('audit-'+n+'.outcome.json')).read_bytes()
        if (sha(raw),sha(ar),sha(closed))!=(entry['raw_sha256'],entry['audit_sha256'],entry['audit_outcome_sha256']): raise ValueError('legacy bytes changed')
        report=json.loads(ar); outcome=json.loads(closed); row=codec.loads(gzip.decompress(raw).decode())
        if len(row)!=4 or row[0]!=n.split('-')[0] or row[1]!=n.split('-')[1] or not report['passed'] or not outcome['passed'] or outcome['result']!=report or report['record_sha256']!=sha(raw): raise ValueError('legacy exact accepted binding')
        if loads(row[3])['version']!=entry['version']: raise ValueError('legacy schema')
        reports[n]=report
    return reports
def main():
    p=argparse.ArgumentParser(); p.add_argument('action',choices=('init','generate','control','audit','tests','finish')); p.add_argument('inputs'); p.add_argument('output')
    p.add_argument('--archives',required=True); p.add_argument('--legacy',required=True); p.add_argument('--setting',choices=('canonical','workflow')); p.add_argument('--mask',type=int); p.add_argument('--control',choices=('restarted','cancelled')); p.add_argument('--record'); p.add_argument('--public',required=True); p.add_argument('--owner',required=True); p.add_argument('--stop-at',required=True)
    a=p.parse_args(); out=pathlib.Path(a.output); protocol=json.loads((ROOT/(PREFIX+'Protocol_v1.json')).read_text()); freeze=json.loads((ROOT/(PREFIX+'Source_Freeze_v1.json')).read_text()); prior=json.loads((ROOT/protocol['prior_source_freeze']).read_text())
    def guard(launch=False):
        state=json.loads((pathlib.Path(a.public)/'docs/FT_Run_State.json').read_text()); now=datetime.now(timezone.utc)
        limit=min(datetime.fromisoformat(state['lease_expires_at']),datetime.fromisoformat(a.stop_at)) if state.get('lease_expires_at') else now
        if state['run_id']!=a.owner or not state['active_worker'] or state['status']!='running' or (limit-now).total_seconds()<(300 if launch else 0): raise ValueError('ownership/deadline')
        for mapping in (prior,freeze):
            for n,h in mapping.items():
                if sha((ROOT/n).read_bytes())!=h: raise ValueError('source '+n)
    guard(True)
    if a.action=='init': out.mkdir(exist_ok=False); (out/'jobs').mkdir()
    if not (out/'jobs').is_dir(): raise ValueError('init required')
    if a.action=='generate':
        if a.setting is None or a.mask not in range(2,16): raise ValueError('only unprocessed fixed panel')
        job=f'generate-{a.setting}-{a.mask:02d}'
    elif a.action=='control':
        if a.setting is None or a.control is None: raise ValueError('fixed mask2 control')
        job=f'control-{a.setting}-02-{a.control}'
    elif a.action=='audit':
        if a.record not in names(): raise ValueError('new records only')
        job='audit-'+a.record
    else: job=a.action
    js(out/'jobs'/(job+'.start.json'),dict(job=job,owner=a.owner,started=datetime.now(timezone.utc).isoformat(),freeze=sha((ROOT/(PREFIX+'Source_Freeze_v1.json')).read_bytes())))
    try:
        if a.action=='init':
            for tag,entry in protocol['accepted_sources'].items():
                with verify_archive(pathlib.Path(a.archives)/entry['filename'],entry) as z:
                    if tag=='a12c':
                        for n,e in protocol['inputs'].items():
                            path=pathlib.Path(a.inputs)/e['file']; raw=path.read_bytes(); row=read(path)
                            if raw!=z.read('attempt1/records/'+e['file']) or sha(raw)!=e['sha256'] or row[:3]!=(n.split('-')[0],int(n.split('-')[1]),'complete') or (sha(row[3].encode()),sha(row[4].encode()))!=(e['native_sha256'],e['windows_sha256']): raise ValueError('exact A12C input')
                    else:
                        for n,e in protocol['retained_a12d_records'].items():
                            for sub,file in [('records',e['file']),('audits',n+'.json'),('jobs','audit-'+n+'.outcome.json')]:
                                data=(pathlib.Path(a.legacy)/sub/file).read_bytes()
                                if data!=z.read('attempt1/'+sub+'/'+file): raise ValueError('exact legacy archive member')
                                write(out/'legacy'/sub/file,data)
                        for file in ('tests.outcome.json','finish.outcome.json'):
                            data=(pathlib.Path(a.legacy)/'jobs'/file).read_bytes()
                            if data!=z.read('attempt1/jobs/'+file) or not json.loads(data)['passed']: raise ValueError('legacy acceptance')
                            write(out/'legacy/jobs'/file,data)
            reports=retained(out,protocol); result=dict(passed=True,inputs=30,retained=len(reports),prior_identities=len(prior),source_identities=len(freeze))
        else:
            if not json.loads((out/'jobs/init.outcome.json').read_text())['passed']: raise ValueError('init gate')
            if a.action in ('generate','control','audit'):
                s=a.setting if a.action!='audit' else a.record.split('-')[0]; m=a.mask if a.action=='generate' else (int(a.record.split('-')[1]) if a.action=='audit' else 2)
                entry=protocol['inputs'][f'{s}-{m:02d}']; path=pathlib.Path(a.inputs)/entry['file']
                if sha(path.read_bytes())!=entry['sha256']: raise ValueError('input changed')
                source=read(path); native,windows=source[3:5]
            def step(e,b,label,**kw):
                b.step(e,**kw); durable(out,label,e,b); guard()
            def complete(e,b,label):
                if b.phase=='active' and b.index==0:
                    step(e,b,label,work_limit=10**7,commit_ready=False); step(e,b,label)
                for turn in range(32):
                    if b.phase!='active': break
                    step(e,b,label,work_limit=10**7)
                else: raise ValueError('finite domain')
            def terminal(e,b):
                pair=(e.checkpoint(),b.checkpoint(e)); b.step(e); b.step(e,cancel=True)
                if pair!=(e.checkpoint(),b.checkpoint(e)): raise ValueError('terminal idempotence')
            if a.action=='generate':
                e=typ(s).restore(native); b=CueProcessingPanel(e,windows); saved=[]; label=f'{s}-{m:02d}'
                if not b.plan: raise ValueError('empty registered domain')
                if m==2: saved.append(save(out,s,m,'before',e,b))
                step(e,b,label,work_limit=1)
                if m==2: saved.append(save(out,s,m,'partial',e,b))
                step(e,b,label,work_limit=10**7,commit_ready=False)
                if m==2: saved.append(save(out,s,m,'ready',e,b))
                step(e,b,label)
                complete(e,b,label); saved.append(save(out,s,m,'complete',e,b)); terminal(e,b)
                if b.phase!='complete': raise ValueError('honest failure preserved; gate not met')
                result=dict(passed=True,records=saved,terminal_idempotence=True,targets=len(b.plan),completed=b.index,energy=sum(x['debit']['energy'] for x in b.events),time=sum(x['debit']['time'] for x in b.events),cursor=e._cursors[b.actor],intents=[x['intent'] for x in b.results])
            elif a.action=='control':
                row=read(out/'records'/(s+'-02-partial.json.gz')); e=typ(s).restore(row[3]); old=typ(s).restore(native); b=CueProcessingPanel.restore(row[4],e,old,windows); guard(); label=f'{s}-02-{a.control}'
                if a.control=='cancelled': step(e,b,label,cancel=True)
                else: complete(e,b,label)
                saved=save(out,s,m,a.control,e,b); terminal(e,b)
                if a.control=='restarted' and (e.checkpoint(),b.checkpoint(e))!=read(out/'records'/(s+'-02-complete.json.gz'))[3:5]: raise ValueError('restart mismatch')
                result=dict(passed=True,records=[saved],terminal_idempotence=True,restart_exact=a.control=='restarted')
            elif a.action=='audit':
                path=out/'records'/(a.record+'.json.gz'); row=read(path)
                if row[:3]!=(s,m,a.record.split('-')[2]): raise ValueError('raw scope')
                e=typ(s).restore(row[3]); old=typ(s).restore(native); guard(); result=audit(e,old,windows,row[4]); result.update(record=a.record,record_sha256=sha(path.read_bytes())); js(out/'audits'/(a.record+'.json'),result)
            elif a.action=='tests':
                import tests_ft7.test_cue_processing_panel as tests
                tests.CONTEXT.update(rows={n:read(out/'records'/(n+'.json.gz')) for n in names()},audits={n:json.loads((out/'audits'/(n+'.json')).read_text()) for n in names()},legacy=retained(out,protocol),protocol=protocol,inputs=pathlib.Path(a.inputs),out=out,root=ROOT,freeze=freeze)
                suite=unittest.defaultTestLoader.loadTestsFromTestCase(tests.CueProcessingPanelTests); methods=[t._testMethodName for t in suite]
                if sorted(methods)!=sorted(protocol['methods']): raise ValueError('exact new method inventory')
                with (out/'tests.log').open('x') as log: checked=unittest.TextTestRunner(stream=log,verbosity=2).run(suite)
                result=dict(passed=checked.wasSuccessful(),methods=methods,probes=tests.PROBES,failures=len(checked.failures),errors=len(checked.errors))
                if not checked.wasSuccessful(): raise ValueError('new methods failed')
            else:
                methods=json.loads((out/'jobs/tests.outcome.json').read_text()); reports=[]; legacy=retained(out,protocol)
                if not methods['passed']: raise ValueError('methods required')
                for n in names():
                    path=out/'records'/(n+'.json.gz'); report=json.loads((out/'audits'/(n+'.json')).read_text()); closed=json.loads((out/'jobs'/('audit-'+n+'.outcome.json')).read_text())
                    if not closed['passed'] or report!=closed['result'] or report['record_sha256']!=sha(path.read_bytes()) or path.read_bytes()!=(out/'records-backup'/path.name).read_bytes(): raise ValueError('new exact binding')
                    reports.append(report)
                starts=list((out/'jobs').glob('*.start.json'))
                if len(starts)!=73 or list((out/'jobs').glob('*.failure.json')): raise ValueError('all registered exclusive jobs')
                for start in starts:
                    if start.name=='finish.start.json': continue
                    if not json.loads(start.with_name(start.name.replace('.start.','.outcome.')).read_text())['passed']: raise ValueError('closed job required')
                result=dict(passed=True,records=50,new_audits=38,retained_audits=12,methods=methods['result']['methods'],probes=methods['result']['probes'],reports=reports,legacy_reports=legacy,source_identities=len(freeze),prior_identities=len(prior),accepted_stage_replays=0,comparison_paid=False,execution_authorized=False,history_choice=False,parent_accepted=False,ft8_unchanged=True); js(out/'summary.json',result)
        guard(); js(out/'jobs'/(job+'.outcome.json'),dict(passed=True,ended=datetime.now(timezone.utc).isoformat(),result=result)); print(json.dumps(dict(job=job,passed=True)),flush=True)
    except BaseException as error:
        js(out/'jobs'/(job+'.failure.json'),dict(error_type=type(error).__name__,message=str(error),traceback=traceback.format_exc(),ended=datetime.now(timezone.utc).isoformat())); raise
if __name__=='__main__': main()
