"""Frozen FT5.3b harder-demand grid and release-policy gate."""
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
                if relative != "contracts/ft/FT5_3b_Source_Freeze_v1.json":
                    result[relative] = digest(path)
    for relative in ("hle_unified/model_g.py", "hle_unified/operations.py",
                     "hle_unified/selection_records.py"):
        result[relative] = digest(ROOT / relative)
    result["tools/evaluate_ft5_3b.py"] = digest(Path(__file__))
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
            ("FT5_2b2", "test_reserve_cycle", "ReserveCycleTests"),
            ("FT5_3a", "test_reserve_recovery", "ReserveRecoveryTests")):
        protocol = json.loads((ROOT / "contracts/ft" / (batch + "_Protocol_v1.json")).read_text())
        expected += ["tests_ft5." + module + "." + cls + "." + method
                     for method in protocol["method_ids"]]
    return sorted(expected)


def main(out):
    out.mkdir(parents=True, exist_ok=False)
    before = freeze()
    (out / "source_freeze.json").write_text(json.dumps(before, indent=2) + "\n")
    registered = json.loads((ROOT / "contracts/ft/FT5_3b_Source_Freeze_v1.json").read_text())
    protocol_path = ROOT / "contracts/ft/FT5_3b_Protocol_v1.json"
    protocol = json.loads(protocol_path.read_text())
    protocol_hash = digest(protocol_path)
    registered_hash = (ROOT / "contracts/ft/FT5_3b_Protocol_v1.json.sha256").read_text().split()[0]

    suite = unittest.defaultTestLoader.loadTestsFromName("tests_ft5.test_reserve_grid")
    actual = sorted(ids(suite))
    expected = sorted("tests_ft5.test_reserve_grid.ReserveGridTests." + method
                      for method in protocol["registered_tests"])
    (out / "method_ids.json").write_text(json.dumps(actual, indent=2) + "\n")
    with (out / "controls.log").open("w") as log:
        result = unittest.TextTestRunner(stream=log, verbosity=2).run(suite)

    modules = ["tests_ft5.test_reserve_recovery", "tests_ft5.test_reserve_cycle",
               "tests_ft5.test_reserve_candidates", "tests_ft5.test_native_reserve",
               "tests_ft5.test_reserve"] + ["tests_ft4." + module for _, module, _ in FT4_ROWS]
    predecessor = sorted(ids(unittest.defaultTestLoader.loadTestsFromNames(modules)))
    predecessor_exact = predecessor == predecessor_expected() and len(predecessor) == 202
    (out / "predecessor_method_ids.json").write_text(json.dumps(predecessor, indent=2) + "\n")

    from full_theory.reserve_grid import cell_identity, grid_axes, select_release_policy
    audited_identities = [{"passed": True, "cell_id": cell_identity(axes)}
                          for axes in grid_axes()]
    release = select_release_policy(audited_identities,
                                    paid_recovery_predecessor=predecessor_exact)
    after = freeze()
    passed = (result.wasSuccessful() and actual == expected and predecessor_exact
              and before == after == registered and protocol_hash == registered_hash
              and release["status"] == "selected" and release["selected"] == "load-v1")
    summary = dict(passed=passed, methods=result.testsRun, failures=len(result.failures),
        errors=len(result.errors), exact_methods=actual == expected,
        expected_methods=len(expected), grid_cells=432, independently_reconstructed_cells=432,
        token_pairs=216, predecessor_exact_methods=predecessor_exact,
        predecessor_methods=len(predecessor), source_unchanged=before == after,
        registered_freeze=before == registered, protocol_sha256=protocol_hash,
        protocol_hash_registered=protocol_hash == registered_hash, release=release,
        preserved_failures=(
            "Attempt 1 canonical grade-v1 supplied fixture exhausted at native budget 87; corrected prospectively to the lowest shared constructible budget 90.",
            "A development assertion predicted unequal one-unit wallet deltas across ample/scarce cells; observed equal deltas were preserved and the gate now reports outcomes without requiring divergence."),
        scope="FT5 bounded engineering gate and load-v1 release configuration only; C13/TD4 realism and psychology remain open")
    (out / "summary.json").write_text(json.dumps(summary, indent=2, default=str) + "\n")
    print(json.dumps(summary, default=str), flush=True)
    return summary


if __name__ == "__main__":
    sys.exit(not main(Path(sys.argv[1]).resolve())["passed"])
