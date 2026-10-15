"""Prospectively frozen existing-policy comparison; original control stays intact."""
import hashlib
import json
from pathlib import Path
import sys
import unittest
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT), str(ROOT / 'baseline/HLE_Rebuild_R21B')]


def digest(p):
    return hashlib.sha256(p.read_bytes()).hexdigest()


def freeze():
    names = set(json.loads((ROOT/'contracts/ft/FT7_1b1_Source_Freeze_v1.json').read_text()))
    names.update(('contracts/ft/FT7_1b1_Source_Freeze_v1.json',
        'contracts/ft/FT7_1b1_Comparison_Protocol_v1.json',
        'contracts/ft/FT7_1b1_Comparison_Protocol_v1.sha256',
        'tools/compare_ft7_1b1.py', 'hle_unified/workflow_selection_execution.py',
        'hle_unified/workflow_selection_policy.py','hle_unified/workflow_selection_audit.py',
        'hle_unified/workflow_content.py'))
    return {n:digest(ROOT/n) for n in sorted(names)}


def main(out, held):
    from hle_unified import codec
    from hle_unified.selection_execution import SelectionEngine
    from hle_unified.workflow_selection_execution import WorkflowSelectionEngine, WorkflowFinalSelectionEngine
    from hle_unified.selection_records import dumps, loads
    from full_theory.social_cycle_audit import audit_social_cycle
    from tools.evaluate_ft6_3b import ids
    from tests_ft7 import test_social_cycle as testmod
    from tests_c3.fixtures import ALICE

    out.mkdir(parents=True, exist_ok=False)
    before=freeze()
    original=json.loads((ROOT/'contracts/ft/FT7_1b1_Source_Freeze_v1.json').read_text())
    assert all(before[n]==h for n,h in original.items()), 'original frozen source differs'
    registered=json.loads((ROOT/'contracts/ft/FT7_1b1_Comparison_Source_Freeze_v1.json').read_text())
    assert before==registered, 'comparison freeze differs'
    protocol_path=ROOT/'contracts/ft/FT7_1b1_Comparison_Protocol_v1.json'
    assert digest(protocol_path)==protocol_path.with_suffix('.sha256').read_text().split()[0]
    protocol=json.loads(protocol_path.read_text())
    assert digest(held)=='443c94c6ec5320918bcf5fa861d4f540f3f079adecda94715b8f67ca86ce920b', 'held raw source differs'
    held_records=codec.loads(held.read_text())
    (out/'source_freeze.json').write_text(json.dumps(before,indent=2)+'\n')
    records=[];reports={};arm_results={};bases={};restarts={};errors={}
    for arm,typ in (('self-only',WorkflowSelectionEngine),('all-cell',WorkflowFinalSelectionEngine)):
        print('Running '+arm,flush=True)
        # Only the fixture constructor binding varies; inherited source and original tests are unchanged.
        with patch.object(testmod,'WorkflowSelectionEngine',typ):
            suite=unittest.defaultTestLoader.loadTestsFromTestCase(testmod.SocialCycleTests)
            method_ids=sorted(ids(suite))
            with (out/(arm+'-controls.log')).open('w') as log:
                result=unittest.TextTestRunner(stream=log,verbosity=2).run(suite)
            cls=testmod.SocialCycleTests
            arm_results[arm]=dict(methods=result.testsRun,failures=len(result.failures),errors=len(result.errors),
                method_ids=method_ids,failed_ids=sorted(t.id() for t,_ in result.failures),
                error_ids=sorted(t.id() for t,_ in result.errors),passed=result.wasSuccessful())
            bases[arm]={}
            for key,(engine_type,native,reply,demand) in cls.bases.items():
                restored=engine_type.restore(native)
                bases[arm][key]=(tuple(restored.world.journal()),reply,demand.record())
            for key,(engine,c,d,bwallet,audit) in sorted(cls.witnesses.items()):
                records.append((arm+'/'+key,tuple(engine.world.journal()),c.checkpoint(engine),engine.checkpoint()))
                request=c.cycle.request
                def job(suffix):
                    if request is None:return None
                    try:return engine.job_status(ALICE,request.key+suffix)
                    except (KeyError,ValueError):return None
                selection=job('');movement=job(':movement');consumer=job(':autonomous-consumer')
                reports[arm+'/'+key]=dict(phase=c.phase,audit=audit,
                    selection={k:selection.get(k) for k in ('policy','candidate_count','required','spent','status')} if selection else None,
                    movement={k:movement.get(k) for k in ('recipe','required','spent','status','failure')} if movement else None,
                    consumer={k:consumer.get(k) for k in ('recipe','required','spent','status','failure')} if consumer else None,
                    before_wallet=bwallet,after_wallet=dict(engine.wallet(ALICE)),reserve=c.cycle.candidates.binding.ledger.balance,
                    independent_history_credit=sum(c.history.scores.values()),
                    causal_link=c.terminal['causal_link'] if c.terminal else None)
            for setting,(engine,c,other,restored) in sorted(cls.restarts.items()):
                records.append((arm+'/'+setting+'/partial-restart',tuple(engine.world.journal()),c.checkpoint(engine),engine.checkpoint()))
                restarts[arm+'/'+setting]=dict(native_exact=engine.checkpoint()==other.checkpoint(),
                    wrapper_exact=c.checkpoint(engine)==restored.checkpoint(other),phase=c.phase)
        (out/(arm+'-result.json')).write_text(json.dumps(arm_results[arm],indent=2)+'\n')
        print(arm+' tests: '+str({k:v for k,v in arm_results[arm].items() if k not in ('method_ids','failed_ids','error_ids')}),flush=True)
    raw=tuple(records);path=out/'raw_policy_comparison.json';path.write_text(codec.dumps(raw)+'\n')
    decoded=codec.loads(path.read_text());audits={}
    for key,journal,checkpoint,native in decoded:
        arm,setting,_=key.split('/',2)
        typ=SelectionEngine if setting=='canonical' else WorkflowSelectionEngine if arm=='self-only' else WorkflowFinalSelectionEngine
        try:
            engine=typ.restore(native)
            if tuple(engine.world.journal())!=journal:raise ValueError('native journal mismatch')
            audits[key]=audit_social_cycle(engine,checkpoint)
        except Exception as exc:
            audits[key]=dict(passed=False,error=type(exc).__name__+': '+str(exc))
    indexed={r[0]:r[1:] for r in raw}
    old={r[0]:r[1:] for r in held_records}
    expected=sorted('tests_ft7.test_social_cycle.SocialCycleTests.'+m for m in protocol['registered_methods'])
    old_protocol=json.loads((ROOT/'contracts/ft/FT7_1b1_Protocol_v1.json').read_text())
    scenario_ids=old_protocol['fixed_panel']['scenario_ids']+['canonical/partial-restart','workflow/partial-restart']
    failure_ids=['test_paid_peer_packet_enables_owned_support_choice_in_both_settings',
        'test_partial_restart_is_exact_in_both_settings','test_success_v1_supported_history_grants_zero_independent_credit',
        'test_supported_settlement_debits_load_v1_once']
    error_ids=['test_exact_reply_is_actual_selected_native_operand','test_forged_support_receipt_operand_or_history_is_rejected',
        'test_paid_consumer_uses_selected_movement_output_and_same_scope']
    prefix='tests_ft7.test_social_cycle.SocialCycleTests.'
    control=arm_results['self-only']
    checks=dict(original_source_unchanged=before==freeze(),
        exact_method_identities_both_arms=all(a['method_ids']==expected and a['methods']==16 for a in arm_results.values()),
        same_precycle_native_journals=bases['self-only']==bases['all-cell'],
        canonical_records_identical=all(indexed['self-only/'+k]==indexed['all-cell/'+k] for k in scenario_ids if k.startswith('canonical/')),
        self_only_records_equal_held_attempt=all(indexed['self-only/'+k]==old[k] for k in scenario_ids),
        self_only_failure_signature_preserved=control['failures']==4 and control['errors']==3 and
            control['failed_ids']==sorted(prefix+m for m in failure_ids) and control['error_ids']==sorted(prefix+m for m in error_ids),
        exact_24_record_domain=len(raw)==24 and set(indexed)=={a+'/'+k for a in arm_results for k in scenario_ids},
        exact_saved_roundtrip=raw==decoded,
        all_decoded_independent_audits_pass=all(a['passed'] for a in audits.values()),
        exact_partial_restart_each_arm=len(restarts)==4 and all(a['native_exact'] and a['wrapper_exact'] for a in restarts.values()))
    assert set(checks)==set(protocol['registered_comparison_checks'])
    valid=all(checks.values())
    summary=dict(batch='FT7.1b1',comparison_valid=valid,ft7_1b1_accepted=valid and arm_results['all-cell']['passed'],
        checks=checks,arms=arm_results,records=len(records),predecessor_identities=281,
        source_unchanged=before==freeze(),protocol_sha256=digest(protocol_path),
        scope='Existing v4 policy versus unchanged v1; no independent social capability, subtype or parent FT7 release claim.')
    (out/'summary.json').write_text(json.dumps(summary,indent=2)+'\n')
    (out/'scenario_reports.json').write_text(dumps(reports)+'\n')
    (out/'restart_reports.json').write_text(json.dumps(restarts,indent=2)+'\n')
    (out/'decoded_audits.json').write_text(json.dumps(audits,indent=2)+'\n')
    (out/'evidence_hashes.json').write_text(json.dumps({p.name:digest(p) for p in sorted(out.iterdir()) if p.is_file()},indent=2)+'\n')
    print(json.dumps({k:v for k,v in summary.items() if k!='arms'},indent=2),flush=True)
    if not valid:raise SystemExit(1)


if __name__=='__main__':
    if len(sys.argv)!=3:raise SystemExit('usage: compare_ft7_1b1.py OUTPUT_DIRECTORY CORRECTED_HELD_RAW_EVIDENCE')
    main(Path(sys.argv[1]).resolve(),Path(sys.argv[2]).resolve())
