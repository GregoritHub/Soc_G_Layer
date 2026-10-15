"""Independent FT6.1 use-history reconstruction; imports no FT6 runtime."""
from copy import deepcopy
from hashlib import sha256

from hle_unified import codec
from hle_unified.conditioning_audit import ELEMENTS, completed_use
from hle_unified.selection_records import dumps, loads


POLICIES = ("null", "success-v1", "success-decay-v1")
TAGS = ("independent", "rehearsal", "supported", "failed")
SCORE_CAP = 8
DECAY_IDLE = 4
RECENT_LIMIT = 32


def _integer(value, low=None, high=None):
    if type(value) is not int or (low is not None and value < low) or (high is not None and value > high):
        raise ValueError("invalid exact integer")
    return value


def _maps(data, name, high=None):
    if type(data) is not dict or set(data) != set(ELEMENTS):
        raise ValueError(name + " has wrong element domain")
    return {element: _integer(data[element], 0, high) for element in ELEMENTS}


def _totals(data):
    if type(data) is not dict or set(data) != set(ELEMENTS):
        raise ValueError("tag totals have wrong element domain")
    result = {}
    for element in ELEMENTS:
        row = data[element]
        if type(row) is not dict or set(row) != set(TAGS):
            raise ValueError("tag totals have wrong tag domain")
        result[element] = {tag: _integer(row[tag], 0) for tag in TAGS}
    return result


def _outcome(value, tag):
    required = {"status", "supported", "rehearsal", "demand_id", "route_id"}
    if type(value) is not dict or set(value) != required:
        raise ValueError("invalid outcome")
    if (type(value["supported"]) is not bool or type(value["rehearsal"]) is not bool
            or type(value["demand_id"]) is not str or not value["demand_id"]
            or type(value["route_id"]) is not str or not value["route_id"]):
        raise ValueError("invalid outcome fields")
    observed = (value["status"], value["supported"], value["rehearsal"])
    expected = {"independent": ("succeeded", False, False),
                "rehearsal": ("succeeded", False, True),
                "supported": ("succeeded", True, False)}
    if tag in expected and observed != expected[tag]:
        raise ValueError("tag/outcome mismatch")
    if tag == "failed" and (value["status"] not in ("failed", "cancelled") or value["rehearsal"]):
        raise ValueError("invalid failed outcome")


def _chain(prior, body):
    return sha256((prior + dumps(body)).encode()).hexdigest()


def _transition(policy, scores, idle, totals, rows, deltas):
    scores = dict(scores); idle = dict(idle)
    totals = {element: dict(totals[element]) for element in ELEMENTS}
    credit = dict.fromkeys(ELEMENTS, 0); decay = dict.fromkeys(ELEMENTS, 0)
    for row in rows:
        totals[row["element"]][row["tag"]] += 1
        if row["tag"] == "independent" and policy != "null":
            before = scores[row["element"]]
            scores[row["element"]] = min(SCORE_CAP, before + 1)
            credit[row["element"]] += scores[row["element"]] - before
    for element in ELEMENTS:
        if deltas[element]:
            idle[element] = 0
        else:
            idle[element] += 1
            if idle[element] == DECAY_IDLE:
                if policy == "success-decay-v1" and scores[element] > 0:
                    scores[element] -= 1; decay[element] = -1
                idle[element] = 0
    return scores, idle, totals, credit, decay


