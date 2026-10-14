"""Frozen FT6.3b decision: audit accepted saved grid and six training replays."""
import hashlib
import json
from pathlib import Path
import sys
import unittest
import zipfile
from dataclasses import replace

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT), str(ROOT / "baseline/HLE_Rebuild_R21B")]


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def freeze():
    accepted = json.loads((ROOT / "contracts/ft/FT6_3a_Source_Freeze_v1.json").read_text())
    names = list(accepted) + ["contracts/ft/FT6_3a_Source_Freeze_v1.json",
        "contracts/ft/FT6_3b_Protocol_v1.json", "contracts/ft/FT6_3b_Protocol_v1.sha256",
        "full_theory/conditioning_release.py", "full_theory/conditioning_release_audit.py",
        "tests_ft6/test_conditioning_release.py", "tools/evaluate_ft6_3b.py"]
    return {name: digest(ROOT / name) for name in sorted(names)}


def ids(suite):
    for item in suite:
        if isinstance(item, unittest.TestSuite):
            yield from ids(item)
        else:
            yield item.id()


def predecessor_identities():
    from tools.evaluate_ft6_3a import predecessor_expected
    from tools.evaluate_ft6_1 import FT4_ROWS
    p = json.loads((ROOT / "contracts/ft/FT6_3a_Protocol_v1.json").read_text())
    expected = sorted(predecessor_expected() + [
        "tests_ft6.test_conditioning_grid.ConditioningGridTests." + method
        for method in p["registered_tests"]])
    modules = ["tests_ft6.test_conditioning_grid", "tests_ft6.test_conditioning_feedback",
        "tests_ft6.test_use_history", "tests_ft5.test_reserve_grid", "tests_ft5.test_reserve_recovery",
        "tests_ft5.test_reserve_cycle", "tests_ft5.test_reserve_candidates",
        "tests_ft5.test_native_reserve", "tests_ft5.test_reserve"]
    modules += ["tests_ft4." + module for _, module, _ in FT4_ROWS]
    actual = sorted(ids(unittest.defaultTestLoader.loadTestsFromNames(modules)))
    if actual != expected or len(actual) != 255:
        raise ValueError("accepted predecessor method identities differ")
    return actual


def load_context(archive):
    from hle_unified import codec
    from hle_unified.selection_records import loads
    from full_theory.conditioning_grid_audit import audit_conditioning_grid
    from full_theory.conditioning_release import decide_conditioning_release
    from full_theory.conditioning_release_audit import audit_training, audit_release
    protocol = json.loads((ROOT / "contracts/ft/FT6_3b_Protocol_v1.json").read_text())
    inputs = protocol["inputs"]
    if digest(archive) != inputs["archive_sha256"]:
        raise ValueError("accepted archive hash differs")
    print("Reading exact accepted archive; no grid rerun", flush=True)
    with zipfile.ZipFile(archive) as z:
        manifest = json.loads(z.read("SHA256.json"))
        if len(z.namelist()) != len(set(z.namelist())):
            raise ValueError("duplicate evidence member")
        for name, expected in manifest.items():
            if hashlib.sha256(z.read(name)).hexdigest() != expected:
                raise ValueError("accepted evidence member differs: " + name)
        accepted = json.loads(z.read("acceptance/summary.json"))
        if (accepted["passed"] is not True or accepted["methods"] != 14
                or accepted["failures"] != 0 or accepted["errors"] != 0
                or accepted["grid_sha256"] != inputs["grid_sha256"]):
            raise ValueError("accepted source gate differs")
        source = json.loads(z.read("acceptance/source_freeze.json"))
        for name, expected in source.items():
            if digest(ROOT / name) != expected:
                raise ValueError("accepted frozen source changed: " + name)
        for label, member in (("protocol", "checkpoint/contracts/ft/FT6_3a_Protocol_v1.json"),
                              ("fixture", "checkpoint/contracts/ft/FT6_3a_Fixtures_v1.json")):
            if hashlib.sha256(z.read(member)).hexdigest() != inputs[label + "_sha256"]:
                raise ValueError("accepted prospective input hash differs")
        fixture = json.loads(z.read("checkpoint/contracts/ft/FT6_3a_Fixtures_v1.json"))
        report = loads(z.read("acceptance/grid_report.json").decode())
        records = codec.loads(z.read("acceptance/raw_paid_evidence.json").decode())
    evidence = {key: (transactions, checkpoint, loads(episode))
                for key, transactions, checkpoint, episode in records}
    if len(records) != len(evidence) or len(evidence) != 228:
        raise ValueError("raw accepted record identities differ")
    del records
    histories = {}
    for policy in report["policies"]:
        for history in report["histories"]:
            rows = sorted((r for r in report["primary"] if r["policy"] == policy
                           and r["history"] == history), key=lambda r: r["schedule_index"])
            histories[policy + "|" + history] = tuple(r["history_checkpoint"] for r in rows)
    removed = {"null": histories["null|no-use"]}
    for policy in ("success-v1", "success-decay-v1"):
        removed[policy] = tuple(r["history_checkpoint"] for r in sorted(
            (r for r in report["controls"] if r["policy"] == policy and r["kind"] == "history-removal"),
            key=lambda r: r["schedule_index"]))
    print("Independently reconstructing all 228 saved paid records", flush=True)
    receipt = audit_conditioning_grid(report, fixture, histories, removed, evidence)
    print("Saved grid reconstructed; replaying exact six paid training requests", flush=True)
    from tests_ft6.test_conditioning_grid import _base, _finish
    engine, request = _base("H")
    baseline = tuple(engine.world.journal())
    training = tuple(_finish(engine, replace(request, key="ft63-training-" + str(i))) for i in range(1, 7))
    training_receipts = tuple(audit_training(baseline, training, histories[policy + "|independent-use"][0])
                              for policy in report["policies"])
    episodes = tuple(row[2] for row in training)
    decision = decide_conditioning_release(report, episodes, receipt)
    release_audit = audit_release(report, episodes, decision, receipt)
    print("Training and policy decision independently reconstructed", flush=True)
    return dict(protocol=protocol, fixture=fixture, report=report, grid_audit=receipt,
        baseline=baseline, training=training, episodes=episodes,
        histories=histories, training_audits=training_receipts, decision=decision,
        release_audit=release_audit, predecessor_ids=predecessor_identities(),
        input_hashes_verified=True, accepted_source_verified=True)


