"""Frozen single FT7.1b2a panel, exact readback and independent audits."""
from pathlib import Path
import hashlib,json,sys,unittest
ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT),str(ROOT/'baseline/HLE_Rebuild_R21B')]

def digest(p):return hashlib.sha256(p.read_bytes()).hexdigest()

def freeze():
    previous=json.loads((ROOT/'contracts/ft/FT7_1b1_Comparison_Source_Freeze_v1.json').read_text())
    names=set(previous)|{'contracts/ft/FT7_1b1_Comparison_Source_Freeze_v1.json','contracts/ft/FT7_1b2a_Protocol_v1.json','contracts/ft/FT7_1b2a_Protocol_v1.sha256','full_theory/peer_cycle.py','full_theory/peer_cycle_audit.py','tests_ft7/peer_fixtures.py','tests_ft7/test_peer_cycle.py','tools/evaluate_ft7_1b2a.py','hle_unified/workflow_selection_execution.py','hle_unified/crossing_records.py','hle_unified/workflow_records.py'}
    return {n:digest(ROOT/n) for n in sorted(names)}

def main(out):
    from hle_unified import codec
    from hle_unified.selection_execution import SelectionEngine
    from hle_unified.workflow_selection_execution import WorkflowFinalSelectionEngine
    from full_theory.peer_cycle_audit import audit_peer_cycle
    from tools.evaluate_ft6_3b import ids
    out.mkdir(parents=True,exist_ok=False);before=freeze();(out/'source_freeze.json').write_text(json.dumps(before,indent=2)+'\n')
    registered=json.loads((ROOT/'contracts/ft/FT7_1b2a_Source_Freeze_v1.json').read_text())
    if before!=registered:raise ValueError('registered source freeze differs')
    for n,h in json.loads((ROOT/'contracts/ft/FT7_1b1_Comparison_Source_Freeze_v1.json').read_text()).items():
        if digest(ROOT/n)!=h:raise ValueError('accepted predecessor changed: '+n)
    path=ROOT/'contracts/ft/FT7_1b2a_Protocol_v1.json';p=json.loads(path.read_text())
    if digest(path)!=path.with_suffix('.sha256').read_text().split()[0] or digest(ROOT/'tests_ft7/peer_fixtures.py')!=p['fixture_sha256']:raise ValueError('protocol/fixture differs')
    suite=unittest.defaultTestLoader.loadTestsFromName('tests_ft7.test_peer_cycle');actual=sorted(ids(suite));expected=sorted('tests_ft7.test_peer_cycle.PeerCycleTests.'+m for m in p['registered_tests'])
    (out/'method_ids.json').write_text(json.dumps(actual,indent=2)+'\n')
    with (out/'controls.log').open('w') as log:r=unittest.TextTestRunner(stream=log,verbosity=2).run(suite)
    from tests_ft7.test_peer_cycle import PeerCycleTests as tests
    rows=[];reports={}
    for key,(e,c,d,wallets) in sorted(getattr(tests,'witnesses',{}).items()):
        rows.append((key,tuple(e.world.journal()),c.checkpoint(e),e.checkpoint()))
        peer=None if c.request is None else e.job_status(c.peer,c.request.key)
        link=None if c.social is None or c.social.terminal is None else c.social.terminal['causal_link']
        consumer=None if link is None else e.job_status(c.actor,link['consumer_key'])
        reports[key]=dict(phase=c.phase,turns=c.turn,peer_key=None if c.request is None else c.request.key,peer_paid=None if peer is None else peer['spent'],peer_required=None if peer is None else peer['required'],reply=c.reply,consumer_key=None if link is None else link['consumer_key'],consumer_paid=None if consumer is None else consumer['spent'],consumer_required=None if consumer is None else consumer['required'],before_wallets=wallets,after_wallets={a:dict(e.wallet(a)) for a in c.channel.participants})
    for key,(e,c,other,restored,partial_native,partial_wrapper) in sorted(getattr(tests,'restarts',{}).items()):
        rows.append((key+'/restart-final',tuple(e.world.journal()),c.checkpoint(e),e.checkpoint()))
        typ=SelectionEngine if key.startswith('canonical/') else WorkflowFinalSelectionEngine
        partial=typ.restore(partial_native)
        rows.append((key+'/restart-partial',tuple(partial.world.journal()),partial_wrapper,partial_native))
        reports[key+'/restart']=dict(native_exact=e.checkpoint()==other.checkpoint(),wrapper_exact=c.checkpoint(e)==restored.checkpoint(other))
    (out/'scenario_reports.json').write_text(codec.dumps(reports)+'\n')
    raw=tuple(rows);path_raw=out/'raw_peer_evidence.json';path_raw.write_text(codec.dumps(raw)+'\n');decoded=codec.loads(path_raw.read_text());audits={}
    for key,txs,wrapper,native in decoded:
        try:
            typ=SelectionEngine if key.startswith('canonical/') else WorkflowFinalSelectionEngine;e=typ.restore(native)
            if tuple(e.world.journal())!=txs:raise ValueError('native/raw journal differs')
            audits[key]=audit_peer_cycle(e,wrapper)
        except Exception as exc:audits[key]=dict(passed=False,error=type(exc).__name__+': '+str(exc))
    (out/'decoded_audits.json').write_text(json.dumps(audits,indent=2)+'\n')
    expected_keys={s+'/'+m for s in p['fixed_panel']['settings'] for m in p['fixed_panel']['scenarios']}|{s+'/'+m+'/restart-'+part for s in p['fixed_panel']['settings'] for m in p['fixed_panel']['restarts'] for part in ('final','partial')}
    passed=r.wasSuccessful() and actual==expected and before==freeze() and raw==decoded and set(audits)==expected_keys and all(a['passed'] for a in audits.values())
    summary=dict(passed=passed,methods=r.testsRun,failures=len(r.failures),errors=len(r.errors),exact_methods=actual==expected,predecessor_identities=297,scenarios=len(getattr(tests,'witnesses',{})),restart_pairs=len(getattr(tests,'restarts',{})),saved_records=len(rows),raw_roundtrip_exact=raw==decoded,decoded_independent_audits=all(a['passed'] for a in audits.values()),source_unchanged=before==freeze(),registered_freeze=before==registered,protocol_sha256=digest(path),configuration=p['configuration'],parent_gate='FT7.1b2b independent training/closure, changed-support retained reuse and later tie-only feedback remain pending',claim='Autonomous paid peer reply and recipient support causality, no independent capability or psychology claim')
    (out/'summary.json').write_text(json.dumps(summary,indent=2)+'\n');(out/'evidence_hashes.json').write_text(json.dumps({f.name:digest(f) for f in sorted(out.iterdir()) if f.is_file()},indent=2)+'\n')
    print(json.dumps(summary,indent=2),flush=True)
    if not passed:raise SystemExit(1)

if __name__=='__main__':
    if len(sys.argv)!=2:raise SystemExit('usage: evaluate_ft7_1b2a.py OUTPUT_DIRECTORY')
    main(Path(sys.argv[1]).resolve())
