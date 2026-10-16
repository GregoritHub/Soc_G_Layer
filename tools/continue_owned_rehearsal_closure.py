"""Bounded A10R continuation: preserve original paid prefixes, finish missing controls."""
import argparse,gzip,json,pathlib,hashlib,gc,unittest,shutil
from datetime import datetime,timezone
from hle_unified import codec
from hle_unified.selection_records import loads,dumps
from full_theory.paid_window_comparison import PaidWorkflowWindowEngine
from full_theory.owned_content_rehearsal import OwnedContentRehearsal
from full_theory.owned_rehearsal_closure import RehearsalClosure,VERSION
from full_theory.owned_rehearsal_closure_audit import audit
from full_theory.owned_content_rehearsal_audit import baseline

def run():
 p=argparse.ArgumentParser();p.add_argument('a5');p.add_argument('original');p.add_argument('output');p.add_argument('--public',required=True);p.add_argument('--owner',required=True);p.add_argument('--stop-at',required=True);a=p.parse_args()
 root=pathlib.Path(__file__).resolve().parents[1];prior=pathlib.Path(a.original);out=pathlib.Path(a.output);out.mkdir(exist_ok=False)
 sha=lambda x:hashlib.sha256(x.encode() if type(x) is str else x).hexdigest()
 freeze=json.loads((root/'contracts/ft/FT7_Owned_Rehearsal_A10R_Source_Freeze_v1.json').read_text())
 binding=json.loads((root/'contracts/ft/FT7_Owned_Rehearsal_A10R_Closed_Binding_v1.json').read_text())
 def guard():
  now=datetime.now(timezone.utc);s=json.loads((pathlib.Path(a.public)/'docs/FT_Run_State.json').read_text())
  if s['run_id']!=a.owner or not s['active_worker'] or s['status']!='running' or now>=datetime.fromisoformat(s['lease_expires_at']) or now>=datetime.fromisoformat(a.stop_at):raise SystemExit('owner/lease/deadline')
 def verify():
  if any(sha((root/n).read_bytes())!=h for n,h in freeze.items()):raise ValueError('source changed')
  old=json.loads((root/'contracts/ft/FT7_Owned_Rehearsal_A10_Source_Freeze_v2.json').read_text())
  if len(old)!=526 or any(freeze.get(n)!=h for n,h in old.items()):raise ValueError('prior526')
  for directory,entries in binding['roots'].items():
   here=prior.parent/directory
   actual={x.relative_to(here).as_posix():sha(x.read_bytes()) for x in here.rglob('*') if x.is_file()}
   if actual!=entries:raise ValueError('closed root changed')
  for name,h in binding['files'].items():
   if sha((prior.parent/name).read_bytes())!=h:raise ValueError('closed input changed')
 def note(kind,**kw):
  with (out/'events.jsonl').open('a') as f:f.write(json.dumps(dict(at=datetime.now(timezone.utc).isoformat(),kind=kind,**kw))+'\n')
  print(kind,kw,flush=True)
 def read(path):
  text=gzip.decompress(path.read_bytes()).decode();value=codec.loads(text)
  if codec.dumps(value)!=text:raise ValueError('typed roundtrip')
  return value
 rows=[];probes=[];extra=[];restarts=[True]
 def write(label,native,text):
  raw=codec.dumps((label,native,text));path=out/('workflow-'+label+'.json.gz')
  path.write_bytes(gzip.compress(raw.encode(),mtime=0))
  if read(path)!=(label,native,text):raise ValueError('saved pair')
  return path
 def save(label,e,o):
  guard();n=e.checkpoint();t=o.checkpoint(e);path=write(label,n,t);note('audit_start',label=label)
  r=audit(e,original,adapter,'workflow',t);r.update(setting='workflow',label=label,file=path.name,sha256=sha(path.read_bytes()))
  rows.append(r);(out/'progress.json').write_text(json.dumps(rows,indent=2)+'\n');note('record_passed',label=label,energy=r['energy'])
 def reject(name,call,target):
  guard()
  try:call()
  except ValueError:target.append(name)
  else:raise ValueError('forgery accepted '+name)
 try:
  guard();verify()
  for proc in pathlib.Path('/proc').iterdir():
   if not proc.name.isdigit():continue
   try:cmd=(proc/'cmdline').read_bytes().split(b'\0')
   except (FileNotFoundError,ProcessLookupError):continue
   if cmd and pathlib.Path(cmd[0].decode()).name.startswith('python') and b'tools/evaluate_ft7_owned_content_rehearsal.py' in cmd:raise ValueError('original worker live')
  events=[json.loads(x) for x in (prior/'events.jsonl').read_text().splitlines()]
  if events[-1].get('kind')!='closed_nonpass' or events[-1].get('message')!='native output consumer required' or any(x['kind']=='methods_start' for x in events):raise ValueError('original outcome')
  oldrows=json.loads((prior/'progress.json').read_text())
  expected={(s,l) for s in ('canonical',) for l in ('before','partial','complete','restored','cancelled')}|{('workflow','before'),('workflow','partial')}
  if len(oldrows)!=7 or {(r['setting'],r['label']) for r in oldrows}!=expected:raise ValueError('seven original audits')
  shutil.copytree(prior,out/'original-preserved')
  for r in oldrows:
   path=prior/r['file']
   if sha(path.read_bytes())!=r['sha256'] or not any(x['kind']=='record_passed' and x['setting']==r['setting'] and x['label']==r['label'] for x in events):raise ValueError('original saved audit binding')
   label,native,base=read(path);text=dumps(dict(version=VERSION,base=base,rejections=[]));dest=out/r['file']
   dest.write_bytes(gzip.compress(codec.dumps((label,native,text)).encode(),mtime=0))
   if read(dest)!=(label,native,text):raise ValueError('wrapper typed roundtrip')
   row=dict(r,rejections=0,rejection_debit=0,sha256=sha(dest.read_bytes()),original_full_audit_preserved=True);rows.append(row)
  cc=read(out/'canonical-complete.json.gz');cr=read(out/'canonical-restored.json.gz')
  if cc[1:]!=cr[1:]:raise ValueError('canonical exact preserved restart')
  if not any(x['kind']=='restore_partial' and x['setting']=='canonical' for x in events):raise ValueError('original canonical forgery completion')
  probes.extend('canonical:'+key for key in ('main_execution_authorized','independent_credit','comparison_paid','index','plan','results','input-native','input-adapter'))
  _,original,adapter=read(pathlib.Path(a.a5)/'workflow-complete.json.gz')
  _,current,base=read(prior/'workflow-current.json.gz');b=loads(base)
  if b['index']!=5 or b['phase']!='rehearse' or len(b['plan'])!=6:raise ValueError('exact uncompleted suffix')
  note('restore_workflow_current');engine=PaidWorkflowWindowEngine.restore(current)
  obj=RehearsalClosure(OwnedContentRehearsal.restore(base,engine,original,adapter,'workflow'))
  guard();obj.step(engine)
  if obj.phase!='complete' or engine.checkpoint()!=current:raise ValueError('unpaid rejection only')
  save('complete',engine,obj);complete=(engine.checkpoint(),obj.checkpoint(engine))
  obj.step(engine)
  if (engine.checkpoint(),obj.checkpoint(engine))!=complete:raise ValueError('terminal mutation')
  wrapper=loads(complete[1]);base_data=loads(wrapper['base'])
  for key,value in (('main_execution_authorized',True),('independent_credit',True),('comparison_paid',True),('index',0),('plan',()),('results',[])):
   bad=dict(base_data);bad[key]=value;w=dict(wrapper,base=dumps(bad))
   reject('workflow:'+key,lambda w=w:audit(engine,original,adapter,'workflow',dumps(w)),probes)
  reject('workflow:input-native',lambda:audit(engine,original+' ',adapter,'workflow',complete[1]),probes)
  reject('workflow:input-adapter',lambda:audit(engine,original,adapter+' ','workflow',complete[1]),probes)
  for key,value in (('index',0),('source',None),('recipe','invalid'),('request_sha256','0'),('native_sha256','0'),('message','forged')):
   row=dict(wrapper['rejections'][0]);row[key]=value;w=dict(wrapper,rejections=[row])
   reject(key,lambda w=w:audit(engine,original,adapter,'workflow',dumps(w)),extra)
  (out/'probes.json').write_text(json.dumps(dict(original=probes,additional=extra),indent=2)+'\n')
  del engine,obj;gc.collect();guard()
  _,partial,partial_base=read(prior/'workflow-partial.json.gz')
  note('restore_workflow_partial');engine=PaidWorkflowWindowEngine.restore(partial)
  obj=RehearsalClosure(OwnedContentRehearsal.restore(partial_base,engine,original,adapter,'workflow'))
  for i in range(256):
   guard()
   if obj.phase=='complete':break
   obj.step(engine);write('current',engine.checkpoint(),obj.checkpoint(engine));note('restart_work',index=obj.base.index,phase=obj.phase)
  else:raise ValueError('step bound')
  if (engine.checkpoint(),obj.checkpoint(engine))!=complete:raise ValueError('workflow restart mismatch')
  restarts.append(True);save('restored',engine,obj)
  del engine,obj;gc.collect();guard();note('restore_workflow_cancel')
  engine=PaidWorkflowWindowEngine.restore(partial);obj=RehearsalClosure(OwnedContentRehearsal.restore(partial_base,engine,original,adapter,'workflow'))
  guard();obj.step(engine,cancel=True);save('cancelled',engine,obj)
  del engine,obj;baseline.cache_clear();gc.collect();guard();verify()
  import tests_ft7.test_owned_content_rehearsal as t
  import tests_ft7.test_owned_rehearsal_closure as u
  t.ROWS=rows;t.PROBES=probes;t.RESTARTS=restarts;u.EXTRA=extra;u.ROWS=rows
  suite=unittest.TestSuite([unittest.defaultTestLoader.loadTestsFromTestCase(t.RehearsalTests),unittest.defaultTestLoader.loadTestsFromTestCase(u.ClosureTests)])
  note('methods_start')
  with (out/'tests.log').open('w') as f:r=unittest.TextTestRunner(stream=f,verbosity=2).run(suite)
  if r.testsRun!=7 or not r.wasSuccessful():raise ValueError('seven-method gate')
  verify();guard()
  summary=dict(passed=True,methods=7,original_methods=6,records=rows,original_records_preserved=7,restarts_exact=restarts,original_forgery_rejections=probes,additional_rejection_forgeries=extra,
      source_identities=len(freeze),prior_identities=526,source_unchanged=True,original_main_paid_candidates_replayed=0,accepted_stages_replayed=0,
      main_execution_authorized=False,comparison_paid=False,independent_credit=False,parent_accepted=False)
  (out/'summary.json').write_text(json.dumps(summary,indent=2)+'\n');note('closed_pass')
 except BaseException as e:note('closed_nonpass',type=type(e).__name__,message=str(e));raise
if __name__=='__main__':run()
