"""FT6.2 opt-in history tie-breaks and measured paid n episodes.

Feedback acts only inside an already admitted TD5 priority/cost tie.  DCNH
labels below are observations of completed n-pair traffic, never subtypes.
"""
from collections import Counter
from copy import deepcopy
from hashlib import sha256

from hle.development_structure import portage
from hle_unified import codec
from hle_unified.axes import AXES, axis_cells
from hle_unified.conditioning_audit import ELEMENTS, completed_use
from hle_unified.selection_records import dumps, loads

from .use_history_audit import audit_use_history


POLICIES = ("null", "success-v1", "success-decay-v1")
LATEST_EPISODES = 6
OCCUPANCY_MINIMUM = 4


def _integer(value, name, low=0):
    if type(value) is not int or value < low:
        raise ValueError(name + " must be an exact bounded integer")
    return value


def _identity(value, name):
    if type(value) is not str or not value:
        raise ValueError(name + " must be a nonempty string")
    return value


def _candidate(row, actor):
    required = {"identity", "actor", "request_key", "eligible", "priority",
                "native_time", "extra_energy", "elements"}
    if type(row) is not dict or set(row) != required:
        raise ValueError("exact conditioned candidate fields required")
    if row["actor"] != actor:
        raise ValueError("candidate actor differs from history actor")
    if type(row["eligible"]) is not bool:
        raise ValueError("candidate eligibility must be exact boolean")
    elements = tuple(row["elements"])
    if not elements or any(element not in ELEMENTS for element in elements):
        raise ValueError("candidate requires a nonempty ordered native element sequence")
    return dict(identity=_identity(row["identity"], "candidate identity"), actor=actor,
        request_key=_identity(row["request_key"], "request key"), eligible=row["eligible"],
        priority=_integer(row["priority"], "priority"),
        native_time=_integer(row["native_time"], "native time"),
        extra_energy=_integer(row["extra_energy"], "extra energy"),
        elements=elements)


def choose_candidate(candidates, history_checkpoint, *, feedback=True):
    """Choose deterministically without changing admission, class, or cost."""
    if type(feedback) is not bool:
        raise ValueError("feedback flag must be exact boolean")
    history = loads(history_checkpoint)
    audit_use_history(history_checkpoint)
    actor, policy = history["actor"], history["policy"]
    rows = tuple(_candidate(row, actor) for row in candidates)
    if not rows or len({row["identity"] for row in rows}) != len(rows):
        raise ValueError("nonempty candidates require unique stable identities")
    eligible = [row for row in rows if row["eligible"]]
    if not eligible:
        raise ValueError("no eligible conditioned candidate")
    best_priority = min(row["priority"] for row in eligible)
    eligible = [row for row in eligible if row["priority"] == best_priority]
    best_time = min(row["native_time"] for row in eligible)
    eligible = [row for row in eligible if row["native_time"] == best_time]
    best_energy = min(row["extra_energy"] for row in eligible)
    tied = [row for row in eligible if row["extra_energy"] == best_energy]
    scores = history["scores"]
    active = bool(feedback and policy != "null")
    evaluated = []
    for row in tied:
        score = sum(scores[element] for element in row["elements"]) if active else 0
        evaluated.append(dict(candidate=deepcopy(row), feedback_score=score))
    top = max(row["feedback_score"] for row in evaluated)
    finalists = [row for row in evaluated if row["feedback_score"] == top]
    chosen = min(finalists, key=lambda row: row["candidate"]["identity"])
    history_binding = dict(actor=actor, policy=policy, tim=history["tim"],
        journal_count=history["journal_count"], journal_sha256=history["journal_sha256"],
        checkpoint_sha256=sha256(history_checkpoint.encode()).hexdigest())
    return dict(version="ft-conditioning-choice-v1", feedback_enabled=feedback,
        feedback_active=active, history=history_binding,
        candidates=tuple(deepcopy(rows)),
        prefeedback=(best_priority, best_time, best_energy),
        tie=tuple(evaluated), chosen=deepcopy(chosen["candidate"]),
        chosen_feedback_score=chosen["feedback_score"])


def _counts(transactions, actor, start, end):
    if not 0 <= start < end <= len(transactions):
        raise ValueError("invalid native evidence window")
    before_profiles, before_counts = completed_use(transactions[:start])
    after_profiles, after_counts = completed_use(transactions[:end])
    if (actor not in before_profiles or actor not in after_profiles
            or before_profiles[actor] != after_profiles[actor]):
        raise ValueError("actor/TIM differs across native evidence window")
    delta = {element: after_counts[actor][element] - before_counts[actor][element]
             for element in ELEMENTS}
    if any(type(value) is not int or value < 0 for value in delta.values()):
        raise ValueError("native completed-use count decreased")
    elements = tuple(element for element in ELEMENTS for _ in range(delta[element]))
    if not elements:
        raise ValueError("claimed behavior lacks completed paid native processing")
    return before_profiles[actor], delta, elements


