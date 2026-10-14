"""Frozen FT6.1 paid-use history and bounded accounting gate."""
from dataclasses import replace
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
    for area in ("full_theory", "tests_ft4", "tests_ft5", "tests_ft6", "contracts/ft"):
        for path in sorted((ROOT / area).rglob("*")):
            if path.is_file() and path.suffix in (".py", ".json", ".sha256"):
                relative = str(path.relative_to(ROOT))
                if relative != "contracts/ft/FT6_1_Source_Freeze_v1.json":
                    result[relative] = digest(path)
    for relative in ("hle_unified/conditioning_audit.py", "hle_unified/codec.py",
                     "hle_unified/operations.py", "hle_unified/selection_records.py"):
        result[relative] = digest(ROOT / relative)
    result["tools/evaluate_ft6_1.py"] = digest(Path(__file__))
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
    grid = json.loads((ROOT / "contracts/ft/FT5_3b_Protocol_v1.json").read_text())
    expected += ["tests_ft5.test_reserve_grid.ReserveGridTests." + method
                 for method in grid["registered_tests"]]
    return sorted(expected)


def independent_witness():
    from hle_unified.conditioning_audit import ELEMENTS
    from hle_unified.energy_audit import blocks
    from tests_energy.fixtures import factory
    from tests_workflow_selection.final_fixtures import final_fixture
    from full_theory.use_history import UseHistoryLedger, classifications_for
    from full_theory.use_history_audit import audit_use_history

    engine, request, _ = final_fixture("Contemplate", "accumulation", factory("grade-v1"))
    actor = request.actor
    request = replace(request, key="ft6-acceptance-paid-use")
    engine.start("ft6-acceptance-start", request)
    engine.advance("ft6-acceptance-select", actor, request.key, 10000)
    engine.commit("ft6-acceptance-select-commit", actor, request.key)
    movement = request.key + ":movement"
    boundary = next(end for _, end, _, element in blocks(engine.job_status(actor, movement))
                    if element is not None)
    before = tuple(engine.world.journal())
    engine.advance("ft6-acceptance-use", actor, movement, boundary)
    after = tuple(engine.world.journal())
    reports = []
    for policy in ("null", "success-v1", "success-decay-v1"):
        outcome = dict(status="succeeded", supported=False, rehearsal=False,
                       demand_id="acceptance-demand", route_id="acceptance-route")
        rows = classifications_for(before, after, actor, 1, "independent", outcome)
        ledger = UseHistoryLedger(actor, policy, before)
        ledger.observe(after, 1, rows)
        for turn in range(2, 6):
            ledger.observe(after, turn, ())
        report = audit_use_history(ledger.checkpoint(), after)
        reports.append(dict(policy=policy, score_sum=sum(report["scores"].values()),
                            paid_delta=len(rows), audit=report["passed"],
                            native_bound=report["native_bound"]))
    by_policy = {row["policy"]: row for row in reports}
    passed = (all(row["audit"] and row["native_bound"] and row["paid_delta"] == 1
                  for row in reports)
              and by_policy["null"]["score_sum"] == 0
              and by_policy["success-v1"]["score_sum"] == 1
              and by_policy["success-decay-v1"]["score_sum"] == 0)
    return dict(passed=passed, policies=reports, elements=ELEMENTS,
                claim="one actual paid use; null/no-decay/decay reconstructed independently")


def main(out):
    out.mkdir(parents=True, exist_ok=False)
    before = freeze()
    (out / "source_freeze.json").write_text(json.dumps(before, indent=2) + "\n")
    registered = json.loads((ROOT / "contracts/ft/FT6_1_Source_Freeze_v1.json").read_text())
    protocol_path = ROOT / "contracts/ft/FT6_1_Protocol_v1.json"
    protocol = json.loads(protocol_path.read_text())
    protocol_hash = digest(protocol_path)
    registered_hash = (ROOT / "contracts/ft/FT6_1_Protocol_v1.json.sha256").read_text().split()[0]

    suite = unittest.defaultTestLoader.loadTestsFromName("tests_ft6.test_use_history")
    actual = sorted(ids(suite))
    expected = sorted("tests_ft6.test_use_history.UseHistoryTests." + method
                      for method in protocol["registered_tests"])
    (out / "method_ids.json").write_text(json.dumps(actual, indent=2) + "\n")
    with (out / "controls.log").open("w") as log:
        result = unittest.TextTestRunner(stream=log, verbosity=2).run(suite)

    modules = ["tests_ft5.test_reserve_grid", "tests_ft5.test_reserve_recovery",
        "tests_ft5.test_reserve_cycle", "tests_ft5.test_reserve_candidates",
        "tests_ft5.test_native_reserve", "tests_ft5.test_reserve"]
    modules += ["tests_ft4." + module for _, module, _ in FT4_ROWS]
    predecessor = sorted(ids(unittest.defaultTestLoader.loadTestsFromNames(modules)))
    predecessor_exact = predecessor == predecessor_expected() and len(predecessor) == 215
    (out / "predecessor_method_ids.json").write_text(json.dumps(predecessor, indent=2) + "\n")

    witness = independent_witness()
    (out / "independent_witness.json").write_text(json.dumps(witness, indent=2) + "\n")
    after = freeze()
    passed = (result.wasSuccessful() and actual == expected and predecessor_exact
              and witness["passed"] and before == after == registered
              and protocol_hash == registered_hash)
    summary = dict(passed=passed, methods=result.testsRun, failures=len(result.failures),
        errors=len(result.errors), exact_methods=actual == expected,
        expected_methods=len(expected), predecessor_exact_methods=predecessor_exact,
        predecessor_methods=len(predecessor), independent_native_witness=witness["passed"],
        feedback_policies=3, semantic_tags=4, score_cap=8, decay_idle_turns=4,
        recent_window=32, source_unchanged=before == after,
        registered_freeze=before == registered, protocol_sha256=protocol_hash,
        protocol_hash_registered=protocol_hash == registered_hash,
        preserved_failures=(
            "Development attempt 1 passed behavioral methods but the independent auditor rejected canonical JSON maps because it incorrectly required insertion order after sort_keys serialization; corrected to exact key-set validation before freeze.",),
        scope="FT6.1 paid-use history accounting only; route feedback, measured DCNH occupancy and subtype remain open")
    (out / "summary.json").write_text(json.dumps(summary, indent=2) + "\n")
    print(json.dumps(summary), flush=True)
    return summary


if __name__ == "__main__":
    sys.exit(not main(Path(sys.argv[1]).resolve())["passed"])
