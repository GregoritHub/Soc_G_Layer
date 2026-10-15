"""Frozen versioned native paid comparison gate with bounded saved readback."""
from pathlib import Path
import gc,gzip,hashlib,json,os,sys,unittest
ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT),str(ROOT/'baseline/HLE_Rebuild_R21B')]
PREFIX='FT7_1b2b3b2b2a'
def digest(p):return hashlib.sha256(p.read_bytes()).hexdigest()

def freeze():
    prior=ROOT/'contracts/ft/FT7_1b2b3b2b1_Source_Freeze_v1.json'
    names=set(json.loads(prior.read_text()))|{str(prior.relative_to(ROOT))}
    names.update(('contracts/ft/'+PREFIX+'_Protocol_v1.json','contracts/ft/'+PREFIX+'_Protocol_v1.sha256',
        'contracts/ft/'+PREFIX+'_Access_Audit_Amendment_v1.json','contracts/ft/'+PREFIX+'_Access_Audit_Amendment_v1.sha256',
        'contracts/ft/'+PREFIX+'_Chronology_Audit_Amendment_v1.json','contracts/ft/'+PREFIX+'_Chronology_Audit_Amendment_v1.sha256',
        'full_theory/owned_paid_comparison.py','full_theory/owned_paid_comparison_audit.py',
        'tests_ft7/test_owned_paid_comparison.py','tools/evaluate_ft7_1b2b3b2b2a.py',
        'hle_unified/operations.py','hle_unified/operation_audit.py','hle_unified/shell.py','hle_unified/compact.py',
        'hle_unified/workflow_execution.py'))
    return {n:digest(ROOT/n) for n in sorted(names)}

def predecessors():
    from tools.evaluate_ft7_1b2b3b2b1 import predecessors as previous
    from tools.evaluate_ft6_3b import ids
    methods=sorted(ids(unittest.defaultTestLoader.loadTestsFromName('tests_ft7.test_owned_proposal_domain')))
    p=json.loads((ROOT/'contracts/ft/FT7_1b2b3b2b1_Protocol_v1.json').read_text())
    if methods!=sorted('tests_ft7.test_owned_proposal_domain.OwnedProposalDomainTests.'+m for m in p['registered_tests']):raise ValueError('exact predecessor methods')
    result=previous()+methods
    if len(result)!=388:raise ValueError('388 predecessor identities required')
    return result

def main(native,binding,out):
    from hle_unified import codec
    from full_theory.owned_paid_comparison import prepare_owned_comparison,step_owned_comparison
    from full_theory.owned_paid_comparison_audit import audit_owned_paid_comparison
    from tests_ft7.test_social_live_outcome import source,read_record,engine_type
    from tests_ft7.test_owned_paid_comparison import paid_type,request_for
    from tools.evaluate_ft6_3b import ids
    from tools.evaluate_ft7_1b2b2b import audit_saved
    out.mkdir(parents=True,exist_ok=False);(out/'records').mkdir()
    before=freeze();registered=json.loads((ROOT/('contracts/ft/'+PREFIX+'_Source_Freeze_v1.json')).read_text())
    if before!=registered:raise ValueError('source freeze differs')
    prior=json.loads((ROOT/'contracts/ft/FT7_1b2b3b2b1_Source_Freeze_v1.json').read_text())
    if any(before[n]!=h for n,h in prior.items()):raise ValueError('accepted source changed')
    pp=ROOT/('contracts/ft/'+PREFIX+'_Protocol_v1.json');p=json.loads(pp.read_text())
    if digest(pp)!=pp.with_suffix('.sha256').read_text().split()[0]:raise ValueError('protocol hash')
    (out/'source_freeze.json').write_text(json.dumps(before,indent=2)+'\n')
    previous=predecessors();(out/'predecessor_ids.json').write_text(json.dumps(previous,indent=2)+'\n')
    os.environ.update(FT7_LIVE_NATIVE=str(native),FT7_LIVE_BINDINGS=str(binding),FT7_PAID_COMPARISON_OUTPUT=str(out))
    index=[];audits={};source_audits={}
    for setting in ('canonical','workflow'):
        old,s,b=source(setting,'harder');n=old.checkpoint()
        source_audits[setting]=audit_saved(setting+'/harder',tuple(old.world.journal()),s,n)
        (out/'source_audits.json').write_text(json.dumps(source_audits,indent=2)+'\n')
        e,r,domain=prepare_owned_comparison(old,s,b)
        def save(case):
            key=setting+'/'+case;row=(key,n,s,b,domain,e.checkpoint())
            path=out/'records'/(setting+'-'+case+'.json.gz')
            with gzip.open(path,'wt',encoding='ascii') as f:f.write(codec.dumps(row)+'\n')
            index.append(dict(key=key,file=str(path.relative_to(out)),sha256=digest(path)))
            (out/'record_index.json').write_text(json.dumps(index,indent=2)+'\n')
            decoded=read_record(path)
            if decoded!=row:raise ValueError('typed roundtrip')
            restored=paid_type(setting).restore(decoded[5])
            audits[key]=audit_owned_paid_comparison(restored,old,decoded[2],decoded[3],decoded[4])
            (out/'decoded_audits.json').write_text(json.dumps(audits,indent=2)+'\n')
            print(key+': saved and independently audited',flush=True)
            del row,decoded,restored;gc.collect()
        save('before');step_owned_comparison(e,r,work_limit=1);save('partial')
        partial=e.checkpoint();required=e.job_status(r.request.actor,r.key)['required']
        step_owned_comparison(e,r,work_limit=required-1,settle=False);save('ready')
        step_owned_comparison(e,r);save('complete');complete=e.checkpoint()
        del e;gc.collect();e=paid_type(setting).restore(partial);r=request_for(e)
        step_owned_comparison(e,r,work_limit=required-1,settle=False);step_owned_comparison(e,r)
        if e.checkpoint()!=complete:raise ValueError('partial restart differs')
        save('restarted');del e;gc.collect();e=paid_type(setting).restore(partial);r=request_for(e)
        e.cancel(r.key+':cancel',r.request.actor,r.key);save('cancelled')
        if old.checkpoint()!=n:raise ValueError('original source changed')
        del e,old,s,b,n,domain,partial,complete;gc.collect()
    suite=unittest.defaultTestLoader.loadTestsFromName('tests_ft7.test_owned_paid_comparison')
    actual=sorted(ids(suite));expected=sorted('tests_ft7.test_owned_paid_comparison.OwnedPaidComparisonTests.'+m for m in p['registered_tests'])
    if actual!=expected:raise ValueError('exact method identities differ')
    (out/'method_ids.json').write_text(json.dumps(actual,indent=2)+'\n')
    with (out/'controls.log').open('w') as stream:result=unittest.TextTestRunner(stream=stream,verbosity=2).run(suite)
    summary=dict(batch=p['batch'],passed=result.wasSuccessful() and before==freeze() and sorted(audits)==sorted(p['saved_records']),
        methods=result.testsRun,failures=len(result.failures),errors=len(result.errors),predecessor_identities=len(previous),saved_records=len(index),
        typed_roundtrip_exact=True,independent_audits=True,source_unchanged=before==freeze(),frozen_identities=len(before),
        claim='Actual native paid owned comparison and restart only; no TD5 admission, history-caused choice, movement or parent acceptance')
    (out/'summary.json').write_text(json.dumps(summary,indent=2)+'\n');print(json.dumps(summary,indent=2),flush=True)
    if not summary['passed']:raise SystemExit(1)

if __name__=='__main__':main(*(Path(x).resolve() for x in sys.argv[1:4]))
