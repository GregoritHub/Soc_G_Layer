"""Exclusive finite A12C jobs with atomic raw persistence before validation."""
import argparse,gzip,hashlib,json,os,pathlib,traceback,unittest,zipfile
from datetime import datetime,timezone
from hle_unified import codec
from hle_unified.selection_records import loads,dumps
from hle_unified.selection_execution import SelectionEngine
from hle_unified.workflow_selection_execution import WorkflowFinalSelectionEngine
from full_theory.cue_comparison import prepare,step_window_comparison,CueCanonicalEngine,CueWorkflowEngine
from full_theory.cue_comparison_audit import audit
ROOT=pathlib.Path(__file__).resolve().parents[1]
PREFIX='contracts/ft/FT7_Cue_Comparison_A12C_'
STAGES=('before','partial','ready','complete')
CONTROLS=('restarted','cancelled')
def digest(b):return hashlib.sha256(b).hexdigest()
def typ(setting):return CueCanonicalEngine if setting=='canonical' else CueWorkflowEngine
def baseline(setting):return SelectionEngine if setting=='canonical' else WorkflowFinalSelectionEngine
def names():return tuple(f'{s}-01-{stage}' for s in ('canonical','workflow') for stage in STAGES)+tuple(f'{s}-{m:02d}-complete' for s in ('canonical','workflow') for m in range(2,16))+tuple(f'{s}-01-{c}' for s in ('canonical','workflow') for c in CONTROLS)
def read(path):return codec.loads(gzip.decompress(path.read_bytes()).decode())
def write(path,data):
    path.parent.mkdir(parents=True,exist_ok=True);temp=path.with_name(path.name+'.pending')
    with temp.open('xb') as f:f.write(data);f.flush();os.fsync(f.fileno())
    os.link(temp,path);temp.unlink();fd=os.open(path.parent,os.O_RDONLY)
    try:os.fsync(fd)
    finally:os.close(fd)
    if path.read_bytes()!=data:raise ValueError('byte readback')
def js(path,value):write(path,(json.dumps(value,indent=2)+'\n').encode())
def save(out,setting,mask,stage,engine,windows):
    name=f'{setting}-{mask:02d}-{stage}';data=codec.dumps((setting,mask,stage,engine.checkpoint(),windows));raw=gzip.compress(data.encode(),mtime=0)
    path=out/'records'/(name+'.json.gz');write(path,raw);write(out/'backup'/(name+'.json.gz'),raw)
    if codec.dumps(read(path))!=data:raise ValueError('typed readback')
    js(out/'identities'/(name+'.json'),dict(sha256=digest(raw),bytes=len(raw),native_sha256=digest(engine.checkpoint().encode()),backup_exact=True,typed_exact=True))
    return name

