"""Frozen FT5.1 integer reserve accounting-state gate."""
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
                if relative != "contracts/ft/FT5_1_Source_Freeze_v1.json":
                    result[relative] = digest(path)
    for relative in ("hle_unified/energy.py", "hle_unified/energy_audit.py",
                     "hle_unified/selection_records.py"):
        result[relative] = digest(ROOT / relative)
    result["tools/evaluate_ft5_1.py"] = digest(Path(__file__))
    return result


def ids(suite):
    for item in suite:
        if isinstance(item, unittest.TestSuite):
            yield from ids(item)
        else:
            yield item.id()


def ft4_expected():
    expected = []
    for batch, module, cls in FT4_ROWS:
        protocol = json.loads((ROOT / "contracts/ft" / (batch + "_Protocol_v1.json")).read_text())
        expected.extend("tests_ft4." + module + "." + cls + "." + name
                        for name in protocol["method_ids"])
    return sorted(expected)


def main(out):
    out.mkdir(parents=True, exist_ok=False)
    before = freeze()
    (out / "source_freeze.json").write_text(json.dumps(before, indent=2) + "\n")
    registered = json.loads((ROOT / "contracts/ft/FT5_1_Source_Freeze_v1.json").read_text())
    protocol_path = ROOT / "contracts/ft/FT5_1_Protocol_v1.json"
    protocol = json.loads(protocol_path.read_text())
    protocol_hash = digest(protocol_path)
    registered_hash = (ROOT / "contracts/ft/FT5_1_Protocol_v1.json.sha256").read_text().split()[0]
    fixtures_ok = all(digest(ROOT / path) == expected
                      for path, expected in protocol["fixtures"].items())

    suite = unittest.defaultTestLoader.loadTestsFromName("tests_ft5.test_reserve")
    actual = sorted(ids(suite))
    expected = sorted("tests_ft5.test_reserve.ReserveTests." + name
                      for name in protocol["method_ids"])
    (out / "method_ids.json").write_text(json.dumps(actual, indent=2) + "\n")
    with (out / "controls.log").open("w") as log:
        result = unittest.TextTestRunner(stream=log, verbosity=2).run(suite)

    ft4_suite = unittest.defaultTestLoader.loadTestsFromNames(
        ["tests_ft4." + module for _, module, _ in FT4_ROWS])
    ft4_actual = sorted(ids(ft4_suite))
    ft4_exact = ft4_actual == ft4_expected() and len(ft4_actual) == 130
    (out / "ft4_method_ids.json").write_text(json.dumps(ft4_actual, indent=2) + "\n")

    witnesses = []
    if result.wasSuccessful() and actual == expected:
        from full_theory.reserve import ReserveLedger
        from full_theory.reserve_audit import audit_reserve
        from tests_ft5.test_reserve import receipt
        for policy in ("null", "load-v1", "grade-load-v1"):
            ledger = ReserveLedger("actor", policy, initial=4, tokens=("token",))
            ledger.admit("owned-demand", 4)
            ledger.interrupt("owned-demand", "attempt")
            grade = 2 if policy == "grade-load-v1" else None
            ledger.complete("owned-demand", "independent", last_paid_grade=grade)
            ledger.replenish("token", receipt("actor", "token", "receipt"))
            report = audit_reserve(ledger.checkpoint())
            (out / (policy + "-reserve.json")).write_text(ledger.checkpoint())
            witnesses.append(report)

    after = freeze()
    passed = (result.wasSuccessful() and actual == expected and ft4_exact
              and before == after == registered and fixtures_ok
              and protocol_hash == registered_hash and len(witnesses) == 3
              and all(row["passed"] for row in witnesses))
    summary = dict(passed=passed, methods=result.testsRun,
                   failures=len(result.failures), errors=len(result.errors),
                   exact_methods=actual == expected, expected_methods=len(expected),
                   ft4_exact_methods=ft4_exact, ft4_methods=len(ft4_actual),
                   source_unchanged=before == after,
                   registered_freeze=before == registered,
                   fixtures_unchanged=fixtures_ok,
                   protocol_sha256=protocol_hash,
                   protocol_hash_registered=protocol_hash == registered_hash,
                   witnesses=witnesses,
                   scope="FT5.1 accounting state only; paid integration and policy election remain open")
    (out / "summary.json").write_text(json.dumps(summary, indent=2, default=str) + "\n")
    print(json.dumps(summary, default=str), flush=True)
    return summary


if __name__ == "__main__":
    sys.exit(not main(Path(sys.argv[1]).resolve())["passed"])
