"""Independent FT6.3a reconstruction; imports no grid runtime module."""
from collections import Counter
from hashlib import sha256

from hle_unified import codec
from hle_unified.selection_records import dumps, loads

from .conditioning_feedback_audit import audit_choice, audit_episode
from .use_history_audit import audit_use_history


POLICIES = ("null", "success-v1", "success-decay-v1")
HISTORIES = ("independent-use", "no-use", "supported-use", "failed-use", "fixed-bias")


def _occupancy(rows):
    counts = {cell: sum(row["execution"]["dcnh_cell"] == cell for row in rows)
              for cell in "DCNH"}
    greatest = max(counts.values()) if rows else 0
    leaders = tuple(cell for cell in "DCNH" if counts[cell] == greatest)
    unique = leaders[0] if len(rows) == 6 and greatest >= 4 and len(leaders) == 1 else None
    return dict(counts=counts, status="unique" if unique else "tie" if len(leaders) > 1
                else "insufficient" if len(rows) < 6 else "not_stabilized", cell=unique)


def audit_conditioning_grid(report, fixture, histories, removed_histories, evidence):
    """Rebuild every factor, choice, paid episode, control and aggregate."""
    fields = {"version", "fixture_sha256", "policies", "histories", "primary",
              "controls", "summaries", "primary_count", "control_count", "claim",
              "grid_sha256"}
    if (type(report) is not dict or set(report) != fields
            or report["version"] != "ft-conditioning-grid-v1"
            or tuple(report["policies"]) != POLICIES
            or tuple(report["histories"]) != HISTORIES
            or report["primary_count"] != 180 or report["control_count"] != 48
            or len(report["primary"]) != 180 or len(report["controls"]) != 48):
        raise ValueError("invalid exact FT6.3a grid")
    body = {key: report[key] for key in report if key != "grid_sha256"}
    if report["grid_sha256"] != sha256(dumps(body).encode()).hexdigest():
        raise ValueError("grid hash differs")
    if report["fixture_sha256"] != sha256(dumps(fixture).encode()).hexdigest():
        raise ValueError("fixture hash differs")
    expected_primary, expected_controls = [], []
    demands = (("held_out", fixture["held_out_demands"]),
               ("changed", fixture["changed_demands"]))
    for policy in POLICIES:
        for history in HISTORIES:
            key = policy + "|" + history
            checkpoints = histories[key]
            for phase, demand_ids in demands:
                for local_index, demand_id in enumerate(demand_ids):
                    index = local_index + (6 if phase == "changed" else 0)
                    run_id = "P|" + policy + "|" + history + "|" + demand_id
                    expected_primary.append((run_id, policy, history, phase, demand_id,
                                             index, checkpoints[index], None))
                    if history == "independent-use" and policy != "null":
                        expected_controls.extend((
                            ("R" + run_id[1:], policy, history, phase, demand_id, index,
                             removed_histories[policy][index], "history-removal"),
                            ("O" + run_id[1:], policy, history, phase, demand_id, index,
                             checkpoints[index], "feedback-off")))
    observed = set()
    for row, expected in zip(report["primary"], expected_primary):
        _audit_row(row, expected, fixture, evidence, observed)
    for row, expected in zip(report["controls"], expected_controls):
        _audit_row(row, expected, fixture, evidence, observed)
    if set(evidence) != observed:
        raise ValueError("raw execution evidence domain differs")
    summaries = []
    for policy in POLICIES:
        for history in HISTORIES:
            rows = [row for row in report["primary"]
                    if row["policy"] == policy and row["history"] == history]
            summaries.append(dict(policy=policy, history=history,
                choices={cell: sum(row["execution"]["dcnh_cell"] == cell for row in rows)
                         for cell in ("N", "H")},
                held_out_occupancy=_occupancy([r for r in rows if r["phase"] == "held_out"]),
                changed_occupancy=_occupancy([r for r in rows if r["phase"] == "changed"])))
    if report["summaries"] != summaries:
        raise ValueError("occupancy summaries differ")
    independent = [r for r in report["primary"] if r["history"] == "independent-use"
                   and r["policy"] != "null"]
    controls = {(r["kind"], r["policy"], r["demand_id"]): r
                for r in report["controls"]}
    discriminating = 0
    for row in independent:
        trained = row["choice"]["chosen"]["identity"]
        removed = controls[("history-removal", row["policy"], row["demand_id"])]["choice"]["chosen"]["identity"]
        off = controls[("feedback-off", row["policy"], row["demand_id"])]["choice"]["chosen"]["identity"]
        if trained != removed and trained != off:
            discriminating += 1
    return dict(passed=True, primary=180, controls=48, executions=len(observed),
                discriminating=discriminating, grid_sha256=report["grid_sha256"])


def _audit_row(row, expected, fixture, evidence, observed):
    run_id, policy, history, phase, demand_id, index, checkpoint, kind = expected
    common = {"run_id", "policy", "history", "phase", "demand_id", "schedule_index",
              "history_checkpoint", "choice", "execution"}
    wanted = common | ({"kind"} if kind else set())
    if type(row) is not dict or set(row) != wanted:
        raise ValueError("grid row fields differ")
    if (row["run_id"], row["policy"], row["history"], row["phase"], row["demand_id"],
            row["schedule_index"], row["history_checkpoint"]) != (
            run_id, policy, history, phase, demand_id, index, checkpoint):
        raise ValueError("grid factor identity differs")
    if kind and row["kind"] != kind:
        raise ValueError("control kind differs")
    audit_use_history(checkpoint)
    audit_choice(row["choice"], checkpoint)
    choice = row["choice"]["chosen"]
    order = fixture["fixed_bias_identity_order"] if history == "fixed-bias" else fixture["normal_identity_order"]
    expected_ids = {order[cell] for cell in ("N", "H")}
    if {candidate["identity"] for candidate in row["choice"]["candidates"]} != expected_ids:
        raise ValueError("candidate stable identity order differs")
    value = row["execution"]
    if (value["run_id"] != run_id or value["candidate_identity"] != choice["identity"]
            or value["request_key"] != choice["request_key"] or value["means"] != "n"
            or value["native_time"] != fixture["native_time"]
            or value["extra_energy"] != fixture["extra_energy"]
            or not value["paid"] or not value["completed"] or not value["route_audit"]):
        raise ValueError("execution binding differs")
    raw = evidence.get(run_id)
    if type(raw) is not tuple or len(raw) != 3:
        raise ValueError("one raw paid witness required")
    transactions, route_checkpoint, episode = raw
    episode_audit = audit_episode(transactions, route_checkpoint, episode)
    traversal = episode["traversal"]
    movement = traversal.get("movement")
    if (type(movement) is not dict
            or tuple(movement.get(name) for name in ("required", "completed", "spent")) != (55, 55, 55)):
        raise ValueError("exact matched movement differs")
    if (episode["request_key"] != choice["request_key"]
            or episode_audit["cell"] != value["dcnh_cell"]
            or tuple(episode["actual_elements"]) != tuple(value["actual_elements"])
            or Counter(episode["actual_elements"]) != Counter(choice["elements"])
            or sha256(codec.dumps(tuple(transactions)).encode()).hexdigest() != value["journal_sha256"]
            or sha256(route_checkpoint.encode()).hexdigest() != value["route_checkpoint_sha256"]):
        raise ValueError("raw paid execution differs")
    observed.add(run_id)
