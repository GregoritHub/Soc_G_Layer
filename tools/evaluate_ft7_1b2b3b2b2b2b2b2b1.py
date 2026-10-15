"""Frozen fresh-task request/comparison composition; accepted inputs are read-only."""
from pathlib import Path
from zipfile import ZipFile
from io import BytesIO
import gc,gzip,hashlib,json,os,sys,unittest
ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT),str(ROOT/'baseline/HLE_Rebuild_R21B')]
PREFIX='FT7_1b2b3b2b2b2b2b2b1'
PRIOR='FT7_1b2b3b2b2b2b2b2a_Source_Freeze_v2.json'
ORIGINAL='FT7_1b2b3b2b1_Owned_Proposal_Domain_Evidence_20261015.zip'
def digest(path):return hashlib.sha256(path.read_bytes()).hexdigest()

def freeze():
    prior=ROOT/'contracts/ft'/PRIOR
    names=set(json.loads(prior.read_text()))|{str(prior.relative_to(ROOT))}
    names.update(('contracts/ft/'+PREFIX+'_Protocol_v1.json','contracts/ft/'+PREFIX+'_Protocol_v1.sha256',
        'full_theory/fresh_task_comparison.py','full_theory/fresh_task_comparison_audit.py',
        'tests_ft7/test_fresh_task_comparison.py','tools/evaluate_ft7_1b2b3b2b2b2b2b2b1.py'))
    return {n:digest(ROOT/n) for n in sorted(names)}

def predecessors():
    from tools.evaluate_ft7_1b2b3b2b2b2b2b2a import predecessors as previous
    from tools.evaluate_ft6_3b import ids
    methods=sorted(ids(unittest.defaultTestLoader.loadTestsFromName('tests_ft7.test_fresh_task_intake')))
    p=json.loads((ROOT/'contracts/ft/FT7_1b2b3b2b2b2b2b2a_Protocol_v1.json').read_text())
    if methods!=sorted('tests_ft7.test_fresh_task_intake.FreshTaskIntakeTests.'+m for m in p['registered_tests']):raise ValueError('exact predecessor identities')
    result=previous()+methods
    if len(result)!=452:raise ValueError('452 exact predecessors required')
    return result

def checked(z,name):
    raw=z.read(name)
    if hashlib.sha256(raw).hexdigest()!=json.loads(z.read('SHA256.json'))[name]:raise ValueError('input member identity')
    return raw

def input_row(setting,stage):
    from hle_unified import codec
    with ZipFile(os.environ['FT7_FRESH_COMPARISON_INPUT']) as z:
        raw=checked(z,'fresh-task-attempt2/records/'+setting+'-'+stage+'.json.gz')
    row=codec.loads(gzip.decompress(raw).decode())
    if row[0]!=setting+'/'+stage:raise ValueError('input record key')
    return row

def original_row(setting):
    from hle_unified import codec
    with ZipFile(os.environ['FT7_FRESH_COMPARISON_INPUT']) as z:
        raw=checked(z,ORIGINAL)
    with ZipFile(BytesIO(raw)) as z:
        raw=checked(z,'ft71b2b3b2b1-attempt1/records/'+setting+'-live.json.gz')
    row=codec.loads(gzip.decompress(raw).decode())
    if row[0]!=setting+'/live':raise ValueError('original record key')
    return row

def verify_members(z):
    m=json.loads(z.read('SHA256.json'))
    if set(z.namelist())!=set(m)|{'SHA256.json'}:raise ValueError('input member domain')
    if any(hashlib.sha256(z.read(n)).hexdigest()!=h for n,h in m.items()):raise ValueError('input member identity')
    return len(m)

