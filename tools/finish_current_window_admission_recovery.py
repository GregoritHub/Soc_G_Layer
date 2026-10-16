"""Conditional unchanged aggregate only, after exact method recovery quiescence."""
from pathlib import Path
from datetime import datetime,timezone
from types import SimpleNamespace
import argparse,hashlib,json,os,shutil,subprocess,sys
ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT),str(ROOT/'baseline/HLE_Rebuild_R21B')]
from tools import evaluate_ft7_current_window_admission as gate
PREFIX=gate.PREFIX+'_Recovered_Finish1'
def read(p):return json.loads(p.read_text())
def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def files(p):return {str(x.relative_to(p)):sha(x) for x in p.rglob('*') if x.is_file()}
def write(p,d):
 p.parent.mkdir(parents=True,exist_ok=True)
 with p.open('x') as f:f.write(json.dumps(d,indent=2,sort_keys=True)+'\n')
def main():
 parser=argparse.ArgumentParser()
 for n in ('archives','paid','capacity','original','prior1','prior2','recovered','recovery_operations','output','operations','public'):parser.add_argument(n,type=lambda s:Path(s).resolve())
 parser.add_argument('--owner',required=True);parser.add_argument('--stop-at',required=True);a=parser.parse_args()
 now=datetime.now(timezone.utc);deadline=datetime.fromisoformat(a.stop_at)
 if deadline.utcoffset()!=timezone.utc.utcoffset(now) or not 0<(deadline-now).total_seconds()<=1800:raise ValueError('future UTC deadline within30minutes')
 C=ROOT/'contracts/ft';op=read(C/(PREFIX+'_Protocol_v1.json'));bound=read(ROOT/op['binding_file']);freeze=read(C/(PREFIX+'_Source_Freeze_v1.json'))
 source=gate.freeze();oldops={}
 for suffix in ('_Continuation_Source_Freeze_v1.json','_Continuation2_Source_Freeze_v1.json','_Method_Recovery1_Source_Freeze_v1.json'):
  f=read(C/(gate.PREFIX+suffix))
  if len(f)!=4 or set(oldops)&set(f):raise ValueError('exact prior disjoint operational freezes')
  oldops.update(f)
 if len(source)!=406 or source!=bound['original_source'] or oldops!=bound['prior_operational_source']:raise ValueError('exact original/prior source binding')
 if set(freeze)!={op['module'],op['binding_file'],'contracts/ft/'+PREFIX+'_Protocol_v1.json','contracts/ft/'+PREFIX+'_Protocol_v1.sha256'}:raise ValueError('four exact finalizer identities')
 roots={n:getattr(a,n) for n in ('original','prior1','prior2','paid','capacity','recovered','recovery_operations')}
 if set(roots)!=set(bound['files']):raise ValueError('complete seven binding roots')
 if (a.output.name,a.operations.name)!=(op['output'],op['operations']):raise ValueError('exact fresh names')
 protected=tuple(roots.values())+(ROOT,a.public)
 for dest in (a.output,a.operations):
  if dest.exists() or any(dest==x or dest in x.parents or x in dest.parents for x in protected):raise ValueError('fresh disjoint outputs')
 if a.output==a.operations or a.output in a.operations.parents or a.operations in a.output.parents:raise ValueError('separate fresh destinations')
 copied={}
 def verify():
  if gate.freeze()!=source or any(sha(ROOT/n)!=h for n,h in {**oldops,**freeze}.items()):raise ValueError('immutable source changed')
  if sha(C/(PREFIX+'_Protocol_v1.json'))!=(C/(PREFIX+'_Protocol_v1.sha256')).read_text().split()[0]:raise ValueError('protocol hash')
  for label,entries in bound['files'].items():
   for n,h in entries.items():
    if Path(n).is_absolute() or '..' in Path(n).parts or sha(roots[label]/n)!=h:raise ValueError('bound prior/input changed')
  if any(sha(a.output/n)!=h for n,h in copied.items()):raise ValueError('copied prefix changed')
 verify()
 for label in set(roots)-{'paid','capacity'}:
  if files(roots[label])!=bound['files'][label]:raise ValueError('complete prefix file domain')
 for n in ('summary.json','method_ids.json','record_index.json'):
  if (a.recovered/n).exists():raise ValueError('aggregate cannot rerun')
 p=gate.protocol();rows=gate.records(SimpleNamespace(output=a.recovered),p,source)
 if len(rows)!=40 or read(a.recovered/'predecessor_ids.json')!=gate.predecessors():raise ValueError('exact40records/484identities')
 for name in p['registered_tests']:
  r=read(a.recovered/'methods'/name/'result.json')
  if r['method']!=gate.METHOD+name or not r['passed'] or (r['methods'],r['failures'],r['errors'])!=(1,0,0) or r['source_freeze']!=source:raise ValueError('all eight exact passed original bodies')
 outcome=read(a.recovery_operations/'outcome.json');plan=read(a.recovery_operations/'plan.json')
 if outcome['status']!='checkpoint' or outcome['active_children']!=0 or not outcome['source_unchanged'] or outcome['gate_accepted']:raise ValueError('quiescent unaggregated checkpoint required')
 launches={x.name:read(x) for x in (a.recovery_operations/'launches').glob('*.json')};jobs={x.name:read(x) for x in (a.recovery_operations/'jobs').glob('*.json')}
 if set(launches)!=set(jobs) or len(jobs)!=3 or {x['target'] for x in jobs.values()}!=set(plan['methods']):raise ValueError('exact three closed recovery methods')
 for n,j in jobs.items():
  if j['action']!='method' or not j['passed'] or j['exit_code']!=0 or sha(a.recovery_operations/j['log'])!=j['log_sha256'] or any(j[k]!=v for k,v in launches[n].items()):raise ValueError('closed exit-zero recovery job')
 if sorted(jobs.values(),key=lambda x:x['target'])!=sorted(outcome['jobs'],key=lambda x:x['target']):raise ValueError('exact recovery outcome')
 for n,h in plan['copied_files'].items():
  if sha(a.recovered/n)!=h:raise ValueError('original copied prefix')
 selfids={os.getpid(),int(Path('/proc/self').resolve().name)};examined=0
 targets={'evaluate_ft7_current_window_admission.py','continue_current_window_admission.py','continue_current_window_admission2.py','recover_current_window_admission_methods.py','finish_current_window_admission_recovery.py'}
 for proc in Path('/proc').iterdir():
  if not proc.name.isdigit() or int(proc.name) in selfids:continue
  try:args=(proc/'cmdline').read_bytes().split(b'\0');examined+=1
  except FileNotFoundError:continue
  if any(Path(x.decode(errors='replace')).name in targets for x in args if x):raise ValueError('surviving B1D process')
 def ownership():
  s=read(a.public/'docs/FT_Run_State.json');now=datetime.now(timezone.utc)
  return now<deadline and s['run_id']==a.owner and s['status']=='running' and s['active_worker'] and (datetime.fromisoformat(s['lease_expires_at'])-now).total_seconds()>op['lease_margin_seconds']
 if not ownership():raise ValueError('current running lease and launch deadline')
 a.output.mkdir();a.operations.mkdir();copied=dict(bound['files']['recovered'])
 for n,h in copied.items():
  dest=a.output/n;dest.parent.mkdir(parents=True,exist_ok=True);shutil.copyfile(a.recovered/n,dest)
 verify();write(a.operations/'plan.json',dict(owner=a.owner,source=source,freeze=freeze,binding_sha256=sha(ROOT/op['binding_file']),copied_files=copied,processes_examined=examined,stop_at=deadline.isoformat()))
 if not ownership():raise ValueError('lease/deadline before single finish')
 cmd=[sys.executable,str(ROOT/'tools/evaluate_ft7_current_window_admission.py'),str(a.archives),str(a.paid),str(a.capacity),str(a.output),'finish']
 launch=dict(action='finish',command=cmd,started_utc=datetime.now(timezone.utc).isoformat(),log='finish.log')
 write(a.operations/'launch.json',launch);print('START unchanged finish',flush=True)
 with (a.operations/'finish.log').open('x') as log:code=subprocess.run(cmd,stdout=log,stderr=subprocess.STDOUT).returncode
 job=dict(launch,exit_code=code,ended_utc=datetime.now(timezone.utc).isoformat(),log_sha256=sha(a.operations/'finish.log'),passed=False)
 try:
  verify();s=read(a.output/'summary.json')
  if code or not s['passed'] or (s['methods'],s['saved_records'],s['predecessor_identities'],s['frozen_identities'],s['prior_identities'],s['errors'],s['failures'],s['native_unchanged'],s['new_native_work'])!=(8,40,484,406,399,0,0,True,False):raise ValueError('unchanged final aggregate failed')
  job['passed']=True
 except Exception as error:job['error']=repr(error)
 write(a.operations/'job.json',job);write(a.operations/'outcome.json',dict(status='passed' if job['passed'] else 'failed',active_children=0,job=job,source_unchanged=gate.freeze()==source))
 print('END unchanged finish '+str(job['passed']),flush=True)
 if not job['passed']:raise SystemExit(1)
if __name__=='__main__':main()

