"""Exact FT5.1 reserve state and accounting, without native integration.

Reserve is deliberately not a wallet, charge, elapsed time, access rule, or
route permission.  FT5.2 must bind preparation and replenishment receipts to
actual native work before an integrated causal claim is available.
"""
from copy import deepcopy

from hle_unified.selection_records import dumps, loads


POLICIES = ("null", "load-v1", "grade-load-v1")
CAPACITY = 8
DEFAULT_INITIAL = 4


def _integer(value, name, minimum=None, maximum=None):
    if type(value) is not int:
        raise ValueError(name + " must be an exact integer")
    if minimum is not None and value < minimum:
        raise ValueError(name + " is below its domain")
    if maximum is not None and value > maximum:
        raise ValueError(name + " is above its domain")
    return value


def _identity(value, name):
    if type(value) is not str or not value:
        raise ValueError(name + " must be a nonempty string identity")
    return value


def _receipt(value, actor, token_id):
    required = {"identity", "actor", "token_id", "source", "seat", "status", "paid"}
    if type(value) is not dict or set(value) != required:
        raise ValueError("exact provisional replenishment receipt required")
    if (_identity(value["identity"], "receipt identity") != value["identity"]
            or value["actor"] != actor or value["token_id"] != token_id
            or value["source"] != "external" or value["seat"] != 5
            or value["status"] != "succeeded" or value["paid"] is not True):
        raise ValueError("receipt does not name external paid A5 uptake")
    return deepcopy(value)


def preparation(policy, reserve, load):
    if policy not in POLICIES:
        raise ValueError("unknown reserve policy")
    _integer(reserve, "reserve", 0, CAPACITY)
    _integer(load, "load", 0)
    return 0 if policy == "null" else max(0, load - reserve)


def independent_loss(policy, reserve, load, last_paid_grade=None):
    if policy not in POLICIES:
        raise ValueError("unknown reserve policy")
    _integer(reserve, "reserve", 0, CAPACITY)
    _integer(load, "load", 0)
    if policy == "grade-load-v1":
        grade = _integer(last_paid_grade, "last paid grade", 0, 3)
        amount = max(1, load + 1 - grade)
    else:
        if last_paid_grade is not None:
            raise ValueError("grade is only an input to grade-load-v1")
        amount = max(1, load)
    return 0 if policy == "null" else min(reserve, amount)


