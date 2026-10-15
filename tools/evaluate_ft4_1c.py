"""Frozen FT4.1 demand-formation gate with independent positive replay."""
from pathlib import Path
import hashlib
import json
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT), str(ROOT / "baseline/HLE_Rebuild_R21B")]
from tools.evaluate_ft4_1 import manifest, ids


def freeze():
    result = manifest()
    for path in (ROOT / "tools/evaluate_ft4_1.py", ROOT / "tools/evaluate_ft4_1b.py", Path(__file__)):
        result[str(path.relative_to(ROOT))] = hashlib.sha256(path.read_bytes()).hexdigest()
    return result


def main(out):
    out.mkdir(parents=True, exist_ok=False)
    before = freeze()
    (out / "source_freeze.json").write_text(json.dumps(before, indent=2) + "\n")
    names = ["tests_ft4.test_demands", "tests_ft4.test_requests", "tests_ft4.test_controller"]
    suite = unittest.defaultTestLoader.loadTestsFromNames(names)
    actual = sorted(ids(suite)); expected = []
    rows = (("FT4_1a_Protocol_v1.json", "tests_ft4.test_demands.DemandTests."),
            ("FT4_1b1_Protocol_v1.json", "tests_ft4.test_requests.RequestTests."),
            ("FT4_1b2_Protocol_v1.json", "tests_ft4.test_controller.ControllerTests."))
    for filename, prefix in rows:
        expected.extend(prefix + name for name in
                        json.loads((ROOT / "contracts/ft" / filename).read_text())["method_ids"])
    (out / "method_ids.json").write_text(json.dumps(actual, indent=2) + "\n")
    with (out / "controls.log").open("w") as log:
        result = unittest.TextTestRunner(stream=log, verbosity=2).run(suite)
    witnesses = []
    if result.wasSuccessful() and actual == sorted(expected):
        from tests_ft4.test_controller import completed
        for setting in ("canonical", "workflow"):
            engine, controller, request, event, report = completed(setting)
            (out / (setting + "-native.json")).write_text(engine.checkpoint())
            (out / (setting + "-controller.json")).write_text(controller.checkpoint())
            witnesses.append(dict(setting=setting, **report))
    after = freeze()
    summary = dict(passed=result.wasSuccessful() and actual == sorted(expected)
        and before == after and len(witnesses) == 2, exact_methods=actual == sorted(expected),
        methods=result.testsRun, failures=len(result.failures), errors=len(result.errors),
        source_unchanged=before == after, witnesses=witnesses,
        scope="FT4.1 demand formation only; FT4.2 choice and FT4.3 full cycle remain open")
    (out / "summary.json").write_text(json.dumps(summary, indent=2) + "\n")
    print(json.dumps(summary), flush=True)
    return summary


if __name__ == "__main__":
    sys.exit(not main(Path(sys.argv[1]).resolve())["passed"])
