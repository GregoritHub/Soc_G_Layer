"""Recover only interrupted/unstarted exact bodies, preserving every prior byte."""
from pathlib import Path
from datetime import datetime,timezone
from types import SimpleNamespace
import argparse,hashlib,json,os,shutil,subprocess,sys,time
ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT),str(ROOT/'baseline/HLE_Rebuild_R21B')]
from tools import evaluate_ft7_current_window_admission as gate
PREFIX=gate.PREFIX+'_Method_Recovery1'
def read(p):return json.loads(p.read_text())
def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def files(p):return {str(x.relative_to(p)):sha(x) for x in p.rglob('*') if x.is_file()}
def write(p,d):
    p.parent.mkdir(parents=True,exist_ok=True)
    with p.open('x') as f:f.write(json.dumps(d,indent=2,sort_keys=True)+'\n')
def no_survivors():
    found=[];examined=0
    targets={'evaluate_ft7_current_window_admission.py','continue_current_window_admission.py','continue_current_window_admission2.py','recover_current_window_admission_methods.py'}
    for p in Path('/proc').iterdir():
        if not p.name.isdigit() or int(p.name)==os.getpid():continue
        try:args=(p/'cmdline').read_bytes().split(b'\0');examined+=1
        except FileNotFoundError:continue
        if any(Path(x.decode(errors='replace')).name in targets for x in args if x):found.append(int(p.name))
    if found:raise ValueError('surviving B1D workers: '+repr(found))
    return dict(examined=examined,matching_workers=0,namespace_entry=False,signals=False)