class ReserveLedger:
    VERSION = "ft-integer-reserve-accounting-v1"

    def __init__(self, actor, policy, *, initial=DEFAULT_INITIAL, tokens=()):
        if actor is None:
            raise ValueError("owned actor required")
        if policy not in POLICIES:
            raise ValueError("unknown reserve policy")
        self.actor = actor
        self.policy = policy
        self.initial = _integer(initial, "initial reserve", 0, CAPACITY)
        if type(tokens) not in (tuple, list):
            raise ValueError("finite token inventory required")
        self.tokens = tuple(_identity(value, "token") for value in tokens)
        if len(set(self.tokens)) != len(self.tokens):
            raise ValueError("duplicate replenishment token")
        self.balance = self.initial
        self.events = []
        self.demands = {}
        self.consumed_tokens = set()
        self.seen_receipts = set()
        self.seen_attempts = set()

    def _append(self, kind, delta, **fields):
        _integer(delta, "reserve delta", -CAPACITY, CAPACITY)
        before = self.balance
        after = before + delta
        _integer(after, "reserve after", 0, CAPACITY)
        event = dict(index=len(self.events), kind=kind, balance_before=before,
                     delta=delta, balance_after=after, **fields)
        self.balance = after
        self.events.append(event)
        return deepcopy(event)

    def admit(self, demand_id, load):
        demand_id = _identity(demand_id, "demand")
        load = _integer(load, "load", 0)
        if demand_id in self.demands:
            raise ValueError("demand identity is immutable and already admitted")
        prep = preparation(self.policy, self.balance, load)
        event = self._append("admission", 0, demand_id=demand_id, load=load,
                             preparation=prep)
        self.demands[demand_id] = dict(load=load, preparation=prep,
                                       status="pending", completion=None)
        return event

    def complete(self, demand_id, completion_kind, *, last_paid_grade=None):
        demand_id = _identity(demand_id, "demand")
        if demand_id not in self.demands or self.demands[demand_id]["status"] != "pending":
            raise ValueError("one admitted unresolved demand required")
        if completion_kind not in ("independent", "supported"):
            raise ValueError("unknown completion kind")
        load = self.demands[demand_id]["load"]
        if completion_kind == "independent":
            loss = independent_loss(self.policy, self.balance, load, last_paid_grade)
        else:
            if last_paid_grade is not None:
                raise ValueError("supported completion has no grade input")
            loss = 0 if self.policy == "null" else min(self.balance, 1)
        event = self._append("completion", -loss, demand_id=demand_id,
                             completion_kind=completion_kind, load=load,
                             last_paid_grade=last_paid_grade)
        self.demands[demand_id]["status"] = "completed"
        self.demands[demand_id]["completion"] = completion_kind
        return event

    def interrupt(self, demand_id, attempt_id):
        demand_id = _identity(demand_id, "demand")
        attempt_id = _identity(attempt_id, "attempt")
        if demand_id not in self.demands or self.demands[demand_id]["status"] != "pending":
            raise ValueError("interruption requires an admitted unresolved demand")
        if attempt_id in self.seen_attempts:
            raise ValueError("attempt identity already accounted")
        self.seen_attempts.add(attempt_id)
        loss = 0 if self.policy == "null" else min(self.balance, 1)
        return self._append("interruption", -loss, demand_id=demand_id,
                            attempt_id=attempt_id)

    def replenish(self, token_id, receipt):
        token_id = _identity(token_id, "token")
        if token_id not in self.tokens:
            raise ValueError("token is outside the finite inventory")
        receipt = _receipt(receipt, self.actor, token_id)
        receipt_id = receipt["identity"]
        if receipt_id in self.seen_receipts:
            raise ValueError("receipt identity already accounted")
        if self.policy != "null" and token_id in self.consumed_tokens:
            raise ValueError("replenishment token already consumed")
        self.seen_receipts.add(receipt_id)
        if self.policy == "null":
            gain = 0
        else:
            self.consumed_tokens.add(token_id)
            gain = min(CAPACITY - self.balance, 2)
        return self._append("replenishment", gain, token_id=token_id, receipt=receipt)

    def _state(self):
        return dict(version=self.VERSION, actor=self.actor, policy=self.policy,
                    initial=self.initial, capacity=CAPACITY, tokens=self.tokens,
                    balance=self.balance, events=self.events, demands=self.demands,
                    consumed_tokens=tuple(sorted(self.consumed_tokens)),
                    seen_receipts=tuple(sorted(self.seen_receipts)),
                    seen_attempts=tuple(sorted(self.seen_attempts)))

    def checkpoint(self):
        return dumps(self._state())

    @classmethod
    def restore(cls, text):
        data = loads(text)
        required = {"version", "actor", "policy", "initial", "capacity", "tokens",
                    "balance", "events", "demands", "consumed_tokens",
                    "seen_receipts", "seen_attempts"}
        if (type(data) is not dict or set(data) != required
                or data["version"] != cls.VERSION or data["capacity"] != CAPACITY):
            raise ValueError("exact FT5.1 reserve checkpoint required")
        result = cls(data["actor"], data["policy"], initial=data["initial"],
                     tokens=data["tokens"])
        for event in data["events"]:
            kind = event.get("kind")
            if kind == "admission":
                result.admit(event.get("demand_id"), event.get("load"))
            elif kind == "completion":
                result.complete(event.get("demand_id"), event.get("completion_kind"),
                                last_paid_grade=event.get("last_paid_grade"))
            elif kind == "interruption":
                result.interrupt(event.get("demand_id"), event.get("attempt_id"))
            elif kind == "replenishment":
                result.replenish(event.get("token_id"), event.get("receipt"))
            else:
                raise ValueError("unknown reserve event")
        if result._state() != data:
            raise ValueError("reserve checkpoint differs from exact replay")
        return result
