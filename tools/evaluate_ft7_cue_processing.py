"""Finite exclusive A12D jobs; no prior accepted paid work is repeated."""
import argparse,gzip,hashlib,json,pathlib,traceback,unittest,zipfile
from datetime import datetime,timezone
from hle_unified import codec
from hle_unified.selection_records import loads,dumps
from full_theory.cue_processing import CueProcessing
from full_theory.cue_processing_audit import audit
from full_theory.cue_comparison import CueCanonicalEngine,CueWorkflowEngine
from tools.evaluate_ft7_cue_comparison import write,js,read
ROOT=pathlib.Path(__file__).resolve().parents[1];PREFIX='contracts/ft/FT7_Cue_Processing_A12D_'
STAGES=('before','partial','ready','complete','restarted','cancelled')
def sha(b):return hashlib.sha256(b).hexdigest()
def names():return tuple(s+'-'+stage for s in ('canonical','workflow') for stage in STAGES)
def typ(s):return CueCanonicalEngine if s=='canonical' else CueWorkflowEngine
def save(out,s,stage,e,b):
    name=s+'-'+stage;data=codec.dumps((s,stage,e.checkpoint(),b.checkpoint(e)));raw=gzip.compress(data.encode(),mtime=0);p=out/'records'/(name+'.json.gz');write(p,raw);write(out/'backup'/p.name,raw)
    if codec.dumps(read(p))!=data:raise ValueError('exact typed raw readback')
    js(out/'identities'/(name+'.json'),dict(sha256=sha(raw),bytes=len(raw),typed_exact=True,backup_exact=True));return name
def durable(out,s,e,b):
    payload=codec.dumps((s,len(b.events),e.checkpoint(),b.checkpoint(e)))
    write(out/'durable'/(s+f'-{len(b.events):03d}.json.gz'),gzip.compress(payload.encode(),mtime=0))
