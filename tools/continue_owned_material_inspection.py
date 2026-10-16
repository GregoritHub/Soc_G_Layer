"""Durable continuation of only the unfinished workflow inspection controls."""
import argparse,gc,gzip,hashlib,json,pathlib,shutil,unittest,zipfile
from datetime import datetime,timezone
from hle_unified import codec
from hle_unified.selection_records import dumps,loads
from full_theory.paid_window_comparison import PaidWorkflowWindowEngine
from full_theory.owned_material_inspection import OwnedMaterialInspection
from full_theory.owned_material_inspection_audit import audit_owned_material_inspection,baseline


def sha(b):return hashlib.sha256(b).hexdigest()


def run():
    p=argparse.ArgumentParser();p.add_argument('archive');p.add_argument('paid');p.add_argument('capacity')
    p.add_argument('original');p.add_argument('output');p.add_argument('operations')
    p.add_argument('--owner',required=True);p.add_argument('--public',required=True);p.add_argument('--stop-at',required=True);a=p.parse_args()
    root=pathlib.Path(__file__).resolve().parents[1];old=pathlib.Path(a.original);out=pathlib.Path(a.output);ops=pathlib.Path(a.operations)
    out.mkdir(exist_ok=False);ops.mkdir(exist_ok=False)
    protocol=json.loads((root/'contracts/ft/FT7_Skill_Intake_A1_Continuation1_Protocol_v1.json').read_text())
    freeze=json.loads((root/'contracts/ft/FT7_Skill_Intake_A1_Continuation1_Source_Freeze_v1.json').read_text())
    stage='initial';serial=0
    def note(kind,**data):
        row=dict(at=datetime.now(timezone.utc).isoformat(),stage=stage,kind=kind,**data)
        with (ops/'events.jsonl').open('a') as f:f.write(json.dumps(row,sort_keys=True)+'\n');f.flush()
    def verify():
        for n,h in freeze.items():
            if sha((root/n).read_bytes())!=h:raise ValueError('frozen identity differs: '+n)
    def guard():
        st=json.loads((pathlib.Path(a.public)/'docs/FT_Run_State.json').read_text());now=datetime.now(timezone.utc)
        if st['run_id']!=a.owner or not st['active_worker'] or st['status']!='running' or now>=datetime.fromisoformat(st['lease_expires_at']) or now>=datetime.fromisoformat(a.stop_at):
            note('operational_stop',last_checkpoint=(ops/'current.json.gz').exists());raise SystemExit('continuation checkpoint guard')
    def durable(e,b,label):
        nonlocal serial
        pair=(e.checkpoint(),b.checkpoint(e));tmp=ops/'current.pending.gz'
        with gzip.open(tmp,'wt',compresslevel=1) as f:f.write(codec.dumps((label,*pair)))
        tmp.replace(ops/'current.json.gz');serial+=1
        note('durable_checkpoint',serial=serial,label=label,sha256=sha((ops/'current.json.gz').read_bytes()),phase=b.phase,event_count=len(b.events))
        return pair
    def read(name):
        with gzip.open(old/('workflow-'+name+'.json.gz'),'rt') as f:
            label,native,text=codec.loads(f.read())
        if label!=name:raise ValueError('saved label')
        return native,text
    try:
        verify();guard();note('start',owner=a.owner,paid_main_replayed=False)
        if set(p.name for p in old.iterdir() if p.is_file())!=set(protocol['input_files']):raise ValueError('original directory membership differs')
        for n,h in protocol['input_files'].items():
            if sha((old/n).read_bytes())!=h:raise ValueError('original input differs: '+n)
        rows=json.loads((old/'progress.json').read_text())
        if len(rows)!=10 or any(not x['passed'] for x in rows):raise ValueError('exact ten passing records')
        for row in rows:
            shutil.copy2(old/row['file'],out/row['file'])
            if sha((out/row['file']).read_bytes())!=row['sha256']:raise ValueError('copied record differs')
        (out/'progress.json').write_text(json.dumps(rows,indent=2)+'\n')
        if sha(pathlib.Path(a.archive).read_bytes())!='4ece02f685fb7df900523bc64983e83e19f3d636994b90bf796f5a1282dca71b':raise ValueError('accepted archive')
        with zipfile.ZipFile(a.archive) as z:
            for n,h in json.loads(z.read('SHA256.json')).items():
                if sha(z.read(n))!=h:raise ValueError('accepted manifest')
            pe=next(x for x in json.loads(z.read('current-window-admission-final2/paid_index.json')) if x['key']=='workflow/mask-1')
            ce=next(x for x in json.loads(z.read('current-window-admission-final2/capacity_index.json')) if x['key']=='workflow/mask-1')
        pr=(pathlib.Path(a.paid)/pe['file']).read_bytes();cr=(pathlib.Path(a.capacity)/ce['file']).read_bytes()
        if sha(pr)!=pe['sha256'] or sha(cr)!=ce['sha256'] or ce['input_sha256']!=pe['sha256']:raise ValueError('raw input pairing')
        prow=codec.loads(gzip.decompress(pr).decode());crow=codec.loads(gzip.decompress(cr).decode())
        if prow[0]!='workflow/mask-1' or crow[0]!=prow[0] or crow[1]!=pe['sha256']:raise ValueError('typed input pairing')
        original=prow[1];capacity=crow[2]
        def save(name,e,b):
            native,text=durable(e,b,name);filename='workflow-'+name+'.json.gz';payload=codec.dumps((name,native,text))
            with gzip.open(out/filename,'wt') as f:f.write(payload)
            note('raw_saved_before_audit',file=filename,sha256=sha((out/filename).read_bytes()))
            audit=audit_owned_material_inspection(e,original,capacity,text)
            with gzip.open(out/filename,'rt') as f:
                if codec.loads(f.read())!=(name,native,text):raise ValueError('raw readback')
            if dumps(loads(text))!=text:raise ValueError('typed roundtrip')
            result=dict(setting='workflow',record=name,file=filename,sha256=sha((out/filename).read_bytes()),**audit)
            rows.append(result);(out/'progress.json').write_text(json.dumps(rows,indent=2)+'\n');note('record_passed',record=name);print(json.dumps(result),flush=True)
        stage='workflow_restart';guard();note('restore_start',source='workflow-read-partial.json.gz')
        native,text=read('read-partial');engine=PaidWorkflowWindowEngine.restore(native)
        adapter=OwnedMaterialInspection.restore(text,engine,original,capacity);durable(engine,adapter,'restart-before');guard()
        for turn in range(768):
            guard();adapter.step(engine,work_limit=1);durable(engine,adapter,'restart-step')
            if adapter.phase=='complete':break
        else:raise ValueError('original restart bound')
        final=read('complete')
        if (engine.checkpoint(),adapter.checkpoint(engine))!=final:raise ValueError('original main and restarted pair differ')
        adapter.step(engine);adapter.step(engine,cancel=True)
        if (engine.checkpoint(),adapter.checkpoint(engine))!=final:raise ValueError('terminal not idempotent')
        save('restarted',engine,adapter)
        for field,value in (('main_execution_authorized',True),('source_native_sha256','0'*64),('plan',())):
            bad=loads(adapter.checkpoint(engine));bad[field]=value
            try:audit_owned_material_inspection(engine,original,capacity,dumps(bad))
            except ValueError:note('original_forgery_rejected',field=field)
            else:raise ValueError('forgery accepted: '+field)
        del engine,adapter,final;baseline.cache_clear();gc.collect()
        stage='workflow_cancel';guard();note('restore_start',source='workflow-inspect-partial.json.gz')
        native,text=read('inspect-partial');engine=PaidWorkflowWindowEngine.restore(native)
        adapter=OwnedMaterialInspection.restore(text,engine,original,capacity);durable(engine,adapter,'cancel-before');guard()
        adapter.step(engine,cancel=True);save('cancelled',engine,adapter)
        del engine,adapter;baseline.cache_clear();gc.collect()
        stage='original_six_methods';guard();note('methods_start')
        import tests_ft7.test_owned_material_inspection as tests
        tests.RESULTS=rows
        with (out/'tests.log').open('w') as f:result=unittest.TextTestRunner(stream=f,verbosity=2).run(unittest.defaultTestLoader.loadTestsFromModule(tests))
        note('methods_finished',count=result.testsRun,passed=result.wasSuccessful())
        if not result.wasSuccessful() or result.testsRun!=6:raise ValueError('original six methods required')
        verify();summary=dict(passed=True,methods=6,records=rows,source_identities=len(freeze),prior_identities=423,
            original_records_copied_exact=10,new_records=2,paid_main_replayed=False,original_interruption_preserved=True,
            skill_acquired=False,main_execution_authorized=False,history_choice=False,parent_accepted=False)
        (out/'summary.json').write_text(json.dumps(summary,indent=2)+'\n');note('closed_pass');print(json.dumps(summary),flush=True)
    except BaseException as error:
        note('closed_nonpass',error_type=type(error).__name__,message=str(error));raise


if __name__=='__main__':run()
