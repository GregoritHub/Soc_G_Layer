"""FT6.1 bounded use history over actual committed paid native work.

This opt-in observer does not affect route eligibility or selection.  FT6.2 is
responsible for any prospective tie-breaking integration.
"""
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


def _integer(value, name, low=None, high=None):
    if type(value) is not int:
        raise ValueError(name + " must be an exact integer")
    if low is not None and value < low:
        raise ValueError(name + " is below its domain")
    if high is not None and value > high:
        raise ValueError(name + " is above its domain")
    return value


def _identity(value, name):
    if type(value) is not str or not value:
        raise ValueError(name + " must be a nonempty string")
    return value


def _element_map(value, name, low=0, high=None):
    if type(value) is not dict or tuple(value) != ELEMENTS:
        raise ValueError(name + " must have the exact ordered element domain")
    return {element: _integer(value[element], name, low, high) for element in ELEMENTS}


def native_snapshot(transactions, actor):
    """Bind an actor's completed-use counts to one exact native journal prefix."""
    transactions = tuple(transactions)
    profiles, counts = completed_use(transactions)
    if actor not in profiles or actor not in counts:
        raise ValueError("actor is absent from paid-use observation")
    canonical = codec.dumps(transactions)
    return dict(actor=actor, tim=profiles[actor], journal_count=len(transactions),
                journal_sha256=sha256(canonical.encode()).hexdigest(),
                counts={element: counts[actor][element] for element in ELEMENTS})


def _validate_outcome(value, tag):
    required = {"status", "supported", "rehearsal", "demand_id", "route_id"}
    if type(value) is not dict or set(value) != required:
        raise ValueError("exact outcome classification required")
    status = value["status"]
    if status not in ("succeeded", "failed", "cancelled"):
        raise ValueError("unknown outcome status")
    if type(value["supported"]) is not bool or type(value["rehearsal"]) is not bool:
        raise ValueError("exact outcome booleans required")
    _identity(value["demand_id"], "demand identity")
    _identity(value["route_id"], "route identity")
    expected = {
        "independent": ("succeeded", False, False),
        "rehearsal": ("succeeded", False, True),
        "supported": ("succeeded", True, False),
    }
    if tag in expected:
        if (status, value["supported"], value["rehearsal"]) != expected[tag]:
            raise ValueError("outcome fields disagree with use tag")
    elif tag == "failed":
        if status not in ("failed", "cancelled") or value["rehearsal"]:
            raise ValueError("failed tag requires an unsuccessful non-rehearsal outcome")
    else:
        raise ValueError("unknown use tag")
    return deepcopy(value)


def classifications_for(transactions_before, transactions_after, actor, turn, tag, outcome):
    """Create exact semantic rows for a real positive paid-use delta."""
    turn = _integer(turn, "turn", 1)
    before = native_snapshot(transactions_before, actor)
    after_transactions = tuple(transactions_after)
    if len(after_transactions) < before["journal_count"]:
        raise ValueError("native journal shortened")
    prefix = native_snapshot(after_transactions[:before["journal_count"]], actor)
    if prefix != before:
        raise ValueError("native journal is not an exact extension")
    after = native_snapshot(after_transactions, actor)
    outcome = _validate_outcome(outcome, tag)
    rows = []
    for element in ELEMENTS:
        delta = after["counts"][element] - before["counts"][element]
        _integer(delta, "native completed-use delta", 0)
        for ordinal in range(delta):
            rows.append(dict(identity=f"{turn}:{element}:{ordinal}", element=element,
                             tag=tag, outcome=deepcopy(outcome)))
    if not rows:
        raise ValueError("classification cannot create a paid-use delta")
    return tuple(rows)


def _validate_classifications(rows, turn, deltas):
    if type(rows) not in (tuple, list):
        raise ValueError("classification sequence required")
    canonical = []
    expected = []
    for element in ELEMENTS:
        expected.extend((element, ordinal) for ordinal in range(deltas[element]))
    for index, row in enumerate(rows):
        if type(row) is not dict or set(row) != {"identity", "element", "tag", "outcome"}:
            raise ValueError("exact use classification fields required")
        element = row["element"]
        if element not in ELEMENTS:
            raise ValueError("unknown classified element")
        tag = row["tag"]
        if tag not in TAGS:
            raise ValueError("unknown use tag")
        canonical.append(dict(identity=_identity(row["identity"], "classification identity"),
                              element=element, tag=tag,
                              outcome=_validate_outcome(row["outcome"], tag)))
    canonical.sort(key=lambda row: (ELEMENTS.index(row["element"]), row["identity"]))
    observed = []
    for element in ELEMENTS:
        matches = [row for row in canonical if row["element"] == element]
        for ordinal, row in enumerate(matches):
            if row["identity"] != f"{turn}:{element}:{ordinal}":
                raise ValueError("classification identity does not bind turn and paid ordinal")
            observed.append((element, ordinal))
    if observed != expected:
        raise ValueError("classifications do not exactly exhaust native paid-use deltas")
    return tuple(canonical)


def _transition(policy, scores, idle, totals, classifications, deltas):
    scores = dict(scores); idle = dict(idle)
    totals = {element: dict(totals[element]) for element in ELEMENTS}
    credit = dict.fromkeys(ELEMENTS, 0); decay = dict.fromkeys(ELEMENTS, 0)
    for row in classifications:
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
                    scores[element] -= 1
                    decay[element] = -1
                idle[element] = 0
    return scores, idle, totals, credit, decay


