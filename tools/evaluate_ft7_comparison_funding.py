"""One bounded saved funding gate; no native commands or accepted test replay."""
import argparse,ast,copy,gzip,hashlib,json,pathlib,unittest
from datetime import datetime,timezone
from hle_unified import codec
from hle_unified.selection_records import dumps,loads
from full_theory.comparison_funding import comparison_funding,floor_status
from full_theory.comparison_funding_audit import audit_comparison_funding


def run():
    p=argparse.ArgumentParser();p.add_argument('a5');p.add_argument('a6');p.add_argument('output')
    p.add_argument('--public',required=True);p.add_argument('--owner',required=True);p.add_argument('--stop-at',required=True);a=p.parse_args()
    root=pathlib.Path(__file__).resolve().parents[1];out=pathlib.Path(a.output);out.mkdir(exist_ok=False)
    protocol=json.loads((root/'contracts/ft/FT7_Comparison_Funding_A7_Protocol_v1.json').read_text())
    freeze=json.loads((root/'contracts/ft/FT7_Comparison_Funding_A7_Source_Freeze_v1.json').read_text())
    sha=lambda v:hashlib.sha256(v.encode() if isinstance(v,str) else v).hexdigest()
    rows=[];probes=[];boundaries=[];costs=[]
    def note(kind,**kw):
        with (out/'events.jsonl').open('a') as f:f.write(json.dumps(dict(at=datetime.now(timezone.utc).isoformat(),kind=kind,**kw))+'\n');f.flush()
    def verify():
        for n,h in freeze.items():
            if sha((root/n).read_bytes())!=h:raise ValueError('source changed: '+n)
        old=json.loads((root/protocol['prior_freeze']).read_text())
        if len(old)!=487 or any(freeze.get(n)!=h for n,h in old.items()):raise ValueError('prior487 identities')
    def guard():
        s=json.loads((pathlib.Path(a.public)/'docs/FT_Run_State.json').read_text());now=datetime.now(timezone.utc)
        if s['run_id']!=a.owner or not s['active_worker'] or s['status']!='running' or now>=datetime.fromisoformat(s['lease_expires_at']) or now>=datetime.fromisoformat(a.stop_at):raise SystemExit('ownership/lease/deadline')
    def reject(setting,name,call):
        try:call()
        except ValueError:probes.append(dict(setting=setting,name=name,rejected=True))
        else:raise ValueError('forgery accepted '+name)
    try:
        verify();guard();note('start',owner=a.owner)
        # Preserve inherited extents; this inspects expressions, it does not call either ballot.
        expected=('1 + s[\'scanned\'] + s[\'foreign_total\'] + 33 + sum((x[\'examined\'] for x in rows))',
            '1 + len(s[\'items\']) + len(rows) + sum((x[\'examined\'] for x in rows))')
        normalized={ast.dump(ast.parse(e,mode='eval').body) for e in expected}
        for name,h in protocol['cost_sources'].items():
            text=(root/name).read_text()
            if sha(text)!=h:raise ValueError('inherited cost source identity')
            ballot=next(n for n in ast.parse(text).body if isinstance(n,ast.FunctionDef) and n.name=='ballot')
            expressions={ast.dump(n.value) for n in ast.walk(ballot) if isinstance(n,ast.Assign) and
                any(isinstance(t,ast.Name) and t.id=='required' for t in n.targets)}
            rejected=[k.value for n in ast.walk(ballot) if isinstance(n,ast.Call) and isinstance(n.func,ast.Name)
                and n.func.id=='dict' for k in n.keywords if k.arg=='required' and isinstance(k.value,ast.Constant)]
            if expressions!=normalized or len(rejected)!=1 or rejected[0].value!=1:raise ValueError('minimum unit cost proof changed')
            costs.append(dict(file=name,sha256=h,rejected_floor=1,successful_constant_floor=1,exact_expressions=True))
        for setting in ('canonical','workflow'):
            guard();_,native,_=codec.loads(gzip.decompress((pathlib.Path(a.a5)/(setting+'-complete.json.gz')).read_bytes()).decode())
            domain=gzip.decompress((pathlib.Path(a.a6)/(setting+'-complete.json.gz')).read_bytes()).decode()
            text=comparison_funding(native,domain,setting);data=loads(text)
            for label in ('complete','restored'):
                if label=='restored' and comparison_funding(native,domain,setting)!=text:raise ValueError('restored saved projection differs')
                filename=setting+'-'+label+'.json';(out/filename).write_text(text)
                note('raw_saved_before_audit',file=filename)
                saved=(out/filename).read_text();result=audit_comparison_funding(native,domain,setting,saved)
                rows.append(dict(record=label,file=filename,sha256=sha(saved),**result));print(json.dumps(rows[-1]),flush=True)
            for field,value in (('energy',data['energy']+1),('assignments',data['assignments']-1),('status','affordable'),
                    ('energy_deficit',data['energy_deficit']+1),('may_launch',True),('comparison_paid',True),('wallet',None),('extra',True)):
                bad=copy.deepcopy(data);bad[field]=value
                reject(setting,field,lambda bad=bad:audit_comparison_funding(native,domain,setting,dumps(bad)))
            for name,bn,bd in (('native_pair','forged',domain),('domain_pair',native,'forged')):
                reject(setting,name+'_builder',lambda bn=bn,bd=bd:comparison_funding(bn,bd,setting))
                reject(setting,name+'_auditor',lambda bn=bn,bd=bd:audit_comparison_funding(bn,bd,setting,text))
            (out/'progress.json').write_text(json.dumps(dict(records=rows,probes=probes),indent=2)+'\n')
        for count,energy,time in ((1,0,0),(1,1,1),(5,4,8),(5,8,4),(5,5,5),(5,9,9)):
            result=floor_status(count,energy,time);boundaries.append(dict(assignments=count,energy=energy,time=time,result=result))
        for name,values in (('bool',(True,1,1)),('zero',(0,1,1)),('negative_count',(-1,1,1)),('negative_wallet',(1,-1,1)),('float',(1,1,1.0))):
            reject('arithmetic',name,lambda values=values:floor_status(*values))
        guard();verify();note('methods_start')
        import tests_ft7.test_comparison_funding as tests
        tests.ROWS=rows;tests.PROBES=probes;tests.BOUNDARIES=boundaries;tests.COSTS=costs
        suite=unittest.defaultTestLoader.loadTestsFromModule(tests);actual=[t._testMethodName for group in suite for t in group]
        if sorted(actual)!=sorted(protocol['methods']):raise ValueError('method identities')
        with (out/'tests.log').open('w') as f:result=unittest.TextTestRunner(stream=f,verbosity=2).run(suite)
        if result.testsRun!=6 or not result.wasSuccessful():raise ValueError('six exact methods required')
        verify();summary=dict(passed=True,methods=actual,records=rows,probes=probes,boundaries=boundaries,cost_sources=costs,
            source_identities=len(freeze),prior_identities=487,native_work_calls=0,engine_restore_calls=0,accepted_stage_replays=0,parent_accepted=False)
        (out/'summary.json').write_text(json.dumps(summary,indent=2)+'\n');note('closed_pass');print('A7 passed',flush=True)
    except BaseException as e:note('closed_nonpass',error_type=type(e).__name__,message=str(e));raise


if __name__=='__main__':run()
