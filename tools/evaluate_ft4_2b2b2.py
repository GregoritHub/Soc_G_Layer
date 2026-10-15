"""Frozen FT4.2 common gate including declared paid opposition."""
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
]


def freeze():
    result = manifest()
    result.pop("contracts/ft/FT4_2b2b2_Source_Freeze_v1.json", None)
    for path in sorted((ROOT / "tools").glob("evaluate_ft4*.py")):
        result[str(path.relative_to(ROOT))] = hashlib.sha256(path.read_bytes()).hexdigest()
    return result


def main(out):
    out.mkdir(parents=True, exist_ok=False)
    before = freeze()
    (out / "source_freeze.json").write_text(json.dumps(before, indent=2) + "\n")
    registered = json.loads((ROOT / "contracts/ft/FT4_2b2b2_Source_Freeze_v1.json").read_text())
    protocol_path = ROOT / "contracts/ft/FT4_2b2b2_Protocol_v1.json"
    protocol = json.loads(protocol_path.read_text())
    digest = hashlib.sha256(protocol_path.read_bytes()).hexdigest()
    digest_file = (ROOT / "contracts/ft/FT4_2b2b2_Protocol_v1.json.sha256").read_text().split()[0]
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
    grid = []
    if (result.wasSuccessful() and actual == sorted(expected)
            and before == registered and fixtures_ok and digest == digest_file):
        from tests_ft4.test_opposition import finish_opposition
        for setting in ("canonical", "workflow"):
            engine, controller, _, _, row, report = finish_opposition(setting)
            (out / (setting + "-native.json")).write_text(engine.checkpoint())
            (out / (setting + "-opposition.json")).write_text(controller.checkpoint(engine))
            witnesses.append(dict(setting=setting, phase=row["phase"], **report))
        from hle.development_structure import lap, portage
        from hle.model_a import TYPES, position
        for tim in TYPES:
            for seat in range(1, 9):
                cp = portage(seat, "cp")
                final = portage(cp, "n")
                grid.append(dict(tim=tim, origin=seat, cp=cp, n=final,
                    opposition=portage(seat, "a"), directive_preserved=
                    position(seat)[0] == position(final)[0],
                    reverse=portage(lap(cp), "cp") == lap(lap(lap(seat)))))
        (out / "opposition_grid.json").write_text(json.dumps(grid, indent=2) + "\n")
    after = freeze()
    passed = (result.wasSuccessful() and actual == sorted(expected)
        and before == after == registered and fixtures_ok and digest == digest_file
        and len(witnesses) == 2 and len(grid) == 128
        and all(row["directive_preserved"] and row["reverse"]
                and row["n"] == row["opposition"] for row in grid))
    summary = dict(passed=passed, methods=result.testsRun,
        failures=len(result.failures), errors=len(result.errors),
        exact_methods=actual == sorted(expected), expected_methods=len(expected),
        source_unchanged=before == after, registered_freeze=before == registered,
        protocol_sha256=digest, protocol_hash_registered=digest == digest_file,
        fixtures_unchanged=fixtures_ok, geometry_cells=len(grid), witnesses=witnesses,
        scope="FT4.2 paid route choice including declared opposition; FT4.3 autonomous closure and reuse remain pending")
    (out / "summary.json").write_text(json.dumps(summary, indent=2) + "\n")
    print(json.dumps(summary), flush=True)
    return summary


if __name__ == "__main__":
    sys.exit(not main(Path(sys.argv[1]).resolve())["passed"])
