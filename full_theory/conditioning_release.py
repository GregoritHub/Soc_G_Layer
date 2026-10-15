"""FT6.3b engineering policy election over independently audited paid records.

This decision does not assign a subtype or change any runtime default.
"""
from collections import Counter


POLICIES = ("null", "success-v1", "success-decay-v1")
HISTORIES = ("independent-use", "no-use", "supported-use", "failed-use", "fixed-bias")


def occupancy(cells):
    cells = tuple(cells)
    if any(cell not in "DCNH" for cell in cells):
        raise ValueError("invalid measured cell")
    counts = {cell: cells.count(cell) for cell in "DCNH"}
    maximum = max(counts.values())
    leaders = [cell for cell in "DCNH" if counts[cell] == maximum]
    unique = len(cells) == 6 and maximum >= 4 and len(leaders) == 1
    return dict(latest=len(cells), counts=counts,
                cell=leaders[0] if unique else None, stabilized=unique)


def decide_conditioning_release(report, training, audit_receipt):
    if (audit_receipt.get("passed") is not True
            or audit_receipt.get("grid_sha256") != report["grid_sha256"]
            or audit_receipt.get("executions") != 228):
        raise ValueError("complete independently reconstructed grid required")
    if len(training) != 6 or any(e.get("version") != "ft-paid-n-episode-v1"
            or e.get("completion_claim") is not False for e in training):
        raise ValueError("six measured paid training episodes required")
    train = occupancy(e["dcnh_cell"] for e in training)
    rows = report["primary"]
    controls = {(r["policy"], r["demand_id"], r["kind"]): r for r in report["controls"]}
    outcomes = []
    for policy in POLICIES:
        for history in HISTORIES:
            cell = [r for r in rows if (r["policy"], r["history"]) == (policy, history)]
            if len(cell) != 12:
                raise ValueError("full policy/history denominator required")
            for r in cell:
                x = r["execution"]
                if (x["paid"] is not True or x["completed"] is not True
                        or x["means"] != "n" or x["route_audit"] is not True
                        or Counter(x["actual_elements"]) != Counter(r["choice"]["chosen"]["elements"])):
                    raise ValueError("completed bound paid n choice required")
            outcomes.append(dict(policy=policy, history=history,
                held_out=occupancy(r["execution"]["dcnh_cell"] for r in cell if r["phase"] == "held_out"),
                changed=occupancy(r["execution"]["dcnh_cell"] for r in cell if r["phase"] == "changed"),
                decisions=tuple((r["demand_id"], r["choice"]["chosen"]["identity"],
                                 r["execution"]["dcnh_cell"]) for r in cell)))
    gates = {}
    for policy in POLICIES[1:]:
        independent = [r for r in rows if r["policy"] == policy
                       and r["history"] == "independent-use" and r["phase"] == "held_out"]
        contrasts = tuple(r["demand_id"] for r in independent if all(
            r["choice"]["chosen"]["identity"] != controls[(policy, r["demand_id"], kind)]["choice"]["chosen"]["identity"]
            for kind in ("history-removal", "feedback-off")))
        held = next(o["held_out"] for o in outcomes
                    if o["policy"] == policy and o["history"] == "independent-use")
        stable = bool(train["stabilized"] and held["stabilized"] and train["cell"] == held["cell"])
        gates[policy] = dict(causal=bool(contrasts), discriminating_demands=contrasts,
                             held_out_persistence=stable, eligible=bool(contrasts) and stable)
    changed = {(r["policy"], r["demand_id"]): r for r in rows
               if r["history"] == "independent-use" and r["phase"] == "changed"}
    differences = tuple(demand for demand in ("C4", "C5") if
        changed[("success-v1", demand)]["choice"]["chosen"]["identity"] !=
        changed[("success-decay-v1", demand)]["choice"]["chosen"]["identity"])
    selected = ("success-decay-v1" if gates["success-decay-v1"]["eligible"] and differences
                else "success-v1" if gates["success-v1"]["eligible"] else "null")
    return dict(version="ft-conditioning-release-v1", grid_sha256=report["grid_sha256"],
        primary_records=180, control_records=48, training=train, outcomes=outcomes,
        policy_gates=gates, decay_distinct_demands=differences, selected_policy=selected,
        engineering_gate="accepted" if selected != "null" else "held",
        subtype_assignment=None, full_subtype_claim="held pending author interpretation",
        permanent_history_changed=False,
        scope="bounded engineering conditioning hypothesis; no psychology validation or C/D closure")
