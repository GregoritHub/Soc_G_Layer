"""Frozen, stage-bounded current-window operand/admission evaluation."""
from pathlib import Path
from zipfile import ZipFile
from datetime import datetime,timezone
import argparse,gzip,hashlib,json,os,subprocess,sys,time,unittest
ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT),str(ROOT/'baseline/HLE_Rebuild_R21B')]
PREFIX='FT7_1b2b3b2b2b2b2b2b1d'
OLD='FT7_1b2b3b2b2b2b2b2b1c'
METHOD='tests_ft7.test_current_window_admission.CurrentWindowAdmissionTests.'
def read(p):return json.loads(p.read_text())
def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def write(p,d):
    p.parent.mkdir(parents=True,exist_ok=True)
    with p.open('x') as f:f.write(json.dumps(d,indent=2,sort_keys=True)+'\n')
def protocol():return read(ROOT/'contracts/ft'/(PREFIX+'_Protocol_v1.json'))
def freeze():
    prior='contracts/ft/'+OLD+'_Source_Freeze_v1.json';p=protocol()
    names=set(read(ROOT/prior))|{prior,'contracts/ft/'+PREFIX+'_Protocol_v1.json',
        'contracts/ft/'+PREFIX+'_Protocol_v1.sha256',*p['modules'],p['tests']}
    return {n:sha(ROOT/n) for n in sorted(names)}
def predecessors():
    from tools.evaluate_ft7_1b2b3b2b2b2b2b2b1c import predecessors as previous
    from tools.evaluate_ft6_3b import ids
    names=read(ROOT/'contracts/ft'/(OLD+'_Protocol_v1.json'))['registered_tests']
    found=sorted(ids(unittest.defaultTestLoader.loadTestsFromName('tests_ft7.test_current_window_capacity')))
    expected=sorted('tests_ft7.test_current_window_capacity.CurrentWindowCapacityTests.'+n for n in names)
    if found!=expected:raise ValueError('exact eight predecessor bodies')
    result=previous()+found
    if len(result)!=484:raise ValueError('exact 484 predecessor identities')
    return result
def output():return Path(os.environ['FT7_ADMISSION_OUTPUT'])
def capacity_row(key):
    from tools.evaluate_ft7_1b2b3b2b2b2b2b2b1c import saved
    return saved(key)
def context(key):
    from tools.evaluate_ft7_1b2b3b2b2b2b2b2b1c import context as previous
    return (*previous(key),capacity_row(key)[2])
def saved(key):
    from hle_unified import codec
    with gzip.open(output()/'records'/(key.replace('/','-')+'.json.gz'),'rt') as f:r=codec.loads(f.read())
    entry=next(x for x in read(output()/'capacity_index.json') if x['key']==key)
    if r[:2]!=(key,entry['sha256']):raise ValueError('exact capacity input hash')
    return r
def check(a):
    p=protocol();f=freeze();prior=read(ROOT/'contracts/ft'/(OLD+'_Source_Freeze_v1.json'))
    if f!=read(ROOT/'contracts/ft'/(PREFIX+'_Source_Freeze_v1.json')):raise ValueError('frozen source changed')
    if len(prior)!=399 or any(f[n]!=h for n,h in prior.items()):raise ValueError('prior source changed')
    path=ROOT/'contracts/ft'/(PREFIX+'_Protocol_v1.json')
    if sha(path)!=path.with_suffix('.sha256').read_text().split()[0]:raise ValueError('protocol hash')
    os.environ.update(FT7_CAPACITY_OUTPUT=str(a.capacity),FT7_CAPACITY_PAID=str(a.paid),FT7_ADMISSION_OUTPUT=str(a.output),
        FT7_WINDOW_INPUT=str(a.archives/p['input']['request']['filename']))
    if a.action not in ('init','run'):
        for index,root in (('capacity_index.json',a.capacity),('paid_index.json',a.paid)):
            for r in read(a.output/index):
                if sha(root/r['file'])!=r['sha256']:raise ValueError('accepted input changed')
    return p,f
