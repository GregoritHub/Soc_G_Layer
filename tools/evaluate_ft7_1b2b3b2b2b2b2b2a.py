"""Frozen fixed fresh-task panel; restore accepted inputs, never rerun them."""
from pathlib import Path
from zipfile import ZipFile
import gc,gzip,hashlib,json,os,sys,unittest
ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT),str(ROOT/'baseline/HLE_Rebuild_R21B')]
PREFIX='FT7_1b2b3b2b2b2b2b2a'
PRIOR='FT7_1b2b3b2b2b2b2b1_Source_Freeze_v4.json'
def digest(path):return hashlib.sha256(path.read_bytes()).hexdigest()


def freeze():
    prior=ROOT/'contracts/ft'/PRIOR
    names=set(json.loads(prior.read_text()))|{str(prior.relative_to(ROOT))}
    names.update(('contracts/ft/'+PREFIX+'_Protocol_v1.json','contracts/ft/'+PREFIX+'_Protocol_v1.sha256',
        'contracts/ft/'+PREFIX+'_Source_Freeze_v1.json',
        'contracts/ft/'+PREFIX+'_Encoding_Amendment_v2.json','contracts/ft/'+PREFIX+'_Encoding_Amendment_v2.sha256',
        'full_theory/fresh_task_intake.py','full_theory/fresh_task_intake_audit.py',
        'tests_ft7/test_fresh_task_intake.py','tools/evaluate_ft7_1b2b3b2b2b2b2b2a.py'))
    return {n:digest(ROOT/n) for n in sorted(names)}


def predecessors():
    from tools.evaluate_ft7_1b2b3b2b2b2b2b1 import predecessors as previous
    from tools.evaluate_ft6_3b import ids
    methods=sorted(ids(unittest.defaultTestLoader.loadTestsFromName('tests_ft7.test_paid_role_comparison')))
    p=json.loads((ROOT/'contracts/ft/FT7_1b2b3b2b2b2b2b1_Protocol_v1.json').read_text())
    if methods!=sorted('tests_ft7.test_paid_role_comparison.PaidRoleComparisonTests.'+m for m in p['registered_tests']):raise ValueError('exact predecessor identities')
    result=previous()+methods
    if len(result)!=444:raise ValueError('444 exact predecessors required')
    return result


def input_row(setting,case):
    from hle_unified import codec
    name='ft71b2b3b2b1-attempt1/records/'+setting+'-'+case+'.json.gz'
    with ZipFile(os.environ['FT7_FRESH_INPUT']) as z:
        raw=z.read(name); manifest=json.loads(z.read('SHA256.json'))
        if hashlib.sha256(raw).hexdigest()!=manifest[name]:raise ValueError('exact input record identity')
    row=codec.loads(gzip.decompress(raw).decode())
    if row[0]!=setting+'/'+case:raise ValueError('input record key')
    return row


