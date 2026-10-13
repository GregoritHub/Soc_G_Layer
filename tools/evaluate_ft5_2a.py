"""Frozen FT5.2a paid native reserve-binding gate."""
from pathlib import Path
import hashlib
import json
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT), str(ROOT / "baseline/HLE_Rebuild_R21B")]

FT4_ROWS = (
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
    ("FT4_3b2b", "test_autonomous_reuse", "AutonomousReuseTests"),
)


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def freeze():
    result = {}
    for area in ("full_theory", "tests_ft4", "tests_ft5", "contracts/ft"):
        for path in sorted((ROOT / area).rglob("*")):
            if path.is_file() and path.suffix in (".py", ".json", ".sha256"):
                relative = str(path.relative_to(ROOT))
                if relative != "contracts/ft/FT5_2a_Source_Freeze_v1.json":
                    result[relative] = digest(path)
    for relative in ("hle_unified/operations.py", "hle_unified/selection_records.py"):
        result[relative] = digest(ROOT / relative)
    result["tools/evaluate_ft5_2a.py"] = digest(Path(__file__))
    return result


def ids(suite):
    for item in suite:
        if isinstance(item, unittest.TestSuite):
            yield from ids(item)
        else:
            yield item.id()


def expected_ft4():
    result = []
    for batch, module, cls in FT4_ROWS:
        protocol = json.loads((ROOT / "contracts/ft" / (batch + "_Protocol_v1.json")).read_text())
        result.extend("tests_ft4." + module + "." + cls + "." + method
                      for method in protocol["method_ids"])
    return sorted(result)


def main(out):
    out.mkdir(parents=True, exist_ok=False)
    before = freeze()
    (out / "source_freeze.json").write_text(json.dumps(before, indent=2) + "\n")
    registered = json.loads((ROOT / "contracts/ft/FT5_2a_Source_Freeze_v1.json").read_text())
    protocol_path = ROOT / "contracts/ft/FT5_2a_Protocol_v1.json"
    protocol = json.loads(protocol_path.read_text())
    protocol_hash = digest(protocol_path)
    registered_hash = (ROOT / "contracts/ft/FT5_2a_Protocol_v1.json.sha256").read_text().split()[0]
    fixtures_ok = all(digest(ROOT / path) == expected for path, expected in protocol["fixtures"].items())

    suite = unittest.defaultTestLoader.loadTestsFromName("tests_ft5.test_native_reserve")
    actual = sorted(ids(suite))
    expected = sorted("tests_ft5.test_native_reserve.NativeReserveTests." + method
                      for method in protocol["method_ids"])
    (out / "method_ids.json").write_text(json.dumps(actual, indent=2) + "\n")
    with (out / "controls.log").open("w") as log:
        test_result = unittest.TextTestRunner(stream=log, verbosity=2).run(suite)

    predecessor_suite = unittest.defaultTestLoader.loadTestsFromNames(
        ["tests_ft5.test_reserve"] + ["tests_ft4." + module for _, module, _ in FT4_ROWS])
    predecessor_actual = sorted(ids(predecessor_suite))
    ft5_protocol = json.loads((ROOT / "contracts/ft/FT5_1_Protocol_v1.json").read_text())
    predecessor_expected = sorted(
        ["tests_ft5.test_reserve.ReserveTests." + method for method in ft5_protocol["method_ids"]]
        + expected_ft4())
    predecessor_exact = predecessor_actual == predecessor_expected and len(predecessor_actual) == 146
    (out / "predecessor_method_ids.json").write_text(json.dumps(predecessor_actual, indent=2) + "\n")

    witnesses = []
    if test_result.wasSuccessful() and actual == expected:
        from tests_ft5.test_native_reserve import preparation_case, uptake_case
        from full_theory.native_reserve_audit import audit_native_reserve
        for setting in ("canonical", "workflow"):
            engine, _, native, _ = preparation_case(setting)
            witnesses.append(audit_native_reserve(engine, native.checkpoint(engine)))
            engine, bridge, _, native, _ = uptake_case(setting)
            native.replenish_from_uptake(engine, bridge, "token", "packet")
            witnesses.append(audit_native_reserve(engine, native.checkpoint(engine)))
            (out / (setting + "-native-reserve.json")).write_text(native.checkpoint(engine))

    after = freeze()
    passed = (test_result.wasSuccessful() and actual == expected and predecessor_exact
              and before == after == registered and fixtures_ok
              and protocol_hash == registered_hash and len(witnesses) == 4
              and all(row["passed"] for row in witnesses))
    summary = dict(passed=passed, methods=test_result.testsRun,
        failures=len(test_result.failures), errors=len(test_result.errors),
        exact_methods=actual == expected, expected_methods=len(expected),
        predecessor_exact_methods=predecessor_exact,
        predecessor_methods=len(predecessor_actual), source_unchanged=before == after,
        registered_freeze=before == registered, fixtures_unchanged=fixtures_ok,
        protocol_sha256=protocol_hash, protocol_hash_registered=protocol_hash == registered_hash,
        witnesses=witnesses,
        scope="FT5.2a paid native binding only; autonomous candidate dynamics and policy election remain open")
    (out / "summary.json").write_text(json.dumps(summary, indent=2, default=str) + "\n")
    print(json.dumps(summary, default=str), flush=True)
    return summary


if __name__ == "__main__":
    sys.exit(not main(Path(sys.argv[1]).resolve())["passed"])
