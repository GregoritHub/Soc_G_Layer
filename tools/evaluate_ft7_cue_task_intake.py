"""Exclusive bounded A12B jobs; completed or interrupted jobs are never rerun."""
import argparse,gzip,hashlib,io,json,pathlib,sys,traceback,unittest,zipfile
from datetime import datetime,timezone
from hle_unified import codec
from hle_unified.selection_records import loads,dumps
from full_theory.cue_task_intake import CueTaskIntake
from full_theory.cue_task_intake_audit import audit_cue_task_intake
from full_theory.observed_cue_panel_audit import audit as audit_panel

ROOT=pathlib.Path(__file__).resolve().parents[1]
PREFIX='contracts/ft/FT7_Cue_Intake_A12B_'
STAGES=('before','read_partial','read_ready','read_complete','bind_partial','bind_ready','complete')
CONTROLS=('restart_read','restart_bind','cancel_read','cancel_bind')
def digest(b):return hashlib.sha256(b).hexdigest()
def expected_names():
    return tuple(f'{s}-01-{stage}' for s in ('canonical','workflow') for stage in STAGES)+tuple(f'{s}-{m:02d}-complete' for s in ('canonical','workflow') for m in range(2,16))+tuple(f'{s}-01-{c}' for s in ('canonical','workflow') for c in CONTROLS)
def read_record(path):return codec.loads(gzip.decompress(path.read_bytes()).decode())
def save_record(out,setting,mask,stage,engine,adapter):
    name=f'{setting}-{mask:02d}-{stage}';path=out/'records'/(name+'.json.gz')
    data=codec.dumps((setting,mask,stage,engine.checkpoint(),adapter.checkpoint(engine)))
    with path.open('xb') as f:f.write(gzip.compress(data.encode(),mtime=0))
    if codec.dumps(read_record(path))!=data:raise ValueError('typed raw roundtrip')
    return name
def engine_type(setting):
    from hle_unified.selection_execution import SelectionEngine
    from hle_unified.workflow_selection_execution import WorkflowFinalSelectionEngine
    return SelectionEngine if setting=='canonical' else WorkflowFinalSelectionEngine
def original(a,setting):
    with zipfile.ZipFile(a.archive) as z:
        r=codec.loads(gzip.decompress(z.read('ft71b2b3b2b1-attempt1/records/'+setting+'-live.json.gz')).decode())
    if r[0]!=setting+'/live':raise ValueError('original label')
    panel=(pathlib.Path(a.panels)/(setting+'-panel.json')).read_text()
    audit_panel(*r[1:4],setting,panel)
    return (*r[1:4],panel)
