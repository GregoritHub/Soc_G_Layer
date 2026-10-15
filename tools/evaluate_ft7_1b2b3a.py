"""Frozen bounded binding gate over the exact 24 accepted native sources."""
from pathlib import Path
import gc,gzip,hashlib,json,os,sys,unittest
ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT),str(ROOT/'baseline/HLE_Rebuild_R21B')]

def digest(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def freeze():
    names=set(json.loads((ROOT/'contracts/ft/FT7_1b2b2b_Saved_Audit_Source_Freeze_v1.json').read_text()))
    names.update(('contracts/ft/FT7_1b2b2b_Saved_Audit_Source_Freeze_v1.json','contracts/ft/FT7_1b2b3a_Protocol_v1.json','contracts/ft/FT7_1b2b3a_Protocol_v1.sha256','full_theory/social_feedback_binding.py','full_theory/social_feedback_binding_audit.py','tests_ft7/test_social_feedback_binding.py','tools/evaluate_ft7_1b2b3a.py','tools/prepare_workspace.py'))
    names.update(str(p.relative_to(ROOT)) for p in (ROOT/'contracts/ft').glob('FT7_1b2b3a_*Amendment*') if p.is_file())
    return {n:digest(ROOT/n) for n in sorted(names)}

def main(source,out):
    from hle_unified import codec
    from hle_unified.selection_records import loads
    from hle_unified.selection_execution import SelectionEngine
    from hle_unified.workflow_selection_execution import WorkflowFinalSelectionEngine
    from full_theory.social_feedback_binding import SocialPostUseBinding
    from full_theory.social_feedback_binding_audit import audit_social_feedback_binding
    from tools.audit_ft7_1b2b2b_saved import predecessor_ids,expected_methods
    from tools.evaluate_ft6_3b import ids
    from tools.evaluate_ft7_1b2b2b import audit_saved
    out.mkdir(parents=True,exist_ok=False);(out/'records').mkdir()
    before=freeze();registered=json.loads((ROOT/'contracts/ft/FT7_1b2b3a_Source_Freeze_v1.json').read_text())
    if before!=registered:raise ValueError('registered binding freeze mismatch')
    pp=ROOT/'contracts/ft/FT7_1b2b3a_Protocol_v1.json';p=json.loads(pp.read_text())
    if digest(pp)!=pp.with_suffix('.sha256').read_text().split()[0]:raise ValueError('protocol hash differs')
    predecessor=predecessor_ids();oldmethods,split=expected_methods()
    actual_old=sorted(ids(unittest.defaultTestLoader.loadTestsFromName('tests_ft7.test_social_reuse')))
    if actual_old!=oldmethods or len(predecessor+actual_old)!=352:raise ValueError('exact 352 predecessor identities differ')
    accepted=json.loads((source/'summary.json').read_text());index=json.loads((source/'record_index.json').read_text())
    expected_keys={s+'/'+m for s in ('canonical','workflow') for m in split['scenarios_per_setting']}|{s+'/'+m+'/restart-'+q for s in ('canonical','workflow') for m in split['restarts_per_setting'] for q in ('final','partial')}
    if not accepted['passed'] or accepted['aggregate_checksum_verified']['payload_sha256']!=p['input']['aggregate_payload_sha256'] or len(index)!=24 or {x['key'] for x in index}!=expected_keys:raise ValueError('accepted exact input domain differs')
    for item in index:
        if digest(source/item['file'])!=item['sha256']:raise ValueError('input record hash differs')
    os.environ['FT7_POST_USE_INPUT']=str(source)
    suite=unittest.defaultTestLoader.loadTestsFromName('tests_ft7.test_social_feedback_binding');actual=sorted(ids(suite))
    expected=sorted('tests_ft7.test_social_feedback_binding.SocialFeedbackBindingTests.'+m for m in p['registered_tests'])
    if actual!=expected:raise ValueError('exact binding method domain differs')
    (out/'method_ids.json').write_text(json.dumps(actual,indent=2)+'\n')
    with (out/'controls.log').open('w') as log:result=unittest.TextTestRunner(stream=log,verbosity=2).run(suite)
    gc.collect();audits={};records=[]
    for i,item in enumerate(index):
        with gzip.open(source/item['file'],'rt',encoding='ascii') as f:key,txs,wrapper,native=codec.loads(f.read())
        source_audit=audit_saved(key,txs,wrapper,native)
        engine=(SelectionEngine if key.startswith('canonical/') else WorkflowFinalSelectionEngine).restore(native)
        binding=SocialPostUseBinding(engine,wrapper);text=binding.checkpoint()
        path=out/'records'/(str(i+1).zfill(2)+'.json.gz')
        row=(key,item['sha256'],hashlib.sha256(wrapper.encode()).hexdigest(),text)
        with gzip.open(path,'wt',encoding='ascii') as f:f.write(codec.dumps(row)+'\n')
        with gzip.open(path,'rt',encoding='ascii') as f:decoded=codec.loads(f.read())
        if decoded!=row:raise ValueError('saved exact binding roundtrip differs')
        audit=audit_social_feedback_binding(engine,wrapper,decoded[3])
        if engine.checkpoint()!=native:raise ValueError('observer mutated native state')
        audits[key]=dict(passed=source_audit['passed'] and audit['passed'],source=source_audit,binding=audit)
        records.append(dict(key=key,file=str(path.relative_to(out)),sha256=digest(path),source_file=item['file'],source_sha256=item['sha256']))
        (out/'record_index.json').write_text(json.dumps(records,indent=2)+'\n');(out/'decoded_audits.json').write_text(json.dumps(audits,indent=2)+'\n')
        print(key+': '+str(audits[key]['passed']),flush=True)
        del engine,binding,text,row,decoded,txs,wrapper,native,source_audit;gc.collect()
    passed=result.wasSuccessful() and before==freeze() and set(audits)==expected_keys and all(x['passed'] for x in audits.values())
    summary=dict(batch=p['batch'],passed=passed,methods=result.testsRun,failures=len(result.failures),errors=len(result.errors),exact_methods=actual==expected,predecessor_identities=352,saved_records=len(records),exact_record_domain=set(audits)==expected_keys,raw_roundtrip_exact=True,decoded_independent_audits=all(x['passed'] for x in audits.values()),source_unchanged=before==freeze(),registered_freeze=before==registered,protocol_sha256=digest(pp),claim='Exact immutable-prefix native reserve/history binding only; no choice causality; FT7.1b2b3b and FT8-FT9 remain mandatory')
    (out/'summary.json').write_text(json.dumps(summary,indent=2)+'\n');(out/'source_freeze.json').write_text(json.dumps(before,indent=2)+'\n');(out/'input_index.json').write_text(json.dumps(index,indent=2)+'\n')
    print(json.dumps(summary,indent=2),flush=True)
    if not passed:raise SystemExit(1)
if __name__=='__main__':main(Path(sys.argv[1]).resolve(),Path(sys.argv[2]).resolve())