def _completed_window(checkpoint, actor, request_key, means=None):
    data = loads(checkpoint)
    if (type(data) is not dict or data.get("version") != "ft-td5-route-policy-v1"
            or type(data.get("attempts")) is not list or type(data.get("events")) is not list):
        raise ValueError("exact route-policy checkpoint required")
    matches = [row for row in data["attempts"]
               if (row.get("actor"), row.get("key")) == (actor, request_key)]
    if len(matches) != 1 or matches[0].get("status") != "complete":
        raise ValueError("one completed chosen route attempt required")
    attempt = matches[0]
    if means is not None and attempt.get("selected", {}).get("name") != means:
        raise ValueError("route mean differs from claimed behavior")
    traversal = attempt.get("traversal")
    if type(traversal) is not dict or traversal.get("content_processed") is not True:
        raise ValueError("completed traversal with actual content processing required")
    events = [row for row in data["events"]
              if (row.get("actor"), row.get("key")) == (actor, request_key)]
    if (not events or any(row.get("index") != index for index, row in enumerate(data["events"]))
            or events[-1].get("phase") != "complete"
            or events[-1].get("traversal") != traversal):
        raise ValueError("route event evidence differs from completed traversal")
    return attempt, traversal, events[0]["before"], events[-1]["after"]


def bind_choice(choice, transactions, route_checkpoint):
    """Bind a prospective choice to its later real paid completion."""
    if type(choice) is not dict or choice.get("version") != "ft-conditioning-choice-v1":
        raise ValueError("exact conditioned choice required")
    transactions = tuple(transactions)
    history = choice["history"]
    prefix = transactions[:history["journal_count"]]
    if (len(prefix) != history["journal_count"]
            or sha256(codec.dumps(prefix).encode()).hexdigest() != history["journal_sha256"]):
        raise ValueError("chosen execution does not extend its exact history")
    chosen = choice["chosen"]
    attempt, traversal, start, end = _completed_window(
        route_checkpoint, chosen["actor"], chosen["request_key"])
    tim, delta, elements = _counts(transactions, chosen["actor"], start, end)
    if Counter(elements) != Counter(chosen["elements"]):
        raise ValueError("chosen declared elements differ from actual paid completion")
    return dict(version="ft-conditioning-binding-v1", choice=deepcopy(chosen),
        history=deepcopy(history), tim=tim, journal_window=(start, end),
        actual_delta=delta, actual_elements=elements,
        means=attempt["selected"]["name"], traversal=deepcopy(traversal))


def compensation_episode(transactions, route_checkpoint, actor, request_key):
    """Reconstruct one completed paid n episode and its inherited DCNH cell."""
    transactions = tuple(transactions)
    attempt, traversal, start, end = _completed_window(
        route_checkpoint, actor, request_key, "n")
    tim, delta, elements = _counts(transactions, actor, start, end)
    origin, target = traversal["origin_seat"], traversal["target_seat"]
    if target != portage(origin, "n"):
        raise ValueError("traversal is not inherited n geometry")
    pair = tuple(sorted((origin, target)))
    pairs = tuple(tuple(sorted(axis)) for axis in AXES)
    if pair not in pairs:
        raise ValueError("n pair is absent from inherited DCNH axes")
    axis_index = pairs.index(pair)
    return dict(version="ft-paid-n-episode-v1", actor=actor, request_key=request_key,
        tim=tim, origin_seat=origin, target_seat=target, n_pair=pair,
        axis_index=axis_index, dcnh_cell=axis_cells(tim)[axis_index],
        journal_window=(start, end), actual_delta=delta, actual_elements=elements,
        traversal=deepcopy(traversal), completion_claim=False,
        interpretation="measured DCNH n-pair occupancy; not a subtype")


def measured_occupancy(episodes):
    episodes = tuple(episodes)[-LATEST_EPISODES:]
    if any(type(row) is not dict or row.get("version") != "ft-paid-n-episode-v1"
           or row.get("dcnh_cell") not in "DCNH" for row in episodes):
        raise ValueError("exact paid n episodes required")
    counts = {cell: sum(row["dcnh_cell"] == cell for row in episodes) for cell in "DCNH"}
    if len(episodes) < LATEST_EPISODES:
        status, cell = "insufficient", None
    else:
        greatest = max(counts.values())
        leaders = tuple(cell for cell in "DCNH" if counts[cell] == greatest)
        if greatest >= OCCUPANCY_MINIMUM and len(leaders) == 1:
            status, cell = "unique", leaders[0]
        elif len(leaders) > 1:
            status, cell = "tie", None
        else:
            status, cell = "not_stabilized", None
    return dict(version="ft-measured-n-occupancy-v1", latest=len(episodes),
        required_latest=LATEST_EPISODES, minimum=OCCUPANCY_MINIMUM,
        counts=counts, status=status, cell=cell,
        interpretation="measurement only; held-out persistence and subtype remain open")