def initialize(a,p,f):
    a.output.mkdir(exist_ok=False);counts={}
    for label,item in p['input'].items():
        path=a.archives/item['filename']
        if sha(path)!=item['sha256']:raise ValueError('input archive hash')
        with ZipFile(path) as z:
            m=json.loads(z.read('SHA256.json'))
            if len(m)!=item['members'] or set(z.namelist())!=set(m)|{'SHA256.json'}:raise ValueError('archive domain')
            if any(hashlib.sha256(z.read(n)).hexdigest()!=h for n,h in m.items()):raise ValueError('archive member')
            counts[label]=len(m)
            if label=='capacity':
                prefix='current-window-capacity-attempt1/';summary=json.loads(z.read(prefix+'summary.json'))
                if not summary['passed'] or (summary['methods'],summary['saved_records'],summary['predecessor_identities'],summary['frozen_identities'])!=(8,40,476,399):raise ValueError('complete prior capacity acceptance')
                capidx=json.loads(z.read(prefix+'record_index.json'))
                for r in capidx:
                    if z.read(prefix+r['file'])!=(a.capacity/r['file']).read_bytes():raise ValueError('exact saved capacity input')
    paididx=read(a.capacity/'input_index.json')
    if [r['key'] for r in capidx]!=p['saved_records'] or sorted(r['key'] for r in paididx)!=sorted(p['saved_records']):raise ValueError('forty inputs')
    for r in paididx:
        if sha(a.paid/r['file'])!=r['sha256']:raise ValueError('paid raw changed')
    write(a.output/'capacity_index.json',capidx);write(a.output/'paid_index.json',paididx)
    write(a.output/'input_verification.json',dict(passed=True,input=p['input'],members=counts,capacity_raw_exact=40,paid_raw_exact=40))
    write(a.output/'source_freeze.json',f);write(a.output/'predecessor_ids.json',predecessors())
def records(a,p,f):
    rows=[]
    for key in p['saved_records']:
        r=read(a.output/'stages'/(key.replace('/','-')+'.json'))
        if r['key']!=key or not r['passed'] or not r['independent_audit']['passed'] or not r['typed_roundtrip_exact'] or r['source_freeze']!=f or sha(a.output/r['file'])!=r['sha256']:raise ValueError('complete exact stage required')
        rows.append(r)
    return rows
def record_stage(a,p,f):
    from hle_unified import codec
    from full_theory.current_window_admission import current_window_admission
    from full_theory.current_window_admission_audit import audit_current_window_admission
    key=a.target
    if key not in p['saved_records']:raise ValueError('registered key')
    report=a.output/'stages'/(key.replace('/','-')+'.json')
    if report.exists():raise ValueError('passing stage refuses rerun')
    print(key+': restore exact accepted inputs; no new payment',flush=True);ctx=context(key)
    path=a.output/'records'/(key.replace('/','-')+'.json.gz');path.parent.mkdir(exist_ok=True)
    entry=next(x for x in read(a.output/'capacity_index.json') if x['key']==key)
    if not path.exists():
        text=current_window_admission(*ctx)
        with gzip.open(path,'xt',encoding='ascii') as g:g.write(codec.dumps((key,entry['sha256'],text))+'\n')
    row=saved(key)
    if codec.loads(codec.dumps(row))!=row:raise ValueError('typed roundtrip')
    proof=audit_current_window_admission(*ctx,row[2])
    if freeze()!=f:raise ValueError('source changed')
    write(report,dict(key=key,file=str(path.relative_to(a.output)),sha256=sha(path),capacity_sha256=entry['sha256'],
        passed=True,typed_roundtrip_exact=True,independent_audit=proof,source_freeze=f))
    print(key+': full independent window/operand/current-cost audit passed',flush=True)
def method_stage(a,p,f):
    from tools.evaluate_ft6_3b import ids
    records(a,p,f)
    if a.target not in p['registered_tests']:raise ValueError('registered method')
    d=a.output/'methods'/a.target;d.mkdir(parents=True,exist_ok=False)
    suite=unittest.defaultTestLoader.loadTestsFromName(METHOD+a.target)
    if list(ids(suite))!=[METHOD+a.target]:raise ValueError('exact actual body')
    with (d/'controls.log').open('x') as log:r=unittest.TextTestRunner(stream=log,verbosity=2).run(suite)
    records(a,p,f);passed=r.wasSuccessful() and r.testsRun==1 and freeze()==f
    write(d/'result.json',dict(method=METHOD+a.target,methods=r.testsRun,failures=len(r.failures),errors=len(r.errors),passed=passed,source_freeze=f))
    if not passed:raise SystemExit(1)
def finish(a,p,f):
    rs=records(a,p,f);names=[]
    for name in p['registered_tests']:
        r=read(a.output/'methods'/name/'result.json')
        if not r['passed'] or r['method']!=METHOD+name or (r['methods'],r['errors'],r['failures'])!=(1,0,0) or r['source_freeze']!=f:raise ValueError('all eight exact methods')
        names.append(r['method'])
    if read(a.output/'predecessor_ids.json')!=predecessors() or freeze()!=f:raise ValueError('exact identities')
    write(a.output/'method_ids.json',names)
    write(a.output/'record_index.json',[{k:r[k] for k in ('key','file','sha256','capacity_sha256')} for r in rs])
    write(a.output/'summary.json',dict(passed=True,batch=p['batch'],methods=8,failures=0,errors=0,saved_records=40,
        predecessor_identities=484,frozen_identities=len(f),prior_identities=399,native_unchanged=True,new_native_work=False,claim=p['claim_boundary']))
    print('PASS: eight exact methods, forty exact audits, 484 predecessor identities, unchanged source',flush=True)
