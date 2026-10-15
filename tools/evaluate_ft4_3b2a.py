"""Frozen FT4.3b2a autonomous capability-certification gate."""
from pathlib import Path
import hashlib
import json
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT), str(ROOT / "baseline/HLE_Rebuild_R21B")]
from tools.evaluate_ft4_1 import manifest, ids


ROWS = [
    ("FT4_1a", "test_demands", "DemandTests"),
    ("FT4_1b1", "test_requests", "RequestTests"),
    ("FT4_1b2", "test_controller", "ControllerTests"),
    ("FT4_2a", "test_route_means", "RouteMeansTests"),
    ("FT4_2b1", "test_route_execution", "NativeTurnTests"),
    ("FT4_2b2a", "test_orientation", "OrientationTests"),
    ("FT4_2b2b1", "test_route_policy", "RoutePolicyTests"),
    ("FT4_2b2b2", "test_opposition", "OppositionTests"),
    ("FT4_3a", "test_autonomous_cycle", "AutonomousCycleTests"),
    ("FT4_3b1", "test_autonomous_closure", "AutonomousClosureTests"),
    ("FT4_3b2a", "test_autonomous_capability", "AutonomousCapabilityTests"),
]


def freeze():
    result = manifest()
    result.pop("contracts/ft/FT4_3b2a_Source_Freeze_v1.json", None)
    for path in sorted((ROOT / "tools").glob("evaluate_ft4*.py")):
        result[str(path.relative_to(ROOT))] = hashlib.sha256(path.read_bytes()).hexdigest()
    return result


def main(out):
    out.mkdir(parents=True, exist_ok=False)
    before = freeze()
    (out / "source_freeze.json").write_text(json.dumps(before, indent=2) + "\n")
    registered = json.loads((ROOT / "contracts/ft/FT4_3b2a_Source_Freeze_v1.json").read_text())
    protocol_path = ROOT / "contracts/ft/FT4_3b2a_Protocol_v1.json"
    protocol = json.loads(protocol_path.read_text())
    digest = hashlib.sha256(protocol_path.read_bytes()).hexdigest()
    digest_file = (ROOT / "contracts/ft/FT4_3b2a_Protocol_v1.json.sha256").read_text().split()[0]
    fixtures_ok = all(hashlib.sha256((ROOT / path).read_bytes()).hexdigest() == expected
                      for path, expected in protocol["fixtures"].items())
    expected = []
    for batch, module, cls in ROWS:
        declared = json.loads((ROOT / "contracts/ft" / (batch + "_Protocol_v1.json")).read_text())
        expected.extend("tests_ft4." + module + "." + cls + "." + name
                        for name in declared["method_ids"])
    suite = unittest.defaultTestLoader.loadTestsFromNames(
        ["tests_ft4." + module for _, module, _ in ROWS])
    actual = sorted(ids(suite))
    (out / "method_ids.json").write_text(json.dumps(actual, indent=2) + "\n")
    with (out / "controls.log").open("w") as log:
        result = unittest.TextTestRunner(stream=log, verbosity=2).run(suite)
    witnesses = []
    if (result.wasSuccessful() and actual == sorted(expected)
            and before == registered and fixtures_ok and digest == digest_file):
        from tests_ft4.test_autonomous_capability import capability_case
        for setting in ("canonical", "workflow"):
            engine, cycle, demand, closure, controller, row, report = capability_case(setting)
            (out / (setting + "-native.json")).write_text(engine.checkpoint())
            (out / (setting + "-cycle.json")).write_text(cycle.checkpoint(engine))
            (out / (setting + "-closure.json")).write_text(closure.checkpoint(engine))
            (out / (setting + "-capability.json")).write_text(controller.checkpoint(engine))
            (out / (setting + "-trace.json")).write_text(json.dumps({
                "setting": setting, "phase": controller.phase,
                "certificate_key": controller.certificate_key,
                "capacity_ref": row["selected"]["capacity_ref"],
                "content_use_refs": row["selected"]["content_use_refs"],
                "applicable": controller.ledger.applicable(
                    controller.certificate_key, controller.actor, demand),
                "report": report}, indent=2, default=str) + "\n")
            witnesses.append(dict(setting=setting, phase=controller.phase,
                certified=report["certified"], certificates=report["certificates"],
                candidates=report["candidates"]))
    after = freeze()
    passed = (result.wasSuccessful() and actual == sorted(expected)
        and before == after == registered and fixtures_ok and digest == digest_file
        and len(witnesses) == 2 and all(row["certified"] and row["certificates"] == 1
                                       for row in witnesses))
    summary = dict(passed=passed, methods=result.testsRun,
        failures=len(result.failures), errors=len(result.errors),
        exact_methods=actual == sorted(expected), expected_methods=len(expected),
        source_unchanged=before == after, registered_freeze=before == registered,
        protocol_sha256=digest, protocol_hash_registered=digest == digest_file,
        fixtures_unchanged=fixtures_ok, witnesses=witnesses,
        scope="FT4.3b2a capability certification only; retained reuse and parent FT4 remain pending")
    (out / "summary.json").write_text(json.dumps(summary, indent=2) + "\n")
    print(json.dumps(summary), flush=True)
    return summary


if __name__ == "__main__":
    sys.exit(not main(Path(sys.argv[1]).resolve())["passed"])
