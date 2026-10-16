"""A6 saved-input domain gate; no native engine restore or execution calls."""
import argparse,copy,gc,gzip,hashlib,itertools,json,pathlib,unittest,zipfile
from datetime import datetime,timezone
from hle_unified import codec
from hle_unified.compact import unseal
from hle_unified.operations import NativeAccess
from hle_unified.selection_records import dumps,loads,fields_of
from full_theory.changed_input_domain import changed_input_domain,request_at,coordinates,ordinal_of
from full_theory.changed_input_domain_audit import audit_changed_input_domain,reconstruct


def sha(value):return hashlib.sha256(value.encode() if isinstance(value,str) else value).hexdigest()


def run():
    p=argparse.ArgumentParser();p.add_argument('a5');p.add_argument('a3');p.add_argument('old_archive');p.add_argument('output')
    p.add_argument('--public',required=True);p.add_argument('--owner',required=True);p.add_argument('--stop-at',required=True);a=p.parse_args()
    root=pathlib.Path(__file__).resolve().parents[1];out=pathlib.Path(a.output);out.mkdir(exist_ok=False)
    protocol=json.loads((root/'contracts/ft/FT7_Changed_Input_Domain_A6_Protocol_v1.json').read_text())
    freeze=json.loads((root/'contracts/ft/FT7_Changed_Input_Domain_A6_Source_Freeze_v1.json').read_text())
    rows=[];probes=[];indices=[];prefixes=[];algebra=[]
    def note(kind,**kw):
        with (out/'events.jsonl').open('a') as f:f.write(json.dumps(dict(at=datetime.now(timezone.utc).isoformat(),kind=kind,**kw))+'\n');f.flush()
    def guard():
        s=json.loads((pathlib.Path(a.public)/'docs/FT_Run_State.json').read_text());now=datetime.now(timezone.utc)
        if s['run_id']!=a.owner or not s['active_worker'] or s['status']!='running' or now>=datetime.fromisoformat(s['lease_expires_at']) or now>=datetime.fromisoformat(a.stop_at):
            raise SystemExit('owner / lease / deadline guard')
    def verify():
        for name,h in freeze.items():
            if sha((root/name).read_bytes())!=h:raise ValueError('frozen identity changed: '+name)
        prior=json.loads((root/protocol['prior_freeze']).read_text())
        if len(prior)!=481 or any(freeze.get(n)!=h for n,h in prior.items()):raise ValueError('predecessor identities')
    def reject(setting,name,call):
        try:call()
        except ValueError:probes.append(dict(setting=setting,name=name,rejected=True))
        else:raise ValueError('forgery accepted: '+setting+'/'+name)
    try:
        guard();verify();note('start',owner=a.owner)
        archive=pathlib.Path(a.old_archive)
        if sha(archive.read_bytes())!=protocol['old_archive']['sha256']:raise ValueError('accepted old archive identity')
        with zipfile.ZipFile(archive) as z:
            for setting in ('canonical','workflow'):
                guard();entry=protocol['inputs'][setting]
                raw=(pathlib.Path(a.a5)/entry['file']).read_bytes()
                if sha(raw)!=entry['raw_sha256']:raise ValueError('A5 raw identity')
                label,native,field=codec.loads(gzip.decompress(raw).decode())
                if label!='complete' or sha(native)!=entry['native_sha256'] or sha(field)!=entry['adapter_sha256']:raise ValueError('A5 pair')
                oldraw=z.read(protocol['old_archive']['member_pattern'].format(setting=setting))
                if sha(oldraw)!=entry['old_raw_sha256']:raise ValueError('old raw identity')
                _,oldnative,old=codec.loads(gzip.decompress(oldraw).decode())
                if sha(oldnative)!=entry['old_native_sha256'] or sha(old)!=entry['old_domain_sha256']:raise ValueError('old pair')
                _,_,refresh=codec.loads(gzip.decompress((pathlib.Path(a.a3)/entry['file']).read_bytes()).decode())
                if sha(refresh)!=entry['refresh_sha256']:raise ValueError('accepted A3 refresh')
                actor=loads(field)['actor'];schema=loads(native)['schema'];oldschema=loads(oldnative)['schema']
                state=unseal(native,schema);oldstate=unseal(oldnative,oldschema)
                access=NativeAccess.restore(state['access']);view=access.view(actor)
                oldview=NativeAccess.restore(oldstate['access']).view(actor)
                # These are immutable saved access prefixes, not rebuilt social wrappers.
                if view.snapshot.bindings!=oldview.snapshot.bindings:raise ValueError('owned binding prefix changed')
                for name in ('particulars','receipts'):
                    before=getattr(oldview.snapshot,name);after=getattr(view.snapshot,name)
                    if after[:len(before)]!=before:raise ValueError('owned access prefix changed: '+name)
                before_access=access.checkpoint();before_view=view.bytes()
                prefixes.append(dict(setting=setting,bindings=len(oldview.snapshot.bindings),particulars=len(oldview.snapshot.particulars),
                    receipts=len(oldview.snapshot.receipts),exact=True,old_native_sha256=sha(oldnative),native_sha256=sha(native)))
                args=(view,sha(native),field,old,refresh,setting)
                text=changed_input_domain(*args);domain=loads(text)
                for label in ('complete','restored'):
                    guard()
                    if label=='restored':
                        restored_view=NativeAccess.restore(state['access']).view(actor)
                        restored=changed_input_domain(restored_view,sha(native),field,old,refresh,setting)
                        if restored!=text:raise ValueError('saved input projection restoration differs')
                    filename=setting+'-'+label+'.json.gz'
                    with gzip.open(out/filename,'wt') as f:f.write(text)
                    note('raw_saved_before_audit',file=filename,sha256=sha((out/filename).read_bytes()))
                    with gzip.open(out/filename,'rt') as f:saved=f.read()
                    if saved!=text:raise ValueError('saved projection bytes')
                    result=audit_changed_input_domain(*args,saved)
                    rows.append(dict(record=label,file=filename,sha256=sha((out/filename).read_bytes()),**result))
                    print(json.dumps(rows[-1]),flush=True);note('record_passed',setting=setting,record=label)
                # Every individual factor coordinate, plus both ends. Other factors are zero.
                chosen={0,domain['assignments']-1};radices=domain['radices']
                for i,radix in enumerate(radices):
                    for digit in range(radix):
                        ds=[0]*len(radices);ds[i]=digit
                        chosen.add(sum(ds[j]*__import__('math').prod(radices[j+1:]) for j in range(len(ds))))
                for index in sorted(chosen):
                    req=request_at(text,index);fields=fields_of(req)
                    ds=tuple((index//__import__('math').prod(radices[j+1:]))%radices[j] for j in range(len(radices)))
                    expected=dict(domain['windows'][ds[0]])
                    expected.update((name,domain['pools'][name][digit]['value']) for name,digit in zip(domain['role_order'],ds[1:]))
                    expected['key']=domain['namespace']+str(index)
                    if setting=='workflow' and expected.get('procedure') is None:expected.pop('procedure',None)
                    if fields!=expected or coordinates(index,radices)!=ds or ordinal_of(ds,radices)!=index:raise ValueError('request coordinate mapping')
                indices.append(dict(setting=setting,checked=len(chosen),assignments=domain['assignments'],all_factor_values=True))
                mutations=('native','fields','source','controller','demand','windows','pool_omit','pool_value','pool_evidence','count','order','authority')
                for name in mutations:
                    bad=copy.deepcopy(domain)
                    if name=='native':bad['native_sha256']='0'*64
                    elif name=='fields':bad['fields_sha256']='0'*64
                    elif name=='source':bad['source_sha256']='0'*64
                    elif name=='controller':bad['controller_prefix']='forged'
                    elif name=='demand':bad['fresh_demand']['status']='fulfilled'
                    elif name=='windows':bad['windows']=bad['windows'][:-1]
                    elif name=='pool_omit':bad['pools']['stock']=bad['pools']['stock'][:-1]
                    elif name=='pool_value':bad['pools']['stock'][1]['value']=None
                    elif name=='pool_evidence':bad['pools']['stock'][1]['supports']=()
                    elif name=='count':bad['assignments']+=1
                    elif name=='order':bad['role_order']=tuple(reversed(bad['role_order']))
                    else:bad['execution_authorized']=True
                    reject(setting,name,lambda bad=bad:audit_changed_input_domain(*args,dumps(bad)))
                for index,name in ((1,'native_pair'),(2,'field_pair'),(3,'old_pair'),(4,'refresh_pair')):
                    altered=list(args);altered[index]='forged'
                    reject(setting,name+'_builder',lambda altered=altered:changed_input_domain(*altered))
                    reject(setting,name+'_auditor',lambda altered=altered:audit_changed_input_domain(*altered,text))
                if access.checkpoint()!=before_access or view.bytes()!=before_view:raise ValueError('saved native access mutated')
                (out/'progress.json').write_text(json.dumps(dict(records=rows,probes=probes,indices=indices,prefixes=prefixes),indent=2)+'\n')
                reconstruct.cache_clear();del state,oldstate,access,view,oldview,restored_view,native,oldnative;gc.collect()
        for radices in ((),(1,),(2,),(1,3),(2,3,4),(3,1,2,4)):
            expected=list(itertools.product(*(range(n) for n in radices)))
            if [coordinates(i,radices) for i in range(len(expected))]!=expected:raise ValueError('synthetic full product')
            if [ordinal_of(ds,radices) for ds in expected]!=list(range(len(expected))):raise ValueError('synthetic inverse')
            algebra.append(dict(radices=radices,rows=len(expected),exact=True))
        for name,call in (('negative',lambda:coordinates(-1,(2,3))),('upper',lambda:coordinates(6,(2,3))),
                ('bool',lambda:coordinates(True,(2,3))),('zero_radix',lambda:coordinates(0,(2,0))),
                ('digit',lambda:ordinal_of((2,),(2,))),('arity',lambda:ordinal_of((0,),(2,3)))):
            reject('algebra',name,call)
        guard();verify();note('methods_start')
        import tests_ft7.test_changed_input_domain as tests
        tests.ROWS=rows;tests.PROBES=probes;tests.INDICES=indices;tests.PREFIXES=prefixes;tests.ALGEBRA=algebra
        suite=unittest.defaultTestLoader.loadTestsFromModule(tests);actual=[t._testMethodName for group in suite for t in group]
        if sorted(actual)!=sorted(protocol['gate']['methods']):raise ValueError('exact method identity set')
        with (out/'tests.log').open('w') as f:result=unittest.TextTestRunner(stream=f,verbosity=2).run(suite)
        if result.testsRun!=6 or not result.wasSuccessful():raise ValueError('six exact new methods')
        verify();summary=dict(passed=True,methods=actual,records=rows,probes=probes,indices=indices,prefixes=prefixes,algebra=algebra,
            source_identities=len(freeze),prior_identities=481,native_work_calls=0,engine_restore_calls=0,accepted_stage_replays=0,parent_accepted=False)
        (out/'summary.json').write_text(json.dumps(summary,indent=2)+'\n');note('closed_pass');print('A6 passed',flush=True)
    except BaseException as error:
        note('closed_nonpass',error_type=type(error).__name__,message=str(error));raise


if __name__=='__main__':run()
