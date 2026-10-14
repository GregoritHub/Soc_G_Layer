"""FT6.3b independent training and release reconstruction.

Imports no release decision, chooser, executor or scheduler.
"""
from collections import Counter
from hashlib import sha256

from hle_unified import codec
from hle_unified.conditioning_audit import ELEMENTS, completed_use
from hle_unified.selection_records import loads
from .conditioning_feedback_audit import audit_episode
from .use_history_audit import audit_use_history


def audit_training(baseline, records, checkpoint):
    audit_use_history(checkpoint)
    data = loads(checkpoint)
    if data["turn"] != 6 or len(data["events"]) != 6 or len(records) != 6:
        raise ValueError("exact six-event training boundary required")
    before = tuple(baseline)
    cells = []
    for index, (record, event) in enumerate(zip(records, data["events"]), 1):
        transactions, route_checkpoint, episode = record
        transactions = tuple(transactions)
        result = audit_episode(transactions, route_checkpoint, episode)
        if (episode["request_key"] != "ft63-training-" + str(index)
                or episode["actor"] != data["actor"] or episode["tim"] != data["tim"]
                or transactions[:len(before)] != before):
            raise ValueError("training replay identity or journal prefix differs")
        for source, binding in ((before, event["journal_before"]),
                                (transactions, event["journal_after"])):
            if binding != dict(count=len(source), sha256=sha256(codec.dumps(source).encode()).hexdigest()):
                raise ValueError("saved history event differs from paid replay")
        _, native_before = completed_use(before)
        _, native_after = completed_use(transactions)
        for element in ELEMENTS:
            if (event["native_before"][element] != native_before[data["actor"]][element]
                    or event["native_after"][element] != native_after[data["actor"]][element]):
                raise ValueError("saved paid training delta differs")
        if any(row["tag"] != "independent" for row in event["classifications"]):
            raise ValueError("independent training classification required")
        cells.append(result["cell"])
        before = transactions
    audit_use_history(checkpoint, before)
    return dict(passed=True, episodes=6, cells=tuple(cells), paid_history_bound=True,
                actor=data["actor"], tim=data["tim"])


def audit_release(report, episodes, decision, receipt):
    if (receipt.get("passed") is not True or receipt.get("executions") != 228
            or receipt.get("grid_sha256") != report["grid_sha256"]):
        raise ValueError("independent grid reconstruction missing")
    def measured(cells):
        cells = tuple(cells)
        if any(cell not in "DCNH" for cell in cells):
            raise ValueError("invalid measured cell")
        counts = {c: sum(x == c for x in cells) for c in "DCNH"}
        winners = [c for c in "DCNH" if counts[c] == max(counts.values())]
        ok = len(cells) == 6 and len(winners) == 1 and counts[winners[0]] >= 4
        return dict(latest=len(cells), counts=counts, cell=winners[0] if ok else None, stabilized=ok)
    if len(episodes) != 6 or any(e.get("version") != "ft-paid-n-episode-v1"
            or e.get("completion_claim") is not False for e in episodes):
        raise ValueError("exact measured training evidence missing")
    train = measured(e["dcnh_cell"] for e in episodes)
    outcomes = []
    for policy in ("null", "success-v1", "success-decay-v1"):
        for history in ("independent-use", "no-use", "supported-use", "failed-use", "fixed-bias"):
            rows = [r for r in report["primary"] if r["policy"] == policy and r["history"] == history]
            if len(rows) != 12:
                raise ValueError("release denominator mismatch")
            for r in rows:
                x = r["execution"]
                if (x["paid"] is not True or x["completed"] is not True or x["means"] != "n"
                        or x["route_audit"] is not True
                        or Counter(x["actual_elements"]) != Counter(r["choice"]["chosen"]["elements"])):
                    raise ValueError("unpaid or unbound decision")
            outcomes.append(dict(policy=policy, history=history,
                held_out=measured(r["execution"]["dcnh_cell"] for r in rows if r["phase"] == "held_out"),
                changed=measured(r["execution"]["dcnh_cell"] for r in rows if r["phase"] == "changed"),
                decisions=tuple((r["demand_id"], r["choice"]["chosen"]["identity"], r["execution"]["dcnh_cell"]) for r in rows)))
    gates = {}
    for policy in ("success-v1", "success-decay-v1"):
        contrasts = []
        for row in report["primary"]:
            if (row["policy"], row["history"], row["phase"]) != (policy, "independent-use", "held_out"):
                continue
            witnesses = [r for r in report["controls"] if r["policy"] == policy and r["demand_id"] == row["demand_id"]]
            if len(witnesses) != 2 or {r["kind"] for r in witnesses} != {"history-removal", "feedback-off"}:
                raise ValueError("exact causal witnesses missing")
            if all(r["choice"]["chosen"]["identity"] != row["choice"]["chosen"]["identity"] for r in witnesses):
                contrasts.append(row["demand_id"])
        held = [x["held_out"] for x in outcomes if x["policy"] == policy and x["history"] == "independent-use"][0]
        stable = train["stabilized"] and held["stabilized"] and train["cell"] == held["cell"]
        gates[policy] = dict(causal=bool(contrasts), discriminating_demands=tuple(contrasts),
                             held_out_persistence=bool(stable), eligible=bool(contrasts) and bool(stable))
    differences = []
    for demand in ("C4", "C5"):
        choices = {r["policy"]: r["choice"]["chosen"]["identity"] for r in report["primary"]
                   if r["history"] == "independent-use" and r["demand_id"] == demand}
        if choices["success-v1"] != choices["success-decay-v1"]:
            differences.append(demand)
    policy = "null"
    if gates["success-decay-v1"]["eligible"] and differences:
        policy = "success-decay-v1"
    elif gates["success-v1"]["eligible"]:
        policy = "success-v1"
    expected = dict(version="ft-conditioning-release-v1", grid_sha256=report["grid_sha256"],
        primary_records=180, control_records=48, training=train, outcomes=outcomes,
        policy_gates=gates, decay_distinct_demands=tuple(differences), selected_policy=policy,
        engineering_gate="accepted" if policy != "null" else "held",
        subtype_assignment=None, full_subtype_claim="held pending author interpretation",
        permanent_history_changed=False,
        scope="bounded engineering conditioning hypothesis; no psychology validation or C/D closure")
    if decision != expected:
        raise ValueError("prospective release decision differs")
    return dict(passed=True, selected_policy=policy, engineering_gate=expected["engineering_gate"],
                independently_reconstructed=True)
