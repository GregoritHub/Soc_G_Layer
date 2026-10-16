"""Conditional exact A3 deadline continuation; original paid outputs are immutable."""
import argparse,gc,gzip,hashlib,json,pathlib,shutil,unittest
from datetime import datetime,timezone
from hle_unified import codec
from hle_unified.selection_records import dumps,loads
from full_theory.paid_window_comparison import PaidCanonicalWindowEngine,PaidWorkflowWindowEngine
from full_theory.owned_material_refresh import OwnedMaterialRefresh
from full_theory.owned_material_refresh_audit import audit_owned_material_refresh,baseline
from tools.audit_owned_repair_practice_saved import SavedNative

def sha(b):return hashlib.sha256(b).hexdigest()
def raw(p):return codec.loads(gzip.decompress(p.read_bytes()).decode())
def run():
    p=argparse.ArgumentParser()
    for name in ('inputs','prior','prior_ops','output','operations'):p.add_argument(name)
    p.add_argument('--owner',required=True);p.add_argument('--public',required=True);p.add_argument('--stop-at',required=True)
    a=p.parse_args();root=pathlib.Path(__file__).resolve().parents[1]
    prior=pathlib.Path(a.prior);prior_ops=pathlib.Path(a.prior_ops);out=pathlib.Path(a.output);ops=pathlib.Path(a.operations)
    out.mkdir(exist_ok=False);ops.mkdir(exist_ok=False)
    protocol=json.loads((root/'contracts/ft/FT7_Skill_Refresh_A3_Protocol_v1.json').read_text())
    binding=json.loads((root/'contracts/ft/FT7_Skill_Refresh_A3_Continuation1_Binding_v1.json').read_text())
    freeze=json.loads((root/'contracts/ft/FT7_Skill_Refresh_A3_Continuation1_Source_Freeze_v1.json').read_text())
    original_freeze=json.loads((root/'contracts/ft/FT7_Skill_Refresh_A3_Source_Freeze_v1.json').read_text())
    stage='initial'
    def note(kind,**fields):
        with (ops/'events.jsonl').open('a') as f:f.write(json.dumps(dict(at=datetime.now(timezone.utc).isoformat(),stage=stage,kind=kind,**fields))+'\n');f.flush()
    def verify():
        for n,h in {**original_freeze,**freeze}.items():
            if sha((root/n).read_bytes())!=h:raise ValueError('source identity: '+n)
        for folder,key in ((prior,'prior'),(prior_ops,'prior_ops')):
            actual={str(f.relative_to(folder)):sha(f.read_bytes()) for f in folder.rglob('*') if f.is_file()}
            if actual!=binding[key]:raise ValueError('closed original changed: '+key)
    def guard():
        now=datetime.now(timezone.utc);s=json.loads((pathlib.Path(a.public)/'docs/FT_Run_State.json').read_text())
        if s['run_id']!=a.owner or s['status']!='running' or not s['active_worker'] or now>=datetime.fromisoformat(s['lease_expires_at']) or now>=datetime.fromisoformat(a.stop_at):
            note('operational_stop');raise SystemExit('continuation owner/lease/deadline checkpoint guard')
    def durable(engine,b,label):
        native,text=engine.checkpoint(),b.checkpoint(engine);tmp=ops/'current.pending.gz'
        with gzip.open(tmp,'wt',compresslevel=1) as f:f.write(codec.dumps((stage,label,native,text)))
        tmp.replace(ops/'current.json.gz')
        note('durable',label=label,phase=b.phase,events=len(b.events),sha256=sha((ops/'current.json.gz').read_bytes()))
        return native,text
    try:
        verify();guard();events=[json.loads(x) for x in (prior_ops/'events.jsonl').read_text().splitlines()]
        last=events[-1]
        if last['kind']!='closed_nonpass' or last.get('error_type')!='SystemExit' or 'owner/lease/deadline checkpoint guard' not in last.get('message',''):
            raise ValueError('only registered operational stop may continue')
        if any(x['kind']=='methods_start' for x in events) or (prior/'summary.json').exists():
            raise ValueError('original method invocation or completion forbids continuation')
        rows=json.loads((prior/'progress.json').read_text())
        if len({r['file'] for r in rows})!=len(rows):raise ValueError('duplicate original records')
        if {f.name for f in prior.glob('*.json.gz')}!={r['file'] for r in rows}:raise ValueError('unclosed original raw record')
        for r in rows:
            if sha((prior/r['file']).read_bytes())!=r['sha256']:raise ValueError('original raw identity')
        for f in prior.iterdir():
            if f.is_file():shutil.copyfile(f,out/f.name)
        probes=json.loads((out/'probes.json').read_text()) if (out/'probes.json').exists() else []
        curstage,curlabel,curnative,curtext=raw(prior_ops/'current.json.gz')
        note('start',copied=len(binding['prior']),records=len(rows),probes=len(probes),owner=a.owner)
        def has(s,n):return any(r['setting']==s and r['record']==n for r in rows)
        for setting,typ in (('canonical',PaidCanonicalWindowEngine),('workflow',PaidWorkflowWindowEngine)):
            entry=protocol['inputs'][setting];source=pathlib.Path(a.inputs)/entry['file']
            if sha(source.read_bytes())!=entry['sha256']:raise ValueError('accepted A2 raw input')
            label,original,practice=raw(source)
            if label!='complete' or sha(original.encode())!=entry['native_sha256'] or sha(practice.encode())!=entry['practice_sha256']:raise ValueError('accepted A2 pairing')
            def save(name,engine,b):
                if has(setting,name):raise ValueError('completed record must not be regenerated')
                native,text=durable(engine,b,name);filename=setting+'-'+name+'.json.gz'
                with gzip.open(out/filename,'wt') as f:f.write(codec.dumps((name,native,text)))
                note('raw_saved_before_audit',file=filename,sha256=sha((out/filename).read_bytes()))
                result=audit_owned_material_refresh(engine,original,practice,text)
                if raw(out/filename)!=(name,native,text) or dumps(loads(text))!=text:raise ValueError('typed raw roundtrip')
                row=dict(setting=setting,record=name,file=filename,sha256=sha((out/filename).read_bytes()),**result)
                rows.append(row);(out/'progress.json').write_text(json.dumps(rows,indent=2)+'\n')
                note('record_passed',record=name);print(json.dumps(row),flush=True)
            if not has(setting,'complete'):
                stage=setting+'/main';guard();note('restore_start')
                if curstage==stage:
                    engine=typ.restore(curnative);b=OwnedMaterialRefresh.restore(curtext,engine,original,practice)
                else:
                    if has(setting,'before'):raise ValueError('missing current durable main')
                    engine=typ.restore(original);b=OwnedMaterialRefresh(engine,practice);save('before',engine,b)
                durable(engine,b,'resume-before')
                for turn in range(4096):
                    if b.phase=='complete':break
                    guard();e=b.step(engine,work_limit=1);durable(engine,b,'step')
                    if e['status']=='partial' and not has(setting,e['phase']+'-partial'):save(e['phase']+'-partial',engine,b)
                else:raise ValueError('main step bound')
                save('complete',engine,b);final=(engine.checkpoint(),b.checkpoint(engine));b.step(engine);b.step(engine,cancel=True)
                if (engine.checkpoint(),b.checkpoint(engine))!=final:raise ValueError('terminal idempotence')
                del engine,b;baseline.cache_clear();gc.collect()
            # Only absent, unpersisted read-only probes; no original method body replay.
            stage=setting+'/saved-probes';guard()
            _,native,text=raw(out/(setting+'-before.json.gz'));facade=SavedNative(native,typ)
            for field,value in (('actor','forged'),('context',None),('unregistered_extra',True)):
                for api in ('constructor','auditor'):
                    if any(r.get('api')==api and r['setting']==setting and r['field']==field for r in probes):continue
                    bad=loads(practice);bad[field]=value
                    try:
                        if api=='constructor':OwnedMaterialRefresh(facade,dumps(bad))
                        else:audit_owned_material_refresh(facade,original,dumps(bad),text)
                    except ValueError as error:
                        if 'exact accepted practice identity' not in str(error):raise
                        probes.append(dict(setting=setting,field=field,api=api,rejected=True))
                    else:raise ValueError('pair forgery accepted')
            if not facade.unchanged():raise ValueError('saved probe mutation')
            del facade;baseline.cache_clear();gc.collect()
            _,native,text=raw(out/(setting+'-complete.json.gz'));final=(native,text);facade=SavedNative(native,typ)
            for field,value in (('plan',()),('source_native_sha256','0'*64),('receipts',[]),('main_execution_authorized',True),('payment',None)):
                if any('api' not in r and r['setting']==setting and r['field']==field for r in probes):continue
                bad=loads(text)
                if field=='payment':bad['events'][0]['debit']['energy']+=1
                else:bad[field]=value
                try:audit_owned_material_refresh(facade,original,practice,dumps(bad))
                except ValueError:probes.append(dict(setting=setting,field=field,rejected=True))
                else:raise ValueError('saved forgery accepted')
            if not facade.unchanged():raise ValueError('saved probe mutation')
            (out/'probes.json').write_text(json.dumps(probes,indent=2)+'\n')
            del facade;baseline.cache_clear();gc.collect()
            if not has(setting,'restarted'):
                stage=setting+'/restart';guard();note('restore_start')
                if curstage==stage:native,text=curnative,curtext
                else:_,native,text=raw(out/(setting+'-read-partial.json.gz'))
                engine=typ.restore(native);b=OwnedMaterialRefresh.restore(text,engine,original,practice);durable(engine,b,'restart-before')
                for turn in range(4096):
                    if b.phase=='complete':break
                    guard();b.step(engine,work_limit=1);durable(engine,b,'restart-step')
                else:raise ValueError('restart step bound')
                if (engine.checkpoint(),b.checkpoint(engine))!=final:raise ValueError('exact restart pair')
                save('restarted',engine,b);del engine,b;baseline.cache_clear();gc.collect()
            else:
                _,n,t=raw(out/(setting+'-restarted.json.gz'))
                if (n,t)!=final:raise ValueError('preserved restart pair')
            if not has(setting,'cancelled'):
                stage=setting+'/cancel';guard();note('restore_start')
                if curstage==stage:native,text=curnative,curtext
                else:_,native,text=raw(out/(setting+'-inspect-partial.json.gz'))
                engine=typ.restore(native);b=OwnedMaterialRefresh.restore(text,engine,original,practice)
                guard()
                if b.phase!='cancelled':b.step(engine,cancel=True)
                save('cancelled',engine,b);del engine,b;baseline.cache_clear();gc.collect()
        stage='six_methods';guard();note('methods_start')
        import tests_ft7.test_owned_material_refresh as tests
        tests.RESULTS=rows;tests.PROBES=probes
        # Original JSON rows normalize tuples; test compares values consistently.
        tests.RESULTS=json.loads(json.dumps(rows))
        with (out/'tests.log').open('w') as f:result=unittest.TextTestRunner(stream=f,verbosity=2).run(unittest.defaultTestLoader.loadTestsFromModule(tests))
        note('methods_finished',count=result.testsRun,passed=result.wasSuccessful())
        if not result.wasSuccessful() or result.testsRun!=6:raise ValueError('six unchanged methods required')
        verify()
        summary=dict(passed=True,methods=6,records=rows,probes=probes,source_identities=len(original_freeze),
                     continuation_identities=len(freeze),prior_identities=449,copied_original_records=len(json.loads((prior/'progress.json').read_text())),
                     main_execution_authorized=False,history_choice=False,parent_accepted=False)
        (out/'summary.json').write_text(json.dumps(summary,indent=2)+'\n');note('closed_pass');print(json.dumps(summary),flush=True)
    except BaseException as error:
        note('closed_nonpass',error_type=type(error).__name__,message=str(error));raise

if __name__=='__main__':run()
