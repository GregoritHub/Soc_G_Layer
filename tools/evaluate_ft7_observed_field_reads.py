"""A5 serial paid-read gate, with durable pre-audit records and bounded ownership."""
import argparse,gc,gzip,hashlib,json,pathlib,unittest
from datetime import datetime,timezone
from hle_unified import codec
from hle_unified.selection_records import dumps,loads
from full_theory.paid_window_comparison import PaidCanonicalWindowEngine,PaidWorkflowWindowEngine
from full_theory.observed_field_reads import ObservedFieldReads
from full_theory.observed_field_reads_audit import audit_observed_field_reads,baseline


def sha(value): return hashlib.sha256(value.encode() if isinstance(value,str) else value).hexdigest()


def run():
    p=argparse.ArgumentParser();p.add_argument('inputs');p.add_argument('projections');p.add_argument('output');p.add_argument('operations')
    p.add_argument('--owner',required=True);p.add_argument('--public',required=True);p.add_argument('--stop-at',required=True);a=p.parse_args()
    root=pathlib.Path(__file__).resolve().parents[1];out=pathlib.Path(a.output);ops=pathlib.Path(a.operations)
    out.mkdir(exist_ok=False);ops.mkdir(exist_ok=False)
    protocol=json.loads((root/'contracts/ft/FT7_Observed_Fields_A5_Protocol_v1.json').read_text())
    freeze=json.loads((root/'contracts/ft/FT7_Observed_Fields_A5_Source_Freeze_v1.json').read_text())
    rows=[];probes=[];controls=[];stage='initial';serial=0
    def note(kind,**fields):
        with (ops/'events.jsonl').open('a') as f:
            f.write(json.dumps(dict(at=datetime.now(timezone.utc).isoformat(),stage=stage,kind=kind,**fields))+'\n');f.flush()
    def verify():
        for name,h in freeze.items():
            if sha((root/name).read_bytes())!=h:raise ValueError('source identity changed: '+name)
    def guard():
        now=datetime.now(timezone.utc);s=json.loads((pathlib.Path(a.public)/'docs/FT_Run_State.json').read_text())
        if s['run_id']!=a.owner or not s['active_worker'] or s['status']!='running' or now>=datetime.fromisoformat(s['lease_expires_at']) or now>=datetime.fromisoformat(a.stop_at):
            note('operational_stop');raise SystemExit('owner/lease/deadline guard')
    def durable(engine,b,label):
        nonlocal serial
        pair=(engine.checkpoint(),b.checkpoint(engine));tmp=ops/'current.pending.gz'
        with gzip.open(tmp,'wt',compresslevel=1) as f:f.write(codec.dumps((stage,label,*pair)))
        tmp.replace(ops/'current.json.gz');serial+=1
        note('durable',serial=serial,label=label,sha256=sha((ops/'current.json.gz').read_bytes()),phase=b.phase,events=len(b.events))
        return pair
    def reject(name,call):
        try:call()
        except ValueError:probes.append(dict(setting=setting,name=name,rejected=True))
        else:raise ValueError('accepted forgery: '+name)
    try:
        verify();guard();note('start',owner=a.owner)
        for setting,typ in (('canonical',PaidCanonicalWindowEngine),('workflow',PaidWorkflowWindowEngine)):
            stage=setting+'/main';guard();entry=protocol['inputs'][setting]
            raw=(pathlib.Path(a.inputs)/entry['file']).read_bytes()
            if sha(raw)!=entry['sha256']:raise ValueError('accepted input raw identity')
            label,original,refresh=codec.loads(gzip.decompress(raw).decode())
            projection=gzip.decompress((pathlib.Path(a.projections)/(setting+'-complete.json.gz')).read_bytes()).decode()
            if label!='complete' or any(sha(t)!=entry[k] for t,k in ((original,'native_sha256'),(refresh,'refresh_sha256'),(projection,'projection_sha256'))):
                raise ValueError('input pairing')
            note('restore_start');print('restoring '+setting,flush=True);engine=typ.restore(original)
            guard();b=ObservedFieldReads(engine,refresh,projection,setting);saved={}
            def save(name):
                native,text=durable(engine,b,name);filename=setting+'-'+name+'.json.gz'
                with gzip.open(out/filename,'wt') as f:f.write(codec.dumps((name,native,text)))
                note('raw_saved_before_audit',file=filename,sha256=sha((out/filename).read_bytes()))
                result=audit_observed_field_reads(engine,original,refresh,projection,setting,text)
                with gzip.open(out/filename,'rt') as f:
                    if codec.loads(f.read())!=(name,native,text):raise ValueError('saved raw roundtrip')
                if dumps(loads(text))!=text:raise ValueError('typed adapter roundtrip')
                row=dict(setting=setting,record=name,file=filename,sha256=sha((out/filename).read_bytes()),**result)
                rows.append(row);saved[name]=(native,text)
                (out/'progress.json').write_text(json.dumps(rows,indent=2)+'\n');note('record_passed',record=name);print(json.dumps(row),flush=True)
            save('before')
            altered=loads(refresh);altered['actor']='forged';bad_refresh=dumps(altered)
            altered=loads(projection);altered['execution_authorized']=True;bad_projection=dumps(altered)
            reject('refresh_pair_constructor',lambda:ObservedFieldReads(engine,bad_refresh,projection,setting))
            reject('projection_pair_constructor',lambda:ObservedFieldReads(engine,refresh,bad_projection,setting))
            reject('refresh_pair_auditor',lambda:audit_observed_field_reads(engine,original,bad_refresh,projection,setting,b.checkpoint(engine)))
            reject('projection_pair_auditor',lambda:audit_observed_field_reads(engine,original,refresh,bad_projection,setting,b.checkpoint(engine)))
            for turn in range(256):
                guard();b.step(engine,work_limit=1);durable(engine,b,'step')
                if 'partial' not in saved and b.events[-1]['status']=='partial':save('partial')
                if b.phase=='complete':break
            else:raise ValueError('finite read step bound')
            save('complete');final=(engine.checkpoint(),b.checkpoint(engine))
            b.step(engine);b.step(engine,cancel=True)
            if final!=(engine.checkpoint(),b.checkpoint(engine)):raise ValueError('terminal idempotence')
            controls.append(dict(setting=setting,name='terminal',exact=True))
            for name in ('plan','source','receipts','authority','payment','selector_path'):
                bad=loads(b.checkpoint(engine))
                if name=='plan':bad['plan']=()
                elif name=='source':bad['source_native_sha256']='0'*64
                elif name=='receipts':bad['receipts']=[]
                elif name=='authority':bad['main_execution_authorized']=True
                elif name=='payment':bad['events'][0]['debit']['energy']+=1
                else:
                    row=bad['plan'][0];key,cat,path=row['selectors'][0]
                    row['selectors']=((key,cat,('unknown','path')),)+row['selectors'][1:]
                reject(name,lambda bad=bad:audit_observed_field_reads(engine,original,refresh,projection,setting,dumps(bad)))
            (out/'probes.json').write_text(json.dumps(probes,indent=2)+'\n')
            del engine,b;baseline.cache_clear();gc.collect();stage=setting+'/restart';guard();note('restore_start')
            native,text=saved['partial'];engine=typ.restore(native)
            b=ObservedFieldReads.restore(text,engine,original,refresh,projection,setting);durable(engine,b,'restart-before')
            for turn in range(256):
                guard();b.step(engine,work_limit=1);durable(engine,b,'restart-step')
                if b.phase=='complete':break
            else:raise ValueError('finite restart bound')
            if (engine.checkpoint(),b.checkpoint(engine))!=final:raise ValueError('restart pair differs')
            controls.append(dict(setting=setting,name='restart',exact=True));save('restarted')
            del engine,b;baseline.cache_clear();gc.collect();stage=setting+'/cancel';guard();note('restore_start')
            native,text=saved['partial'];engine=typ.restore(native)
            b=ObservedFieldReads.restore(text,engine,original,refresh,projection,setting)
            guard();b.step(engine,cancel=True);save('cancelled')
            terminal=(engine.checkpoint(),b.checkpoint(engine));b.step(engine)
            if terminal!=(engine.checkpoint(),b.checkpoint(engine)):raise ValueError('cancel terminal mutation')
            del engine,b,saved,final;baseline.cache_clear();gc.collect()
        (out/'controls.json').write_text(json.dumps(controls,indent=2)+'\n')
        stage='methods';guard();note('methods_start')
        import tests_ft7.test_observed_field_reads as tests
        tests.RESULTS=rows;tests.PROBES=probes;tests.CONTROLS=controls
        suite=unittest.defaultTestLoader.loadTestsFromModule(tests)
        actual=[]
        for group in suite:
            for test in group:actual.append(test._testMethodName)
        if sorted(actual)!=sorted(protocol['methods']):raise ValueError('exact method identity set')
        with (out/'tests.log').open('w') as f:result=unittest.TextTestRunner(stream=f,verbosity=2).run(suite)
        note('methods_finished',count=result.testsRun,passed=result.wasSuccessful())
        if result.testsRun!=6 or not result.wasSuccessful():raise ValueError('six exact methods required')
        verify();summary=dict(passed=True,methods=actual,records=rows,probes=probes,controls=controls,
            source_identities=len(freeze),prior_identities=468,main_execution_authorized=False,comparison_paid=False,
            td5_admitted=False,history_choice=False,parent_accepted=False)
        (out/'summary.json').write_text(json.dumps(summary,indent=2)+'\n');note('closed_pass');print('A5 passed',flush=True)
    except BaseException as error:
        note('closed_nonpass',error_type=type(error).__name__,message=str(error));raise


if __name__=='__main__':run()
