"""Bounded fresh paid preparation gate; no accepted engine gate reruns."""
from pathlib import Path
import gc,gzip,hashlib,json,os,sys,unittest

ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT),str(ROOT/'baseline/HLE_Rebuild_R21B')]

def digest(p):return hashlib.sha256(p.read_bytes()).hexdigest()

def freeze():
    names=set(json.loads((ROOT/'contracts/ft/FT_Setup_Self_Overlay_Source_Freeze_v1.json').read_text()))
    names.update(('contracts/ft/FT_Setup_Self_Overlay_Source_Freeze_v1.json',
        'contracts/ft/FT7_1b2b3b1_Protocol_v1.json','contracts/ft/FT7_1b2b3b1_Protocol_v1.sha256',
        'full_theory/social_preparation.py','full_theory/social_preparation_audit.py',
        'tests_ft7/test_social_preparation.py','tools/evaluate_ft7_1b2b3b1.py'))
    return {n:digest(ROOT/n) for n in sorted(names)}

def main(native_root,binding_root,out):
    from hle_unified import codec
    from hle_unified.selection_records import loads
    from full_theory.social_preparation import SocialPaidPreparation
    from full_theory.social_preparation_audit import audit_social_preparation
    from tests_ft7.test_social_preparation import source,engine_type,read_record
    from tools.audit_ft7_1b2b2b_saved import predecessor_ids,expected_methods
    from tools.evaluate_ft6_3b import ids
    from tools.evaluate_ft7_1b2b2b import audit_saved
    out.mkdir(parents=True,exist_ok=False);(out/'records').mkdir()
    before=freeze();registered=json.loads((ROOT/'contracts/ft/FT7_1b2b3b1_Source_Freeze_v1.json').read_text())
    if before!=registered:raise ValueError('registered freeze differs')
    (out/'source_freeze.json').write_text(json.dumps(before,indent=2)+'\n')
    pp=ROOT/'contracts/ft/FT7_1b2b3b1_Protocol_v1.json';protocol=json.loads(pp.read_text())
    if digest(pp)!=pp.with_suffix('.sha256').read_text().split()[0]:raise ValueError('protocol hash differs')
    previous=predecessor_ids();reuse,_=expected_methods()
    actual_reuse=sorted(ids(unittest.defaultTestLoader.loadTestsFromName('tests_ft7.test_social_reuse')))
    bp=json.loads((ROOT/'contracts/ft/FT7_1b2b3a_Protocol_v1.json').read_text())
    expected_binding=sorted('tests_ft7.test_social_feedback_binding.SocialFeedbackBindingTests.'+m for m in bp['registered_tests'])
    actual_binding=sorted(ids(unittest.defaultTestLoader.loadTestsFromName('tests_ft7.test_social_feedback_binding')))
    if reuse!=actual_reuse or actual_binding!=expected_binding or len(previous+reuse+actual_binding)!=360:
        raise ValueError('360 exact predecessor identities differ')
    (out/'predecessor_ids.json').write_text(json.dumps(previous+reuse+actual_binding,indent=2)+'\n')
    os.environ.update(FT7_PREPARATION_NATIVE=str(native_root),FT7_PREPARATION_BINDINGS=str(binding_root),FT7_PREPARATION_OUTPUT=str(out))
    input_hashes={}
    for label,root in (('native',native_root),('binding',binding_root)):
        index=json.loads((root/'record_index.json').read_text())
        for row in index:
            if row['key'] in protocol['inputs']['keys']:
                if digest(root/row['file'])!=row['sha256']:raise ValueError('input saved hash differs')
                input_hashes[label+'/'+row['key']]=row['sha256']
    (out/'input_hashes.json').write_text(json.dumps(input_hashes,indent=2)+'\n')
    audits={};index=[]
    for setting in ('canonical','workflow'):
        original,s,b=source(setting);native=original.checkpoint()
        source_audit=audit_saved(setting+'/harder',tuple(original.world.journal()),s,native)
        e=engine_type(setting).restore(native);p=SocialPaidPreparation(e,s,b)
        def save(stage):
            key=setting+'/'+stage;path=out/'records'/(setting+'-'+stage+'.json.gz')
            row=(key,e.checkpoint(),p.checkpoint(e))
            with gzip.open(path,'wt',encoding='ascii') as f:f.write(codec.dumps(row)+'\n')
            decoded=read_record(path)
            if decoded!=row:raise ValueError('typed saved roundtrip differs')
            restored=engine_type(setting).restore(decoded[1])
            audit=audit_social_preparation(restored,original,s,b,decoded[2])
            audits[key]=dict(source=source_audit,preparation=audit)
            index.append(dict(key=key,file=str(path.relative_to(out)),sha256=digest(path)))
            (out/'decoded_audits.json').write_text(json.dumps(audits,indent=2)+'\n')
            (out/'record_index.json').write_text(json.dumps(index,indent=2)+'\n')
            print(key+': independently audited',flush=True)
            del restored,decoded,row;gc.collect()
        save('before');p.step(e,work_limit=1);save('partial')
        partial_native=e.checkpoint();partial_wrapper=p.checkpoint(e)
        p.step(e,work_limit=1);save('complete')
        del e,p;gc.collect()
        e=engine_type(setting).restore(partial_native)
        p=SocialPaidPreparation.restore(partial_wrapper,e,original,s,b)
        p.step(e,work_limit=1);save('restarted')
        del original,s,b,e,p,native,partial_native,partial_wrapper;gc.collect()
    suite=unittest.defaultTestLoader.loadTestsFromName('tests_ft7.test_social_preparation')
    actual=sorted(ids(suite));expected=sorted('tests_ft7.test_social_preparation.SocialPreparationTests.'+m for m in protocol['registered_tests'])
    if actual!=expected:raise ValueError('exact new method domain differs')
    (out/'method_ids.json').write_text(json.dumps(actual,indent=2)+'\n')
    with (out/'controls.log').open('w') as log:result=unittest.TextTestRunner(stream=log,verbosity=2).run(suite)
    passed=result.wasSuccessful() and before==freeze() and sorted(audits)==sorted(protocol['saved_records'])
    summary=dict(batch=protocol['batch'],passed=passed,methods=result.testsRun,failures=len(result.failures),errors=len(result.errors),
        predecessor_identities=360,saved_records=len(index),exact_method_domain=actual==expected,typed_roundtrip_exact=True,
        independent_audits=True,source_unchanged=before==freeze(),frozen_identities=len(before),input_hashes=input_hashes,
        claim='Fresh exact paid reserve preparation only; no parent or autonomous tie-only choice acceptance')
    (out/'summary.json').write_text(json.dumps(summary,indent=2)+'\n');print(json.dumps(summary,indent=2),flush=True)
    if not passed:raise SystemExit(1)

if __name__=='__main__':main(*(Path(x).resolve() for x in sys.argv[1:4]))
