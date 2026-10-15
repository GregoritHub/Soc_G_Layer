"""Frozen complete accessible-content request grammar; no new paid native work."""
from pathlib import Path
from zipfile import ZipFile
from io import BytesIO
import gc,gzip,hashlib,json,os,sys,unittest
ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT),str(ROOT/'baseline/HLE_Rebuild_R21B')]
PREFIX='FT7_1b2b3b2b2b2b2b2b1a'
PRIOR='FT7_1b2b3b2b2b2b2b2b1_Source_Freeze_v1.json'
def digest(path):return hashlib.sha256(path.read_bytes()).hexdigest()

def freeze():
    prior=ROOT/'contracts/ft'/PRIOR
    names=set(json.loads(prior.read_text()))|{str(prior.relative_to(ROOT))}
    names.update(('contracts/ft/'+PREFIX+'_Protocol_v1.json','contracts/ft/'+PREFIX+'_Protocol_v1.sha256',
        'full_theory/owned_request_windows.py','full_theory/owned_request_windows_audit.py',
        'tests_ft7/test_owned_request_windows.py','tools/evaluate_ft7_1b2b3b2b2b2b2b2b1a.py'))
    return {n:digest(ROOT/n) for n in sorted(names)}

def predecessors():
    from tools.evaluate_ft7_1b2b3b2b2b2b2b2b1 import predecessors as previous
    from tools.evaluate_ft6_3b import ids
    methods=sorted(ids(unittest.defaultTestLoader.loadTestsFromName('tests_ft7.test_fresh_task_comparison')))
    p=json.loads((ROOT/'contracts/ft/FT7_1b2b3b2b2b2b2b2b1_Protocol_v1.json').read_text())
    if methods!=sorted('tests_ft7.test_fresh_task_comparison.FreshTaskComparisonTests.'+m for m in p['registered_tests']):raise ValueError('exact failed predecessor method identities')
    result=previous()+methods
    if len(result)!=460:raise ValueError('460 exact identities required; not predecessor acceptance')
    return result

def main(archive,out):
    from hle_unified import codec
    from full_theory.owned_request_windows import owned_request_windows
    from full_theory.owned_request_windows_audit import audit_owned_request_windows
    from tests_ft7.test_social_live_outcome import engine_type
    from tools.evaluate_ft7_1b2b3b2b2b2b2b2b1 import input_row,original_row,verify_members,checked,ORIGINAL
    from tools.evaluate_ft6_3b import ids
    out.mkdir(parents=True,exist_ok=False);(out/'records').mkdir()
    before=freeze()
    if before!=json.loads((ROOT/'contracts/ft'/(PREFIX+'_Source_Freeze_v1.json')).read_text()):raise ValueError('source freeze differs')
    prior=json.loads((ROOT/'contracts/ft'/PRIOR).read_text())
    if any(before[n]!=h for n,h in prior.items()):raise ValueError('prior accepted/failed source changed')
    pp=ROOT/'contracts/ft'/(PREFIX+'_Protocol_v1.json');p=json.loads(pp.read_text())
    if digest(pp)!=pp.with_suffix('.sha256').read_text().split()[0]:raise ValueError('protocol hash')
    if digest(archive)!=p['input']['sha256']:raise ValueError('exact input archive')
    with ZipFile(archive) as z:members=verify_members(z);raw=checked(z,ORIGINAL)
    if hashlib.sha256(raw).hexdigest()!=p['input']['original_sha256']:raise ValueError('original archive identity')
    with ZipFile(BytesIO(raw)) as z:nested=verify_members(z)
    del raw
    os.environ.update(FT7_FRESH_COMPARISON_INPUT=str(archive),FT7_REQUEST_WINDOWS_OUTPUT=str(out))
    previous=predecessors()
    for name,data in [('input_verification.json',dict(passed=True,members=members,original_members=nested,sha256=digest(archive))),
        ('source_freeze.json',before),('predecessor_ids.json',previous)]:
        (out/name).write_text(json.dumps(data,indent=2)+'\n')
    index=[];audits={}
    for setting in ('canonical','workflow'):
        original=original_row(setting);old=engine_type(setting).restore(original[1]);source,binding=original[2:4]
        for mask in range(1,16):
            intake=input_row(setting,'mask-'+str(mask));native=engine_type(setting).restore(intake[1])
            domain=owned_request_windows(native,old,source,binding,intake[2])
            if native.checkpoint()!=intake[1] or old.checkpoint()!=original[1]:raise ValueError('input mutation')
            def save(stage):
                key=setting+'/'+stage;row=(key,native.checkpoint(),domain)
                path=out/'records'/(setting+'-'+stage+'.json.gz')
                with gzip.open(path,'wt',encoding='ascii') as f:f.write(codec.dumps(row)+'\n')
                index.append(dict(key=key,file=str(path.relative_to(out)),sha256=digest(path)))
                (out/'record_index.json').write_text(json.dumps(index,indent=2)+'\n')
                with gzip.open(path,'rt') as f:decoded=codec.loads(f.read())
                if decoded!=row:raise ValueError('typed roundtrip differs')
                restored=engine_type(setting).restore(decoded[1])
                audits[key]=audit_owned_request_windows(restored,old,source,binding,intake[2],decoded[2])
                if restored.checkpoint()!=intake[1]:raise ValueError('readback native changed')
                (out/'decoded_audits.json').write_text(json.dumps(audits,indent=2)+'\n')
                print(key+': exact unchanged native, full domain independently audited',flush=True)
            save('mask-'+str(mask))
            if mask==1:
                native=engine_type(setting).restore(intake[1])
                if owned_request_windows(native,old,source,binding,intake[2])!=domain:raise ValueError('exact reconstruction differs')
                save('restarted')
            del native,intake,domain;gc.collect()
        del old,original;gc.collect()
    suite=unittest.defaultTestLoader.loadTestsFromName('tests_ft7.test_owned_request_windows')
    actual=sorted(ids(suite));expected=sorted('tests_ft7.test_owned_request_windows.OwnedRequestWindowTests.'+m for m in p['registered_tests'])
    if actual!=expected:raise ValueError('exact actual method domain')
    (out/'method_ids.json').write_text(json.dumps(actual,indent=2)+'\n')
    with (out/'controls.log').open('w') as stream:result=unittest.TextTestRunner(stream=stream,verbosity=2).run(suite)
    summary=dict(batch=p['batch'],passed=result.wasSuccessful() and before==freeze() and sorted(audits)==sorted(p['saved_records']),
        methods=result.testsRun,failures=len(result.failures),errors=len(result.errors),predecessor_identities=len(previous),saved_records=len(index),
        typed_roundtrip_exact=True,independent_audits=True,source_unchanged=before==freeze(),frozen_identities=len(before),
        prior_accepted_identities=367,prior_failed_gate_identities=374,prior_failed_gate_accepted=False,new_paid_work=False,claim=p['claim_boundary'])
    (out/'summary.json').write_text(json.dumps(summary,indent=2)+'\n');print(json.dumps(summary,indent=2),flush=True)
    if not summary['passed']:raise SystemExit(1)

if __name__=='__main__':main(*(Path(x).resolve() for x in sys.argv[1:3]))
