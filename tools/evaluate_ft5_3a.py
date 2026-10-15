"""Frozen FT5.3a paid reserve recovery gate."""
from pathlib import Path
import hashlib
import json
import sys
import unittest


ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT), str(ROOT / "baseline/HLE_Rebuild_R21B")]

FT4_ROWS = (("FT4_1a", "test_demands", "DemandTests"),
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
 ("FT4_3b2b", "test_autonomous_reuse", "AutonomousReuseTests"))


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def freeze():
    result = {}
    for area in ("full_theory", "tests_ft4", "tests_ft5", "contracts/ft"):
        for path in sorted((ROOT / area).rglob("*")):
            if path.is_file() and path.suffix in (".py", ".json", ".sha256"):
                relative = str(path.relative_to(ROOT))
                if relative != "contracts/ft/FT5_3a_Source_Freeze_v1.json":
                    result[relative] = digest(path)
    for relative in ("hle_unified/model_g.py", "hle_unified/operations.py",
                     "hle_unified/selection_records.py"):
        result[relative] = digest(ROOT / relative)
    result["tools/evaluate_ft5_3a.py"] = digest(Path(__file__))
    return result


def ids(suite):
    for item in suite:
        if isinstance(item, unittest.TestSuite):
            yield from ids(item)
        else:
            yield item.id()


def predecessor_expected():
    expected = []
    for batch, module, cls in FT4_ROWS:
        protocol = json.loads((ROOT / "contracts/ft" / (batch + "_Protocol_v1.json")).read_text())
        expected += ["tests_ft4." + module + "." + cls + "." + method
                     for method in protocol["method_ids"]]
    for batch, module, cls in (("FT5_1", "test_reserve", "ReserveTests"),
                               ("FT5_2a", "test_native_reserve", "NativeReserveTests"),
                               ("FT5_2b1", "test_reserve_candidates", "ReserveCandidateTests"),
                               ("FT5_2b2", "test_reserve_cycle", "ReserveCycleTests")):
        protocol = json.loads((ROOT / "contracts/ft" / (batch + "_Protocol_v1.json")).read_text())
        expected += ["tests_ft5." + module + "." + cls + "." + method
                     for method in protocol["method_ids"]]
    return sorted(expected)


def main(out):
    out.mkdir(parents=True, exist_ok=False)
    before = freeze()
    (out / "source_freeze.json").write_text(json.dumps(before, indent=2) + "\n")
    registered = json.loads((ROOT / "contracts/ft/FT5_3a_Source_Freeze_v1.json").read_text())
    protocol_path = ROOT / "contracts/ft/FT5_3a_Protocol_v1.json"
    protocol = json.loads(protocol_path.read_text())
    protocol_hash = digest(protocol_path)
    registered_hash = (ROOT / "contracts/ft/FT5_3a_Protocol_v1.json.sha256").read_text().split()[0]
    fixtures = all(digest(ROOT / path) == value for path, value in protocol["fixtures"].items())

    suite = unittest.defaultTestLoader.loadTestsFromName("tests_ft5.test_reserve_recovery")
    actual = sorted(ids(suite))
    expected = sorted("tests_ft5.test_reserve_recovery.ReserveRecoveryTests." + method
                      for method in protocol["method_ids"])
    (out / "method_ids.json").write_text(json.dumps(actual, indent=2) + "\n")
    with (out / "controls.log").open("w") as log:
        result = unittest.TextTestRunner(stream=log, verbosity=2).run(suite)

    modules = ["tests_ft5.test_reserve_cycle", "tests_ft5.test_reserve_candidates",
               "tests_ft5.test_native_reserve", "tests_ft5.test_reserve"] + [
                   "tests_ft4." + module for _, module, _ in FT4_ROWS]
    predecessor = sorted(ids(unittest.defaultTestLoader.loadTestsFromNames(modules)))
    predecessor_exact = predecessor == predecessor_expected() and len(predecessor) == 186
    (out / "predecessor_method_ids.json").write_text(json.dumps(predecessor, indent=2) + "\n")

    witnesses = []
    if result.wasSuccessful() and actual == expected:
        from tests_ft5.test_reserve_recovery import recovered_case
        from full_theory.reserve_cycle_audit import audit_reserve_cycle
        for policy, initial in (("null", 0), ("load-v1", 2), ("grade-load-v1", 2)):
            for setting in ("canonical", "workflow"):
                engine, demand, controller, _, _, _, _, _ = recovered_case(
                    setting, policy, initial)
                report = audit_reserve_cycle(engine, controller.checkpoint(engine))
                witnesses.append(report)
                (out / (setting + "-" + policy + "-recovery.json")).write_text(
                    controller.checkpoint(engine))

    after = freeze()
    passed = (result.wasSuccessful() and actual == expected and predecessor_exact
        and before == after == registered and fixtures and protocol_hash == registered_hash
        and len(witnesses) == 6 and all(witness["passed"] for witness in witnesses))
    summary = dict(passed=passed, methods=result.testsRun, failures=len(result.failures),
        errors=len(result.errors), exact_methods=actual == expected, expected_methods=len(expected),
        predecessor_exact_methods=predecessor_exact, predecessor_methods=len(predecessor),
        source_unchanged=before == after, registered_freeze=before == registered,
        fixtures_unchanged=fixtures, protocol_sha256=protocol_hash,
        protocol_hash_registered=protocol_hash == registered_hash, witnesses=witnesses,
        scope="FT5.3a paid depletion/recovery only; FT5.3b partial order, grid and release policy remain open")
    (out / "summary.json").write_text(json.dumps(summary, indent=2, default=str) + "\n")
    print(json.dumps(summary, default=str), flush=True)
    return summary


if __name__ == "__main__":
    sys.exit(not main(Path(sys.argv[1]).resolve())["passed"])
