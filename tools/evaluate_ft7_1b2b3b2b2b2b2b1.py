"""Frozen actual paid role comparison gate; old accepted work is restored only."""
from pathlib import Path
import gc,gzip,hashlib,json,os,sys,unittest
ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT),str(ROOT/'baseline/HLE_Rebuild_R21B')]
PREFIX='FT7_1b2b3b2b2b2b2b1'
def digest(p):return hashlib.sha256(p.read_bytes()).hexdigest()


def freeze():
    prior=ROOT/'contracts/ft/FT7_1b2b3b2b2b2b2a_Source_Freeze_v1.json'
    names=set(json.loads(prior.read_text()))|{str(prior.relative_to(ROOT))}
    names.update(('contracts/ft/'+PREFIX+'_Protocol_v1.json','contracts/ft/'+PREFIX+'_Protocol_v1.sha256',
        'contracts/ft/'+PREFIX+'_Amendment_v2.json','contracts/ft/'+PREFIX+'_Amendment_v2.sha256',
        'contracts/ft/'+PREFIX+'_Source_Freeze_v1.json',
        'full_theory/paid_role_comparison.py','full_theory/paid_role_comparison_audit.py',
        'tests_ft7/test_paid_role_comparison.py','tools/evaluate_ft7_1b2b3b2b2b2b2b1.py'))
    return {n:digest(ROOT/n) for n in sorted(names)}


def predecessors():
    from tools.evaluate_ft7_1b2b3b2b2b2b2a import predecessors as previous
    from tools.evaluate_ft6_3b import ids
    methods=sorted(ids(unittest.defaultTestLoader.loadTestsFromName('tests_ft7.test_owned_role_domain')))
    p=json.loads((ROOT/'contracts/ft/FT7_1b2b3b2b2b2b2a_Protocol_v1.json').read_text())
    if methods!=sorted('tests_ft7.test_owned_role_domain.OwnedRoleDomainTests.'+m for m in p['registered_tests']):raise ValueError('predecessor methods')
    result=previous()+methods
    if len(result)!=436:raise ValueError('436 exact predecessor identities required')
    return result