def main(archive,out):
    from hle_unified import codec
    from full_theory.fresh_task_intake import FreshTaskIntake
    from full_theory.fresh_task_intake_audit import audit_fresh_task_intake
    from tests_ft7.test_social_live_outcome import engine_type
    from tools.evaluate_ft6_3b import ids
    out.mkdir(parents=True,exist_ok=False);(out/'records').mkdir()
    before=freeze();registered=json.loads((ROOT/('contracts/ft/'+PREFIX+'_Source_Freeze_v2.json')).read_text())
    if before!=registered:raise ValueError('registered source freeze differs')
    prior=json.loads((ROOT/'contracts/ft'/PRIOR).read_text())
    if any(before[n]!=h for n,h in prior.items()):raise ValueError('accepted source changed')
    pp=ROOT/('contracts/ft/'+PREFIX+'_Protocol_v1.json');p=json.loads(pp.read_text())
    if digest(pp)!=pp.with_suffix('.sha256').read_text().split()[0]:raise ValueError('protocol hash')
    amendment=ROOT/('contracts/ft/'+PREFIX+'_Encoding_Amendment_v2.json')
    if digest(amendment)!=amendment.with_suffix('.sha256').read_text().split()[0]:raise ValueError('amendment hash')
    if digest(archive)!=p['input']['sha256']:raise ValueError('exact input archive required')
    with ZipFile(archive) as z:
        manifest=json.loads(z.read('SHA256.json'))
        if set(z.namelist())!=set(manifest)|{'SHA256.json'}:raise ValueError('input member domain')
        if any(hashlib.sha256(z.read(n)).hexdigest()!=h for n,h in manifest.items()):raise ValueError('input member identity')
    (out/'input_verification.json').write_text(json.dumps(dict(sha256=digest(archive),members=len(manifest),passed=True),indent=2)+'\n')
    os.environ.update(FT7_FRESH_INPUT=str(archive),FT7_FRESH_OUTPUT=str(out))
    previous=predecessors();(out/'predecessor_ids.json').write_text(json.dumps(previous,indent=2)+'\n')
    (out/'source_freeze.json').write_text(json.dumps(before,indent=2)+'\n')
    index=[];audits={}
    def save(setting,stage,e,c,old,source,binding):
        key=setting+'/'+stage;row=(key,e.checkpoint(),c.checkpoint(e))
        path=out/'records'/(setting+'-'+stage+'.json.gz')
        with gzip.open(path,'wt',encoding='ascii') as f:f.write(codec.dumps(row)+'\n')
        index.append(dict(key=key,file=str(path.relative_to(out)),sha256=digest(path)))
        (out/'record_index.json').write_text(json.dumps(index,indent=2)+'\n')
        with gzip.open(path,'rt') as f:decoded=codec.loads(f.read())
        if decoded!=row:raise ValueError('typed roundtrip differs')
        restored=engine_type(setting).restore(decoded[1])
        audits[key]=audit_fresh_task_intake(restored,old,source,binding,decoded[2])
        (out/'decoded_audits.json').write_text(json.dumps(audits,indent=2)+'\n')
        print(key+': saved, roundtrip exact, independently audited',flush=True)
    for setting in ('canonical','workflow'):
        row=input_row(setting,'live');old=engine_type(setting).restore(row[1]);source,binding=row[2:4]
        for mask in range(1,16):
            e=engine_type(setting).restore(row[1]);c=FreshTaskIntake(e,source,binding,mask);partials=[]
            if mask==1:save(setting,'before',e,c,old,source,binding)
            for step in range(5):
                c.step(e,work_limit=1)
                if mask==1 and step in (0,1,2):
                    stage=('read-partial','read-complete','bind-partial')[step]
                    save(setting,stage,e,c,old,source,binding)
                    if step in (0,2):partials.append((stage,e.checkpoint(),c.checkpoint(e)))
            if c.receipt is None:raise ValueError('fixed five-unit paid task intake must complete')
            save(setting,'mask-'+str(mask),e,c,old,source,binding)
            if mask==1:
                terminal=(e.checkpoint(),c.checkpoint(e));c.step(e);c.step(e)
                if terminal!=(e.checkpoint(),c.checkpoint(e)):raise ValueError('terminal changed')
                for stage,native,wrapper in partials:
                    re=engine_type(setting).restore(native);rc=FreshTaskIntake.restore(wrapper,re,old,source,binding)
                    for _ in range(5):
                        if rc.receipt is not None:break
                        rc.step(re,work_limit=1)
                    if (re.checkpoint(),rc.checkpoint(re))!=terminal:raise ValueError('exact partial restart differs')
                    save(setting,stage.replace('partial','restarted'),re,rc,old,source,binding)
                    del re,rc
            del e,c;gc.collect()
        del old,row;gc.collect()
    suite=unittest.defaultTestLoader.loadTestsFromName('tests_ft7.test_fresh_task_intake')
    actual=sorted(ids(suite));expected=sorted('tests_ft7.test_fresh_task_intake.FreshTaskIntakeTests.'+m for m in p['registered_tests'])
    if actual!=expected:raise ValueError('exact actual method domain')
    (out/'method_ids.json').write_text(json.dumps(actual,indent=2)+'\n')
    with (out/'controls.log').open('w') as stream:result=unittest.TextTestRunner(stream=stream,verbosity=2).run(suite)
    summary=dict(batch=p['batch'],passed=result.wasSuccessful() and before==freeze() and sorted(audits)==sorted(p['saved_records']),
        methods=result.testsRun,failures=len(result.failures),errors=len(result.errors),predecessor_identities=len(previous),saved_records=len(index),
        typed_roundtrip_exact=True,independent_audits=True,source_unchanged=before==freeze(),frozen_identities=len(before),
        claim=p['claim_boundary'])
    (out/'summary.json').write_text(json.dumps(summary,indent=2)+'\n');print(json.dumps(summary,indent=2),flush=True)
    if not summary['passed']:raise SystemExit(1)


if __name__=='__main__':main(*(Path(x).resolve() for x in sys.argv[1:3]))