def main(archive, out):
    from hle_unified import codec
    from hle_unified.selection_records import dumps, loads
    out.mkdir(parents=True, exist_ok=False)
    before = freeze()
    (out / "source_freeze.json").write_text(json.dumps(before, indent=2) + "\n")
    registered = json.loads((ROOT / "contracts/ft/FT6_3b_Source_Freeze_v1.json").read_text())
    if before != registered:
        raise ValueError("FT6.3b source freeze differs before evaluation")
    p = ROOT / "contracts/ft/FT6_3b_Protocol_v1.json"
    if digest(p) != p.with_suffix('.sha256').read_text().split()[0]:
        raise ValueError("FT6.3b protocol hash differs")
    context = load_context(archive)
    import tests_ft6.test_conditioning_release as tests
    tests.CONTEXT = context
    suite = unittest.defaultTestLoader.loadTestsFromModule(tests)
    actual = sorted(ids(suite))
    expected = sorted("tests_ft6.test_conditioning_release.ConditioningReleaseTests." + m
                      for m in context["protocol"]["registered_tests"])
    (out / "method_ids.json").write_text(json.dumps(actual, indent=2) + "\n")
    (out / "predecessor_ids.json").write_text(json.dumps(context["predecessor_ids"], indent=2) + "\n")
    with (out / "controls.log").open("w") as log:
        result = unittest.TextTestRunner(stream=log, verbosity=2).run(suite)
    (out / "decision.json").write_text(dumps(context["decision"]) + "\n")
    (out / "audits.json").write_text(dumps(dict(grid=context["grid_audit"],
        training=context["training_audits"], release=context["release_audit"])) + "\n")
    raw = (context["baseline"], tuple((transactions, checkpoint, dumps(episode))
                                    for transactions, checkpoint, episode in context["training"]))
    raw_path = out / "training_paid_evidence.json"
    raw_path.write_text(codec.dumps(raw) + "\n")
    decoded = codec.loads(raw_path.read_text())
    roundtrip = decoded == raw
    from full_theory.conditioning_release_audit import audit_training
    restored = tuple((transactions, checkpoint, loads(episode)) for transactions, checkpoint, episode in decoded[1])
    decoded_audit = audit_training(decoded[0], restored, context["histories"]["success-v1|independent-use"][0])
    passed = (result.wasSuccessful() and actual == expected and len(actual) == 12
              and before == freeze() and roundtrip and decoded_audit["passed"]
              and context["decision"]["engineering_gate"] == "accepted")
    summary = dict(passed=passed, methods=result.testsRun, failures=len(result.failures), errors=len(result.errors),
        exact_methods=actual == expected, predecessor_methods=len(context["predecessor_ids"]),
        saved_paid_records=228, new_training_executions=6,
        saved_grid_independently_reconstructed=context["grid_audit"]["passed"],
        exact_training_history_bound=all(x["paid_history_bound"] for x in context["training_audits"]),
        selected_policy=context["decision"]["selected_policy"],
        decay_distinct_demands=context["decision"]["decay_distinct_demands"],
        source_unchanged=before == freeze(), registered_freeze=before == registered,
        protocol_sha256=digest(p), input_archive_sha256=digest(archive),
        grid_sha256=context["report"]["grid_sha256"], training_roundtrip_exact=roundtrip,
        decoded_training_audit=decoded_audit["passed"], subtype_assignment=None,
        full_subtype_claim="held pending author interpretation", next_batch="FT7.1")
    (out / "summary.json").write_text(json.dumps(summary, indent=2) + "\n")
    (out / "evidence_hashes.json").write_text(json.dumps({p.name:digest(p) for p in sorted(out.iterdir()) if p.is_file()}, indent=2) + "\n")
    if not passed:
        raise SystemExit(1)
    print(json.dumps(summary, indent=2), flush=True)


if __name__ == "__main__":
    if len(sys.argv) != 3:
        raise SystemExit("usage: evaluate_ft6_3b.py ACCEPTED_FT6_3A_ARCHIVE OUTPUT_DIRECTORY")
    main(Path(sys.argv[1]).resolve(), Path(sys.argv[2]).resolve())
