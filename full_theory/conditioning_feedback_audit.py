"""Independent FT6.2 feedback and paid n-episode reconstruction.

This auditor imports no FT6.2 runtime module.
"""
from collections import Counter
from copy import deepcopy
from hashlib import sha256

from hle.development_structure import portage
from hle_unified import codec
from hle_unified.axes import AXES, axis_cells
from hle_unified.conditioning_audit import ELEMENTS, completed_use
from hle_unified.selection_records import loads

from .use_history_audit import audit_use_history


def _int(value):
    if type(value) is not int or value < 0:
        raise ValueError("invalid exact integer")
    return value


def _text(value):
    if type(value) is not str or not value:
        raise ValueError("invalid identity")
    return value


def _row(row, actor):
    fields = {"identity", "actor", "request_key", "eligible", "priority",
              "native_time", "extra_energy", "elements"}
    if type(row) is not dict or set(row) != fields or row["actor"] != actor:
        raise ValueError("invalid candidate")
    if type(row["eligible"]) is not bool:
        raise ValueError("invalid eligibility")
    elements = tuple(row["elements"])
    if not elements or any(element not in ELEMENTS for element in elements):
        raise ValueError("invalid candidate elements")
    return dict(identity=_text(row["identity"]), actor=actor,
        request_key=_text(row["request_key"]), eligible=row["eligible"],
        priority=_int(row["priority"]), native_time=_int(row["native_time"]),
        extra_energy=_int(row["extra_energy"]), elements=elements)


def audit_choice(choice, history_checkpoint):
    history = loads(history_checkpoint)
    audit_use_history(history_checkpoint)
    fields = {"version", "feedback_enabled", "feedback_active", "history", "candidates",
              "prefeedback", "tie", "chosen", "chosen_feedback_score"}
    if (type(choice) is not dict or set(choice) != fields
            or choice["version"] != "ft-conditioning-choice-v1"
            or type(choice["feedback_enabled"]) is not bool):
        raise ValueError("invalid conditioned choice")
    binding = dict(actor=history["actor"], policy=history["policy"], tim=history["tim"],
        journal_count=history["journal_count"], journal_sha256=history["journal_sha256"],
        checkpoint_sha256=sha256(history_checkpoint.encode()).hexdigest())
    if choice["history"] != binding:
        raise ValueError("choice history binding differs")
    candidates = tuple(_row(row, history["actor"]) for row in choice["candidates"])
    if (not candidates or len({row["identity"] for row in candidates}) != len(candidates)):
        raise ValueError("invalid complete candidate set")
    eligible = [row for row in candidates if row["eligible"]]
    if not eligible:
        raise ValueError("no eligible candidate")
    priority = min(row["priority"] for row in eligible)
    eligible = [row for row in eligible if row["priority"] == priority]
    native_time = min(row["native_time"] for row in eligible)
    eligible = [row for row in eligible if row["native_time"] == native_time]
    extra_energy = min(row["extra_energy"] for row in eligible)
    expected_tie = [row for row in eligible if row["extra_energy"] == extra_energy]
    if choice["prefeedback"] != (priority, native_time, extra_energy):
        raise ValueError("pre-feedback coordinates differ")
    tie = choice["tie"]
    if type(tie) is not tuple or not tie:
        raise ValueError("empty pre-feedback tie")
    rows = []
    for item in tie:
        if type(item) is not dict or set(item) != {"candidate", "feedback_score"}:
            raise ValueError("invalid tie row")
        row = _row(item["candidate"], history["actor"])
        rows.append(row)
    if rows != expected_tie:
        raise ValueError("recorded tie differs from full candidate reconstruction")
    active = bool(choice["feedback_enabled"] and history["policy"] != "null")
    if choice["feedback_active"] != active:
        raise ValueError("feedback activation differs")
    evaluated = []
    for item, row in zip(tie, rows):
        score = sum(history["scores"][element] for element in row["elements"]) if active else 0
        if item["feedback_score"] != score:
            raise ValueError("feedback score differs from paid history")
        evaluated.append((score, row))
    top = max(score for score, _ in evaluated)
    expected = min((row for score, row in evaluated if score == top),
                   key=lambda row: row["identity"])
    if choice["chosen"] != expected or choice["chosen_feedback_score"] != top:
        raise ValueError("conditioned winner differs")
    return dict(passed=True, active=active, tie=len(rows), chosen=expected["identity"])


def _window(checkpoint, actor, key, means=None):
    data = loads(checkpoint)
    if data.get("version") != "ft-td5-route-policy-v1":
        raise ValueError("invalid route-policy checkpoint")
    attempts = [row for row in data["attempts"]
                if (row.get("actor"), row.get("key")) == (actor, key)]
    if len(attempts) != 1 or attempts[0].get("status") != "complete":
        raise ValueError("completed attempt missing")
    attempt = attempts[0]
    if means is not None and attempt["selected"]["name"] != means:
        raise ValueError("route mean differs")
    traversal = attempt.get("traversal")
    if type(traversal) is not dict or traversal.get("content_processed") is not True:
        raise ValueError("actual traversal missing")
    if any(row.get("index") != index for index, row in enumerate(data["events"])):
        raise ValueError("route events reordered")
    events = [row for row in data["events"]
              if (row.get("actor"), row.get("key")) == (actor, key)]
    if not events or events[-1].get("phase") != "complete" or events[-1].get("traversal") != traversal:
        raise ValueError("completed route event differs")
    return attempt, traversal, events[0]["before"], events[-1]["after"]