def audit_use_history(checkpoint, transactions=None):
    data = loads(checkpoint)
    required = {"version", "actor", "policy", "elements", "score_cap", "decay_idle",
                "recent_limit", "tim", "turn", "journal_count", "journal_sha256",
                "native_counts", "scores", "idle", "tag_totals", "event_count",
                "chain_head", "base", "events"}
    if (type(data) is not dict or set(data) != required
            or data["version"] != "ft-bounded-use-history-v1"
            or data["policy"] not in POLICIES or data["elements"] != ELEMENTS
            or data["score_cap"] != SCORE_CAP or data["decay_idle"] != DECAY_IDLE
            or data["recent_limit"] != RECENT_LIMIT):
        raise ValueError("invalid FT6.1 checkpoint contract")
    if type(data["tim"]) is not str or not data["tim"]:
        raise ValueError("invalid immutable TIM")
    base_required = {"turn", "journal_count", "journal_sha256", "native_counts",
                     "scores", "idle", "tag_totals", "event_count", "chain_head"}
    base = data["base"]
    if type(base) is not dict or set(base) != base_required:
        raise ValueError("invalid retained base")
    state = dict(turn=_integer(base["turn"], 0),
                 journal_count=_integer(base["journal_count"], 0),
                 journal_sha256=base["journal_sha256"],
                 native_counts=_maps(base["native_counts"], "base native counts"),
                 scores=_maps(base["scores"], "base scores", SCORE_CAP),
                 idle=_maps(base["idle"], "base idle", DECAY_IDLE - 1),
                 tag_totals=_totals(base["tag_totals"]),
                 event_count=_integer(base["event_count"], 0),
                 chain_head=base["chain_head"])
    if any(type(state[key]) is not str or len(state[key]) != 64
           for key in ("journal_sha256", "chain_head")):
        raise ValueError("invalid base hashes")
    events = data["events"]
    if type(events) is not list or len(events) > RECENT_LIMIT:
        raise ValueError("recent window is not bounded")
    event_fields = {"index", "turn", "journal_before", "journal_after",
        "native_before", "native_after", "classifications", "scores_before",
        "scores_after", "idle_before", "idle_after", "tag_totals_before",
        "tag_totals_after", "credit_delta", "decay_delta", "prior_chain", "chain"}
    for event in events:
        if type(event) is not dict or set(event) != event_fields:
            raise ValueError("invalid turn event fields")
        if (event["index"] != state["event_count"]
                or event["turn"] != state["turn"] + 1
                or event["journal_before"] != {"count": state["journal_count"],
                                                 "sha256": state["journal_sha256"]}
                or event["native_before"] != state["native_counts"]
                or event["scores_before"] != state["scores"]
                or event["idle_before"] != state["idle"]
                or event["tag_totals_before"] != state["tag_totals"]
                or event["prior_chain"] != state["chain_head"]):
            raise ValueError("turn prior state differs")
        after = event["journal_after"]
        if (type(after) is not dict or set(after) != {"count", "sha256"}
                or _integer(after["count"], state["journal_count"]) != after["count"]
                or type(after["sha256"]) is not str or len(after["sha256"]) != 64):
            raise ValueError("invalid journal successor")
        native_after = _maps(event["native_after"], "native successor")
        deltas = {element: native_after[element] - state["native_counts"][element]
                  for element in ELEMENTS}
        if any(type(value) is not int or value < 0 for value in deltas.values()):
            raise ValueError("native count decreased")
        rows = event["classifications"]
        if type(rows) is not tuple:
            raise ValueError("canonical classification tuple required")
        observed = []
        for row in rows:
            if (type(row) is not dict or set(row) != {"identity", "element", "tag", "outcome"}
                    or row["element"] not in ELEMENTS or row["tag"] not in TAGS):
                raise ValueError("invalid classification")
            _outcome(row["outcome"], row["tag"])
            observed.append(row)
        if list(rows) != sorted(rows, key=lambda row: (ELEMENTS.index(row["element"]), row["identity"])):
            raise ValueError("classifications not canonical")
        for element in ELEMENTS:
            matches = [row for row in rows if row["element"] == element]
            if len(matches) != deltas[element]:
                raise ValueError("classification count differs from paid delta")
            for ordinal, row in enumerate(matches):
                if row["identity"] != f'{event["turn"]}:{element}:{ordinal}':
                    raise ValueError("classification identity differs")
        scores, idle, totals, credit, decay = _transition(
            data["policy"], state["scores"], state["idle"], state["tag_totals"], rows, deltas)
        if (event["scores_after"] != scores or event["idle_after"] != idle
                or event["tag_totals_after"] != totals or event["credit_delta"] != credit
                or event["decay_delta"] != decay):
            raise ValueError("derived history transition differs")
        body = {key: event[key] for key in event if key != "chain"}
        if event["chain"] != _chain(state["chain_head"], body):
            raise ValueError("history evidence chain differs")
        state = dict(turn=event["turn"], journal_count=after["count"],
            journal_sha256=after["sha256"], native_counts=native_after,
            scores=scores, idle=idle, tag_totals=totals,
            event_count=state["event_count"] + 1, chain_head=event["chain"])
    for key in ("turn", "journal_count", "journal_sha256", "native_counts", "scores",
                "idle", "tag_totals", "event_count", "chain_head"):
        if data[key] != state[key]:
            raise ValueError("checkpoint terminal state differs: " + key)
    if data["event_count"] - len(events) != base["event_count"]:
        raise ValueError("bounded window/base count differs")
    if transactions is not None:
        transactions = tuple(transactions)
        profiles, counts = completed_use(transactions)
        if data["actor"] not in profiles or profiles[data["actor"]] != data["tim"]:
            raise ValueError("final native actor/TIM differs")
        expected_counts = {element: counts[data["actor"]][element] for element in ELEMENTS}
        expected_hash = sha256(codec.dumps(transactions).encode()).hexdigest()
        if (len(transactions) != data["journal_count"]
                or expected_hash != data["journal_sha256"]
                or expected_counts != data["native_counts"]):
            raise ValueError("final raw native evidence differs")
    return dict(passed=True, policy=data["policy"], turns=data["turn"],
                events=data["event_count"], retained_events=len(events),
                scores=deepcopy(data["scores"]), totals=deepcopy(data["tag_totals"]),
                native_bound=transactions is not None,
                scope="FT6.1 accounting only; route feedback and subtype remain open")
