"""Saved native evidence -> audited role domain; no accepted engine rerun."""
from pathlib import Path
import gc,gzip,hashlib,json,os,sys,unittest
ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT),str(ROOT/'baseline/HLE_Rebuild_R21B')]
PREFIX='FT7_1b2b3b2b2b2b2a'
def digest(p):return hashlib.sha256(p.read_bytes()).hexdigest()

def freeze():
    prior=ROOT/'contracts/ft/FT7_1b2b3b2b2b2b1_Source_Freeze_v1.json'
    names=set(json.loads(prior.read_text()))|{str(prior.relative_to(ROOT))}
    names.update(('contracts/ft/'+PREFIX+'_Protocol_v1.json','contracts/ft/'+PREFIX+'_Protocol_v1.sha256',
        'full_theory/owned_role_domain.py','full_theory/owned_role_domain_audit.py',
        'tests_ft7/test_owned_role_domain.py','tools/evaluate_ft7_1b2b3b2b2b2b2a.py'))
    return {n:digest(ROOT/n) for n in sorted(names)}

def predecessors():
    from tools.evaluate_ft7_1b2b3b2b2b2b1 import predecessors as previous
    from tools.evaluate_ft6_3b import ids
    methods=sorted(ids(unittest.defaultTestLoader.loadTestsFromName('tests_ft7.test_compared_preparation')))
    p=json.loads((ROOT/'contracts/ft/FT7_1b2b3b2b2b2b1_Protocol_v1.json').read_text())
    if methods!=sorted('tests_ft7.test_compared_preparation.ComparedPreparationTests.'+m for m in p['registered_tests']):
        raise ValueError('exact predecessor methods')
    result=previous()+methods
    if len(result)!=428:raise ValueError('428 exact predecessor identities required')
    return result

def main(original,out):
    from hle_unified import codec
    from full_theory.owned_role_domain import owned_role_domain
    from full_theory.owned_role_domain_audit import audit_owned_role_domain
    from tests_ft7.test_social_live_outcome import read_record,engine_type
    from tests_ft7.test_owned_paid_comparison import paid_type
    from tools.evaluate_ft6_3b import ids
    out.mkdir(parents=True,exist_ok=False);(out/'records').mkdir()
    before=freeze();registered=json.loads((ROOT/('contracts/ft/'+PREFIX+'_Source_Freeze_v1.json')).read_text())
    if before!=registered:raise ValueError('source freeze differs')
    prior=json.loads((ROOT/'contracts/ft/FT7_1b2b3b2b2b2b1_Source_Freeze_v1.json').read_text())
    if any(before[n]!=h for n,h in prior.items()):raise ValueError('accepted source changed')
    pp=ROOT/('contracts/ft/'+PREFIX+'_Protocol_v1.json');p=json.loads(pp.read_text())
    if digest(pp)!=pp.with_suffix('.sha256').read_text().split()[0]:raise ValueError('protocol hash')
    previous=predecessors();(out/'predecessor_ids.json').write_text(json.dumps(previous,indent=2)+'\n')
    (out/'source_freeze.json').write_text(json.dumps(before,indent=2)+'\n')
    os.environ['FT7_ROLE_DOMAIN_OUTPUT']=str(out)
    incoming=json.loads((original/'record_index.json').read_text())
    if sorted(x['key'] for x in incoming)!=sorted(p['saved_records']):raise ValueError('exact input domain')
    index=[];audits={}
    for item in incoming:
        path=original/item['file']
        if digest(path)!=item['sha256']:raise ValueError('saved input identity')
        row=read_record(path);setting=row[0].split('/')[0]
        old=engine_type(setting).restore(row[1]);comparison=paid_type(setting).restore(row[5]);e=paid_type(setting).restore(row[8])
        args=(e,comparison,old,row[2],row[3],row[4],row[6],row[7],row[9])
        result=owned_role_domain(*args);output=(*row,result)
        dest=out/item['file']
        with gzip.open(dest,'wt',encoding='ascii') as f:f.write(codec.dumps(output)+'\n')
        index.append(dict(key=row[0],file=item['file'],sha256=digest(dest),input_sha256=item['sha256']))
        (out/'record_index.json').write_text(json.dumps(index,indent=2)+'\n')
        decoded=read_record(dest)
        if decoded!=output:raise ValueError('typed roundtrip')
        audits[row[0]]=audit_owned_role_domain(*args,decoded[10])
        (out/'decoded_audits.json').write_text(json.dumps(audits,indent=2)+'\n')
        if (e.checkpoint(),comparison.checkpoint(),old.checkpoint())!=(row[8],row[5],row[1]):raise ValueError('immutable input changed')
        print(row[0]+': exact saved role domain independently audited',flush=True)
        del old,comparison,e,args,row,result,output,decoded;gc.collect()
    suite=unittest.defaultTestLoader.loadTestsFromName('tests_ft7.test_owned_role_domain')
    actual=sorted(ids(suite));expected=sorted('tests_ft7.test_owned_role_domain.OwnedRoleDomainTests.'+m for m in p['registered_tests'])
    if actual!=expected:raise ValueError('exact new methods')
    (out/'method_ids.json').write_text(json.dumps(actual,indent=2)+'\n')
    with (out/'controls.log').open('w') as stream:result=unittest.TextTestRunner(stream=stream,verbosity=2).run(suite)
    summary=dict(batch=p['batch'],passed=result.wasSuccessful() and before==freeze() and sorted(audits)==sorted(p['saved_records']),
        methods=result.testsRun,failures=len(result.failures),errors=len(result.errors),predecessor_identities=len(previous),
        saved_records=len(index),typed_roundtrip_exact=True,independent_audits=True,source_unchanged=before==freeze(),
        frozen_identities=len(before),accepted_paid_work_rerun=False,claim='Paid role vocabulary only; no newly paid comparison, admission or live choice')
    (out/'summary.json').write_text(json.dumps(summary,indent=2)+'\n');print(json.dumps(summary,indent=2),flush=True)
    if not summary['passed']:raise SystemExit(1)

if __name__=='__main__':main(*(Path(x).resolve() for x in sys.argv[1:3]))
