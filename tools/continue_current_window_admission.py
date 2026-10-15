"""Continue only missing frozen stages after a verified quiescent checkpoint."""
from pathlib import Path
from datetime import datetime,timezone
import argparse,hashlib,json,subprocess,sys,time
ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT),str(ROOT/'baseline/HLE_Rebuild_R21B')]
from tools import evaluate_ft7_current_window_admission as gate
PREFIX=gate.PREFIX+'_Continuation'
def read(p):return json.loads(p.read_text())
def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def write(p,d):
    p.parent.mkdir(parents=True,exist_ok=True)
    with p.open('x') as f:f.write(json.dumps(d,indent=2,sort_keys=True)+'\n')
def main():
    parser=argparse.ArgumentParser()
    for name in ('archives','paid','capacity','output','operations','public'):
        parser.add_argument(name,type=lambda s:Path(s).resolve())
    parser.add_argument('--owner',required=True);parser.add_argument('--stop-at',required=True)
    a=parser.parse_args();now=datetime.now(timezone.utc);deadline=datetime.fromisoformat(a.stop_at)
    if deadline.utcoffset()!=timezone.utc.utcoffset(now) or not 0<(deadline-now).total_seconds()<=1800:
        raise ValueError('explicit future UTC deadline within thirty minutes required')
    contract=ROOT/'contracts/ft';op=read(contract/(PREFIX+'_Protocol_v1.json'))
    frozen=read(contract/(PREFIX+'_Source_Freeze_v1.json'))
    binding=read(ROOT/op['binding_file']);p=gate.protocol();source=gate.freeze()
    if len(source)!=406 or source!=read(contract/(gate.PREFIX+'_Source_Freeze_v1.json')):
        raise ValueError('original frozen source')
    expected_op={op['module'],op['binding_file'],'contracts/ft/'+PREFIX+'_Protocol_v1.json',
        'contracts/ft/'+PREFIX+'_Protocol_v1.sha256'}
    if set(frozen)!=expected_op:raise ValueError('exact four operational identities')
    roots={'original_output':a.output,'capacity':a.capacity,'paid':a.paid}
    def verify():
        if gate.freeze()!=source or any(sha(ROOT/n)!=h for n,h in frozen.items()):raise ValueError('source changed')
        if sha(contract/(PREFIX+'_Protocol_v1.json'))!=(contract/(PREFIX+'_Protocol_v1.sha256')).read_text().split()[0]:
            raise ValueError('operational protocol hash')
        for label,files in binding['files'].items():
            root=roots[label]
            for name,digest in files.items():
                relative=Path(name)
                if relative.is_absolute() or '..' in relative.parts or sha(root/relative)!=digest:
                    raise ValueError('exact closed prefix or accepted input changed')
        if binding['original_source']!=source:raise ValueError('source binding')
    verify()
    if set(binding['files'])!=set(roots):raise ValueError('exact three binding roots')
    existing={str(path.relative_to(a.output)) for path in a.output.rglob('*') if path.is_file()}
    if existing!=set(binding['files']['original_output']):raise ValueError('complete initial closed-prefix file domain')
    for protected in (a.output,a.paid,a.capacity,a.public,ROOT):
        if a.operations==protected or protected in a.operations.parents or a.operations in protected.parents:
            raise ValueError('disjoint fresh operational output required')
    outcome=read(a.output/'outcome.json')
    if outcome['status']!='checkpoint' or outcome['active_children']!=0 or not outcome['source_unchanged']:
        raise ValueError('only quiescent nonfailed checkpoint can continue')
    launches={x.name for x in (a.output/'launches').glob('*.json')}
    jobs={x.name for x in (a.output/'jobs').glob('*.json')}
    if launches!=jobs:raise ValueError('unclosed original launch')
    for path in (a.output/'jobs').glob('*.json'):
        row=read(path)
        if row['exit_code']!=0 or not row['passed'] or sha(a.output/row['log'])!=row['log_sha256']:
            raise ValueError('all original launches must be closed and passing')
    for name,label in (('capacity_index.json','capacity'),('paid_index.json','paid')):
        index=read(a.output/name)
        if sorted(r['key'] for r in index)!=sorted(p['saved_records']):raise ValueError('exact forty input keys')
        if {r['file']:r['sha256'] for r in index}!=binding['files'][label]:raise ValueError('all accepted raw bound')
    def record(key):
        path=a.output/'stages'/(key.replace('/','-')+'.json')
        raw=a.output/'records'/(key.replace('/','-')+'.json.gz')
        if not path.exists():
            if raw.exists():raise ValueError('unclosed raw requires diagnosed recovery')
            return False
        r=read(path)
        if (r['key']!=key or not r['passed'] or not r['typed_roundtrip_exact'] or not r['independent_audit']['passed']
            or r['source_freeze']!=source or sha(a.output/r['file'])!=r['sha256']):raise ValueError('exact closed record')
        return True
    def method(name):
        d=a.output/'methods'/name;path=d/'result.json'
        if not path.exists():
            if d.exists():raise ValueError('unclosed method requires diagnosed recovery')
            return False
        r=read(path)
        if (r['method']!=gate.METHOD+name or not r['passed'] or (r['methods'],r['errors'],r['failures'])!=(1,0,0)
            or r['source_freeze']!=source):raise ValueError('exact passing actual body')
        return True
    pending_records=[key for key in p['saved_records'] if not record(key)]
    pending_methods=[name for name in p['registered_tests'] if not method(name)]
    if (a.output/'summary.json').exists():raise ValueError('existing aggregate cannot rerun')
    a.operations.mkdir(exist_ok=False)
    write(a.operations/'plan.json',dict(owner=a.owner,started_utc=now.isoformat(),stop_at=deadline.isoformat(),
        records=pending_records,methods=pending_methods,original_source=source,operational_freeze=frozen,
        binding_sha256=sha(ROOT/op['binding_file'])))
    failed=False;stop=None;closed=[]
    def allowed():
        nonlocal failed,stop
        current=datetime.now(timezone.utc)
        try:verify()
        except Exception as e:failed=True;stop=repr(e)
        state=read(a.public/'docs/FT_Run_State.json')
        if failed:stop=stop or 'child failure'
        elif (a.operations/'STOP').exists():stop='cooperative checkpoint'
        elif current>=deadline:stop='prospective deadline'
        elif state['run_id']!=a.owner or not state['active_worker'] or state['status']!='running':stop='ownership unavailable'
        elif (datetime.fromisoformat(state['lease_expires_at'])-current).total_seconds()<=op['lease_margin_seconds']:stop='lease margin'
        return stop is None
    def phase(action,targets,workers):
        nonlocal failed
        todo=list(targets);active={};done=0
        while todo or active:
            while todo and len(active)<workers and allowed():
                target=todo.pop(0);label=action+('-'+target.replace('/','-') if target else '')
                log=a.operations/'logs'/(label+'.log');log.parent.mkdir(exist_ok=True)
                cmd=[sys.executable,str(ROOT/'tools/evaluate_ft7_current_window_admission.py'),str(a.archives),str(a.paid),str(a.capacity),str(a.output),action]+([target] if target else [])
                stream=log.open('x');child=subprocess.Popen(cmd,stdout=stream,stderr=subprocess.STDOUT)
                job=dict(action=action,target=target,started_utc=datetime.now(timezone.utc).isoformat(),command=cmd,log=str(log.relative_to(a.operations)))
                active[child]=(stream,job);write(a.operations/'launches'/(label+'.json'),job);print('START '+label,flush=True)
            if not active:break
            time.sleep(.5)
            for child,(stream,job) in list(active.items()):
                code=child.poll()
                if code is None:continue
                stream.close();del active[child]
                job.update(exit_code=code,ended_utc=datetime.now(timezone.utc).isoformat(),log_sha256=sha(a.operations/job['log']),passed=False)
                try:
                    verify()
                    if code!=0:raise ValueError('child failed')
                    if action=='record' and not record(job['target']):raise ValueError('missing record')
                    if action=='method' and not method(job['target']):raise ValueError('missing actual method')
                    if action=='finish':
                        summary=read(a.output/'summary.json')
                        if not summary['passed'] or (summary['methods'],summary['saved_records'],summary['predecessor_identities'],summary['frozen_identities'])!=(8,40,484,406):raise ValueError('unchanged final aggregate')
                    job['passed']=True;done+=1
                except Exception as error:failed=True;job['error']=repr(error)
                closed.append(job);write(a.operations/'jobs'/(job['action']+('-'+job['target'].replace('/','-') if job['target'] else '')+'.json'),job)
                print('END '+job['action']+' '+str(job['target'])+' '+str(job['passed']),flush=True)
        return done==len(targets) and not failed
    complete=phase('record',pending_records,op['record_workers'])
    if complete:
        if not all(record(k) for k in p['saved_records']):raise ValueError('all forty exact records before methods')
        complete=phase('method',pending_methods,op['method_workers'])
    if complete:
        if not all(method(n) for n in p['registered_tests']):raise ValueError('all eight exact actual methods before finish')
        complete=phase('finish',[None],1)
    write(a.operations/'outcome.json',dict(status='failed' if failed else 'passed' if complete else 'checkpoint',
        active_children=0,stop_reason=stop,jobs=closed,source_unchanged=gate.freeze()==source,gate_accepted=complete))
    if failed:raise SystemExit(1)
if __name__=='__main__':main()