def main(original,out):
    from hle_unified import codec
    from hle_unified.selection_records import loads,dumps
    from full_theory.owned_role_domain_audit import audit_owned_role_domain
    from full_theory.paid_role_comparison import prepare_role_comparison,step_role_comparison
    from full_theory.paid_role_comparison_audit import reconstruct,audit_paid_roles
    from tests_ft7.test_social_live_outcome import read_record,engine_type
    from tests_ft7.test_owned_paid_comparison import paid_type
    from tests_ft7.test_paid_role_comparison import role_type
    from tools.evaluate_ft6_3b import ids
    out.mkdir(parents=True,exist_ok=False);(out/'records').mkdir()
    before=freeze();registered=json.loads((ROOT/('contracts/ft/'+PREFIX+'_Source_Freeze_v2.json')).read_text())
    if before!=registered:raise ValueError('source freeze differs')
    prior=json.loads((ROOT/'contracts/ft/FT7_1b2b3b2b2b2b2a_Source_Freeze_v1.json').read_text())
    if any(before[n]!=h for n,h in prior.items()):raise ValueError('accepted source changed')
    pp=ROOT/('contracts/ft/'+PREFIX+'_Protocol_v1.json');p=json.loads(pp.read_text())
    if digest(pp)!=pp.with_suffix('.sha256').read_text().split()[0]:raise ValueError('protocol hash')
    previous=predecessors();(out/'predecessor_ids.json').write_text(json.dumps(previous,indent=2)+'\n')
    (out/'source_freeze.json').write_text(json.dumps(before,indent=2)+'\n')
    os.environ['FT7_PAID_ROLES_OUTPUT']=str(out);os.environ['FT7_PAID_ROLES_INPUT']=str(original)
    incoming=json.loads((original/'record_index.json').read_text());index=[];audits={}
    for setting in ('canonical','workflow'):
        item=next(x for x in incoming if x['key']==setting+'/complete');path=original/item['file']
        if digest(path)!=item['sha256']:raise ValueError('input identity')
        row=read_record(path);old=paid_type(setting).restore(row[8]);comparison=paid_type(setting).restore(row[5]);source=engine_type(setting).restore(row[1])
        audit_owned_role_domain(old,comparison,source,row[2],row[3],row[4],row[6],row[7],row[9],row[10])
        del comparison,source;gc.collect()
        print(setting+': exact accepted input independently audited',flush=True)
        expected=reconstruct(old,row[10],row[9]);required=sum(x['required'] for x in expected)
        e,r=prepare_role_comparison(old,row[10],row[9],tuple(row[1:8]));actor=loads(row[10])['request']['actor']
        def save(stage,engine):
            key=setting+'/'+stage;native=engine.checkpoint()
            result=None if (actor,r.key) not in engine._jobs else engine.role_result(actor,r.key)
            data=(key,native,dumps(expected),dumps(result));dest=out/'records'/(setting+'-'+stage+'.json.gz')
            with gzip.open(dest,'wt',encoding='ascii') as f:f.write(codec.dumps(data)+'\n')
            index.append(dict(key=key,file=str(dest.relative_to(out)),sha256=digest(dest),input_sha256=item['sha256']))
            (out/'record_index.json').write_text(json.dumps(index,indent=2)+'\n')
            if read_record(dest)!=data:raise ValueError('typed roundtrip')
            audits[key]=audit_paid_roles(engine,old,row[10],row[9])
            (out/'decoded_audits.json').write_text(json.dumps(audits,indent=2)+'\n')
            print(key+': exact saved paid role audit '+str(audits[key]),flush=True)
        save('before',e);step_role_comparison(e,r,work_limit=1);save('partial',e);partial=e.checkpoint()
        step_role_comparison(e,r,work_limit=required,settle=False);save('ready',e)
        step_role_comparison(e,r,work_limit=required);save('complete',e);complete=e.checkpoint();del e;gc.collect()
        e=role_type(setting).restore(partial);step_role_comparison(e,r,work_limit=required,settle=False)
        step_role_comparison(e,r,work_limit=required)
        if e.checkpoint()!=complete:raise ValueError('partial restart differs')
        save('restarted',e);del e,complete;gc.collect()
        e=role_type(setting).restore(partial);e.cancel(r.key+':cancel',actor,r.key);save('cancelled',e)
        del e,old,row,expected,partial;gc.collect()
    suite=unittest.defaultTestLoader.loadTestsFromName('tests_ft7.test_paid_role_comparison');actual=sorted(ids(suite))
    if actual!=sorted('tests_ft7.test_paid_role_comparison.PaidRoleComparisonTests.'+m for m in p['registered_tests']):raise ValueError('exact new methods')
    (out/'method_ids.json').write_text(json.dumps(actual,indent=2)+'\n')
    with (out/'controls.log').open('w') as stream:result=unittest.TextTestRunner(stream=stream,verbosity=2).run(suite)
    summary=dict(batch=p['batch'],passed=result.wasSuccessful() and before==freeze() and sorted(audits)==sorted(p['saved_records']),
        methods=result.testsRun,failures=len(result.failures),errors=len(result.errors),predecessor_identities=len(previous),saved_records=len(index),
        typed_roundtrip_exact=True,independent_audits=True,source_unchanged=before==freeze(),frozen_identities=len(before),accepted_paid_work_rerun=False,
        claim='Paid complete declared role comparison only; no TD5 or live choice acceptance')
    (out/'summary.json').write_text(json.dumps(summary,indent=2)+'\n');print(json.dumps(summary,indent=2),flush=True)
    if not summary['passed']:raise SystemExit(1)


if __name__=='__main__':main(*(Path(x).resolve() for x in sys.argv[1:3]))
