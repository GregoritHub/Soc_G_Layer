"""FT6.3a matched conditioning grid over paid executor callbacks.

The grid never supplies success.  Its callback must execute the chosen request
and return independently auditable paid n evidence matching the frozen panel.
"""
from collections import Counter
from copy import deepcopy
from hashlib import sha256

from hle_unified.selection_records import dumps

from .conditioning_feedback import choose_candidate


POLICIES = ("null", "success-v1", "success-decay-v1")
HISTORIES = ("independent-use", "no-use", "supported-use", "failed-use", "fixed-bias")
PHASES = ("held_out", "changed")


def _exact_fixture(data):
    required = {"batch", "fixture_version", "tim", "actor", "setting",
        "demand_requirements", "candidate_class", "native_time", "extra_energy",
        "alternatives", "normal_identity_order", "fixed_bias_identity_order",
        "held_out_demands", "changed_demands", "policies", "history_regimes",
        "decay_intervention", "preflight_rule", "construction_boundary"}
    if type(data) is not dict or set(data) != required or data["batch"] != "FT6.3a":
        raise ValueError("exact FT6.3a fixture manifest required")
    if (tuple(data["policies"]) != POLICIES or tuple(data["history_regimes"]) != HISTORIES
            or tuple(data["alternatives"]) != ("N", "H")
            or len(data["held_out_demands"]) != 6 or len(data["changed_demands"]) != 6
            or len(set(data["held_out_demands"] + data["changed_demands"])) != 12):
        raise ValueError("fixed factorial domain differs")
    if (type(data["native_time"]) is not int or data["native_time"] < 1
            or type(data["extra_energy"]) is not int or data["extra_energy"] < 0):
        raise ValueError("invalid exact candidate costs")
    for cell in ("N", "H"):
        row = data["alternatives"][cell]
        fields = {"action", "face", "extra_target_disclosures", "route_mean",
            "origin_seat", "target_seat", "dcnh_cell", "movement_required",
            "actual_elements"}
        if (type(row) is not dict or set(row) != fields or row["dcnh_cell"] != cell
                or row["route_mean"] != "n" or row["movement_required"] != data["native_time"]
                or not row["actual_elements"]):
            raise ValueError("invalid frozen alternative")
    return deepcopy(data)


def _keys(policy, history):
    return policy + "|" + history


def _schedules(values, name):
    expected = {_keys(policy, history) for policy in POLICIES for history in HISTORIES}
    if type(values) is not dict or set(values) != expected:
        raise ValueError(name + " has wrong policy/history domain")
    for key, rows in values.items():
        if type(rows) is not tuple or len(rows) != 12 or any(type(row) is not str for row in rows):
            raise ValueError(name + " requires twelve exact checkpoints per cell")
    return values


def _candidates(fixture, actor, run_id, fixed=False):
    order = fixture["fixed_bias_identity_order"] if fixed else fixture["normal_identity_order"]
    rows = []
    for cell in ("N", "H"):
        alt = fixture["alternatives"][cell]
        rows.append(dict(identity=order[cell], actor=actor,
            request_key=run_id + ":" + cell, eligible=True,
            priority=fixture["candidate_class"], native_time=fixture["native_time"],
            extra_energy=fixture["extra_energy"], elements=tuple(alt["actual_elements"])))
    return tuple(rows)


def _execution(value, run_id, chosen, fixture):
    required = {"run_id", "candidate_identity", "request_key", "native_time",
        "extra_energy", "means", "dcnh_cell", "actual_elements", "paid",
        "completed", "route_audit", "journal_sha256", "route_checkpoint_sha256"}
    if type(value) is not dict or set(value) != required:
        raise ValueError("exact paid execution result required")
    if (value["run_id"] != run_id or value["candidate_identity"] != chosen["identity"]
            or value["request_key"] != chosen["request_key"]
            or value["native_time"] != chosen["native_time"]
            or value["extra_energy"] != chosen["extra_energy"]
            or value["means"] != "n" or value["dcnh_cell"] not in ("N", "H")
            or value["paid"] is not True or value["completed"] is not True
            or value["route_audit"] is not True):
        raise ValueError("chosen execution did not complete exact paid n work")
    elements = tuple(value["actual_elements"])
    if Counter(elements) != Counter(chosen["elements"]):
        raise ValueError("chosen execution differs from prospective element multiset")
    expected_cell = "H" if chosen["request_key"].endswith(":H") else "N"
    if value["dcnh_cell"] != expected_cell:
        raise ValueError("chosen execution differs from frozen DCNH fixture")
    if any(type(value[name]) is not str or len(value[name]) != 64
           for name in ("journal_sha256", "route_checkpoint_sha256")):
        raise ValueError("execution evidence hash missing")
    return deepcopy(dict(value, actual_elements=elements))


