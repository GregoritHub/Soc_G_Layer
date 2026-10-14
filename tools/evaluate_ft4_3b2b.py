"""Frozen FT4.3b2b retained-reuse and final common FT4 gate."""
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
    ("FT4_3b2b", "test_autonomous_reuse", "AutonomousReuseTests"),
]


def freeze():
    result = manifest()
    result.pop("contracts/ft/FT4_3b2b_Source_Freeze_v1.json", None)
    for path in sorted((ROOT / "tools").glob("evaluate_ft4*.py")):
        result[str(path.relative_to(ROOT))] = hashlib.sha256(path.read_bytes()).hexdigest()
    return result


def history_rows(ledger):
    return tuple(sorted(((str(actor), tuple(sorted(values)))
                         for actor, values in ledger.history.items())))


def main(out):
    out.mkdir(parents=True, exist_ok=False)
    before = freeze()
    (out / "source_freeze.json").write_text(json.dumps(before, indent=2) + "\n")
    registered = json.loads((ROOT / "contracts/ft/FT4_3b2b_Source_Freeze_v1.json").read_text())
    protocol_path = ROOT / "contracts/ft/FT4_3b2b_Protocol_v1.json"
    protocol = json.loads(protocol_path.read_text())
    digest = hashlib.sha256(protocol_path.read_bytes()).hexdigest()
    digest_file = (ROOT / "contracts/ft/FT4_3b2b_Protocol_v1.json.sha256").read_text().split()[0]
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
    controls = []
    if (result.wasSuccessful() and actual == sorted(expected)
            and before == registered and fixtures_ok and digest == digest_file):
        from tests_ft4.test_autonomous_reuse import finish_reuse
        from tests_ft4.test_opposition import finish_opposition
        for setting in ("canonical", "workflow"):
            engine, _, _, controller, _, report = finish_reuse(setting)
            (out / (setting + "-native.json")).write_text(engine.checkpoint())
            (out / (setting + "-reuse.json")).write_text(controller.checkpoint(engine))
            (out / (setting + "-trace.json")).write_text(json.dumps({
                "setting": setting, "phase": controller.phase,
                "selected": report["selected"], "retained": report["retained"],
                "fulfilled": report["fulfillment"]["fulfilled"],
                "history": history_rows(controller.ledger)}, indent=2, default=str) + "\n")
            witnesses.append(dict(setting=setting, phase=controller.phase,
                selected=report["selected"], retained=report["retained"],
                fulfilled=report["fulfillment"]["fulfilled"]))
            _, opposed, _, _, _, opposed_report = finish_opposition(setting)
            controls.append(dict(setting=setting, opposition=opposed_report["completed"],
                moves=tuple(opposed.attempts[0]["moves"]),
                paid_energy=opposed_report["orientation"]["paid_energy"],
                paid_time=opposed_report["orientation"]["paid_time"]))
        _, _, _, removed, _, removed_report = finish_reuse("canonical", revoke=True)
        controls.append(dict(setting="canonical-ablation", selected=removed_report["selected"],
            revoked=removed_report["revoked"], history=history_rows(removed.ledger)))
    after = freeze()
    passed = (result.wasSuccessful() and actual == sorted(expected)
        and before == after == registered and fixtures_ok and digest == digest_file
        and len(witnesses) == 2
        and all(row["phase"] == "complete" and row["selected"] == "retained"
                and row["fulfilled"] == 1 for row in witnesses)
        and len(controls) == 3 and controls[-1].get("selected") == "ordinary"
        and controls[-1].get("revoked") is True
        and all(row.get("opposition") == 1 and row.get("moves") == ("cp", "n")
                for row in controls[:2]))
    summary = dict(passed=passed, methods=result.testsRun,
        failures=len(result.failures), errors=len(result.errors),
        exact_methods=actual == sorted(expected), expected_methods=len(expected),
        source_unchanged=before == after, registered_freeze=before == registered,
        protocol_sha256=digest, protocol_hash_registered=digest == digest_file,
        fixtures_unchanged=fixtures_ok, witnesses=witnesses, controls=controls,
        scope="Bounded FT4 engineering gate; no psychological validation or theoretical closure")
    (out / "summary.json").write_text(json.dumps(summary, indent=2, default=str) + "\n")
    print(json.dumps(summary, default=str), flush=True)
    return summary


if __name__ == "__main__":
    sys.exit(not main(Path(sys.argv[1]).resolve())["passed"])