def _paid(transactions, actor, start, end):
    transactions = tuple(transactions)
    if not 0 <= start < end <= len(transactions):
        raise ValueError("invalid journal window")
    bp, bc = completed_use(transactions[:start]); ap, ac = completed_use(transactions[:end])
    if actor not in bp or actor not in ap or bp[actor] != ap[actor]:
        raise ValueError("actor/TIM differs")
    delta = {element: ac[actor][element] - bc[actor][element] for element in ELEMENTS}
    if any(type(value) is not int or value < 0 for value in delta.values()):
        raise ValueError("paid count decreased")
    elements = tuple(element for element in ELEMENTS for _ in range(delta[element]))
    if not elements:
        raise ValueError("no completed paid use")
    return bp[actor], delta, elements


def audit_binding(choice, transactions, route_checkpoint, binding):
    if binding.get("version") != "ft-conditioning-binding-v1":
        raise ValueError("invalid binding")
    h = choice["history"]; transactions = tuple(transactions)
    prefix = transactions[:h["journal_count"]]
    if sha256(codec.dumps(prefix).encode()).hexdigest() != h["journal_sha256"]:
        raise ValueError("execution does not extend history")
    chosen = choice["chosen"]
    attempt, traversal, start, end = _window(route_checkpoint, chosen["actor"], chosen["request_key"])
    tim, delta, elements = _paid(transactions, chosen["actor"], start, end)
    expected = dict(version="ft-conditioning-binding-v1", choice=deepcopy(chosen),
        history=deepcopy(h), tim=tim, journal_window=(start, end), actual_delta=delta,
        actual_elements=elements, means=attempt["selected"]["name"], traversal=deepcopy(traversal))
    if Counter(elements) != Counter(chosen["elements"]) or binding != expected:
        raise ValueError("claimed behavioral binding differs")
    return dict(passed=True, paid_elements=len(elements), request_key=chosen["request_key"])


def audit_episode(transactions, route_checkpoint, episode):
    fields = {"version", "actor", "request_key", "tim", "origin_seat", "target_seat",
        "n_pair", "axis_index", "dcnh_cell", "journal_window", "actual_delta",
        "actual_elements", "traversal", "completion_claim", "interpretation"}
    if type(episode) is not dict or set(episode) != fields or episode["version"] != "ft-paid-n-episode-v1":
        raise ValueError("invalid paid n episode")
    actor, key = episode["actor"], episode["request_key"]
    _, traversal, start, end = _window(route_checkpoint, actor, key, "n")
    tim, delta, elements = _paid(transactions, actor, start, end)
    origin, target = traversal["origin_seat"], traversal["target_seat"]
    pairs = tuple(tuple(sorted(axis)) for axis in AXES)
    pair = tuple(sorted((origin, target)))
    if target != portage(origin, "n") or pair not in pairs:
        raise ValueError("invalid n/DCNH geometry")
    index = pairs.index(pair)
    expected = dict(version="ft-paid-n-episode-v1", actor=actor, request_key=key,
        tim=tim, origin_seat=origin, target_seat=target, n_pair=pair,
        axis_index=index, dcnh_cell=axis_cells(tim)[index], journal_window=(start, end),
        actual_delta=delta, actual_elements=elements, traversal=deepcopy(traversal),
        completion_claim=False, interpretation="measured DCNH n-pair occupancy; not a subtype")
    if episode != expected:
        raise ValueError("paid n episode differs")
    return dict(passed=True, cell=expected["dcnh_cell"], paid_elements=len(elements))


def audit_occupancy(episodes, occupancy):
    episodes = tuple(episodes)[-6:]
    counts = {cell: sum(row.get("dcnh_cell") == cell for row in episodes) for cell in "DCNH"}
    if len(episodes) < 6:
        status, cell = "insufficient", None
    else:
        greatest = max(counts.values()); leaders = tuple(c for c in "DCNH" if counts[c] == greatest)
        if greatest >= 4 and len(leaders) == 1: status, cell = "unique", leaders[0]
        elif len(leaders) > 1: status, cell = "tie", None
        else: status, cell = "not_stabilized", None
    expected = dict(version="ft-measured-n-occupancy-v1", latest=len(episodes),
        required_latest=6, minimum=4, counts=counts, status=status, cell=cell,
        interpretation="measurement only; held-out persistence and subtype remain open")
    if occupancy != expected:
        raise ValueError("measured occupancy differs")
    return dict(passed=True, status=status, cell=cell, counts=counts)
