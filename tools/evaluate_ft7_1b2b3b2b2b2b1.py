"""Bounded actual comparison-to-preparation composition; accepted comparison is not rerun."""
from pathlib import Path
import gc,gzip,hashlib,json,os,sys,unittest
ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT),str(ROOT/'baseline/HLE_Rebuild_R21B')]
PREFIX='FT7_1b2b3b2b2b2b1'
def digest(p):return hashlib.sha256(p.read_bytes()).hexdigest()

def freeze():
    prior=ROOT/'contracts/ft/FT7_1b2b3b2b2b2a_Source_Freeze_v1.json'
    names=set(json.loads(prior.read_text()))|{str(prior.relative_to(ROOT))}
    names.update(('contracts/ft/'+PREFIX+'_Protocol_v1.json','contracts/ft/'+PREFIX+'_Protocol_v1.sha256',
        'full_theory/compared_preparation.py','full_theory/compared_preparation_audit.py',
        'tests_ft7/test_compared_preparation.py','tools/evaluate_ft7_1b2b3b2b2b2b1.py'))
    return {n:digest(ROOT/n) for n in sorted(names)}

def predecessors():
    from tools.evaluate_ft7_1b2b3b2b2b2a import predecessors as previous
    from tools.evaluate_ft6_3b import ids
    methods=sorted(ids(unittest.defaultTestLoader.loadTestsFromName('tests_ft7.test_current_owned_admission')))
    p=json.loads((ROOT/'contracts/ft/FT7_1b2b3b2b2b2a_Protocol_v1.json').read_text())
    if methods!=sorted('tests_ft7.test_current_owned_admission.CurrentOwnedAdmissionTests.'+m for m in p['registered_tests']):
        raise ValueError('exact predecessor methods')
    result=previous()+methods
    if len(result)!=418:raise ValueError('418 exact predecessor identities required')
    return result

def main(original,out):
    from hle_unified import codec
    from hle_unified.selection_records import loads
    from full_theory.compared_preparation import ComparedSocialPreparation
    from full_theory.compared_preparation_audit import audit_compared_preparation
    from tests_ft7.test_social_live_outcome import read_record,engine_type
    from tests_ft7.test_owned_paid_comparison import paid_type
    from tools.evaluate_ft6_3b import ids
    out.mkdir(parents=True,exist_ok=False);(out/'records').mkdir()
    before=freeze();registered=json.loads((ROOT/('contracts/ft/'+PREFIX+'_Source_Freeze_v1.json')).read_text())
    if before!=registered:raise ValueError('source freeze differs')
    prior=json.loads((ROOT/'contracts/ft/FT7_1b2b3b2b2b2a_Source_Freeze_v1.json').read_text())
    if any(before[n]!=h for n,h in prior.items()):raise ValueError('accepted source changed')
    pp=ROOT/('contracts/ft/'+PREFIX+'_Protocol_v1.json');p=json.loads(pp.read_text())
    if digest(pp)!=pp.with_suffix('.sha256').read_text().split()[0]:raise ValueError('protocol hash')
    previous=predecessors();(out/'predecessor_ids.json').write_text(json.dumps(previous,indent=2)+'\n')
    (out/'source_freeze.json').write_text(json.dumps(before,indent=2)+'\n')
    os.environ.update(FT7_COMPARED_PREPARATION_OUTPUT=str(out),FT7_COMPARED_PREPARATION_INPUT=str(original))
    incoming=[x for x in json.loads((original/'record_index.json').read_text()) if x['key'] in p['input']['keys']]
    if sorted(x['key'] for x in incoming)!=sorted(p['input']['keys']):raise ValueError('exact input domain')
    index=[];audits={}
    for item in incoming:
        path=original/item['file']
        if digest(path)!=item['sha256']:raise ValueError('saved input identity')
        row=read_record(path);setting=row[0].split('/')[0]
        old=engine_type(setting).restore(row[1]);comparison=paid_type(setting).restore(row[5])
        e=paid_type(setting).restore(row[5])
        adapter=ComparedSocialPreparation(e,old,row[2],row[3],row[4],row[6],row[7])
        def save(stage):
            key=setting+'/'+stage;dest=out/'records'/(setting+'-'+stage+'.json.gz')
            output=(key,*row[1:],e.checkpoint(),adapter.checkpoint(e))
            with gzip.open(dest,'wt',encoding='ascii') as f:f.write(codec.dumps(output)+'\n')
            index.append(dict(key=key,file=str(dest.relative_to(out)),sha256=digest(dest),input_sha256=item['sha256']))
            (out/'record_index.json').write_text(json.dumps(index,indent=2)+'\n')
            decoded=read_record(dest)
            if decoded!=output:raise ValueError('typed roundtrip')
            restored=paid_type(setting).restore(decoded[8])
            audits[key]=audit_compared_preparation(restored,comparison,old,row[2],row[3],row[4],row[6],row[7],decoded[9])
            (out/'decoded_audits.json').write_text(json.dumps(audits,indent=2)+'\n')
            if old.checkpoint()!=row[1] or comparison.checkpoint()!=row[5]:raise ValueError('immutable inputs changed')
            print(key+': independently audited',flush=True)
            del restored,decoded,output;gc.collect()
        save('before');adapter.step(e,work_limit=1);save('partial')
        partial_native=e.checkpoint();partial_wrapper=adapter.checkpoint(e)
        adapter.step(e,work_limit=1);save('complete')
        del e,adapter;gc.collect()
        e=paid_type(setting).restore(partial_native)
        adapter=ComparedSocialPreparation.restore(partial_wrapper,e,comparison,old,row[2],row[3],row[4],row[6],row[7])
        adapter.step(e,work_limit=1);save('restarted')
        del e,adapter,old,comparison,row,partial_native,partial_wrapper;gc.collect()
    suite=unittest.defaultTestLoader.loadTestsFromName('tests_ft7.test_compared_preparation')
    actual=sorted(ids(suite));expected=sorted('tests_ft7.test_compared_preparation.ComparedPreparationTests.'+m for m in p['registered_tests'])
    if actual!=expected:raise ValueError('exact new methods')
    (out/'method_ids.json').write_text(json.dumps(actual,indent=2)+'\n')
    with (out/'controls.log').open('w') as stream:result=unittest.TextTestRunner(stream=stream,verbosity=2).run(suite)
    summary=dict(batch=p['batch'],passed=result.wasSuccessful() and before==freeze() and sorted(audits)==sorted(p['saved_records']),
        methods=result.testsRun,failures=len(result.failures),errors=len(result.errors),predecessor_identities=len(previous),
        saved_records=len(index),typed_roundtrip_exact=True,independent_audits=True,source_unchanged=before==freeze(),
        frozen_identities=len(before),accepted_comparison_rerun=False,
        claim='Actual comparison-to-preparation composition only; no live choice or parent acceptance')
    (out/'summary.json').write_text(json.dumps(summary,indent=2)+'\n');print(json.dumps(summary,indent=2),flush=True)
    if not summary['passed']:raise SystemExit(1)

if __name__=='__main__':main(*(Path(x).resolve() for x in sys.argv[1:3]))