def main():
    p=argparse.ArgumentParser();p.add_argument('action',choices=('init','generate','control','audit','tests','finish'));p.add_argument('archive');p.add_argument('panels');p.add_argument('output')
    p.add_argument('--setting',choices=('canonical','workflow'));p.add_argument('--mask',type=int);p.add_argument('--control',choices=CONTROLS);p.add_argument('--record')
    p.add_argument('--public',required=True);p.add_argument('--owner',required=True);p.add_argument('--stop-at',required=True);a=p.parse_args()
    protocol=json.loads((ROOT/(PREFIX+'Protocol_v1.json')).read_text());freeze=json.loads((ROOT/(PREFIX+'Source_Freeze_v1.json')).read_text());prior=json.loads((ROOT/protocol['prior_source_freeze']).read_text())
    out=pathlib.Path(a.output)
    def verify(launch=False):
        state=json.loads((pathlib.Path(a.public)/'docs/FT_Run_State.json').read_text());now=datetime.now(timezone.utc)
        limit=min(datetime.fromisoformat(state['lease_expires_at']),datetime.fromisoformat(a.stop_at)) if state.get('lease_expires_at') else now
        if state['run_id']!=a.owner or not state['active_worker'] or state['status']!='running' or (limit-now).total_seconds() < (300 if launch else 0):raise ValueError('ownership/deadline')
        for mapping in (prior,freeze):
            for n,h in mapping.items():
                if digest((ROOT/n).read_bytes())!=h:raise ValueError('source '+n)
    verify(True)
    if a.action=='init':
        out.mkdir(exist_ok=False);(out/'jobs').mkdir();(out/'records').mkdir();(out/'audits').mkdir()
    if not (out/'jobs').is_dir():raise ValueError('init required')
    if a.action=='generate':
        if a.setting is None or a.mask not in range(1,16):raise ValueError('exact setting/mask')
        job=f'generate-{a.setting}-{a.mask:02d}'
    elif a.action=='control':
        if a.setting is None or a.control is None:raise ValueError('exact control')
        job=f'control-{a.setting}-{a.control}'
    elif a.action=='audit':
        if a.record not in expected_names():raise ValueError('exact record')
        job='audit-'+a.record
    else:job=a.action
    start=dict(job=job,owner=a.owner,started_at=datetime.now(timezone.utc).isoformat(),freeze=digest((ROOT/(PREFIX+'Source_Freeze_v1.json')).read_bytes()))
    with (out/'jobs'/(job+'.start.json')).open('x') as f:json.dump(start,f,indent=2)
    result=None;error=None
    try:
        if a.action=='init':
            archive=pathlib.Path(a.archive)
            if digest(archive.read_bytes())!=protocol['archive']['sha256']:raise ValueError('archive hash')
            with zipfile.ZipFile(archive) as z:
                manifest=json.loads(z.read('SHA256.json'))
                if len(manifest)!=protocol['archive']['members']:raise ValueError('manifest count')
                for n,h in manifest.items():
                    if digest(z.read(n))!=h:raise ValueError('archive member '+n)
            panels={s:digest(original(a,s)[3].encode()) for s in ('canonical','workflow')}
            result=dict(passed=True,archive_members=len(manifest),panels=panels,source_identities=len(freeze),prior_identities=len(prior),expected_records=expected_names())
        else:
            init=json.loads((out/'jobs/init.outcome.json').read_text())
            if not init['passed']:raise ValueError('init did not pass')
            if a.action in ('generate','control','audit'):
                setting=a.setting if a.action!='audit' else a.record.split('-')[0]
                native,source,binding,panel=original(a,setting)
                if digest(panel.encode())!=init['result']['panels'][setting]:raise ValueError('changed saved panel')
                typ=engine_type(setting)
            if a.action=='generate':
                engine=typ.restore(native);adapter=CueTaskIntake(engine,source,binding,panel,a.mask);names=[]
                if a.mask==1:
                    names.append(save_record(out,setting,1,'before',engine,adapter))
                    plan=(('read_partial',dict()),('read_ready',dict(commit_ready=False)),('read_complete',dict()),
                          ('bind_partial',dict()),('bind_ready',dict(work_limit=2,commit_ready=False)),('complete',dict()))
                    for stage,kw in plan:
                        verify();adapter.step(engine,**kw);names.append(save_record(out,setting,1,stage,engine,adapter))
                else:
                    adapter.step(engine,work_limit=2);verify();adapter.step(engine,work_limit=3);names.append(save_record(out,setting,a.mask,'complete',engine,adapter))
                if adapter.receipt is None:raise ValueError('primary intake did not settle')
                result=dict(passed=True,records=names,native_cost=adapter.receipt['energy'])
            elif a.action=='control':
                stage='read_partial' if a.control.endswith('read') else 'bind_partial'
                row=read_record(out/'records'/f'{setting}-01-{stage}.json.gz')
                engine=typ.restore(row[3]);old=typ.restore(native)
                adapter=CueTaskIntake.restore(row[4],engine,old,source,binding,panel);verify()
                if a.control.startswith('cancel'):adapter.step(engine,cancel=True)
                else:
                    sequence=([dict(commit_ready=False),dict(),dict()] if stage=='read_partial' else [])+[dict(work_limit=2,commit_ready=False),dict()]
                    for kw in sequence:verify();adapter.step(engine,**kw)
                name=save_record(out,setting,1,a.control,engine,adapter)
                if a.control.startswith('restart'):
                    terminal=read_record(out/'records'/f'{setting}-01-complete.json.gz')
                    if (engine.checkpoint(),adapter.checkpoint(engine))!=terminal[3:5]:raise ValueError('restart differs')
                result=dict(passed=True,records=[name],cancelled=adapter.cancelled)
            elif a.action=='audit':
                path=out/'records'/(a.record+'.json.gz');row=read_record(path)
                if f'{row[0]}-{row[1]:02d}-{row[2]}'!=a.record:raise ValueError('record label')
                engine=typ.restore(row[3]);old=typ.restore(native);verify()
                result=audit_cue_task_intake(engine,old,source,binding,panel,row[4])
                if codec.dumps(row)!=codec.dumps(read_record(path)):raise ValueError('raw changed')
                result.update(record=a.record,record_sha256=digest(path.read_bytes()))
                with (out/'audits'/(a.record+'.json')).open('x') as f:json.dump(result,f,indent=2)
            elif a.action in ('tests','finish'):
                rows={};audits={}
                for name in expected_names():
                    row=read_record(out/'records'/(name+'.json.gz'));audit=json.loads((out/'audits'/(name+'.json')).read_text());outcome=json.loads((out/'jobs'/('audit-'+name+'.outcome.json')).read_text())
                    if not audit['passed'] or not outcome['passed'] or audit['record_sha256']!=digest((out/'records'/(name+'.json.gz')).read_bytes()):raise ValueError('missing exact closed audit '+name)
                    rows[name]=row;audits[name]=audit
                if a.action=='tests':
                    from tests_ft7 import test_cue_task_intake as tests
                    tests.CONTEXT.update(rows=rows,audits=audits,inputs={s:original(a,s) for s in ('canonical','workflow')})
                    suite=unittest.defaultTestLoader.loadTestsFromTestCase(tests.CueTaskIntakeTests);names=[t._testMethodName for t in suite]
                    if sorted(names)!=sorted(protocol['methods']):raise ValueError('exact methods')
                    log=io.StringIO();r=unittest.TextTestRunner(stream=log,verbosity=2).run(suite);(out/'tests.log').write_text(log.getvalue())
                    result=dict(passed=r.wasSuccessful(),methods=names,failures=len(r.failures),errors=len(r.errors))
                    if not r.wasSuccessful():raise ValueError('test failures')
                else:
                    test=json.loads((out/'jobs/tests.outcome.json').read_text())
                    if not test['passed']:raise ValueError('tests did not pass')
                    result=dict(passed=True,records=len(rows),methods=test['result']['methods'],source_identities=len(freeze),prior_identities=len(prior),accepted_replays=0,comparison_paid=False,execution_authorized=False,td5_admitted=False,history_choice=False)
                    with (out/'summary.json').open('x') as f:json.dump(result,f,indent=2)
        verify()
    except BaseException as e:
        error=traceback.format_exc();print(error,file=sys.stderr)
    outcome=dict(**start,ended_at=datetime.now(timezone.utc).isoformat(),passed=error is None,result=result,error=error)
    with (out/'jobs'/(job+'.outcome.json')).open('x') as f:json.dump(outcome,f,indent=2)
    print(json.dumps(outcome));return 0 if error is None else 1

if __name__=='__main__':sys.exit(main())
