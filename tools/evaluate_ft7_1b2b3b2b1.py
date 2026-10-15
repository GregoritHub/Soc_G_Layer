"""Freeze and exact saved-record gate for the owned proposal prerequisite."""
from pathlib import Path
import gc,gzip,hashlib,json,os,sys,unittest
ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT),str(ROOT/'baseline/HLE_Rebuild_R21B')]
PREFIX='FT7_1b2b3b2b1'

def digest(p):return hashlib.sha256(p.read_bytes()).hexdigest()

def freeze():
    prior=ROOT/'contracts/ft/FT7_1b2b3b2a_Source_Freeze_v1.json'
    names=set(json.loads(prior.read_text()))|{str(prior.relative_to(ROOT))}
    names.update(('contracts/ft/'+PREFIX+'_Protocol_v1.json','contracts/ft/'+PREFIX+'_Protocol_v1.sha256',
        'full_theory/owned_proposal_domain.py','full_theory/owned_proposal_domain_audit.py',
        'tests_ft7/test_owned_proposal_domain.py','tools/evaluate_ft7_1b2b3b2b1.py',
        'hle_unified/selection_policy.py','hle_unified/selection_audit.py'))
    return {n:digest(ROOT/n) for n in sorted(names)}

def predecessors():
    from tools.evaluate_ft7_1b2b3b2a import predecessors as previous
    from tools.evaluate_ft6_3b import ids
    methods=sorted(ids(unittest.defaultTestLoader.loadTestsFromName('tests_ft7.test_social_live_outcome')))
    protocol=json.loads((ROOT/'contracts/ft/FT7_1b2b3b2a_Protocol_v1.json').read_text())
    expected=sorted('tests_ft7.test_social_live_outcome.SocialLiveOutcomeTests.'+m for m in protocol['registered_tests'])
    if methods!=expected:raise ValueError('exact predecessor methods differ')
    result=previous()+methods
    if len(result)!=378:raise ValueError('378 exact predecessors required')
    return result

def main(native,binding,out):
    from hle_unified import codec
    from full_theory.owned_proposal_domain import owned_proposal_domain
    from full_theory.owned_proposal_domain_audit import audit_owned_proposal_domain
    from tests_ft7.test_social_live_outcome import source,read_record,engine_type
    from tools.evaluate_ft6_3b import ids
    from tools.evaluate_ft7_1b2b2b import audit_saved
    out.mkdir(parents=True,exist_ok=False);(out/'records').mkdir()
    before=freeze();registered=json.loads((ROOT/('contracts/ft/'+PREFIX+'_Source_Freeze_v1.json')).read_text())
    if before!=registered:raise ValueError('source freeze differs')
    prior=json.loads((ROOT/'contracts/ft/FT7_1b2b3b2a_Source_Freeze_v1.json').read_text())
    if any(before[n]!=h for n,h in prior.items()):raise ValueError('accepted source changed')
    pp=ROOT/('contracts/ft/'+PREFIX+'_Protocol_v1.json');protocol=json.loads(pp.read_text())
    if digest(pp)!=pp.with_suffix('.sha256').read_text().split()[0]:raise ValueError('protocol hash')
    (out/'source_freeze.json').write_text(json.dumps(before,indent=2)+'\n')
    previous=predecessors();(out/'predecessor_ids.json').write_text(json.dumps(previous,indent=2)+'\n')
    os.environ.update(FT7_LIVE_NATIVE=str(native),FT7_LIVE_BINDINGS=str(binding),FT7_DOMAIN_OUTPUT=str(out))
    audits={};index=[]
    for key in protocol['saved_records']:
        setting,case=key.split('/');e,s,b=source(setting,case);n=e.checkpoint()
        source_report=audit_saved(key,tuple(e.world.journal()),s,n)
        text=owned_proposal_domain(e,s,b)
        if e.checkpoint()!=n:raise ValueError('native state mutated')
        row=(key,n,s,b,text);path=out/'records'/(setting+'-'+case+'.json.gz')
        with gzip.open(path,'wt',encoding='ascii') as f:f.write(codec.dumps(row)+'\n')
        decoded=read_record(path)
        if decoded!=row:raise ValueError('typed roundtrip differs')
        restored=engine_type(setting).restore(decoded[1])
        report=audit_owned_proposal_domain(restored,decoded[2],decoded[3],decoded[4])
        audits[key]=dict(source=source_report,domain=report)
        index.append(dict(key=key,file=str(path.relative_to(out)),sha256=digest(path)))
        (out/'record_index.json').write_text(json.dumps(index,indent=2)+'\n')
        (out/'decoded_audits.json').write_text(json.dumps(audits,indent=2)+'\n')
        print(key+': saved and independently reconstructed',flush=True)
        del e,s,b,n,text,row,decoded,restored;gc.collect()
    suite=unittest.defaultTestLoader.loadTestsFromName('tests_ft7.test_owned_proposal_domain')
    actual=sorted(ids(suite));expected=sorted('tests_ft7.test_owned_proposal_domain.OwnedProposalDomainTests.'+m for m in protocol['registered_tests'])
    if actual!=expected:raise ValueError('exact new methods differ')
    (out/'method_ids.json').write_text(json.dumps(actual,indent=2)+'\n')
    with (out/'controls.log').open('w') as stream:result=unittest.TextTestRunner(stream=stream,verbosity=2).run(suite)
    summary=dict(batch=protocol['batch'],passed=result.wasSuccessful() and before==freeze() and sorted(audits)==sorted(protocol['saved_records']),
        methods=result.testsRun,failures=len(result.failures),errors=len(result.errors),predecessor_identities=len(previous),saved_records=len(index),
        typed_roundtrip_exact=True,independent_audits=True,source_unchanged=before==freeze(),frozen_identities=len(before),
        claim='Complete bounded owned native proposal inventory only; no TD5 admission, paid comparison, history-caused choice or parent acceptance')
    (out/'summary.json').write_text(json.dumps(summary,indent=2)+'\n');print(json.dumps(summary,indent=2),flush=True)
    if not summary['passed']:raise SystemExit(1)

if __name__=='__main__':main(*(Path(x).resolve() for x in sys.argv[1:4]))