def main(archive,out):
    from hle_unified import codec
    from hle_unified.selection_records import loads
    from full_theory.fresh_task_comparison import prepare_fresh_comparison
    from full_theory.fresh_task_comparison_audit import audit_fresh_paid_comparison
    from full_theory.owned_paid_comparison import step_owned_comparison
    from tests_ft7.test_social_live_outcome import engine_type
    from tests_ft7.test_owned_paid_comparison import paid_type
    from tools.evaluate_ft6_3b import ids
    out.mkdir(parents=True,exist_ok=False);(out/'records').mkdir()
    before=freeze();registered=json.loads((ROOT/('contracts/ft/'+PREFIX+'_Source_Freeze_v1.json')).read_text())
    if before!=registered:raise ValueError('registered source freeze differs')
    prior=json.loads((ROOT/'contracts/ft'/PRIOR).read_text())
    if any(before[n]!=h for n,h in prior.items()):raise ValueError('accepted source changed')
    pp=ROOT/('contracts/ft/'+PREFIX+'_Protocol_v1.json');p=json.loads(pp.read_text())
    if digest(pp)!=pp.with_suffix('.sha256').read_text().split()[0]:raise ValueError('protocol hash')
    if digest(archive)!=p['input']['sha256']:raise ValueError('exact input archive required')
    with ZipFile(archive) as z:
        members=verify_members(z);raw=checked(z,ORIGINAL)
    if hashlib.sha256(raw).hexdigest()!=p['input']['original_sha256']:raise ValueError('original archive identity')
    with ZipFile(BytesIO(raw)) as z:nested=verify_members(z)
    del raw
    (out/'input_verification.json').write_text(json.dumps(dict(sha256=digest(archive),members=members,original_members=nested,passed=True),indent=2)+'\n')
    os.environ.update(FT7_FRESH_COMPARISON_INPUT=str(archive),FT7_FRESH_COMPARISON_OUTPUT=str(out))
    previous=predecessors();(out/'predecessor_ids.json').write_text(json.dumps(previous,indent=2)+'\n')
    (out/'source_freeze.json').write_text(json.dumps(before,indent=2)+'\n')
    index=[];audits={};costs={}
    for setting in ('canonical','workflow'):
        original=original_row(setting);old=engine_type(setting).restore(original[1]);source,binding=original[2:4]
        for mask in range(1,16):
            intake=input_row(setting,'mask-'+str(mask));native=engine_type(setting).restore(intake[1])
            e,r,domain=prepare_fresh_comparison(native,old,source,binding,intake[2])
            required=loads(domain)['comparison_required']
            def save(stage):
                key=setting+'/'+stage;row=(key,e.checkpoint(),domain)
                path=out/'records'/(setting+'-'+stage+'.json.gz')
                with gzip.open(path,'wt',encoding='ascii') as f:f.write(codec.dumps(row)+'\n')
                index.append(dict(key=key,file=str(path.relative_to(out)),sha256=digest(path)))
                (out/'record_index.json').write_text(json.dumps(index,indent=2)+'\n')
                with gzip.open(path,'rt') as f:decoded=codec.loads(f.read())
                if decoded!=row:raise ValueError('typed roundtrip differs')
                restored=paid_type(setting).restore(decoded[1])
                audits[key]=audit_fresh_paid_comparison(restored,native,old,source,binding,intake[2],decoded[2])
                (out/'decoded_audits.json').write_text(json.dumps(audits,indent=2)+'\n')
                print(key+': saved, roundtrip exact, independently audited',flush=True)
            if mask==1:
                save('before');step_owned_comparison(e,r,work_limit=1,settle=False);save('partial')
                partial=e.checkpoint()
                step_owned_comparison(e,r,work_limit=required-1,settle=False);save('ready')
                step_owned_comparison(e,r)
            else:step_owned_comparison(e,r,work_limit=required)
            save('mask-'+str(mask))
            costs[setting+'/'+str(mask)]=dict(required=required,energy=required,time=required,
                wallet_before={u:native.wallet(r.request.actor)[u] for u in ('energy','time')},
                wallet_after={u:e.wallet(r.request.actor)[u] for u in ('energy','time')})
            (out/'cost_readback.json').write_text(json.dumps(costs,indent=2)+'\n')
            terminal=e.checkpoint();step_owned_comparison(e,r);step_owned_comparison(e,r)
            if e.checkpoint()!=terminal:raise ValueError('terminal changed')
            if mask==1:
                del e;gc.collect();e=paid_type(setting).restore(partial)
                step_owned_comparison(e,r,work_limit=required-1,settle=False);step_owned_comparison(e,r)
                if e.checkpoint()!=terminal:raise ValueError('exact partial restart differs')
                save('restarted');del e;gc.collect();e=paid_type(setting).restore(partial)
                e.cancel(r.key+':cancel',r.request.actor,r.key);save('cancelled')
                del partial
            if native.checkpoint()!=intake[1] or old.checkpoint()!=original[1]:raise ValueError('immutable input changed')
            del e,r,domain,native,intake,terminal;gc.collect()
        del old,original;gc.collect()
    suite=unittest.defaultTestLoader.loadTestsFromName('tests_ft7.test_fresh_task_comparison')
    actual=sorted(ids(suite));expected=sorted('tests_ft7.test_fresh_task_comparison.FreshTaskComparisonTests.'+m for m in p['registered_tests'])
    if actual!=expected:raise ValueError('exact actual method domain')
    (out/'method_ids.json').write_text(json.dumps(actual,indent=2)+'\n')
    with (out/'controls.log').open('w') as stream:result=unittest.TextTestRunner(stream=stream,verbosity=2).run(suite)
    summary=dict(batch=p['batch'],passed=result.wasSuccessful() and before==freeze() and sorted(audits)==sorted(p['saved_records']),
        methods=result.testsRun,failures=len(result.failures),errors=len(result.errors),predecessor_identities=len(previous),saved_records=len(index),
        typed_roundtrip_exact=True,independent_audits=True,source_unchanged=before==freeze(),frozen_identities=len(before),claim=p['claim_boundary'])
    (out/'summary.json').write_text(json.dumps(summary,indent=2)+'\n');print(json.dumps(summary,indent=2),flush=True)
    if not summary['passed']:raise SystemExit(1)

if __name__=='__main__':main(*(Path(x).resolve() for x in sys.argv[1:3]))
