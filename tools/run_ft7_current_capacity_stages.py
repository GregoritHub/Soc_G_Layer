"""Bounded operational runner over unchanged, disjoint frozen capacity stages."""
from pathlib import Path
from datetime import datetime,timezone
import argparse,hashlib,json,os,subprocess,sys,time
PREFIX='FT7_1b2b3b2b2b2b2b2b1c'
METHOD='tests_ft7.test_current_window_capacity.CurrentWindowCapacityTests.'
def read(p):return json.loads(p.read_text())
def sha(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def stamp():return datetime.now(timezone.utc).isoformat()
def write(p,data):
    p.parent.mkdir(parents=True,exist_ok=True)
    with p.open('x') as f:f.write(json.dumps(data,indent=2,sort_keys=True)+'\n')

class Runner:
    def __init__(self,a):
        self.a=a;self.p=read(a.public/'contracts/ft'/(PREFIX+'_Bounded_Process_Protocol_v1.json'))
        self.original=read(a.runtime/'contracts/ft'/(PREFIX+'_Protocol_v1.json'))
        self.freeze=read(a.runtime/'contracts/ft'/(PREFIX+'_Source_Freeze_v1.json'))
        self.operational=read(a.public/'contracts/ft'/(PREFIX+'_Bounded_Process_Freeze_v1.json'))
        self.failed=False;self.stop_reason=None;self.jobs=[]
        self.run=a.archives/self.p['execution']['directory']
    def identities(self):
        assert len(self.freeze)==399
        assert sha(self.a.runtime/'contracts/ft'/(PREFIX+'_Source_Freeze_v1.json'))==self.p['source_freeze_sha256']
        for n,h in self.freeze.items():assert sha(self.a.runtime/n)==h,n
        for n,h in self.operational.items():assert sha(self.a.public/n)==h,n
        for n,h in self.p['bound_output_files'].items():assert sha(self.a.output/n)==h,n
        for r in read(self.a.output/'input_index.json'):assert sha(self.a.paid/r['file'])==r['sha256'],r['key']
    def record(self,key):
        r=read(self.a.output/'stages'/(key.replace('/','-')+'.json'))
        assert r['key']==key and r['passed'] and r['typed_roundtrip_exact'] and r['independent_audit']['passed']
        assert r['source_freeze']==self.freeze and sha(self.a.output/r['file'])==r['sha256']
    def method(self,name):
        r=read(self.a.output/'methods'/name/'result.json')
        assert r['method']==METHOD+name and r['passed']
        assert (r['methods'],r['failures'],r['errors'])==(1,0,0) and r['source_freeze']==self.freeze
    def launch_allowed(self):
        if self.failed:self.stop_reason='a child or verification failed';return False
        if (self.run/'STOP').exists():self.stop_reason='cooperative STOP checkpoint';return False
        now=datetime.now(timezone.utc)
        if now>=datetime.fromisoformat(self.p['execution']['stop_before_utc']):
            self.stop_reason='prospective wall-clock checkpoint';return False
        s=read(self.a.public/'docs/FT_Run_State.json')
        if s['run_id']!=self.a.owner or not s['active_worker'] or s['status']!='running':
            self.stop_reason='ownership unavailable';return False
        expiry=datetime.fromisoformat(s['lease_expires_at'])
        if (expiry-now).total_seconds()<=self.p['execution']['lease_margin_seconds']:
            self.stop_reason='lease safety margin';return False
        return True
    def phase(self,action,targets,workers):
        todo=list(targets);active={};done=[]
        while todo or active:
            while todo and len(active)<workers and self.launch_allowed():
                target=todo.pop(0);label=action+('-'+target.replace('/','-') if target else '')
                log=self.run/'logs'/(label+'.log');log.parent.mkdir(exist_ok=True)
                if action=='record':assert not (self.a.output/'stages'/(target.replace('/','-')+'.json')).exists()
                if action=='method':assert not (self.a.output/'methods'/target).exists()
                command=[sys.executable,str(self.a.runtime/self.p['frozen_evaluator']),str(self.a.archives),
                    str(self.a.paid),str(self.a.output),action]+([target] if target else [])
                job=dict(action=action,target=target,command=command,started_utc=stamp(),log=str(log.relative_to(self.run)))
                stream=log.open('x')
                try:child=subprocess.Popen(command,stdout=stream,stderr=subprocess.STDOUT)
                except BaseException:stream.close();raise
                active[child]=(stream,job);write(self.run/'launches'/(label+'.json'),job)
                print('START '+label,flush=True)
            if not active:break
            time.sleep(0.5)
            for child,(stream,job) in list(active.items()):
                code=child.poll()
                if code is None:continue
                stream.close();del active[child]
                label=job['action']+('-'+job['target'].replace('/','-') if job['target'] else '')
                job.update(ended_utc=stamp(),exit_code=code,log_sha256=sha(self.run/job['log']),passed=False)
                try:
                    assert code==0,('child exit',code)
                    if action=='record':self.record(job['target'])
                    elif action=='method':self.method(job['target'])
                    else:
                        s=read(self.a.output/'summary.json')
                        assert s['passed'] and (s['methods'],s['saved_records'],s['predecessor_identities'],s['frozen_identities'])==(8,40,476,399)
                    self.identities();job['passed']=True;done.append(job['target'])
                except BaseException as e:self.failed=True;job['verification_error']=repr(e)
                self.jobs.append(job);write(self.run/'results'/(label+'.json'),job)
                print('END '+label+' exit='+str(code)+' verified='+str(job['passed']),flush=True)
        return len(done)==len(targets) and not self.failed
    def execute(self):
        self.identities()
        for key in self.p['completed_records']:self.record(key)
        for key in self.p['pending_records']:
            assert not (self.a.output/'records'/(key.replace('/','-')+'.json.gz')).exists()
            assert not (self.a.output/'stages'/(key.replace('/','-')+'.json')).exists()
        assert not list((self.a.output/'methods').glob('*/result.json'))
        own=Path('/proc/self').resolve()
        for proc in Path('/proc').iterdir():
            if not proc.name.isdigit() or proc==own:continue
            try:argv=(proc/'cmdline').read_bytes().split(b'\0')
            except (FileNotFoundError,PermissionError):continue
            if len(argv)>1:
                name=argv[1].decode(errors='replace')
                assert not name.endswith('/'+self.p['frozen_evaluator']),name
                assert not name.endswith('/tools/run_ft7_current_capacity_stages.py'),name
        if self.a.inspect:
            print(json.dumps(dict(passed=True,prior_bound_files=len(self.p['bound_output_files']),completed=24,pending=16,source=399)))
            return
        self.run.mkdir(exist_ok=False)
        write(self.run/'entry.json',dict(owner=self.a.owner,started_utc=stamp(),protocol=self.p,operational_freeze=self.operational))
        complete=self.phase('record',self.p['pending_records'],self.p['execution']['record_workers'])
        if complete:
            for key in self.original['saved_records']:self.record(key)
            complete=self.phase('method',self.original['registered_tests'],self.p['execution']['method_workers'])
        if complete:
            for name in self.original['registered_tests']:self.method(name)
            complete=self.phase('finish',[None],1)
        self.identities()
        report=dict(status='failed' if self.failed else 'passed' if complete else 'checkpoint',
            completed_utc=stamp(),stop_reason=self.stop_reason,active_children=0,jobs=self.jobs,
            source_unchanged=True,prior_output_files_exact=True,new_native_work=False,
            gate_accepted=complete and not self.failed)
        write(self.run/'outcome.json',report);print(json.dumps({k:v for k,v in report.items() if k!='jobs'}),flush=True)
        if self.failed:raise SystemExit(1)

def main():
    p=argparse.ArgumentParser()
    for n in ('public','runtime','archives','paid','output'):p.add_argument(n,type=lambda x:Path(x).resolve())
    p.add_argument('--owner',required=True);p.add_argument('--inspect',action='store_true')
    Runner(p.parse_args()).execute()
if __name__=='__main__':main()
