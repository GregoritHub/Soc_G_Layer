"""Frozen FT6.3a matched paid-grid acceptance gate."""
from pathlib import Path
import hashlib
import json
import sys
import unittest


ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT), str(ROOT / "baseline/HLE_Rebuild_R21B")]


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def freeze():
    result = {}
    for area in ("full_theory", "tests_ft4", "tests_ft5", "tests_ft6", "contracts/ft"):
        for path in sorted((ROOT / area).rglob("*")):
            if path.is_file() and path.suffix in (".py", ".json", ".sha256"):
                relative = str(path.relative_to(ROOT))
                if relative != "contracts/ft/FT6_3a_Source_Freeze_v1.json":
                    result[relative] = digest(path)
    for relative in ("hle_unified/conditioning_audit.py", "hle_unified/axes.py",
                     "hle_unified/codec.py", "hle_unified/model_g.py",
                     "hle_unified/selection_records.py",
                     "baseline/HLE_Rebuild_R21B/hle/development_structure.py"):
        result[relative] = digest(ROOT / relative)
    result["tools/evaluate_ft6_3a.py"] = digest(Path(__file__))
    return result


def ids(suite):
    for item in suite:
        if isinstance(item, unittest.TestSuite):
            yield from ids(item)
        else:
            yield item.id()


def predecessor_expected():
    from tools.evaluate_ft6_2 import predecessor_expected as earlier
    protocol = json.loads((ROOT / "contracts/ft/FT6_2_Protocol_v1.json").read_text())
    return sorted(earlier() + [
        "tests_ft6.test_conditioning_feedback.ConditioningFeedbackTests." + method
        for method in protocol["registered_tests"]])


def main(out):
    from hle_unified import codec
    from hle_unified.selection_records import dumps, loads
    out.mkdir(parents=True, exist_ok=False)
    before = freeze()
    (out / "source_freeze.json").write_text(json.dumps(before, indent=2) + "\n")
    registered = json.loads((ROOT / "contracts/ft/FT6_3a_Source_Freeze_v1.json").read_text())
    protocol_path = ROOT / "contracts/ft/FT6_3a_Protocol_v1.json"
    fixture_path = ROOT / "contracts/ft/FT6_3a_Fixtures_v1.json"
    protocol = json.loads(protocol_path.read_text())
    suite = unittest.defaultTestLoader.loadTestsFromName("tests_ft6.test_conditioning_grid")
    actual = sorted(ids(suite))
    expected = sorted("tests_ft6.test_conditioning_grid.ConditioningGridTests." + method
                      for method in protocol["registered_tests"])
    (out / "method_ids.json").write_text(json.dumps(actual, indent=2) + "\n")
    with (out / "controls.log").open("w") as log:
        result = unittest.TextTestRunner(stream=log, verbosity=2).run(suite)
    from tests_ft6.test_conditioning_grid import ConditioningGridTests
    report = ConditioningGridTests.report
    evidence = ConditioningGridTests.evidence
    (out / "grid_report.json").write_text(dumps(report) + "\n")
    # The U2 codec accepts typed transactions and tuples, not string-keyed
    # maps. Episodes use their existing C6 audit codec inside the tuple.
    records = tuple((run_id, transactions, route_checkpoint, dumps(episode))
                    for run_id, (transactions, route_checkpoint, episode)
                    in sorted(evidence.items()))
    raw_path = out / "raw_paid_evidence.json"
    raw_path.write_text(codec.dumps(records) + "\n")
    decoded = codec.loads(raw_path.read_text())
    restored = {run_id: (transactions, route_checkpoint, loads(episode))
                for run_id, transactions, route_checkpoint, episode in decoded}
    roundtrip = (decoded == records and restored == evidence
                 and len(restored) == len(decoded) == 228)
    from full_theory.conditioning_grid_audit import audit_conditioning_grid
    decoded_audit = audit_conditioning_grid(report, ConditioningGridTests.fixture,
        ConditioningGridTests.histories, ConditioningGridTests.removed, restored)
    after = freeze()
    protocol_hash = digest(protocol_path)
    fixture_hash = digest(fixture_path)
    hashes_registered = (
        protocol_hash == (ROOT / "contracts/ft/FT6_3a_Protocol_v1.sha256").read_text().split()[0]
        and fixture_hash == (ROOT / "contracts/ft/FT6_3a_Fixtures_v1.sha256").read_text().split()[0])
    passed = (result.wasSuccessful() and actual == expected and len(actual) == 14
              and before == after == registered and hashes_registered
              and report["primary_count"] == 180 and report["control_count"] == 48
              and ConditioningGridTests.audit["passed"]
              and roundtrip and decoded_audit["passed"])
    summary = dict(passed=passed, methods=result.testsRun, failures=len(result.failures),
        errors=len(result.errors), exact_methods=actual == expected,
        expected_methods=len(expected), predecessor_methods=len(predecessor_expected()),
        primary_paid_executions=report["primary_count"],
        causal_control_executions=report["control_count"],
        independently_reconstructed=ConditioningGridTests.audit["passed"],
        discriminating_controls=ConditioningGridTests.audit["discriminating"],
        grid_sha256=report["grid_sha256"], source_unchanged=before == after,
        registered_freeze=before == registered, protocol_sha256=protocol_hash,
        fixture_sha256=fixture_hash, hashes_registered=hashes_registered,
        evidence_format="ordered run_id/transactions/route_checkpoint/C6-encoded-episode tuples in U2 codec",
        evidence_roundtrip_exact=roundtrip,
        decoded_evidence_independently_reconstructed=decoded_audit["passed"],
        preserved_failures=("FT6_3a_Held_Evidence_20261013.zip",),
        scope="FT6.3a engineering grid only; FT6.3 parent release and subtype interpretation remain open")
    (out / "summary.json").write_text(json.dumps(summary, indent=2) + "\n")
    (out / "evidence_hashes.json").write_text(json.dumps({
        path.name: digest(path) for path in sorted(out.iterdir()) if path.is_file()
    }, indent=2) + "\n")
    if not passed:
        raise SystemExit(1)


if __name__ == "__main__":
    if len(sys.argv) != 2:
        raise SystemExit("usage: evaluate_ft6_3a.py OUTPUT_DIRECTORY")
    main(Path(sys.argv[1]))
