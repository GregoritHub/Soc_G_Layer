"""A9 one bounded saved-input evaluation; no native work or prior stage replay."""
import argparse,gzip,hashlib,json,pathlib,unittest,gc
from datetime import datetime,timezone
from hle_unified import codec
from hle_unified.selection_records import loads,dumps
from hle.model_a import fields
from hle.development_structure import lap,portage
from full_theory.content import FACETS
from full_theory.universal_td5_veto import analyze,structural_veto
from full_theory.universal_td5_veto_audit import audit,reconstruct

def run():
    p=argparse.ArgumentParser();p.add_argument('a5');p.add_argument('a6');p.add_argument('capacity');p.add_argument('output')
    p.add_argument('--public',required=True);p.add_argument('--owner',required=True);p.add_argument('--stop-at',required=True);a=p.parse_args()
    root=pathlib.Path(__file__).resolve().parents[1];out=pathlib.Path(a.output);out.mkdir(exist_ok=False)
    sha=lambda x:hashlib.sha256(x.encode() if isinstance(x,str) else x).hexdigest()
    freeze=json.loads((root/'contracts/ft/FT7_Universal_TD5_Veto_A9_Source_Freeze_v1.json').read_text())
    protocol=json.loads((root/'contracts/ft/FT7_Universal_TD5_Veto_A9_Protocol_v1.json').read_text())
    def guard():
        now=datetime.now(timezone.utc);s=json.loads((pathlib.Path(a.public)/'docs/FT_Run_State.json').read_text())
        if s['run_id']!=a.owner or not s['active_worker'] or s['status']!='running' or now>=datetime.fromisoformat(s['lease_expires_at']) or now>=datetime.fromisoformat(a.stop_at):raise SystemExit('owner/lease/deadline')
    def verify():
        for n,h in freeze.items():
            if sha((root/n).read_bytes())!=h:raise ValueError('source changed: '+n)
        prior=json.loads((root/protocol['prior_freeze']).read_text())
        if len(prior)!=510 or any(freeze.get(n)!=h for n,h in prior.items()):raise ValueError('prior510 identities')
    def note(kind,**kw):
        with (out/'events.jsonl').open('a') as f:f.write(json.dumps(dict(at=datetime.now(timezone.utc).isoformat(),kind=kind,**kw))+'\n')
        print(kind,kw,flush=True)
    rows=[];probes=[];boundaries=[]
    def reject(name,call):
        try:call()
        except ValueError:probes.append(name)
        else:raise ValueError('forgery accepted: '+name)
    try:
        guard();verify();note('start',owner=a.owner)
        for setting in ('canonical','workflow'):
            guard();_,native,_=codec.loads(gzip.decompress((pathlib.Path(a.a5)/(setting+'-complete.json.gz')).read_bytes()).decode())
            domain=gzip.decompress((pathlib.Path(a.a6)/(setting+'-complete.json.gz')).read_bytes()).decode()
            _,_,capacity=codec.loads(gzip.decompress((pathlib.Path(a.capacity)/(setting+'-mask-1.json.gz')).read_bytes()).decode())
            note('construct',setting=setting);text=analyze(native,domain,capacity,setting);note('constructed',setting=setting)
            for label in ('complete','restored'):
                saved=text if label=='complete' else dumps(loads(text))
                if saved!=text:raise ValueError('typed roundtrip')
                file=setting+'-'+label+'.json';(out/file).write_text(saved)
                result=audit(native,domain,capacity,setting,(out/file).read_text())
                z=loads(saved)
                result.update(record=label,file=file,sha256=sha((out/file).read_bytes()),
                    authority_false=all(z[k] is False for k in ('may_launch','comparison_paid','execution_authorized','td5_admitted','history_choice','completion_claim','parent_accepted')),
                    no_pruning=z['domain_pruned'] is False)
                rows.append(result);note('record_passed',setting=setting,record=label)
            z=loads(text)
            mutations=[('covered_assignments',1),('all_work_ineligible',False),('status','admitted'),('domain_pruned',True),
                ('may_launch',True),('comparison_paid',True),('td5_admitted',True),('origin_seat',1),
                ('recall',dict(z['recall'],truncated=False)),('blocked',dict(z['blocked'],ordinary=False)),
                ('required',dict(z['required'],requirements=('experience',))),('certificates',())]
            for name,value in mutations:
                bad=dict(z);bad[name]=value
                reject(setting+':'+name,lambda bad=bad:audit(native,domain,capacity,setting,dumps(bad)))
            for index in range(3):
                args=[native,domain,capacity];args[index]='forged'
                reject(setting+':input'+str(index)+':runtime',lambda args=args:analyze(*args,setting))
                reject(setting+':input'+str(index)+':auditor',lambda args=args:audit(*args,setting,text))
            reconstruct.cache_clear();del native,domain,capacity,text;gc.collect();guard()
        for seat in range(1,9):
            for count in range(1,5):
                for truncated in (False,True):
                    for support in ((),('hypothetical-peer',)):
                        requirements=tuple(FACETS[:count]);got=structural_veto(seat,requirements,truncated,support)
                        expected=dict(retained=truncated or fields(seat)['dimensionality']<count,
                            ordinary=fields(lap(seat))['dimensionality']<count,n=fields(portage(seat,'n'))['dimensionality']<count,
                            cp=fields(portage(seat,'cp'))['dimensionality']<count,support=len(support)==0)
                        if got!=expected:raise ValueError('boundary truth differs')
                        boundaries.append(dict(seat=seat,facets=count,truncated=truncated,support=bool(support),veto=all(got.values()),passed=True))
        import tests_ft7.test_universal_td5_veto as t
        t.ROWS=rows;t.PROBES=probes;t.BOUNDARIES=boundaries
        suite=unittest.defaultTestLoader.loadTestsFromModule(t)
        methods=[x._testMethodName for group in suite for x in group]
        if sorted(methods)!=sorted(protocol['methods']):raise ValueError('exact method IDs')
        guard();note('methods_start')
        with (out/'tests.log').open('w') as f:result=unittest.TextTestRunner(stream=f,verbosity=2).run(suite)
        if result.testsRun!=6 or not result.wasSuccessful():raise ValueError('six exact methods')
        verify();guard()
        summary=dict(passed=True,methods=methods,records=rows,forgery_rejections=probes,boundary_cases=boundaries,
            frozen_identities=len(freeze),prior_identities=510,native_commands=0,native_view_calls=0,engine_restores=0,
            accepted_stage_replays=0,source_unchanged=True,comparison_paid=False,parent_accepted=False)
        (out/'summary.json').write_text(json.dumps(summary,indent=2)+'\n');note('closed_pass')
    except BaseException as e:note('closed_nonpass',type=type(e).__name__,message=str(e));raise

if __name__=='__main__':run()