def _occupancy(rows):
    counts = {cell: sum(row["execution"]["dcnh_cell"] == cell for row in rows)
              for cell in "DCNH"}
    greatest = max(counts.values()) if rows else 0
    leaders = tuple(cell for cell in "DCNH" if counts[cell] == greatest)
    unique = leaders[0] if len(rows) == 6 and greatest >= 4 and len(leaders) == 1 else None
    return dict(counts=counts, status="unique" if unique else "tie" if len(leaders) > 1
                else "insufficient" if len(rows) < 6 else "not_stabilized", cell=unique)


def run_matched_grid(fixture, histories, removed_histories, executor):
    """Execute 180 primary cells and 48 exact causal controls."""
    fixture = _exact_fixture(fixture)
    histories = _schedules(histories, "history schedules")
    if type(removed_histories) is not dict or set(removed_histories) != set(POLICIES):
        raise ValueError("removed-history policy domain differs")
    for policy in POLICIES:
        rows = removed_histories[policy]
        if type(rows) is not tuple or len(rows) != 12:
            raise ValueError("removed history requires twelve checkpoints")
    if not callable(executor):
        raise ValueError("paid executor callback required")

    actor = None
    primary, controls = [], []
    schedules = (("held_out", fixture["held_out_demands"]),
                 ("changed", fixture["changed_demands"]))
    for policy in POLICIES:
        for history in HISTORIES:
            checkpoints = histories[_keys(policy, history)]
            for phase, demand_ids in schedules:
                for local_index, demand_id in enumerate(demand_ids):
                    index = local_index + (6 if phase == "changed" else 0)
                    from hle_unified.selection_records import loads
                    current = loads(checkpoints[index])
                    actor = current["actor"] if actor is None else actor
                    if current["actor"] != actor or current["policy"] != policy:
                        raise ValueError("history schedule actor/policy differs")
                    run_id = "P|" + policy + "|" + history + "|" + demand_id
                    candidates = _candidates(fixture, actor, run_id, history == "fixed-bias")
                    choice = choose_candidate(candidates, checkpoints[index],
                                              feedback=history != "fixed-bias")
                    execution = _execution(executor(run_id, choice["chosen"]),
                                           run_id, choice["chosen"], fixture)
                    primary.append(dict(run_id=run_id, policy=policy, history=history,
                        phase=phase, demand_id=demand_id, schedule_index=index,
                        history_checkpoint=checkpoints[index], choice=choice,
                        execution=execution))

                    if history == "independent-use" and policy != "null":
                        for kind, checkpoint, feedback in (
                                ("history-removal", removed_histories[policy][index], True),
                                ("feedback-off", checkpoints[index], False)):
                            control_id = ("R" if kind == "history-removal" else "O") + run_id[1:]
                            control_candidates = _candidates(fixture, actor, control_id)
                            control_choice = choose_candidate(
                                control_candidates, checkpoint, feedback=feedback)
                            control_execution = _execution(
                                executor(control_id, control_choice["chosen"]),
                                control_id, control_choice["chosen"], fixture)
                            controls.append(dict(run_id=control_id, kind=kind, policy=policy,
                                history=history, phase=phase, demand_id=demand_id,
                                schedule_index=index, history_checkpoint=checkpoint,
                                choice=control_choice, execution=control_execution))
    if len(primary) != 180 or len(controls) != 48:
        raise ValueError("matched grid denominator differs")
    summaries = []
    for policy in POLICIES:
        for history in HISTORIES:
            rows = [row for row in primary if row["policy"] == policy and row["history"] == history]
            held = [row for row in rows if row["phase"] == "held_out"]
            changed = [row for row in rows if row["phase"] == "changed"]
            summaries.append(dict(policy=policy, history=history,
                choices={cell: sum(row["execution"]["dcnh_cell"] == cell for row in rows)
                         for cell in ("N", "H")},
                held_out_occupancy=_occupancy(held), changed_occupancy=_occupancy(changed)))
    body = dict(version="ft-conditioning-grid-v1", fixture_sha256=sha256(dumps(fixture).encode()).hexdigest(),
        policies=POLICIES, histories=HISTORIES, primary=primary, controls=controls,
        summaries=summaries, primary_count=len(primary), control_count=len(controls),
        claim="matched paid executions; measured occupancy only; no subtype")
    body["grid_sha256"] = sha256(dumps(body).encode()).hexdigest()
    return body
