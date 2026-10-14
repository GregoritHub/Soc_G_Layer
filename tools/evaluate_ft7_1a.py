"""Frozen FT7.1a paid transport acceptance and raw witness serialization."""
import hashlib
import json
from pathlib import Path
import sys
import unittest

ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT),str(ROOT/"baseline/HLE_Rebuild_R21B")]


def digest(path):return hashlib.sha256(path.read_bytes()).hexdigest()


def freeze():
    accepted=json.loads((ROOT/"contracts/ft/FT6_3b_Source_Freeze_v1.json").read_text())
    names=list(accepted)+["contracts/ft/FT6_3b_Source_Freeze_v1.json",
        "contracts/ft/FT_Selected_Engineering_Policies_v1.json",
        "contracts/ft/FT7_1a_Protocol_v1.json","contracts/ft/FT7_1a_Protocol_v1.sha256",
        "full_theory/packet_channel.py","full_theory/packet_channel_audit.py",
        "tests_ft7/test_packet_channel.py","tools/evaluate_ft7_1a.py"]
    return {name:digest(ROOT/name) for name in sorted(names)}


def main(out):
    from hle_unified import codec
    from full_theory.packet_channel_audit import audit_packet_channel
    from tools.evaluate_ft6_3b import ids
    out.mkdir(parents=True,exist_ok=False)
    before=freeze()
    (out/"source_freeze.json").write_text(json.dumps(before,indent=2)+'\n')
    registered=json.loads((ROOT/"contracts/ft/FT7_1a_Source_Freeze_v1.json").read_text())
    if before!=registered:raise ValueError("registered FT7.1a freeze differs")
    p=ROOT/"contracts/ft/FT7_1a_Protocol_v1.json";protocol=json.loads(p.read_text())
    if digest(p)!=p.with_suffix('.sha256').read_text().split()[0]:raise ValueError("protocol hash differs")
    suite=unittest.defaultTestLoader.loadTestsFromName("tests_ft7.test_packet_channel")
    actual=sorted(ids(suite));expected=sorted("tests_ft7.test_packet_channel.PacketChannelTests."+m for m in protocol["registered_tests"])
    (out/"method_ids.json").write_text(json.dumps(actual,indent=2)+'\n')
    with (out/"controls.log").open('w') as log:result=unittest.TextTestRunner(stream=log,verbosity=2).run(suite)
    from tests_ft7.test_packet_channel import PacketChannelTests as tests
    records=[];audits={}
    for key,(engine,channel,_,_) in tests.witnesses.items():
        records.append((key,tuple(engine.world.journal()),channel.checkpoint(),engine.checkpoint()))
    for key,(engine,channel,other,restored) in tests.restarts.items():
        records.append((key+'/partial-restart',tuple(engine.world.journal()),channel.checkpoint(),engine.checkpoint()))
    if hasattr(tests,'permutation'):
        engine,channel=tests.permutation
        records.append(('canonical/queue-permutation',tuple(engine.world.journal()),channel.checkpoint(),engine.checkpoint()))
    raw=tuple(records)
    raw_path=out/"raw_paid_transport.json";raw_path.write_text(codec.dumps(raw)+'\n')
    decoded=codec.loads(raw_path.read_text());roundtrip=decoded==raw
    for key,transactions,checkpoint,native in decoded:
        audits[key]=audit_packet_channel(transactions,checkpoint,native)
    (out/"audits.json").write_text(json.dumps(audits,indent=2)+'\n')
    expected_keys=set(protocol["fixed_panel"]["primary_ids"]+protocol["fixed_panel"]["controls"]+
                      ['canonical/partial-restart','workflow/partial-restart','canonical/queue-permutation'])
    passed=(result.wasSuccessful() and actual==expected and len(actual)==14 and before==freeze()
            and roundtrip and set(audits)==expected_keys and all(a['passed'] for a in audits.values()))
    summary=dict(passed=passed,methods=result.testsRun,failures=len(result.failures),errors=len(result.errors),
        exact_methods=actual==expected,predecessor_methods=267,primary_witnesses=4,controls=4,
        partial_restarts=2,queue_permutations=1,saved_records=len(audits),decoded_independent_audit=all(a['passed'] for a in audits.values()),
        raw_roundtrip_exact=roundtrip,source_unchanged=before==freeze(),registered_freeze=before==registered,
        protocol_sha256=digest(p),selected_conditioning_policy='success-v1',parent_ft7_1='pending FT7.1b',
        scope='Paid transport only; no autonomous social coupling or subtype assignment')
    (out/"summary.json").write_text(json.dumps(summary,indent=2)+'\n')
    (out/"evidence_hashes.json").write_text(json.dumps({p.name:digest(p) for p in sorted(out.iterdir()) if p.is_file()},indent=2)+'\n')
    print(json.dumps(summary,indent=2),flush=True)
    if not passed:raise SystemExit(1)


if __name__=='__main__':
    if len(sys.argv)!=2:raise SystemExit('usage: evaluate_ft7_1a.py OUTPUT_DIRECTORY')
    main(Path(sys.argv[1]).resolve())
