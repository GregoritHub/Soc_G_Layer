"""Single-worker recovery of the one unfinished, unchanged original method."""
from pathlib import Path
from datetime import datetime, timezone
from types import SimpleNamespace
import argparse, json, os, shutil, subprocess, sys
ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT), str(ROOT/'baseline/HLE_Rebuild_R21B')]
from tools import evaluate_ft7_current_window_admission as gate
from tools.recover_current_window_admission_methods import read, sha, files, write
PREFIX = gate.PREFIX + '_Method_Recovery2'

def main():
    parser = argparse.ArgumentParser()
    for name in ('archives','paid','capacity','original','prior1','prior2','recovered','recovery_operations','output','operations','public'):
        parser.add_argument(name, type=lambda s: Path(s).resolve())
    parser.add_argument('--owner', required=True)
    parser.add_argument('--stop-at', required=True)
    a = parser.parse_args()
    now = datetime.now(timezone.utc); deadline = datetime.fromisoformat(a.stop_at)
    if deadline.utcoffset() != timezone.utc.utcoffset(now) or not 0 < (deadline-now).total_seconds() <= 1800:
        raise ValueError('future UTC launch deadline within thirty minutes')
    C = ROOT/'contracts/ft'; op = read(C/(PREFIX+'_Protocol_v1.json'))
    binding = read(ROOT/op['binding_file']); frozen = read(C/(PREFIX+'_Source_Freeze_v1.json'))
    source = gate.freeze(); p = gate.protocol(); prior = {}
    for name in op['prior_operational_freezes']:
        f = read(C/name)
        if len(f) != 4 or set(f)&set(prior): raise ValueError('disjoint prior freezes')
        prior.update(f)
    if len(source) != 406 or len(prior) != 12 or source != binding['original_source'] or prior != binding['prior_operational_source']:
        raise ValueError('original406 and prior12 exact')
    if set(frozen) != {op['module'],op['binding_file'],'contracts/ft/'+PREFIX+'_Protocol_v1.json','contracts/ft/'+PREFIX+'_Protocol_v1.sha256'}:
        raise ValueError('four new operational identities')
    roots = {n:getattr(a,n) for n in ('original','prior1','prior2','recovered','recovery_operations','paid','capacity')}
    if set(roots) != set(binding['files']): raise ValueError('seven exact binding roots')
    if (a.output.name,a.operations.name) != (op['output'],op['operations']): raise ValueError('exact fresh names')
    for dest in (a.output,a.operations):
        if dest.exists() or any(dest==r or dest in r.parents or r in dest.parents for r in (*roots.values(),ROOT,a.public)):
            raise ValueError('fresh disjoint destinations')
    if a.output==a.operations or a.output in a.operations.parents or a.operations in a.output.parents: raise ValueError('distinct destinations')
    copied = {}
    def verify():
        if gate.freeze()!=source or any(sha(ROOT/n)!=h for n,h in {**prior,**frozen}.items()): raise ValueError('immutable source changed')
        if sha(C/(PREFIX+'_Protocol_v1.json')) != (C/(PREFIX+'_Protocol_v1.sha256')).read_text().split()[0]: raise ValueError('protocol hash')
        for label,entries in binding['files'].items():
            for n,h in entries.items():
                if Path(n).is_absolute() or '..' in Path(n).parts or sha(roots[label]/n)!=h: raise ValueError('bound evidence changed')
        if any(sha(a.output/n)!=h for n,h in copied.items()): raise ValueError('copied prefix changed')
    verify()
    for label in set(roots)-{'paid','capacity'}:
        if files(roots[label])!=binding['files'][label]: raise ValueError('complete prefix domain')
    for name,label in (('capacity_index.json','capacity'),('paid_index.json','paid')):
        idx=read(a.recovered/name)
        if sorted(r['key'] for r in idx)!=sorted(p['saved_records']) or {r['file']:r['sha256'] for r in idx}!=binding['files'][label]: raise ValueError('exact80raw inputs')
    if len(gate.records(SimpleNamespace(output=a.recovered),p,source))!=40 or read(a.recovered/'predecessor_ids.json')!=gate.predecessors(): raise ValueError('exact40 and484')
    passed=set()
    for path in (a.recovered/'methods').glob('*/result.json'):
        r=read(path); n=path.parent.name
        if n not in p['registered_tests'] or r['method']!=gate.METHOD+n or not r['passed'] or (r['methods'],r['errors'],r['failures'])!=(1,0,0) or r['source_freeze']!=source: raise ValueError('exact prior pass')
        passed.add(n)
    if len(passed)!=7 or set(p['registered_tests'])-passed!={op['method']}: raise ValueError('only unfinished original method')
    if (a.recovered/'summary.json').exists() or (a.recovered/'methods'/op['method']/'result.json').exists(): raise ValueError('no passing rerun')
    if not (a.recovered/'methods'/op['method']/'controls.log').is_file(): raise ValueError('preserved partial log')
    alljobs=[]
    for label in ('original','prior1','prior2','recovery_operations'):
        root=roots[label]; launches={x.name:read(x) for x in (root/'launches').glob('*.json')}; jobs={x.name:read(x) for x in (root/'jobs').glob('*.json')}
        if not set(jobs)<=set(launches): raise ValueError('job without launch')
        for n,j in jobs.items():
            if j['exit_code']!=0 or not j['passed'] or sha(root/j['log'])!=j['log_sha256'] or any(j[k]!=v for k,v in launches[n].items()): raise ValueError('exact closed parent job')
            alljobs.append((j['action'],j['target']))
        unclosed={(launches[n]['action'],launches[n]['target']) for n in set(launches)-set(jobs)}
        expected={('method',op['method']),('method','test_old_nominees_and_bounded_cells')} if label=='prior2' else {('method',op['method'])} if label=='recovery_operations' else set()
        if unclosed!=expected: raise ValueError('exact interrupted launch set')
        if label in ('prior2','recovery_operations'):
            if (root/'outcome.json').exists(): raise ValueError('unexpected interrupted outcome')
        else:
            outcome=read(root/'outcome.json'); order=lambda j:(j['action'],str(j['target']))
            if outcome['status']!='checkpoint' or outcome['active_children']!=0 or not outcome['source_unchanged'] or sorted(jobs.values(),key=order)!=sorted(outcome['jobs'],key=order): raise ValueError('exact closed original outcome')
    if len(alljobs)!=47 or len(set(alljobs))!=47 or {n for act,n in alljobs if act=='method'}!=passed or {n for act,n in alljobs if act=='record'}!=set(p['saved_records']): raise ValueError('unique47 closed target union')
    plan=read(a.recovery_operations/'plan.json')
    if any(sha(a.recovered/n)!=h for n,h in plan['copied_files'].items()): raise ValueError('recovery1 copied prefix')
    selfids={os.getpid(),int(Path('/proc/self').resolve().name)}; examined=0
    names={'evaluate_ft7_current_window_admission.py','continue_current_window_admission.py','continue_current_window_admission2.py','recover_current_window_admission_methods.py','recover_current_window_admission_forgery.py','finish_current_window_admission_recovery.py'}
    for proc in Path('/proc').iterdir():
        if not proc.name.isdigit() or int(proc.name) in selfids: continue
        try: args=(proc/'cmdline').read_bytes().split(b'\0'); examined+=1
        except FileNotFoundError: continue
        if any(Path(x.decode(errors='replace')).name in names for x in args if x): raise ValueError('surviving B1D worker')
    def allowed():
        s=read(a.public/'docs/FT_Run_State.json'); now=datetime.now(timezone.utc)
        return now<deadline and s['run_id']==a.owner and s['active_worker'] and s['status']=='running' and (datetime.fromisoformat(s['lease_expires_at'])-now).total_seconds()>op['lease_margin_seconds'] and not (a.operations/'STOP').exists()
    if not allowed(): raise ValueError('current lease/deadline')
    copied={n:h for n,h in binding['files']['recovered'].items() if not n.startswith('methods/'+op['method']+'/')}
    a.output.mkdir(); a.operations.mkdir()
    for n in copied:
        dest=a.output/n; dest.parent.mkdir(parents=True,exist_ok=True); shutil.copyfile(a.recovered/n,dest)
    verify(); write(a.operations/'plan.json',dict(owner=a.owner,stop_at=a.stop_at,method=op['method'],copied_files=copied,passed_methods=sorted(passed),source=source,freeze=frozen,binding_sha256=sha(ROOT/op['binding_file']),processes_examined=examined))
    if not allowed(): raise ValueError('lease/deadline before one method launch')
    cmd=[sys.executable,str(ROOT/'tools/evaluate_ft7_current_window_admission.py'),str(a.archives),str(a.paid),str(a.capacity),str(a.output),'method',op['method']]
    launch=dict(action='method',target=op['method'],command=cmd,started_utc=datetime.now(timezone.utc).isoformat(),log='method.log')
    write(a.operations/'launch.json',launch); print('START sole original forgery method',flush=True)
    with (a.operations/'method.log').open('x') as log: code=subprocess.run(cmd,stdout=log,stderr=subprocess.STDOUT).returncode
    job=dict(launch,exit_code=code,ended_utc=datetime.now(timezone.utc).isoformat(),log_sha256=sha(a.operations/'method.log'),passed=False)
    try:
        verify(); r=read(a.output/'methods'/op['method']/'result.json')
        if code!=0 or r['method']!=gate.METHOD+op['method'] or not r['passed'] or (r['methods'],r['errors'],r['failures'])!=(1,0,0) or r['source_freeze']!=source: raise ValueError('exact original body failed')
        job['passed']=True
    except Exception as error: job['error']=repr(error)
    write(a.operations/'job.json',job)
    write(a.operations/'outcome.json',dict(status='checkpoint' if job['passed'] else 'failed',active_children=0,job=job,gate_accepted=False,source_unchanged=gate.freeze()==source,aggregate_run=False))
    print('END sole original forgery method '+str(job['passed']),flush=True)
    if not job['passed']: raise SystemExit(1)

if __name__=='__main__': main()