def run(a,p,f):
    initialize(a,p,f);jobs=[];failed=False;stop=None
    def allowed():
        nonlocal stop
        now=datetime.now(timezone.utc);state=read(a.public/'docs/FT_Run_State.json')
        if failed:stop='child or verification failed'
        elif (a.output/'STOP').exists():stop='cooperative checkpoint'
        elif now>=datetime.fromisoformat(p['execution']['stop_before_utc']):stop='prospective deadline'
        elif state['run_id']!=a.owner or not state['active_worker'] or state['status']!='running':stop='ownership unavailable'
        elif (datetime.fromisoformat(state['lease_expires_at'])-now).total_seconds()<=p['execution']['lease_margin_seconds']:stop='lease margin'
        return stop is None
    def phase(action,targets,workers):
        nonlocal failed
        todo=list(targets);active={};done=0
        while todo or active:
            while todo and len(active)<workers and allowed():
                target=todo.pop(0);label=action+('-'+target.replace('/','-') if target else '')
                log=a.output/'logs'/(label+'.log');log.parent.mkdir(exist_ok=True)
                cmd=[sys.executable,str(Path(__file__).resolve()),str(a.archives),str(a.paid),str(a.capacity),str(a.output),action]+([target] if target else [])
                stream=log.open('x');child=subprocess.Popen(cmd,stdout=stream,stderr=subprocess.STDOUT)
                job=dict(action=action,target=target,started_utc=datetime.now(timezone.utc).isoformat(),command=cmd,log=str(log.relative_to(a.output)))
                active[child]=(stream,job);write(a.output/'launches'/(label+'.json'),job);print('START '+label,flush=True)
            if not active:break
            time.sleep(.5)
            for child,(stream,job) in list(active.items()):
                code=child.poll()
                if code is None:continue
                stream.close();del active[child];job.update(exit_code=code,ended_utc=datetime.now(timezone.utc).isoformat(),log_sha256=sha(a.output/job['log']),passed=False)
                try:
                    if code!=0 or freeze()!=f:raise ValueError('child exit/source changed')
                    if action=='record':
                        r=read(a.output/'stages'/(job['target'].replace('/','-')+'.json'))
                        if not r['passed'] or r['source_freeze']!=f or sha(a.output/r['file'])!=r['sha256']:raise ValueError('record result')
                    elif action=='method':
                        r=read(a.output/'methods'/job['target']/'result.json')
                        if not r['passed'] or r['method']!=METHOD+job['target'] or (r['methods'],r['errors'],r['failures'])!=(1,0,0) or r['source_freeze']!=f:raise ValueError('method result')
                    elif not read(a.output/'summary.json')['passed']:raise ValueError('aggregate')
                    job['passed']=True;done+=1
                except BaseException as e:failed=True;job['error']=repr(e)
                jobs.append(job);write(a.output/'jobs'/(job['action']+('-'+job['target'].replace('/','-') if job['target'] else '')+'.json'),job)
                print('END '+job['action']+' '+str(job['target'])+' '+str(job['passed']),flush=True)
        return done==len(targets) and not failed
    complete=phase('record',p['saved_records'],p['execution']['records_workers'])
    if complete:complete=phase('method',p['registered_tests'],p['execution']['method_workers'])
    if complete:complete=phase('finish',[None],1)
    write(a.output/'outcome.json',dict(status='failed' if failed else 'passed' if complete else 'checkpoint',
        active_children=0,stop_reason=stop,jobs=jobs,source_unchanged=freeze()==f,gate_accepted=complete))
    if failed:raise SystemExit(1)
def main():
    p=argparse.ArgumentParser()
    for n in ('archives','paid','capacity','output'):p.add_argument(n,type=lambda s:Path(s).resolve())
    p.add_argument('action',choices=('init','record','method','finish','run'));p.add_argument('target',nargs='?')
    p.add_argument('--public',type=lambda s:Path(s).resolve());p.add_argument('--owner')
    a=p.parse_args();protocol_data,f=check(a)
    if a.action=='run':
        if a.public is None or a.owner is None:raise ValueError('owner and public state required')
        run(a,protocol_data,f)
    elif a.action=='init':initialize(a,protocol_data,f)
    elif a.action=='record':record_stage(a,protocol_data,f)
    elif a.action=='method':method_stage(a,protocol_data,f)
    else:finish(a,protocol_data,f)
if __name__=='__main__':main()