def main():
    parser=argparse.ArgumentParser()
    for n in ('archives','paid','capacity','original','prior1','prior2','output','operations','public'):
        parser.add_argument(n,type=lambda s:Path(s).resolve())
    parser.add_argument('--owner',required=True);parser.add_argument('--stop-at',required=True)
    a=parser.parse_args();now=datetime.now(timezone.utc);deadline=datetime.fromisoformat(a.stop_at)
    if deadline.utcoffset()!=timezone.utc.utcoffset(now) or not 0<(deadline-now).total_seconds()<=1800:raise ValueError('future UTC deadline within thirty minutes')
    contract=ROOT/'contracts/ft';op=read(contract/(PREFIX+'_Protocol_v1.json'))
    frozen=read(contract/(PREFIX+'_Source_Freeze_v1.json'));binding=read(ROOT/op['binding_file']);p=gate.protocol();source=gate.freeze()
    prior={}
    for suffix in ('_Continuation_Source_Freeze_v1.json','_Continuation2_Source_Freeze_v1.json'):
        f=read(contract/(gate.PREFIX+suffix))
        if len(f)!=4 or set(prior)&set(f):raise ValueError('disjoint original operational freezes')
        prior.update(f)
    if len(source)!=406 or binding['original_source']!=source or binding['prior_operational_source']!=prior:raise ValueError('exact source binding')
    if set(frozen)!={op['module'],op['binding_file'],'contracts/ft/'+PREFIX+'_Protocol_v1.json','contracts/ft/'+PREFIX+'_Protocol_v1.sha256'}:raise ValueError('four recovery identities')
    roots=dict(original=a.original,prior1=a.prior1,prior2=a.prior2,paid=a.paid,capacity=a.capacity)
    if set(binding['files'])!=set(roots):raise ValueError('exact five binding roots')
    if (a.prior1.name,a.prior2.name,a.output.name,a.operations.name)!=('current-window-admission-continuation1','current-window-admission-continuation2',op['output'],op['operations']):raise ValueError('registered output names')
    protected=tuple(roots.values())+(ROOT,a.public)
    for dest in (a.output,a.operations):
        if dest.exists() or any(dest==x or dest in x.parents or x in dest.parents for x in protected):raise ValueError('fresh disjoint output required')
    if a.output==a.operations or a.output in a.operations.parents or a.operations in a.output.parents:raise ValueError('separate outputs')
    copied={}
    def verify():
        if gate.freeze()!=source or any(sha(ROOT/n)!=h for n,h in {**prior,**frozen}.items()):raise ValueError('source changed')
        if sha(contract/(PREFIX+'_Protocol_v1.json'))!=(contract/(PREFIX+'_Protocol_v1.sha256')).read_text().split()[0]:raise ValueError('protocol hash')
        for label,entries in binding['files'].items():
            for n,h in entries.items():
                if Path(n).is_absolute() or '..' in Path(n).parts or sha(roots[label]/n)!=h:raise ValueError('bound prefix or input changed')
        if any(sha(a.output/n)!=h for n,h in copied.items()):raise ValueError('copied prefix changed')
    verify()
    for label in ('original','prior1','prior2'):
        if files(roots[label])!=binding['files'][label]:raise ValueError('complete preserved file domain')
    for name,label in (('capacity_index.json','capacity'),('paid_index.json','paid')):
        index=read(a.original/name)
        if sorted(r['key'] for r in index)!=sorted(p['saved_records']) or {r['file']:r['sha256'] for r in index}!=binding['files'][label]:raise ValueError('eighty exact input records')
    rows=gate.records(SimpleNamespace(output=a.original),p,source)
    if len(rows)!=40 or read(a.original/'predecessor_ids.json')!=gate.predecessors():raise ValueError('exact records and predecessors')
    passed={}
    for r in (a.original/'methods').glob('*/result.json'):
        d=read(r);n=r.parent.name
        if n not in p['registered_tests'] or d['method']!=gate.METHOD+n or not d['passed'] or (d['methods'],d['errors'],d['failures'])!=(1,0,0) or d['source_freeze']!=source:raise ValueError('exact passed body')
        passed[n]=d
    if sorted(passed)!=sorted(op['passed_methods']):raise ValueError('exact five prior passes')
    jobs=[];unclosed=[]
    for root in (a.original,a.prior1,a.prior2):
        launches={x.name:read(x) for x in (root/'launches').glob('*.json')}
        closed={x.name:read(x) for x in (root/'jobs').glob('*.json')}
        if not set(closed)<=set(launches):raise ValueError('job without launch')
        for name,row in closed.items():
            if not row['passed'] or row['exit_code']!=0 or sha(root/row['log'])!=row['log_sha256'] or any(row[k]!=v for k,v in launches[name].items()):raise ValueError('closed prior job')
            jobs.append((row['action'],row['target']))
        if root!=a.prior2:
            outcome=read(root/'outcome.json')
            order=lambda x:(x['action'],str(x['target']))
            if set(launches)!=set(closed) or outcome['status']!='checkpoint' or outcome['active_children']!=0 or not outcome['source_unchanged'] or sorted(closed.values(),key=order)!=sorted(outcome['jobs'],key=order):raise ValueError('original quiescent outcomes')
        else:
            if (root/'outcome.json').exists():raise ValueError('interrupted prior outcome unexpectedly present')
            unclosed=[(launches[n]['action'],launches[n]['target']) for n in set(launches)-set(closed)]
    if len(jobs)!=len(set(jobs)) or {n for act,n in jobs if act=='record'}!=set(p['saved_records']) or {n for act,n in jobs if act=='method'}!=set(passed):raise ValueError('exact prior unique job union')
    if set(unclosed)!={('method',n) for n in op['interrupted_methods']}:raise ValueError('exact two interrupted launches')
    if any(act not in ('record','method') for act,n in jobs):raise ValueError('unexpected prior action')
    for n in op['interrupted_methods']:
        d=a.original/'methods'/n
        if not d.is_dir() or (d/'result.json').exists() or not (d/'controls.log').exists():raise ValueError('preserve incomplete attempt')
    if any((a.original/'methods'/n).exists() for n in op['unstarted_methods']):raise ValueError('exact unstarted method')
    if (a.original/'summary.json').exists():raise ValueError('accepted aggregate cannot rerun')
    process_proof=no_survivors()
    def ownership():
        state=read(a.public/'docs/FT_Run_State.json');current=datetime.now(timezone.utc)
        return state['run_id']==a.owner and state['active_worker'] and state['status']=='running' and (datetime.fromisoformat(state['lease_expires_at'])-current).total_seconds()>op['lease_margin_seconds']
    if not ownership():raise ValueError('current owned lease required')
    excluded=tuple('methods/'+n+'/' for n in op['interrupted_methods'])
    copied={n:h for n,h in binding['files']['original'].items() if not n.startswith(excluded)}
    a.output.mkdir();a.operations.mkdir()
    for n,h in copied.items():
        dest=a.output/n;dest.parent.mkdir(parents=True,exist_ok=True);shutil.copyfile(a.original/n,dest)
    verify()
    pending=[n for n in p['registered_tests'] if n not in passed]
    if set(pending)!=set(op['interrupted_methods']+op['unstarted_methods']):raise ValueError('exact pending bodies')
    write(a.operations/'plan.json',dict(owner=a.owner,started_utc=now.isoformat(),stop_at=deadline.isoformat(),methods=pending,copied_files=copied,source=source,recovery_freeze=frozen,binding_sha256=sha(ROOT/op['binding_file']),process_proof=process_proof,prior_passed=sorted(passed),interrupted=op['interrupted_methods']))
    failed=False;stop=None;closed=[]
    def allowed():
        nonlocal stop,failed
        try:verify()
        except Exception as e:failed=True;stop=repr(e)
        if failed:stop=stop or 'child failure'
        elif (a.operations/'STOP').exists():stop='cooperative checkpoint'
        elif datetime.now(timezone.utc)>=deadline:stop='prospective deadline'
        elif not ownership():stop='ownership or lease margin'
        return stop is None
    def phase(action,targets,workers):
        nonlocal failed
        todo=list(targets);active={};done=0
        while todo or active:
            while todo and len(active)<workers and allowed():
                target=todo.pop(0);label=action+('-'+target if target else '')
                log=a.operations/'logs'/(label+'.log');log.parent.mkdir(exist_ok=True);stream=log.open('x')
                cmd=[sys.executable,str(ROOT/'tools/evaluate_ft7_current_window_admission.py'),str(a.archives),str(a.paid),str(a.capacity),str(a.output),action]+([target] if target else [])
                child=subprocess.Popen(cmd,stdout=stream,stderr=subprocess.STDOUT)
                job=dict(action=action,target=target,command=cmd,started_utc=datetime.now(timezone.utc).isoformat(),log=str(log.relative_to(a.operations)))
                active[child]=(stream,job);write(a.operations/'launches'/(label+'.json'),job);print('START '+label,flush=True)
            if not active:break
            time.sleep(.5)
            for child,(stream,job) in list(active.items()):
                code=child.poll()
                if code is None:continue
                stream.close();del active[child];job.update(exit_code=code,ended_utc=datetime.now(timezone.utc).isoformat(),log_sha256=sha(a.operations/job['log']),passed=False)
                try:
                    verify()
                    if code!=0:raise ValueError('child exit')
                    if action=='method':
                        r=read(a.output/'methods'/job['target']/'result.json')
                        if r['method']!=gate.METHOD+job['target'] or not r['passed'] or (r['methods'],r['errors'],r['failures'])!=(1,0,0) or r['source_freeze']!=source:raise ValueError('exact original body result')
                    else:
                        r=read(a.output/'summary.json')
                        if not r['passed'] or (r['methods'],r['saved_records'],r['predecessor_identities'],r['frozen_identities'])!=(8,40,484,406):raise ValueError('original final gate')
                    job['passed']=True;done+=1
                except Exception as e:failed=True;job['error']=repr(e)
                closed.append(job);write(a.operations/'jobs'/(job['action']+('-'+job['target'] if job['target'] else '')+'.json'),job);print('END '+job['action']+' '+str(job['target'])+' '+str(job['passed']),flush=True)
        return done==len(targets) and not failed
    complete=phase('method',pending,op['method_workers'])
    if complete:complete=phase('finish',[None],1)
    write(a.operations/'outcome.json',dict(status='failed' if failed else 'passed' if complete else 'checkpoint',jobs=closed,active_children=0,source_unchanged=gate.freeze()==source,gate_accepted=complete,stop_reason=stop))
    if failed:raise SystemExit(1)
if __name__=='__main__':main()
