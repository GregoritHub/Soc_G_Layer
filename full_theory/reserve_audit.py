"""Independent FT5.1 reserve reconstruction; imports no reserve runtime."""
from hle_unified.selection_records import loads


POLICIES = ("null", "load-v1", "grade-load-v1")
CAPACITY = 8


def _int(value, low=None, high=None):
    if type(value) is not int or (low is not None and value < low) or (high is not None and value > high):
        raise ValueError("invalid exact integer")
    return value


def _id(value):
    if type(value) is not str or not value:
        raise ValueError("invalid identity")
    return value


def audit_reserve(checkpoint):
    data = loads(checkpoint)
    required = {"version", "actor", "policy", "initial", "capacity", "tokens",
                "balance", "events", "demands", "consumed_tokens",
                "seen_receipts", "seen_attempts"}
    if (type(data) is not dict or set(data) != required
            or data["version"] != "ft-integer-reserve-accounting-v1"
            or data["policy"] not in POLICIES or data["capacity"] != CAPACITY):
        raise ValueError("invalid reserve contract")
    initial = _int(data["initial"], 0, CAPACITY)
    tokens = tuple(_id(value) for value in data["tokens"])
    if len(tokens) != len(set(tokens)):
        raise ValueError("duplicate configured token")
    balance = initial
    demands = {}
    consumed = set()
    receipts = set()
    attempts = set()
    for index, event in enumerate(data["events"]):
        common = {"index", "kind", "balance_before", "delta", "balance_after"}
        if (type(event) is not dict or event.get("index") != index
                or event.get("balance_before") != balance):
            raise ValueError("event order or prior balance differs")
        kind = event.get("kind")
        if kind == "admission":
            if set(event) != common | {"demand_id", "load", "preparation"}:
                raise ValueError("invalid admission fields")
            demand = _id(event["demand_id"]); load = _int(event["load"], 0)
            if demand in demands:
                raise ValueError("demand identity reused")
            prep = 0 if data["policy"] == "null" else max(0, load - balance)
            delta = 0
            if event["preparation"] != prep:
                raise ValueError("preparation formula differs")
            demands[demand] = dict(load=load, preparation=prep,
                                   status="pending", completion=None)
        elif kind == "completion":
            fields = {"demand_id", "completion_kind", "load", "last_paid_grade"}
            if set(event) != common | fields:
                raise ValueError("invalid completion fields")
            demand = _id(event["demand_id"])
            if demand not in demands or demands[demand]["status"] != "pending":
                raise ValueError("completion demand unavailable")
            load = demands[demand]["load"]
            if event["load"] != load:
                raise ValueError("completion load rewritten")
            completion = event["completion_kind"]
            if completion == "supported":
                if event["last_paid_grade"] is not None:
                    raise ValueError("supported completion has grade")
                loss = 0 if data["policy"] == "null" else min(balance, 1)
            elif completion == "independent":
                if data["policy"] == "grade-load-v1":
                    grade = _int(event["last_paid_grade"], 0, 3)
                    raw = max(1, load + 1 - grade)
                else:
                    if event["last_paid_grade"] is not None:
                        raise ValueError("unexpected grade")
                    raw = max(1, load)
                loss = 0 if data["policy"] == "null" else min(balance, raw)
            else:
                raise ValueError("unknown completion")
            delta = -loss
            demands[demand]["status"] = "completed"
            demands[demand]["completion"] = completion
        elif kind == "interruption":
            if set(event) != common | {"demand_id", "attempt_id"}:
                raise ValueError("invalid interruption fields")
            demand = _id(event["demand_id"]); attempt = _id(event["attempt_id"])
            if (demand not in demands or demands[demand]["status"] != "pending"
                    or attempt in attempts):
                raise ValueError("invalid or duplicate interruption")
            attempts.add(attempt)
            delta = 0 if data["policy"] == "null" else -min(balance, 1)
        elif kind == "replenishment":
            if set(event) != common | {"token_id", "receipt"}:
                raise ValueError("invalid replenishment fields")
            token = _id(event["token_id"]); receipt = event["receipt"]
            exact = {"identity", "actor", "token_id", "source", "seat", "status", "paid"}
            if (token not in tokens or type(receipt) is not dict or set(receipt) != exact
                    or receipt["actor"] != data["actor"] or receipt["token_id"] != token
                    or receipt["source"] != "external" or receipt["seat"] != 5
                    or receipt["status"] != "succeeded" or receipt["paid"] is not True):
                raise ValueError("invalid provisional A5 receipt")
            receipt_id = _id(receipt["identity"])
            if receipt_id in receipts:
                raise ValueError("duplicate receipt")
            receipts.add(receipt_id)
            if data["policy"] == "null":
                delta = 0
            else:
                if token in consumed:
                    raise ValueError("duplicate token consumption")
                consumed.add(token)
                delta = min(CAPACITY - balance, 2)
        else:
            raise ValueError("unknown reserve event")
        after = balance + delta
        _int(after, 0, CAPACITY)
        if event["delta"] != delta or event["balance_after"] != after:
            raise ValueError("reserve delta or resulting balance differs")
        balance = after
    expected = dict(balance=balance, demands=demands,
                    consumed_tokens=tuple(sorted(consumed)),
                    seen_receipts=tuple(sorted(receipts)),
                    seen_attempts=tuple(sorted(attempts)))
    for key, value in expected.items():
        if data[key] != value:
            raise ValueError("derived reserve state differs: " + key)
    return dict(passed=True, policy=data["policy"], actor=data["actor"],
                initial=initial, balance=balance, events=len(data["events"]),
                demands=len(demands), consumed_tokens=len(consumed),
                scope="FT5.1 accounting only; native receipt binding remains FT5.2")
