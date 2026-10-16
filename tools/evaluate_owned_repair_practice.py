"""Serial bounded paid practice gate with durable per-step checkpoints."""
import argparse,gc,gzip,hashlib,json,pathlib,unittest
from datetime import datetime,timezone
from hle_unified import codec
from hle_unified.selection_records import dumps,loads
from full_theory.paid_window_comparison import PaidCanonicalWindowEngine,PaidWorkflowWindowEngine
from full_theory.owned_repair_practice import OwnedRepairPractice
from full_theory.owned_repair_practice_audit import audit_owned_repair_practice,baseline


def sha(b):return hashlib.sha256(b).hexdigest()


def run():
    p=argparse.ArgumentParser();p.add_argument('inputs');p.add_argument('output');p.add_argument('operations')
    p.add_argument('--owner',required=True);p.add_argument('--public',required=True);p.add_argument('--stop-at',required=True);a=p.parse_args()
    root=pathlib.Path(__file__).resolve().parents[1];out=pathlib.Path(a.output);ops=pathlib.Path(a.operations)
    out.mkdir(exist_ok=False);ops.mkdir(exist_ok=False)
    protocol=json.loads((root/'contracts/ft/FT7_Skill_Practice_A2_Protocol_v1.json').read_text())
    freeze=json.loads((root/'contracts/ft/FT7_Skill_Practice_A2_Source_Freeze_v1.json').read_text())
    rows=[];probes=[];stage='initial';serial=0
    def note(kind,**fields):
        with (ops/'events.jsonl').open('a') as f:
            f.write(json.dumps(dict(at=datetime.now(timezone.utc).isoformat(),stage=stage,kind=kind,**fields))+'\n');f.flush()
    def verify():
        for name,h in freeze.items():
            if sha((root/name).read_bytes())!=h:raise ValueError('frozen identity differs: '+name)
    def guard():
        now=datetime.now(timezone.utc);s=json.loads((pathlib.Path(a.public)/'docs/FT_Run_State.json').read_text())
        if s['run_id']!=a.owner or not s['active_worker'] or s['status']!='running' or now>=datetime.fromisoformat(s['lease_expires_at']) or now>=datetime.fromisoformat(a.stop_at):
            note('operational_stop');raise SystemExit('owner/lease/deadline checkpoint guard')
    def durable(engine,b,label):
        nonlocal serial
        pair=(engine.checkpoint(),b.checkpoint(engine));tmp=ops/'current.pending.gz'
        with gzip.open(tmp,'wt',compresslevel=1) as f:f.write(codec.dumps((stage,label,*pair)))
        tmp.replace(ops/'current.json.gz');serial+=1
        note('durable',serial=serial,label=label,sha256=sha((ops/'current.json.gz').read_bytes()),phase=b.phase,events=len(b.events))
        return pair
    try:
        verify();guard();note('start',owner=a.owner)
        for setting,typ in (('canonical',PaidCanonicalWindowEngine),('workflow',PaidWorkflowWindowEngine)):
            stage=setting+'/main';guard();entry=protocol['inputs'][setting]
            raw=(pathlib.Path(a.inputs)/entry['file']).read_bytes()
            if sha(raw)!=entry['sha256']:raise ValueError('exact accepted complete input')
            label,original,intake=codec.loads(gzip.decompress(raw).decode())
            if label!='complete' or sha(original.encode())!=entry['native_sha256']:raise ValueError('input native pairing')
            note('restore_start');print('restoring '+setting,flush=True);engine=typ.restore(original)
            guard();b=OwnedRepairPractice(engine,intake);saved={}
            def save(name):
                native,text=durable(engine,b,name);filename=setting+'-'+name+'.json.gz';payload=codec.dumps((name,native,text))
                with gzip.open(out/filename,'wt') as f:f.write(payload)
                note('raw_saved_before_audit',file=filename,sha256=sha((out/filename).read_bytes()))
                result=audit_owned_repair_practice(engine,original,intake,text)
                with gzip.open(out/filename,'rt') as f:
                    if codec.loads(f.read())!=(name,native,text):raise ValueError('raw roundtrip')
                if dumps(loads(text))!=text:raise ValueError('typed adapter roundtrip')
                row=dict(setting=setting,record=name,file=filename,sha256=sha((out/filename).read_bytes()),**result)
                rows.append(row);saved[name]=(native,text)
                (out/'progress.json').write_text(json.dumps(rows,indent=2)+'\n');note('record_passed',record=name);print(json.dumps(row),flush=True)
            save('before')
            for turn in range(4096):
                guard();event=b.step(engine,work_limit=1);durable(engine,b,'step')
                if event is not None and event['status']=='partial':
                    name=event['phase']+'-partial'
                    if name not in saved:save(name)
                if b.phase in ('complete','exhausted'):break
            else:raise ValueError('finite step bound')
            save('complete')
            if not b.skill_acquired:raise ValueError('required new native skill not acquired; keep honest exhausted record')
            final=(engine.checkpoint(),b.checkpoint(engine));b.step(engine);b.step(engine,cancel=True)
            if final!=(engine.checkpoint(),b.checkpoint(engine)):raise ValueError('terminal not idempotent')
            for field,value in (('plan',()),('source_native_sha256','0'*64),('skill_acquired',False),('main_execution_authorized',True)):
                forged=loads(b.checkpoint(engine));forged[field]=value
                try:audit_owned_repair_practice(engine,original,intake,dumps(forged))
                except ValueError:probes.append(dict(setting=setting,field=field,rejected=True))
                else:raise ValueError('forgery accepted: '+field)
            forged=loads(b.checkpoint(engine));forged['events'][0]['debit']['energy']+=1
            try:audit_owned_repair_practice(engine,original,intake,dumps(forged))
            except ValueError:probes.append(dict(setting=setting,field='payment',rejected=True))
            else:raise ValueError('payment forgery accepted')
            (out/'probes.json').write_text(json.dumps(probes,indent=2)+'\n')
            del engine,b;baseline.cache_clear();gc.collect();stage=setting+'/restart';guard();note('restore_start')
            native,text=saved['acquire-partial'];engine=typ.restore(native);b=OwnedRepairPractice.restore(text,engine,original,intake)
            durable(engine,b,'restart-before')
            for turn in range(4096):
                guard();b.step(engine,work_limit=1);durable(engine,b,'restart-step')
                if b.phase=='complete':break
            else:raise ValueError('restart step bound')
            if (engine.checkpoint(),b.checkpoint(engine))!=final:raise ValueError('restart pair differs')
            save('restarted');del engine,b;baseline.cache_clear();gc.collect()
            stage=setting+'/cancel';guard();note('restore_start')
            native,text=saved['practice-partial'];engine=typ.restore(native);b=OwnedRepairPractice.restore(text,engine,original,intake)
            guard();b.step(engine,cancel=True);save('cancelled');del engine,b,saved,final;baseline.cache_clear();gc.collect()
        stage='six_methods';guard();note('methods_start')
        import tests_ft7.test_owned_repair_practice as tests
        tests.RESULTS=rows;tests.PROBES=probes
        with (out/'tests.log').open('w') as f:result=unittest.TextTestRunner(stream=f,verbosity=2).run(unittest.defaultTestLoader.loadTestsFromModule(tests))
        note('methods_finished',count=result.testsRun,passed=result.wasSuccessful())
        if not result.wasSuccessful() or result.testsRun!=6:raise ValueError('six exact methods required')
        verify();summary=dict(passed=True,methods=6,records=rows,probes=probes,source_identities=len(freeze),prior_identities=427,
            main_execution_authorized=False,history_choice=False,parent_accepted=False)
        (out/'summary.json').write_text(json.dumps(summary,indent=2)+'\n');note('closed_pass');print(json.dumps(summary),flush=True)
    except BaseException as error:
        note('closed_nonpass',error_type=type(error).__name__,message=str(error));raise


if __name__=='__main__':run()
