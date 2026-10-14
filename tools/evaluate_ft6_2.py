"""Frozen FT6.2 conditioned-choice and paid n-episode acceptance gate."""
from dataclasses import replace
from pathlib import Path
import hashlib
import json
import sys
import unittest


ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT), str(ROOT / "baseline/HLE_Rebuild_R21B")]


def digest(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


def freeze():
    result = {}
    for area in ("full_theory", "tests_ft4", "tests_ft5", "tests_ft6", "contracts/ft"):
        for path in sorted((ROOT / area).rglob("*")):
            if path.is_file() and path.suffix in (".py", ".json", ".sha256"):
                relative = str(path.relative_to(ROOT))
                if relative != "contracts/ft/FT6_2_Source_Freeze_v1.json":
                    result[relative] = digest(path)
    for relative in ("hle_unified/conditioning_audit.py", "hle_unified/axes.py",
                     "hle_unified/codec.py", "hle_unified/model_g.py",
                     "hle_unified/selection_records.py",
                     "baseline/HLE_Rebuild_R21B/hle/development_structure.py"):
        result[relative] = digest(ROOT / relative)
    result["tools/evaluate_ft6_2.py"] = digest(Path(__file__))
    return result


def ids(suite):
    for item in suite:
        if isinstance(item, unittest.TestSuite):
            yield from ids(item)
        else:
            yield item.id()


def predecessor_expected():
    from tools.evaluate_ft6_1 import predecessor_expected as ft5_expected
    protocol = json.loads((ROOT / "contracts/ft/FT6_1_Protocol_v1.json").read_text())
    return sorted(ft5_expected() + [
        "tests_ft6.test_use_history.UseHistoryTests." + method
        for method in protocol["registered_tests"]])


def independent_witness():
    from tests_c6 import fixtures as c6
    from full_theory.conditioning_feedback import (bind_choice, choose_candidate,
        compensation_episode, measured_occupancy)
    from full_theory.conditioning_feedback_audit import (audit_binding, audit_choice,
        audit_episode, audit_occupancy)
    from full_theory.retention import Demand
    from full_theory.route_policy import IntegratedRoutePolicy
    from full_theory.route_policy_audit import audit_route_policy
    from full_theory.use_history import UseHistoryLedger, classifications_for

    engine, request = c6.fixture("Understand", "accumulation", tim="eii")
    actor = request.actor
    required = Demand("canonical", request.context, request.cue, request.target,
        requirements=("experience", "norms"))

    def finish(key):
        current = replace(request, key=key); controller = IntegratedRoutePolicy()
        for _ in range(32):
            event = controller.step(engine, current, required, work_limit=1000000)
            if event["phase"] in ("complete", "deferred", "failed", "cancelled", "rejected"):
                break
        checkpoint = controller.checkpoint(engine)
        route_audit = audit_route_policy(engine.world.journal(), engine.access.checkpoint(),
                                         checkpoint, engine.checkpoint())
        if event["phase"] != "complete" or event["selected"] != "n" or not route_audit["passed"]:
            raise AssertionError("acceptance n route did not complete and audit")
        transactions = tuple(engine.world.journal())
        episode = compensation_episode(transactions, checkpoint, actor, key)
        return transactions, checkpoint, episode

    first_transactions, first_checkpoint, first_episode = finish("ft62-witness-training")
    baseline = first_transactions[:first_episode["journal_window"][0]]
    outcome = dict(status="succeeded", supported=False, rehearsal=False,
                   demand_id="ft62-witness-demand", route_id="ft62-witness-training")
    rows = classifications_for(baseline, first_transactions, actor, 1, "independent", outcome)
    history = UseHistoryLedger(actor, "success-v1", baseline)
    history.observe(first_transactions, 1, rows)
    actual = first_episode["actual_elements"]
    unused = next(element for element, score in history.scores.items() if score == 0)
    candidates = (
        dict(identity="a-untrained", actor=actor, request_key="ft62-unused",
             eligible=True, priority=2, native_time=10, extra_energy=0,
             elements=(unused,) * len(actual)),
        dict(identity="z-trained", actor=actor, request_key="ft62-witness-chosen",
             eligible=True, priority=2, native_time=10, extra_energy=0, elements=actual),
    )
    choice = choose_candidate(candidates, history.checkpoint())
    choice_audit = audit_choice(choice, history.checkpoint())
    off = choose_candidate(candidates, history.checkpoint(), feedback=False)
    removed = UseHistoryLedger(actor, "success-v1", first_transactions)
    removed_choice = choose_candidate(candidates, removed.checkpoint())
    transactions, checkpoint, second_episode = finish("ft62-witness-chosen")
    binding = bind_choice(choice, transactions, checkpoint)
    binding_audit = audit_binding(choice, transactions, checkpoint, binding)
    episodes = [first_episode, second_episode]
    episode_audits = [audit_episode(first_transactions, first_checkpoint, first_episode),
                      audit_episode(transactions, checkpoint, second_episode)]
    for index in range(2, 6):
        current_transactions, current_checkpoint, episode = finish(f"ft62-witness-repeat-{index}")
        episodes.append(episode)
        episode_audits.append(audit_episode(current_transactions, current_checkpoint, episode))
    occupancy = measured_occupancy(episodes)
    occupancy_audit = audit_occupancy(episodes, occupancy)
    passed = (choice["chosen"]["identity"] == "z-trained"
              and off["chosen"]["identity"] == "a-untrained"
              and removed_choice["chosen"]["identity"] == "a-untrained"
              and choice_audit["passed"] and binding_audit["passed"]
              and all(row["passed"] for row in episode_audits)
              and occupancy["status"] == "unique" and occupancy_audit["passed"])
    return dict(passed=passed, trained_choice=choice["chosen"]["identity"],
        feedback_off_choice=off["chosen"]["identity"],
        history_removed_choice=removed_choice["chosen"]["identity"],
        actual_paid_binding=binding_audit, paid_n_episodes=len(episodes),
        episode_audits=episode_audits, occupancy=occupancy,
        occupancy_audit=occupancy_audit,
        claim="paid history changed an exact tie; controls removed the effect; six actual n traversals produced measured occupancy")


def main(out):
    out.mkdir(parents=True, exist_ok=False)
    before = freeze()
    (out / "source_freeze.json").write_text(json.dumps(before, indent=2) + "\n")
    registered = json.loads((ROOT / "contracts/ft/FT6_2_Source_Freeze_v1.json").read_text())
    protocol_path = ROOT / "contracts/ft/FT6_2_Protocol_v1.json"
    protocol = json.loads(protocol_path.read_text())
    protocol_hash = digest(protocol_path)
    registered_hash = (ROOT / "contracts/ft/FT6_2_Protocol_v1.sha256").read_text().split()[0]

    suite = unittest.defaultTestLoader.loadTestsFromName("tests_ft6.test_conditioning_feedback")
    actual = sorted(ids(suite))
    expected = sorted("tests_ft6.test_conditioning_feedback.ConditioningFeedbackTests." + method
                      for method in protocol["registered_tests"])
    (out / "method_ids.json").write_text(json.dumps(actual, indent=2) + "\n")
    with (out / "controls.log").open("w") as log:
        result = unittest.TextTestRunner(stream=log, verbosity=2).run(suite)

    modules = ["tests_ft6.test_use_history", "tests_ft5.test_reserve_grid",
        "tests_ft5.test_reserve_recovery", "tests_ft5.test_reserve_cycle",
        "tests_ft5.test_reserve_candidates", "tests_ft5.test_native_reserve",
        "tests_ft5.test_reserve"]
    from tools.evaluate_ft6_1 import FT4_ROWS
    modules += ["tests_ft4." + module for _, module, _ in FT4_ROWS]
    predecessor = sorted(ids(unittest.defaultTestLoader.loadTestsFromNames(modules)))
    predecessor_exact = predecessor == predecessor_expected() and len(predecessor) == 228
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
        predecessor_methods=len(predecessor), independent_causal_witness=witness["passed"],
        feedback_policies=3, paid_n_episodes=witness["paid_n_episodes"],
        occupancy=witness["occupancy"], source_unchanged=before == after,
        registered_freeze=before == registered, protocol_sha256=protocol_hash,
        protocol_hash_registered=protocol_hash == registered_hash,
        preserved_failures=(),
        scope="FT6.2 feedback and measured n-pair occupancy only; held-out stabilization and subtype interpretation remain open")
    (out / "summary.json").write_text(json.dumps(summary, indent=2) + "\n")
    (out / "evidence_hashes.json").write_text(json.dumps({
        path.name: digest(path) for path in sorted(out.iterdir()) if path.is_file()
    }, indent=2) + "\n")
    if not passed:
        raise SystemExit(1)


if __name__ == "__main__":
    if len(sys.argv) != 2:
        raise SystemExit("usage: evaluate_ft6_2.py OUTPUT_DIRECTORY")
    main(Path(sys.argv[1]))
