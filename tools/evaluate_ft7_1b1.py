"""Frozen FT7.1b1 support-seam acceptance and exact saved native audit."""
import hashlib
import json
from pathlib import Path
import sys
import unittest

ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT),str(ROOT/"baseline/HLE_Rebuild_R21B")]


def digest(path):return hashlib.sha256(path.read_bytes()).hexdigest()


def freeze():
    accepted=json.loads((ROOT/"contracts/ft/FT7_1a_Source_Freeze_v1.json").read_text())
    names=set(accepted)|{"contracts/ft/FT7_1a_Source_Freeze_v1.json",
        "contracts/ft/FT7_1b1_Protocol_v1.json","contracts/ft/FT7_1b1_Protocol_v1.sha256",
        "contracts/ft/FT7_1b1_Public_Intake_Amendment_v1.json",
        "contracts/ft/FT7_1b1_Public_Intake_Amendment_v1.sha256",
        "full_theory/social_cycle.py","full_theory/social_cycle_audit.py",
        "tests_ft7/test_social_cycle.py","tools/evaluate_ft7_1b1.py",
        "tests_c3/fixtures.py","tests_c5/fixtures.py","tests_c6/fixtures.py",
        "tests_c7_workflow/fixtures.py","tests_ft4/test_demands.py",
        "hle_unified/selection_execution.py","hle_unified/workflow_selection_execution.py",
        "hle_unified/self_content.py"}
    return {n:digest(ROOT/n) for n in sorted(names)}


def main(out):
    from hle_unified import codec
    from hle_unified.selection_records import dumps
    from hle_unified.selection_execution import SelectionEngine
    from hle_unified.workflow_selection_execution import WorkflowSelectionEngine
    from full_theory.social_cycle_audit import audit_social_cycle
    from tools.evaluate_ft6_3b import ids
    out.mkdir(parents=True,exist_ok=False)
    before=freeze()
    (out/"source_freeze.json").write_text(json.dumps(before,indent=2)+'\n')
    registered=json.loads((ROOT/"contracts/ft/FT7_1b1_Source_Freeze_v1.json").read_text())
    if before!=registered:raise ValueError("FT7.1b1 freeze differs")
    previous=json.loads((ROOT/"contracts/ft/FT7_1a_Source_Freeze_v1.json").read_text())
    for name,expected_hash in previous.items():
        if digest(ROOT/name)!=expected_hash:raise ValueError("accepted predecessor source differs: "+name)
    p=ROOT/"contracts/ft/FT7_1b1_Protocol_v1.json";protocol=json.loads(p.read_text())
    if digest(p)!=p.with_suffix('.sha256').read_text().split()[0]:raise ValueError("prospective protocol hash differs")
    amendment=ROOT/"contracts/ft/FT7_1b1_Public_Intake_Amendment_v1.json"
    if digest(amendment)!=amendment.with_suffix('.sha256').read_text().split()[0]:raise ValueError("public intake amendment hash differs")
    suite=unittest.defaultTestLoader.loadTestsFromName("tests_ft7.test_social_cycle")
    actual=sorted(ids(suite));expected=sorted("tests_ft7.test_social_cycle.SocialCycleTests."+m for m in protocol["registered_tests"])
    (out/"method_ids.json").write_text(json.dumps(actual,indent=2)+'\n')
    with (out/"controls.log").open('w') as log:result=unittest.TextTestRunner(stream=log,verbosity=2).run(suite)
    from tests_ft7.test_social_cycle import SocialCycleTests as tests
    records=[];reports={}
    for key,(engine,controller,demand,before_wallet,audit) in sorted(getattr(tests,'witnesses',{}).items()):
        records.append((key,tuple(engine.world.journal()),controller.checkpoint(engine),engine.checkpoint()))
        reports[key]=dict(audit=audit,before_wallet=before_wallet,after_wallet=dict(engine.wallet(controller.actor)),
            terminal_phase=controller.phase,recipe=None if controller.cycle.request is None or not controller.cycle.candidates.route_policy.attempts else
            controller.cycle.candidates.route_policy.attempts[0].get('traversal'),
            peer_main_cost=engine.job_status(__import__('tests_c3.fixtures',fromlist=['BOB']).BOB,'social-reply')['spent'])
    for setting,(engine,controller,other,restored) in sorted(getattr(tests,'restarts',{}).items()):
        key=setting+'/partial-restart'
        records.append((key,tuple(engine.world.journal()),controller.checkpoint(engine),engine.checkpoint()))
        reports[key]=dict(native_exact=engine.checkpoint()==other.checkpoint(),
                          wrapper_exact=controller.checkpoint(engine)==restored.checkpoint(other))
    (out/"scenario_reports.json").write_text(dumps(reports)+'\n')
    raw=tuple(records);path=out/"raw_paid_social_evidence.json";path.write_text(codec.dumps(raw)+'\n')
    decoded=codec.loads(path.read_text());roundtrip=raw==decoded;audits={}
    for key,transactions,checkpoint,native in decoded:
        engine_type=WorkflowSelectionEngine if key.startswith('workflow/') else SelectionEngine
        try:
            engine=engine_type.restore(native)
            if tuple(engine.world.journal())!=transactions:raise ValueError("saved native journal differs: "+key)
            audits[key]=audit_social_cycle(engine,checkpoint)
        except Exception as exc:
            audits[key]=dict(passed=False,error=type(exc).__name__+': '+str(exc))
    (out/"decoded_audits.json").write_text(json.dumps(audits,indent=2)+'\n')
    expected_keys=set(protocol["fixed_panel"]["scenario_ids"]+['canonical/partial-restart','workflow/partial-restart'])
    passed=(result.wasSuccessful() and actual==expected and len(actual)==16 and before==freeze()
            and roundtrip and set(audits)==expected_keys and all(a['passed'] for a in audits.values()))
    summary=dict(passed=passed,methods=result.testsRun,failures=len(result.failures),errors=len(result.errors),
        exact_methods=actual==expected,predecessor_methods=281,scenarios=len(getattr(tests,'witnesses',{})),
        restart_records=len(getattr(tests,'restarts',{})),saved_records=len(audits),decoded_independent_audit=all(a['passed'] for a in audits.values()),
        raw_roundtrip_exact=roundtrip,source_unchanged=before==freeze(),registered_freeze=before==registered,
        protocol_sha256=digest(p),reserve_policy='load-v1',conditioning_policy='success-v1',
        public_intake_amendment_sha256=digest(amendment),
        parent_ft7_1b='pending FT7.1b2 autonomous peer production and scoped independent reuse',
        scope='Packet-mediated owned support choice and paid later use only; no independent capability or subtype assignment')
    (out/"summary.json").write_text(json.dumps(summary,indent=2)+'\n')
    (out/"evidence_hashes.json").write_text(json.dumps({p.name:digest(p) for p in sorted(out.iterdir()) if p.is_file()},indent=2)+'\n')
    print(json.dumps(summary,indent=2),flush=True)
    if not passed:raise SystemExit(1)


if __name__=='__main__':
    if len(sys.argv)!=2:raise SystemExit('usage: evaluate_ft7_1b1.py OUTPUT_DIRECTORY')
    main(Path(sys.argv[1]).resolve())