def main():
    p=argparse.ArgumentParser();p.add_argument('action',choices=('init','generate','control','audit','tests','finish'));p.add_argument('inputs');p.add_argument('output');p.add_argument('--archive',required=True);p.add_argument('--setting',choices=('canonical','workflow'));p.add_argument('--control',choices=('restarted','cancelled'));p.add_argument('--record');p.add_argument('--public',required=True);p.add_argument('--owner',required=True);p.add_argument('--stop-at',required=True);a=p.parse_args()
    protocol=json.loads((ROOT/(PREFIX+'Protocol_v1.json')).read_text());freeze=json.loads((ROOT/(PREFIX+'Source_Freeze_v1.json')).read_text());prior=json.loads((ROOT/protocol['prior_source_freeze']).read_text());out=pathlib.Path(a.output)
    def guard(launch=False):
        state=json.loads((pathlib.Path(a.public)/'docs/FT_Run_State.json').read_text());now=datetime.now(timezone.utc);limit=min(datetime.fromisoformat(state['lease_expires_at']),datetime.fromisoformat(a.stop_at)) if state.get('lease_expires_at') else now
        if state['run_id']!=a.owner or not state['active_worker'] or state['status']!='running' or (limit-now).total_seconds()<(300 if launch else 0):raise ValueError('ownership/deadline')
        for mapping in (prior,freeze):
            for n,h in mapping.items():
                if sha((ROOT/n).read_bytes())!=h:raise ValueError('frozen source '+n)
    guard(True)
    if a.action=='init':out.mkdir(exist_ok=False);(out/'jobs').mkdir()
    if not (out/'jobs').is_dir():raise ValueError('init required')
    if a.action=='generate':
        if a.setting is None:raise ValueError('exact setting')
        job='generate-'+a.setting
    elif a.action=='control':
        if a.setting is None or a.control is None:raise ValueError('exact saved control')
        job='control-'+a.setting+'-'+a.control
    elif a.action=='audit':
        if a.record not in names():raise ValueError('exact saved record')
        job='audit-'+a.record
    else:job=a.action
    js(out/'jobs'/(job+'.start.json'),dict(job=job,started=datetime.now(timezone.utc).isoformat(),owner=a.owner,freeze=sha((ROOT/(PREFIX+'Source_Freeze_v1.json')).read_bytes())))
    try:
        result=None
        if a.action=='init':
            archive=pathlib.Path(a.archive)
            if sha(archive.read_bytes())!=protocol['archive']['sha256']:raise ValueError('exact accepted A12C archive')
            with zipfile.ZipFile(archive) as z:
                manifest=json.loads(z.read('SHA256.json'))
                if len(manifest)!=protocol['archive']['members']:raise ValueError('archive manifest count')
                for n,h in manifest.items():
                    if sha(z.read(n))!=h:raise ValueError('archive member '+n)
                for s,e in protocol['inputs'].items():
                    raw=(pathlib.Path(a.inputs)/e['file']).read_bytes()
                    if raw!=z.read('attempt1/records/'+e['file']) or sha(raw)!=e['sha256']:raise ValueError('exact accepted raw input')
                    row=read(pathlib.Path(a.inputs)/e['file'])
                    if (row[0],row[1],row[2])!=(s,1,'complete') or (sha(row[3].encode()),sha(row[4].encode()))!=(e['native_sha256'],e['windows_sha256']):raise ValueError('source/native/windows pair')
            result=dict(passed=True,archive_members=len(manifest),inputs=2,source_identities=len(freeze),prior_identities=len(prior),record_gate=12)
        else:
            if not json.loads((out/'jobs/init.outcome.json').read_text())['passed']:raise ValueError('init gate')
            if a.action in ('generate','control','audit'):
                s=a.setting if a.action!='audit' else a.record.split('-')[0];entry=protocol['inputs'][s];path=pathlib.Path(a.inputs)/entry['file']
                if sha(path.read_bytes())!=entry['sha256']:raise ValueError('changed source input')
                source=read(path);native,windows=source[3:5]
            def finish(e,b):
                if b.phase=='active' and b.index==0:
                    b.step(e,work_limit=10**7,commit_ready=False);durable(out,s+'-resume',e,b);guard()
                    b.step(e);durable(out,s+'-resume',e,b);guard()
                for turn in range(32):
                    if b.phase!='active':break
                    b.step(e,work_limit=10**7);durable(out,s+'-resume',e,b);guard()
                else:raise ValueError('finite opportunity bound')
            if a.action=='generate':
                e=typ(s).restore(native);b=CueProcessing(e,windows);saved=[save(out,s,'before',e,b)]
                if not b.plan:raise ValueError('registered paid panel unexpectedly empty')
                b.step(e,work_limit=1);durable(out,s,e,b);saved.append(save(out,s,'partial',e,b));guard()
                b.step(e,work_limit=10**7,commit_ready=False);durable(out,s,e,b);saved.append(save(out,s,'ready',e,b));guard()
                b.step(e);durable(out,s,e,b);guard()
                for turn in range(32):
                    if b.phase!='active':break
                    b.step(e,work_limit=10**7);durable(out,s,e,b);guard()
                else:raise ValueError('finite opportunity bound')
                saved.append(save(out,s,'complete',e,b));pair=(e.checkpoint(),b.checkpoint(e));b.step(e);b.step(e,cancel=True)
                if pair!=(e.checkpoint(),b.checkpoint(e)):raise ValueError('terminal idempotence')
                if b.phase!='complete':raise ValueError('honest failed record saved; complete domain gate not met')
                result=dict(passed=True,records=saved,targets=len(b.plan),complete=b.index,cost=sum(x['debit']['energy'] for x in b.events),terminal_idempotence=True,intents=[x['intent'] for x in b.results],cursor=e._cursors[b.actor])
            elif a.action=='control':
                saved=read(out/'records'/(s+'-partial.json.gz'));e=typ(s).restore(saved[2]);old=typ(s).restore(native);b=CueProcessing.restore(saved[3],e,old,windows);guard()
                if a.control=='cancelled':b.step(e,cancel=True)
                else:finish(e,b)
                n=save(out,s,a.control,e,b)
                if a.control=='restarted':
                    final=read(out/'records'/(s+'-complete.json.gz'))
                    if (e.checkpoint(),b.checkpoint(e))!=final[2:4]:raise ValueError('exact partial restart differs')
                result=dict(passed=True,records=[n],restart_exact=a.control=='restarted')
            elif a.action=='audit':
                row=read(out/'records'/(a.record+'.json.gz'));e=typ(s).restore(row[2]);old=typ(s).restore(native);guard();result=audit(e,old,windows,row[3]);result.update(record=a.record,record_sha256=sha((out/'records'/(a.record+'.json.gz')).read_bytes()));js(out/'audits'/(a.record+'.json'),result)
            elif a.action=='tests':
                rows={n:read(out/'records'/(n+'.json.gz')) for n in names()};audits={n:json.loads((out/'audits'/(n+'.json')).read_text()) for n in names()}
                import tests_ft7.test_cue_processing as tests
                tests.CONTEXT.update(rows=rows,audits=audits,protocol=protocol,inputs=pathlib.Path(a.inputs),out=out)
                suite=unittest.defaultTestLoader.loadTestsFromTestCase(tests.CueProcessingTests);methods=[t._testMethodName for t in suite]
                if sorted(methods)!=sorted(protocol['methods']):raise ValueError('exact method inventory')
                with (out/'tests.log').open('x') as log:checked=unittest.TextTestRunner(stream=log,verbosity=2).run(suite)
                result=dict(passed=checked.wasSuccessful(),methods=methods,probes=tests.PROBES,failures=len(checked.failures),errors=len(checked.errors))
                if not checked.wasSuccessful():raise ValueError('eight actual required methods did not pass')
            else:
                methods=json.loads((out/'jobs/tests.outcome.json').read_text());reports=[]
                if not methods['passed']:raise ValueError('methods required')
                for n in names():
                    arow=json.loads((out/'audits'/(n+'.json')).read_text());closed=json.loads((out/'jobs'/('audit-'+n+'.outcome.json')).read_text())
                    if not closed['passed'] or arow!=closed['result'] or arow['record_sha256']!=sha((out/'records'/(n+'.json.gz')).read_bytes()):raise ValueError('exact saved audit binding')
                    reports.append(arow)
                result=dict(passed=True,records=12,methods=methods['result']['methods'],probes=methods['result']['probes'],reports=reports,source_identities=len(freeze),prior_identities=len(prior),comparison_paid=False,execution_authorized=False,td5_admitted=False,history_choice=False,independent_credit=False,clearance_claim=False,skill_acquired=False,parent_accepted=False,ft8_unchanged=True,accepted_stage_replays=0);js(out/'summary.json',result)
        guard();js(out/'jobs'/(job+'.outcome.json'),dict(passed=True,ended=datetime.now(timezone.utc).isoformat(),result=result));print(json.dumps(dict(job=job,passed=True)),flush=True)
    except BaseException as error:
        js(out/'jobs'/(job+'.failure.json'),dict(error_type=type(error).__name__,message=str(error),traceback=traceback.format_exc(),ended=datetime.now(timezone.utc).isoformat()));raise
if __name__=='__main__':main()
