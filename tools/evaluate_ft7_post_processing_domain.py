"""A12E1 saved-access projection gate; no native engine restore or work."""
import argparse,copy,gc,gzip,hashlib,itertools,json,pathlib,unittest
from datetime import datetime,timezone
from math import prod
from hle_unified import codec
from hle_unified.compact import unseal
from hle_unified.operations import NativeAccess
from hle_unified.selection_records import loads,dumps,fields_of
from full_theory.post_processing_domain import post_processing_domain,request_at,coordinates,ordinal_of
from full_theory.post_processing_domain_audit import audit_post_processing_domain,reconstruct
from tools.evaluate_ft7_cue_comparison import write,js,read
ROOT=pathlib.Path(__file__).resolve().parents[1]
def sha(v):return hashlib.sha256(v.encode() if isinstance(v,str) else v).hexdigest()
def main():
    p=argparse.ArgumentParser();p.add_argument('current');p.add_argument('sources');p.add_argument('output');p.add_argument('--public',required=True);p.add_argument('--owner',required=True);p.add_argument('--stop-at',required=True);a=p.parse_args()
    current=pathlib.Path(a.current);sources=pathlib.Path(a.sources);out=pathlib.Path(a.output);out.mkdir(exist_ok=False)
    for n in ('records','records-backup','audits','jobs','identities'):(out/n).mkdir()
    protocol=json.loads((ROOT/'contracts/ft/FT7_Post_Processing_Domain_A12E1_Protocol_v1.json').read_text());source_protocol=json.loads((ROOT/'contracts/ft/FT7_Cue_Processing_Panel_A12D2_Protocol_v1.json').read_text())
    freeze=json.loads((ROOT/'contracts/ft/FT7_Post_Processing_Domain_A12E1_Source_Freeze_v1.json').read_text());prior=json.loads((ROOT/protocol['prior_source_freeze']).read_text())
    rows=[];probes=[];indices=[];identities=[];algebra=[]
    def guard(launch=False):
        s=json.loads((pathlib.Path(a.public)/'docs/FT_Run_State.json').read_text());now=datetime.now(timezone.utc);limit=min(datetime.fromisoformat(s['lease_expires_at']),datetime.fromisoformat(a.stop_at))
        if s['run_id']!=a.owner or not s['active_worker'] or s['status']!='running' or (limit-now).total_seconds()<(300 if launch else 0):raise ValueError('ownership/deadline')
    def verify():
        if len(prior)!=594 or any(freeze.get(n)!=h for n,h in prior.items()):raise ValueError('predecessor identities')
        for n,h in freeze.items():
            if sha((ROOT/n).read_bytes())!=h:raise ValueError('frozen source '+n)
    def job(name,call):
        js(out/'jobs'/(name+'.start.json'),dict(job=name,owner=a.owner,started=datetime.now(timezone.utc).isoformat()))
        try:r=call();js(out/'jobs'/(name+'.outcome.json'),dict(passed=True,ended=datetime.now(timezone.utc).isoformat(),result=r));return r
        except BaseException as e:js(out/'jobs'/(name+'.failure.json'),dict(error_type=type(e).__name__,message=str(e),ended=datetime.now(timezone.utc).isoformat()));raise
    def reject(setting,name,call):
        try:call()
        except (ValueError,TypeError):probes.append(dict(setting=setting,name=name,rejected=True))
        else:raise ValueError('forgery accepted '+setting+'/'+name)
    guard(True);verify()
    contexts={}
    for setting in ('canonical','workflow'):
        for mask in range(1,16):
            guard();key=f'{setting}-{mask:02d}';entry=protocol['inputs'][key];src=source_protocol['inputs'][key]
            raw=(current/entry['path']).read_bytes()
            if sha(raw)!=entry['raw_sha256']:raise ValueError('current raw '+key)
            row=codec.loads(gzip.decompress(raw).decode())
            if len(row)!=entry['raw_arity']:raise ValueError('raw provenance')
            native=row[2] if len(row)==4 else row[3];adapter=row[3] if len(row)==4 else row[4]
            if (sha(native),sha(adapter))!=(entry['native_sha256'],entry['adapter_sha256']):raise ValueError('current pair '+key)
            source_path=sources/src['file'];source_raw=source_path.read_bytes()
            if sha(source_raw)!=src['sha256']:raise ValueError('source raw '+key)
            source=read(source_path);windows=source[4]
            if (source[:3],sha(source[3]),sha(windows))!=((setting,mask,'complete'),src['native_sha256'],src['windows_sha256']):raise ValueError('source tuple '+key)
            state=unseal(native,loads(native)['schema']);access=NativeAccess.restore(state['access']);actor=loads(adapter)['actor'];view=access.view(actor)
            before_access=access.checkpoint();before_view=view.bytes()
            def project():
                text=post_processing_domain(view,native,adapter,windows,setting,mask);payload=codec.dumps((setting,mask,native,adapter,windows,text));z=gzip.compress(payload.encode(),mtime=0)
                path=out/'records'/(key+'.json.gz');write(path,z);write(out/'records-backup'/path.name,z)
                if codec.dumps(read(path))!=payload:raise ValueError('typed saved report')
                ident=dict(setting=setting,mask=mask,sha256=sha(z),bytes=len(z),backup_exact=path.read_bytes()==(out/'records-backup'/path.name).read_bytes(),typed_exact=True)
                js(out/'identities'/(key+'.json'),ident);identities.append(ident);return dict(file=path.name,sha256=sha(z))
            job('project-'+key,project);saved=read(out/'records'/(key+'.json.gz'));text=saved[5];args=(view,native,adapter,windows,setting,mask)
            result=job('audit-'+key,lambda:audit_post_processing_domain(*args,text));rows.append(result)
            d=loads(text);radices=d['radices'];chosen={0,d['assignments']-1}
            for i,n in enumerate(radices):
                for digit in range(n):
                    ds=[0]*len(radices);ds[i]=digit;chosen.add(ordinal_of(tuple(ds),radices))
            for ordinal in chosen:
                ds=coordinates(ordinal,radices);r=request_at(text,ordinal);expected=dict(d['windows'][ds[0]])
                expected.update((name,d['pools'][name][x]['value']) for name,x in zip(d['role_order'],ds[1:]));expected['key']=d['namespace']+str(ordinal)
                if setting=='workflow' and expected.get('procedure') is None:expected.pop('procedure',None)
                if fields_of(r)!=expected or ordinal_of(ds,radices)!=ordinal:raise ValueError('mixed radix request')
            indices.append(dict(setting=setting,mask=mask,checked=len(chosen),assignments=d['assignments'],exact=True))
            if mask==1:
                for name in ('native','adapter','source','controller','demand','windows','pool_omit','pool_value','pool_evidence','revision','count','order','authority'):
                    bad=copy.deepcopy(d)
                    if name=='native':bad['current_native_sha256']='0'*64
                    elif name=='adapter':bad['adapter_sha256']='0'*64
                    elif name=='source':bad['source_windows_sha256']='0'*64
                    elif name=='controller':bad['controller_prefix']='forged'
                    elif name=='demand':bad['fresh_demand']['status']='fulfilled'
                    elif name=='windows':bad['windows']=bad['windows'][:-1]
                    elif name=='pool_omit':bad['pools']['stock']=bad['pools']['stock'][:-1]
                    elif name=='pool_value':bad['pools']['stock'][0]['value']='forged'
                    elif name=='pool_evidence':bad['pools']['stock'][0]['supports']=('forged',)
                    elif name=='revision':bad['version']='forged'
                    elif name=='count':bad['assignments']+=1
                    elif name=='order':bad['role_order']=tuple(reversed(bad['role_order']))
                    else:bad['execution_authorized']=True
                    reject(setting,name,lambda bad=bad:audit_post_processing_domain(*args,dumps(bad)))
                for index,name in ((1,'native_pair'),(2,'adapter_pair'),(3,'window_pair'),(5,'mask_pair')):
                    altered=list(args);altered[index]='forged' if index<5 else 99
                    reject(setting,name+'_builder',lambda altered=altered:post_processing_domain(*altered))
            if access.checkpoint()!=before_access or view.bytes()!=before_view:raise ValueError('saved access mutated')
            contexts[key]=dict(native=native,adapter=adapter,windows=windows,text=text);gc.collect()
    for rs in ((),(1,),(2,),(1,3),(2,3,4),(3,1,2,4)):
        expected=list(itertools.product(*(range(n) for n in rs)))
        if [coordinates(i,rs) for i in range(len(expected))]!=expected or [ordinal_of(x,rs) for x in expected]!=list(range(len(expected))):raise ValueError('synthetic algebra')
        algebra.append(dict(radices=rs,rows=len(expected),exact=True))
    for name,call in (('negative',lambda:coordinates(-1,(2,3))),('upper',lambda:coordinates(6,(2,3))),('bool',lambda:coordinates(True,(2,3))),('zero',lambda:coordinates(0,(2,0))),('digit',lambda:ordinal_of((2,),(2,))),('arity',lambda:ordinal_of((0,),(2,3)))):
        reject('algebra',name,call)
    def run_tests():
        import tests_ft7.test_post_processing_domain as tests
        tests.CONTEXT.update(rows=rows,probes=probes,indices=indices,identities=identities,algebra=algebra)
        suite=unittest.defaultTestLoader.loadTestsFromTestCase(tests.PostProcessingDomainTests);methods=[t._testMethodName for t in suite]
        if sorted(methods)!=sorted(protocol['methods']):raise ValueError('exact method inventory')
        with (out/'tests.log').open('x') as log:r=unittest.TextTestRunner(stream=log,verbosity=2).run(suite)
        if not r.wasSuccessful() or r.testsRun!=6:raise ValueError('six exact methods')
        return dict(methods=methods,passed=True,failures=0,errors=0)
    test_result=job('tests',run_tests)
    def finish():
        starts=list((out/'jobs').glob('*.start.json'))
        if len(starts)!=62 or list((out/'jobs').glob('*.failure.json')):raise ValueError('exclusive job closure')
        for p in starts:
            if p.name=='finish.start.json':continue
            if not json.loads(p.with_name(p.name.replace('.start.','.outcome.')).read_text())['passed']:raise ValueError('job nonpass')
        summary=dict(passed=True,records=30,audits=30,methods=test_result['methods'],probes=probes,indices=indices,algebra=algebra,source_identities=len(freeze),prior_identities=len(prior),
            native_work_calls=0,engine_restore_calls=0,accepted_stage_replays=0,comparison_paid=False,execution_authorized=False,td5_admitted=False,history_choice=False,parent_accepted=False,ft8_unchanged=True)
        js(out/'summary.json',summary);return summary
    job('finish',finish);guard();verify();print(json.dumps(dict(passed=True,records=30,audits=30,methods=6,probes=len(probes))),flush=True)
if __name__=='__main__':main()
