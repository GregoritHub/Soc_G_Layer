"""Single frozen owned-training gate; saved native records and exact readback."""
from pathlib import Path
import hashlib,json,sys,unittest
ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT),str(ROOT/'baseline/HLE_Rebuild_R21B')]

def digest(p):return hashlib.sha256(p.read_bytes()).hexdigest()

def freeze():
    predecessor=json.loads((ROOT/'contracts/ft/FT7_1b2a_Source_Freeze_v1.json').read_text())
    names=set(predecessor)|{'contracts/ft/FT7_1b2a_Source_Freeze_v1.json','contracts/ft/FT7_1b2b1_Protocol_v1.json','contracts/ft/FT7_1b2b1_Protocol_v1.sha256','contracts/ft/FT7_1b2b1_Preflight_Amendment_v1.json','contracts/ft/FT7_1b2b1_Preflight_Amendment_v1.sha256','full_theory/social_training.py','full_theory/social_training_audit.py','tests_ft7/training_fixtures.py','tests_ft7/test_social_training.py','tools/evaluate_ft7_1b2b1.py'}
    return {n:digest(ROOT/n) for n in sorted(names)}

def main(out):
    from hle_unified import codec
    from hle_unified.selection_records import loads
    from hle_unified.selection_execution import SelectionEngine
    from hle_unified.workflow_selection_execution import WorkflowFinalSelectionEngine
    from full_theory.peer_cycle_audit import audit_peer_cycle
    from full_theory.social_training_audit import audit_social_training
    from tools.evaluate_ft6_3b import ids
    out.mkdir(parents=True,exist_ok=False);before=freeze();(out/'source_freeze.json').write_text(json.dumps(before,indent=2)+'\n')
    registered=json.loads((ROOT/'contracts/ft/FT7_1b2b1_Source_Freeze_v1.json').read_text())
    if before!=registered:raise ValueError('source does not match registered freeze')
    predecessor=json.loads((ROOT/'contracts/ft/FT7_1b2a_Source_Freeze_v1.json').read_text())
    if any(digest(ROOT/n)!=h for n,h in predecessor.items()):raise ValueError('accepted predecessor changed')
    pp=ROOT/'contracts/ft/FT7_1b2b1_Protocol_v1.json';p=json.loads(pp.read_text())
    if digest(pp)!=pp.with_suffix('.sha256').read_text().split()[0]:raise ValueError('protocol digest differs')
    ap=ROOT/'contracts/ft/FT7_1b2b1_Preflight_Amendment_v1.json';amendment=json.loads(ap.read_text())
    if digest(ap)!=ap.with_suffix('.sha256').read_text().split()[0] or digest(ROOT/'tests_ft7/training_fixtures.py')!=amendment['fixture_sha256']:raise ValueError('amendment/fixture digest differs')
    suite=unittest.defaultTestLoader.loadTestsFromName('tests_ft7.test_social_training');actual=sorted(ids(suite));expected=sorted('tests_ft7.test_social_training.SocialTrainingTests.'+m for m in p['registered_tests'])
    (out/'method_ids.json').write_text(json.dumps(actual,indent=2)+'\n')
    with (out/'controls.log').open('w') as log:r=unittest.TextTestRunner(stream=log,verbosity=2).run(suite)
    from tests_ft7.test_social_training import SocialTrainingTests as tests
    rows=[]
    for key,(e,c) in sorted(getattr(tests,'witnesses',{}).items()):rows.append((key,tuple(e.world.journal()),c.checkpoint(e),e.checkpoint()))
    for key,(e,c,other,restored,partial_native,partial_wrapper) in sorted(getattr(tests,'restarts',{}).items()):
        typ=type(e);partial=typ.restore(partial_native)
        rows.extend(((key+'/restart-final',tuple(e.world.journal()),c.checkpoint(e),e.checkpoint()),(key+'/restart-partial',tuple(partial.world.journal()),partial_wrapper,partial_native)))
    raw=tuple(rows);rawpath=out/'raw_training_evidence.json';rawpath.write_text(codec.dumps(raw)+'\n');decoded=codec.loads(rawpath.read_text());audits={}
    for key,txs,wrapper,native in decoded:
        try:
            typ=SelectionEngine if key.startswith('canonical/') else WorkflowFinalSelectionEngine;e=typ.restore(native)
            if tuple(e.world.journal())!=txs:raise ValueError('saved native/raw journal differs')
            d=loads(wrapper);prefix=typ.restore(d['prefix_native']);prefix_audit=audit_peer_cycle(prefix,d['prefix_peer'])
            audits[key]=dict(training=audit_social_training(e,wrapper),prefix=prefix_audit,passed=True)
        except Exception as exc:audits[key]=dict(passed=False,error=type(exc).__name__+': '+str(exc))
    (out/'decoded_audits.json').write_text(json.dumps(audits,indent=2)+'\n')
    expected_keys={s+'/'+m for s in p['panel']['settings'] for m in p['panel']['scenarios']}|{s+'/'+m+'/restart-'+part for s in p['panel']['settings'] for m in p['panel']['restarts'] for part in ('final','partial')}
    passed=r.wasSuccessful() and actual==expected and before==freeze() and raw==decoded and set(audits)==expected_keys and all(a['passed'] for a in audits.values())
    summary=dict(passed=passed,methods=r.testsRun,failures=len(r.failures),errors=len(r.errors),exact_methods=actual==expected,predecessor_identities=312,saved_records=len(rows),exact_record_domain=set(audits)==expected_keys,raw_roundtrip_exact=raw==decoded,decoded_independent_audits=all(a['passed'] for a in audits.values()),source_unchanged=before==freeze(),registered_freeze=before==registered,protocol_sha256=digest(pp),configuration=p['configuration'],claim='native owned guarded training only; no FT closure/certificate/reuse or feedback acceptance',parent_gate='FT7.1b2b2 closure/reuse and FT7.1b2b3 feedback remain mandatory')
    (out/'summary.json').write_text(json.dumps(summary,indent=2)+'\n');(out/'evidence_hashes.json').write_text(json.dumps({f.name:digest(f) for f in sorted(out.iterdir()) if f.is_file()},indent=2)+'\n');print(json.dumps(summary,indent=2),flush=True)
    if not passed:raise SystemExit(1)

if __name__=='__main__':main(Path(sys.argv[1]).resolve())