def main():
    p=argparse.ArgumentParser();p.add_argument('action',choices=('init','generate','control','audit','tests','finish'));p.add_argument('inputs');p.add_argument('output');p.add_argument('--archive',required=True)
    p.add_argument('--setting',choices=('canonical','workflow'));p.add_argument('--mask',type=int);p.add_argument('--control',choices=CONTROLS);p.add_argument('--record');p.add_argument('--public',required=True);p.add_argument('--owner',required=True);p.add_argument('--stop-at',required=True);a=p.parse_args()
    protocol=json.loads((ROOT/(PREFIX+'Protocol_v1.json')).read_text());freeze=json.loads((ROOT/(PREFIX+'Source_Freeze_v1.json')).read_text());prior=json.loads((ROOT/protocol['prior_source_freeze']).read_text());out=pathlib.Path(a.output)
    def guard(launch=False):
        state=json.loads((pathlib.Path(a.public)/'docs/FT_Run_State.json').read_text());now=datetime.now(timezone.utc)
        limit=min(datetime.fromisoformat(state['lease_expires_at']),datetime.fromisoformat(a.stop_at)) if state.get('lease_expires_at') else now
        if state['run_id']!=a.owner or not state['active_worker'] or state['status']!='running' or (limit-now).total_seconds()<(300 if launch else 0):raise ValueError('ownership/deadline')
        for mapping in (prior,freeze):
            for n,h in mapping.items():
                if digest((ROOT/n).read_bytes())!=h:raise ValueError('source identity '+n)
    guard(True)
    if a.action=='init':out.mkdir(exist_ok=False);(out/'jobs').mkdir()
    if not (out/'jobs').is_dir():raise ValueError('init required')
    if a.action=='generate':
        if a.setting is None or a.mask not in range(1,16):raise ValueError('fixed setting/mask')
        job=f'generate-{a.setting}-{a.mask:02d}'
    elif a.action=='control':
        if a.setting is None or a.control is None:raise ValueError('exact saved control')
        job=f'control-{a.setting}-{a.control}'
    elif a.action=='audit':
        if a.record not in names():raise ValueError('exact record')
        job='audit-'+a.record
    else:job=a.action
    js(out/'jobs'/(job+'.start.json'),dict(job=job,owner=a.owner,started=datetime.now(timezone.utc).isoformat(),source_freeze=digest((ROOT/(PREFIX+'Source_Freeze_v1.json')).read_bytes())))
    try:
        result=None
        if a.action=='init':
            archive=pathlib.Path(a.archive);entry=protocol['accepted_input_archive']
            if digest(archive.read_bytes())!=entry['sha256']:raise ValueError('accepted archive identity')
            with zipfile.ZipFile(archive) as z:
                manifest=json.loads(z.read('SHA256.json'))
                if len(manifest)!=entry['members']:raise ValueError('manifest count')
                for n,h in manifest.items():
                    if digest(z.read(n))!=h:raise ValueError('archive member '+n)
                for n,e in protocol['inputs'].items():
                    raw=(pathlib.Path(a.inputs)/e['file']).read_bytes();auditraw=(pathlib.Path(a.inputs)/'audits'/(n+'.json')).read_bytes()
                    if raw!=z.read(e['file']) or digest(raw)!=e['sha256'] or auditraw!=z.read('audits/'+n+'.json') or digest(auditraw)!=e['audit_sha256'] or not json.loads(auditraw)['passed']:raise ValueError('accepted exact record/audit')
                    row=read(pathlib.Path(a.inputs)/e['file'])
                    if digest(row[3].encode())!=e['native_sha256'] or digest(row[4].encode())!=e['intake_sha256']:raise ValueError('accepted paired source')
            result=dict(passed=True,archive_members=len(manifest),accepted_inputs=30,source_identities=len(freeze),prior_identities=len(prior),expected_records=len(names()))
        else:
            if not json.loads((out/'jobs/init.outcome.json').read_text())['passed']:raise ValueError('init gate')
            if a.action in ('generate','control','audit'):
                setting=a.setting if a.action!='audit' else a.record.split('-')[0];mask=a.mask if a.action=='generate' else (int(a.record.split('-')[1]) if a.action=='audit' else 1)
                e=protocol['inputs'][f'{setting}-{mask:02d}-complete'];path=pathlib.Path(a.inputs)/e['file']
                if digest(path.read_bytes())!=e['sha256']:raise ValueError('input changed')
                original=read(path);native,intake=original[3:5]
            if a.action=='generate':
                old=baseline(setting).restore(native);engine,request=prepare(old,intake);windows=request.windows;key=request.key;actor=loads(windows)['actor'];saved=[]
                if mask==1:
                    saved.append(save(out,setting,mask,'before',engine,windows))
                    step_window_comparison(engine,request,work_limit=1,settle=False);saved.append(save(out,setting,mask,'partial',engine,windows));guard()
                    step_window_comparison(engine,request,work_limit=10**7,settle=False);saved.append(save(out,setting,mask,'ready',engine,windows))
                step_window_comparison(engine,request,work_limit=10**7);guard();saved.append(save(out,setting,mask,'complete',engine,windows))
                pair=engine.checkpoint();step_window_comparison(engine,request);step_window_comparison(engine,request,settle=False)
                if pair!=engine.checkpoint():raise ValueError('terminal idempotence')
                status=engine.job_status(actor,key)
                if status['status']!='succeeded' or engine.window_result(actor,key) is None:raise ValueError('full comparison settlement')
                result=dict(passed=True,records=saved,cost=status['spent'],required=status['required'],windows=len(loads(windows)['requests']),terminal_idempotence=True)
            elif a.action=='control':
                saved=read(out/'records'/f'{setting}-01-partial.json.gz');engine=typ(setting).restore(saved[3]);windows=saved[4];actor=loads(windows)['actor'];key='ft-cue-comparison:'+digest(windows.encode());request=engine._window_comparisons[actor,key][0]
                if a.control=='cancelled':engine.cancel(key+':cancel',actor,key)
                else:step_window_comparison(engine,request,work_limit=10**7)
                name=save(out,setting,1,a.control,engine,windows)
                if a.control=='restarted':
                    complete=read(out/'records'/f'{setting}-01-complete.json.gz')
                    if saved[4]!=complete[4] or engine.checkpoint()!=complete[3]:raise ValueError('exact restored native pair')
                result=dict(passed=True,records=[name],restart_exact=a.control=='restarted')
            elif a.action=='audit':
                row=read(out/'records'/(a.record+'.json.gz'));engine=typ(setting).restore(row[3]);old=baseline(setting).restore(native);guard()
                result=audit(engine,old,intake,row[4]);result.update(record=a.record,record_sha256=digest((out/'records'/(a.record+'.json.gz')).read_bytes()))
                js(out/'audits'/(a.record+'.json'),result)
            elif a.action=='tests':
                rows={n:read(out/'records'/(n+'.json.gz')) for n in names()};audits={n:json.loads((out/'audits'/(n+'.json')).read_text()) for n in names()}
                import tests_ft7.test_cue_comparison as tests
                tests.CONTEXT.update(rows=rows,audits=audits,inputs=pathlib.Path(a.inputs),protocol=protocol,out=out)
                suite=unittest.defaultTestLoader.loadTestsFromTestCase(tests.CueComparisonTests);methods=[t._testMethodName for t in suite]
                if sorted(methods)!=sorted(protocol['methods']):raise ValueError('unchanged method inventory')
                with (out/'tests.log').open('x') as log:checked=unittest.TextTestRunner(stream=log,verbosity=2).run(suite)
                result=dict(passed=checked.wasSuccessful(),methods=methods,forgery_probes=tests.PROBES,failures=len(checked.failures),errors=len(checked.errors))
                if not checked.wasSuccessful():raise ValueError('required original A12C methods failed; preserve log')
            else:
                tests=json.loads((out/'jobs/tests.outcome.json').read_text());reports=[]
                if not tests['passed']:raise ValueError('all actual methods required')
                for n in names():
                    closed=json.loads((out/'jobs'/('audit-'+n+'.outcome.json')).read_text());report=json.loads((out/'audits'/(n+'.json')).read_text())
                    if not closed['passed'] or closed['result']!=report or report['record_sha256']!=digest((out/'records'/(n+'.json.gz')).read_bytes()):raise ValueError('exact independently audited record binding')
                    reports.append(report)
                result=dict(passed=True,records=len(reports),independent_audits=len(reports),methods=tests['result']['methods'],forgery_probes=tests['result']['forgery_probes'],source_identities=len(freeze),prior_identities=len(prior),reports=reports,comparison_paid=True,execution_authorized=False,td5_admitted=False,history_choice=False,full_future_role_domain=False,parent_accepted=False,ft8_unchanged=True,accepted_stage_replays=0)
                js(out/'summary.json',result)
        guard();js(out/'jobs'/(job+'.outcome.json'),dict(passed=True,ended=datetime.now(timezone.utc).isoformat(),result=result));print(json.dumps(dict(job=job,passed=True)),flush=True)
    except BaseException as error:
        js(out/'jobs'/(job+'.failure.json'),dict(error_type=type(error).__name__,message=str(error),traceback=traceback.format_exc(),ended=datetime.now(timezone.utc).isoformat()))
        raise
if __name__=='__main__':main()