def _chain(prior, body):
    return sha256((prior + dumps(body)).encode()).hexdigest()


class UseHistoryLedger:
    VERSION = "ft-bounded-use-history-v1"

    def __init__(self, actor, policy, transactions):
        if policy not in POLICIES:
            raise ValueError("unknown feedback policy")
        baseline = native_snapshot(transactions, actor)
        self.actor = actor; self.policy = policy; self.tim = baseline["tim"]
        self.turn = 0
        self.journal_count = baseline["journal_count"]
        self.journal_sha256 = baseline["journal_sha256"]
        self.native_counts = baseline["counts"]
        self.scores = dict.fromkeys(ELEMENTS, 0)
        self.idle = dict.fromkeys(ELEMENTS, 0)
        self.tag_totals = {element: dict.fromkeys(TAGS, 0) for element in ELEMENTS}
        genesis = dict(version=self.VERSION, actor=actor, policy=policy, baseline=baseline)
        self.chain_head = sha256(dumps(genesis).encode()).hexdigest()
        self.event_count = 0
        self.events = []
        self.base = self._base_state()

    def _base_state(self):
        return dict(turn=self.turn, journal_count=self.journal_count,
                    journal_sha256=self.journal_sha256,
                    native_counts=deepcopy(self.native_counts), scores=deepcopy(self.scores),
                    idle=deepcopy(self.idle), tag_totals=deepcopy(self.tag_totals),
                    event_count=self.event_count, chain_head=self.chain_head)

    def observe(self, transactions, turn, classifications=()):
        turn = _integer(turn, "turn", 1)
        if turn != self.turn + 1:
            raise ValueError("turn must advance exactly once")
        transactions = tuple(transactions)
        if len(transactions) < self.journal_count:
            raise ValueError("native journal shortened")
        prefix = native_snapshot(transactions[:self.journal_count], self.actor)
        if (prefix["journal_count"] != self.journal_count
                or prefix["journal_sha256"] != self.journal_sha256
                or prefix["counts"] != self.native_counts or prefix["tim"] != self.tim):
            raise ValueError("native journal does not preserve the observed prefix")
        current = native_snapshot(transactions, self.actor)
        if current["tim"] != self.tim:
            raise ValueError("TIM changed across conditioning history")
        deltas = {}
        for element in ELEMENTS:
            deltas[element] = current["counts"][element] - self.native_counts[element]
            _integer(deltas[element], "native completed-use delta", 0)
        rows = _validate_classifications(classifications, turn, deltas)
        scores, idle, totals, credit, decay = _transition(
            self.policy, self.scores, self.idle, self.tag_totals, rows, deltas)
        body = dict(index=self.event_count, turn=turn,
            journal_before=dict(count=self.journal_count, sha256=self.journal_sha256),
            journal_after=dict(count=current["journal_count"], sha256=current["journal_sha256"]),
            native_before=deepcopy(self.native_counts), native_after=deepcopy(current["counts"]),
            classifications=rows, scores_before=deepcopy(self.scores), scores_after=deepcopy(scores),
            idle_before=deepcopy(self.idle), idle_after=deepcopy(idle),
            tag_totals_before=deepcopy(self.tag_totals), tag_totals_after=deepcopy(totals),
            credit_delta=credit, decay_delta=decay, prior_chain=self.chain_head)
        event = dict(body, chain=_chain(self.chain_head, body))
        self.turn = turn; self.journal_count = current["journal_count"]
        self.journal_sha256 = current["journal_sha256"]
        self.native_counts = current["counts"]
        self.scores = scores; self.idle = idle; self.tag_totals = totals
        self.event_count += 1; self.chain_head = event["chain"]
        self.events.append(event)
        if len(self.events) > RECENT_LIMIT:
            self.events.pop(0)
            self.base = self._base_state_from_event(self.events[0])
        return deepcopy(event)

    @staticmethod
    def _base_state_from_event(first):
        return dict(turn=first["turn"] - 1,
                    journal_count=first["journal_before"]["count"],
                    journal_sha256=first["journal_before"]["sha256"],
                    native_counts=deepcopy(first["native_before"]),
                    scores=deepcopy(first["scores_before"]),
                    idle=deepcopy(first["idle_before"]),
                    tag_totals=deepcopy(first["tag_totals_before"]),
                    event_count=first["index"], chain_head=first["prior_chain"])

    def _state(self):
        return dict(version=self.VERSION, actor=self.actor, policy=self.policy,
            elements=ELEMENTS, score_cap=SCORE_CAP, decay_idle=DECAY_IDLE,
            recent_limit=RECENT_LIMIT, tim=self.tim, turn=self.turn,
            journal_count=self.journal_count, journal_sha256=self.journal_sha256,
            native_counts=self.native_counts, scores=self.scores, idle=self.idle,
            tag_totals=self.tag_totals, event_count=self.event_count,
            chain_head=self.chain_head, base=self.base, events=self.events)

    def checkpoint(self):
        return dumps(self._state())

    @classmethod
    def restore(cls, text):
        from .use_history_audit import audit_use_history
        data = loads(text)
        audit_use_history(text)
        result = cls.__new__(cls)
        for name in ("actor", "policy", "tim", "turn", "journal_count",
                     "journal_sha256", "native_counts", "scores", "idle",
                     "tag_totals", "event_count", "chain_head", "base", "events"):
            setattr(result, name, deepcopy(data[name]))
        if result.checkpoint() != text:
            raise ValueError("use-history checkpoint differs after restore")
        return result
