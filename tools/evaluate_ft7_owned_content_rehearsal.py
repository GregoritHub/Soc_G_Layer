"""One bounded A10 execution, exact saved records and independent native audits."""
import argparse,gzip,hashlib,json,pathlib,gc,unittest
from datetime import datetime,timezone
from hle_unified import codec
from hle_unified.selection_records import dumps,loads
from hle_unified.selection_execution import SelectionEngine
from hle_unified.workflow_selection_execution import WorkflowFinalSelectionEngine
from full_theory.owned_content_rehearsal import OwnedContentRehearsal
from full_theory.owned_content_rehearsal_audit import audit,baseline

def run():
    p=argparse.ArgumentParser();p.add_argument('a5');p.add_argument('output');p.add_argument('--public',required=True);p.add_argument('--owner',required=True);p.add_argument('--stop-at',required=True);a=p.parse_args()
    root=pathlib.Path(__file__).resolve().parents[1];out=pathlib.Path(a.output);out.mkdir(exist_ok=False)
    freeze=json.loads((root/'contracts/ft/FT7_Owned_Rehearsal_A10_Source_Freeze_v1.json').read_text())
    protocol=json.loads((root/'contracts/ft/FT7_Owned_Rehearsal_A10_Protocol_v1.json').read_text())
    sha=lambda x:hashlib.sha256(x.encode() if isinstance(x,str) else x).hexdigest()
    def guard():
        now=datetime.now(timezone.utc);s=json.loads((pathlib.Path(a.public)/'docs/FT_Run_State.json').read_text())
        if s['run_id']!=a.owner or not s['active_worker'] or s['status']!='running' or now>=datetime.fromisoformat(s['lease_expires_at']) or now>=datetime.fromisoformat(a.stop_at):raise SystemExit('owner/lease/deadline')
    def verify():
        if any(sha((root/n).read_bytes())!=h for n,h in freeze.items()):raise ValueError('source changed')
        prior=json.loads((root/protocol['prior_freeze']).read_text())
        if len(prior)!=517 or any(freeze.get(n)!=h for n,h in prior.items()):raise ValueError('prior517 mismatch')
    def note(kind,**kw):
        with (out/'events.jsonl').open('a') as f:f.write(json.dumps(dict(at=datetime.now(timezone.utc).isoformat(),kind=kind,**kw))+'\n')
        print(kind,kw,flush=True)
    rows=[];probes=[];restarts=[]
    def reject(name,call):
        try:call()
        except ValueError:probes.append(name)
        else:raise ValueError('forgery accepted '+name)
    try:
        guard();verify();note('start',owner=a.owner)
        for setting,typ in (('canonical',SelectionEngine),('workflow',WorkflowFinalSelectionEngine)):
            guard();_,original,adapter=codec.loads(gzip.decompress((pathlib.Path(a.a5)/(setting+'-complete.json.gz')).read_bytes()).decode())
            note('restore_original',setting=setting);engine=typ.restore(original);obj=OwnedContentRehearsal(engine,adapter,setting)
            def save(label,e,o):
                guard();n=e.checkpoint();text=o.checkpoint(e);raw=codec.dumps((label,n,text))
                file=setting+'-'+label+'.json.gz';(out/file).write_bytes(gzip.compress(raw.encode(),mtime=0))
                back=codec.loads(gzip.decompress((out/file).read_bytes()).decode())
                if back!=(label,n,text) or codec.dumps(back)!=raw:raise ValueError('typed saved roundtrip')
                note('audit_start',setting=setting,label=label)
                result=audit(e,original,adapter,setting,back[2]);result.update(setting=setting,label=label,file=file,sha256=sha((out/file).read_bytes()))
                rows.append(result);note('record_passed',setting=setting,label=label,energy=result['energy'])
            save('before',engine,obj)
            obj.step(engine,work_limit=1);save('partial',engine,obj)
            partial_native=engine.checkpoint();partial_text=obj.checkpoint(engine)
            def finish(e,o):
                for step in range(256):
                    guard()
                    if o.phase in ('complete','cancelled'):return
                    o.step(e,work_limit=1000000);note('work',setting=setting,index=o.index,phase=o.phase)
                raise ValueError('step bound')
            finish(engine,obj);save('complete',engine,obj);complete_native=engine.checkpoint();complete_text=obj.checkpoint(engine)
            terminal=(complete_native,complete_text);obj.step(engine)
            if terminal!=(engine.checkpoint(),obj.checkpoint(engine)):raise ValueError('terminal mutation')
            bad=loads(complete_text)
            for key,value in (('main_execution_authorized',True),('independent_credit',True),('comparison_paid',True),('index',0),('plan',()),('results',[])):
                altered=dict(bad);altered[key]=value
                reject(setting+':'+key,lambda altered=altered:audit(engine,original,adapter,setting,dumps(altered)))
            reject(setting+':input-native',lambda:audit(engine,original+' ',adapter,setting,complete_text))
            reject(setting+':input-adapter',lambda:audit(engine,original,adapter+' ',setting,complete_text))
            del engine,obj;gc.collect();guard()
            note('restore_partial',setting=setting);engine=typ.restore(partial_native);obj=OwnedContentRehearsal.restore(partial_text,engine,original,adapter,setting)
            finish(engine,obj)
            exact=(engine.checkpoint(),obj.checkpoint(engine))==(complete_native,complete_text)
            if not exact:raise ValueError('restart bytes differ')
            restarts.append(exact);save('restored',engine,obj)
            del engine,obj;gc.collect();guard()
            engine=typ.restore(partial_native);obj=OwnedContentRehearsal.restore(partial_text,engine,original,adapter,setting)
            obj.step(engine,cancel=True);save('cancelled',engine,obj)
            del engine,obj,original,adapter,partial_native,partial_text,complete_native,complete_text;baseline.cache_clear();gc.collect()
        import tests_ft7.test_owned_content_rehearsal as t
        t.ROWS=rows;t.PROBES=probes;t.RESTARTS=restarts
        suite=unittest.defaultTestLoader.loadTestsFromModule(t);methods=[x._testMethodName for group in suite for x in group]
        if sorted(methods)!=sorted(protocol['methods']):raise ValueError('exact six method IDs')
        guard();note('methods_start')
        with (out/'tests.log').open('w') as f:r=unittest.TextTestRunner(stream=f,verbosity=2).run(suite)
        if r.testsRun!=6 or not r.wasSuccessful():raise ValueError('method gate')
        verify();guard()
        summary=dict(passed=True,methods=methods,records=rows,restarts_exact=restarts,forgery_rejections=probes,
            source_identities=len(freeze),prior_identities=517,source_unchanged=True,accepted_stages_replayed=0,
            main_execution_authorized=False,comparison_paid=False,independent_credit=False,parent_accepted=False)
        (out/'summary.json').write_text(json.dumps(summary,indent=2)+'\n');note('closed_pass')
    except BaseException as e:note('closed_nonpass',type=type(e).__name__,message=str(e));raise
if __name__=='__main__':run()
