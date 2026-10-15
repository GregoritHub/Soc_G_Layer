"""Bounded new live suffix gate over accepted saved native inputs."""
from pathlib import Path
import gc,gzip,hashlib,json,os,sys,unittest
ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT),str(ROOT/'baseline/HLE_Rebuild_R21B')]

def digest(p):return hashlib.sha256(p.read_bytes()).hexdigest()

def freeze():
    names=set(json.loads((ROOT/'contracts/ft/FT7_1b2b3b1_Source_Freeze_v1.json').read_text()))
    names.update(('contracts/ft/FT7_1b2b3b1_Source_Freeze_v1.json',
        'contracts/ft/FT7_1b2b3b2a_Protocol_v1.json','contracts/ft/FT7_1b2b3b2a_Protocol_v1.sha256',
        'full_theory/social_live_outcome.py','full_theory/social_live_outcome_audit.py',
        'tests_ft7/test_social_live_outcome.py','tools/evaluate_ft7_1b2b3b2a.py'))
    return {n:digest(ROOT/n) for n in sorted(names)}

def predecessors():
    from tools.audit_ft7_1b2b2b_saved import predecessor_ids,expected_methods
    from tools.evaluate_ft6_3b import ids
    old=predecessor_ids();reuse,_=expected_methods()
    actual=sorted(ids(unittest.defaultTestLoader.loadTestsFromName('tests_ft7.test_social_reuse')))
    if actual!=reuse:raise ValueError('exact reuse methods differ')
    old+=reuse
    for batch,module,cls in (('3a','social_feedback_binding','SocialFeedbackBindingTests'),
                             ('3b1','social_preparation','SocialPreparationTests')):
        p=json.loads((ROOT/('contracts/ft/FT7_1b2b'+batch+'_Protocol_v1.json')).read_text())
        expected=sorted('tests_ft7.test_'+module+'.'+cls+'.'+m for m in p['registered_tests'])
        actual=sorted(ids(unittest.defaultTestLoader.loadTestsFromName('tests_ft7.test_'+module)))
        if expected!=actual:raise ValueError('exact predecessor methods differ')
        old+=actual
    if len(old)!=368:raise ValueError('368 exact predecessor methods required')
    return old

def main(native_root,binding_root,out):
    from hle_unified import codec
    from full_theory.social_live_outcome import SocialLiveOutcome
    from full_theory.social_live_outcome_audit import audit_social_live_outcome
    from tests_ft7.test_social_live_outcome import source,engine_type,read_record
    from tools.evaluate_ft6_3b import ids
    from tools.evaluate_ft7_1b2b2b import audit_saved
    out.mkdir(parents=True,exist_ok=False);(out/'records').mkdir()
    before=freeze();registered=json.loads((ROOT/'contracts/ft/FT7_1b2b3b2a_Source_Freeze_v1.json').read_text())
    if before!=registered:raise ValueError('freeze differs')
    prior=json.loads((ROOT/'contracts/ft/FT7_1b2b3b1_Source_Freeze_v1.json').read_text())
    if any(before[n]!=h for n,h in prior.items()):raise ValueError('accepted source changed')
    pp=ROOT/'contracts/ft/FT7_1b2b3b2a_Protocol_v1.json';protocol=json.loads(pp.read_text())
    if digest(pp)!=pp.with_suffix('.sha256').read_text().split()[0]:raise ValueError('protocol hash differs')
    (out/'source_freeze.json').write_text(json.dumps(before,indent=2)+'\n')
    previous=predecessors();(out/'predecessor_ids.json').write_text(json.dumps(previous,indent=2)+'\n')
    os.environ.update(FT7_LIVE_NATIVE=str(native_root),FT7_LIVE_BINDINGS=str(binding_root),FT7_LIVE_OUTPUT=str(out))
    audits={};index=[]
    for setting in ('canonical','workflow'):
        original,s,b=source(setting)
        original_native=original.checkpoint()
        input_audit=audit_saved(setting+'/partial-movement',tuple(original.world.journal()),s,original_native)
        e=engine_type(setting).restore(original_native);p=SocialLiveOutcome(e,s,b)
        def save(stage):
            key=setting+'/'+stage;path=out/'records'/(setting+'-'+stage+'.json.gz')
            row=(key,e.checkpoint(),p.checkpoint(e))
            with gzip.open(path,'wt',encoding='ascii') as f:f.write(codec.dumps(row)+'\n')
            decoded=read_record(path)
            if decoded!=row:raise ValueError('typed roundtrip differs')
            restored=engine_type(setting).restore(decoded[1])
            audits[key]=dict(source=input_audit,live=audit_social_live_outcome(restored,original,s,b,decoded[2]))
            index.append(dict(key=key,file=str(path.relative_to(out)),sha256=digest(path)))
            (out/'record_index.json').write_text(json.dumps(index,indent=2)+'\n')
            (out/'decoded_audits.json').write_text(json.dumps(audits,indent=2)+'\n')
            print(key+': independently audited',flush=True)
            del restored,decoded,row;gc.collect()
        save('before');p.step(e,work_limit=1);save('movement-partial')
        mn,mw=e.checkpoint(),p.checkpoint(e)
        p.step(e,work_limit=1000000)
        if p.cycle.phase!='consumer':raise ValueError('movement did not complete')
        save('movement-complete');p.step(e,work_limit=1);save('consumer-partial')
        cn,cw=e.checkpoint(),p.checkpoint(e)
        p.step(e,work_limit=1000000);save('complete')
        del e,p;gc.collect()
        for split,n,w in (('movement',mn,mw),('consumer',cn,cw)):
            e=engine_type(setting).restore(n);p=SocialLiveOutcome.restore(w,e,original,s,b)
            if split=='movement':p.step(e,work_limit=1000000);p.step(e,work_limit=1)
            p.step(e,work_limit=1000000);save('restart-'+split+'-final')
            del e,p;gc.collect()
        del original,s,b,original_native,mn,mw,cn,cw;gc.collect()
        original,s,b=source(setting,'harder');e=engine_type(setting).restore(original.checkpoint())
        input_audit=audit_saved(setting+'/harder',tuple(original.world.journal()),s,original.checkpoint())
        p=SocialLiveOutcome(e,s,b);p.step(e);save('deferred')
        del original,s,b,e,p;gc.collect()
    suite=unittest.defaultTestLoader.loadTestsFromName('tests_ft7.test_social_live_outcome')
    actual=sorted(ids(suite));expected=sorted('tests_ft7.test_social_live_outcome.SocialLiveOutcomeTests.'+m for m in protocol['registered_tests'])
    if actual!=expected:raise ValueError('exact new method domain differs')
    (out/'method_ids.json').write_text(json.dumps(actual,indent=2)+'\n')
    with (out/'controls.log').open('w') as log:result=unittest.TextTestRunner(stream=log,verbosity=2).run(suite)
    passed=result.wasSuccessful() and before==freeze() and sorted(audits)==sorted(protocol['saved_records'])
    summary=dict(batch=protocol['batch'],passed=passed,methods=result.testsRun,failures=len(result.failures),errors=len(result.errors),
        predecessor_identities=len(previous),saved_records=len(index),exact_method_domain=actual==expected,
        typed_roundtrip_exact=True,independent_audits=True,source_unchanged=before==freeze(),frozen_identities=len(before),
        claim='New paid live suffix outcome staging only; no candidate-domain, tie-only choice or parent acceptance')
    (out/'summary.json').write_text(json.dumps(summary,indent=2)+'\n');print(json.dumps(summary,indent=2),flush=True)
    if not passed:raise SystemExit(1)

if __name__=='__main__':main(*(Path(x).resolve() for x in sys.argv[1:4]))
