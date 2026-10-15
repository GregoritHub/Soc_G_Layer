"""Deterministic discovery of honest FT4 closure evidence.

The native engine owns every operation and object.  This controller only
discovers already committed paid evidence; callers cannot name a favorable
operation, kept object, return path, Shell result, or success value.
"""
from copy import deepcopy
from hashlib import sha256

from hle_unified.material import attrs
from hle_unified.selection_records import dumps, loads

from .content import ContentBridge, semantic_scope
from .historical import type_map
from .retention import Demand, RetentionLedger


def _paid(row, actor):
    return (row.get("actor") == actor and row.get("status", "succeeded") == "succeeded"
            and row.get("required", 0) > 0 and row.get("completed") == row.get("required")
            and row.get("spent", 0) >= row.get("required", 0))


def _output(row):
    return row.get("binding") or row.get("result")


def _inputs(row):
    return tuple(value for key, value in row.items() if key.startswith("input."))


def _scope(engine, row):
    try:
        return semantic_scope(engine, row)
    except ValueError:
        return None


def _jobs(engine, actor):
    rows = []
    for (owner, key), ref in engine._jobs.items():
        if owner != actor:
            continue
        row = attrs(engine.world.head(ref.identity))
        rows.append(dict(key=key, ref=ref, row=row))
    return sorted(rows, key=lambda item: (
        item["row"].get("finished_tick", 10**18),
        item["row"].get("started_tick", 10**18), dumps(item["ref"])))


def discover_candidates(engine, actor, demand):
    """Return exact candidate episodes in committed chronological order."""
    if type(demand) is not Demand:
        raise ValueError("exact FT3 demand required")
    jobs = _jobs(engine, actor)
    paid = [item for item in jobs if _paid(item["row"], actor)]
    tm = type_map(ContentBridge(engine).tim(actor))
    complement, native = tm["complementary_perspective"], tm["native_perspective"]
    routes = [item for item in paid if item["row"].get("route_count", 0) > 0
              and item["row"].get("context") == demand.context
              and _scope(engine, item["row"]) == demand.target]
    chains = []

    def extend(chain):
        last = chain[-1]; row = last["row"]
        if row.get("destination") == native:
            chains.append(tuple(chain)); return
        if len(chain) >= 4:
            return
        out = _output(row)
        for candidate in routes:
            nxt = candidate["row"]
            if (candidate in chain or nxt.get("started_tick", -1) < row.get("finished_tick", 0)
                    or nxt.get("origin") != row.get("destination") or out not in _inputs(nxt)):
                continue
            extend(chain + [candidate])

    for item in routes:
        if item["row"].get("origin") == complement:
            extend([item])

    candidates = []
    for chain in chains:
        kept = tuple(_output(item["row"]) for item in chain)
        if not kept or any(value is None for value in kept):
            continue
        end = chain[-1]["row"].get("finished_tick", -1)
        consumers = [item for item in paid
            if item not in chain and item["row"].get("started_tick", -1) >= end
            and item["row"].get("context") == demand.context
            and _scope(engine, item["row"]) == demand.target
            and any(value in kept for value in _inputs(item["row"]))]
        for consumer in consumers:
            finished = consumer["row"].get("finished_tick", -1)
            for shell in paid:
                row = shell["row"]
                if (row.get("started_tick", -1) < finished or row.get("purpose") != "encounter"
                        or row.get("context") != demand.context or row.get("target") != demand.target):
                    continue
                candidates.append(dict(
                    kept=kept, return_keys=tuple(item["key"] for item in chain),
                    return_refs=tuple(item["ref"] for item in chain),
                    consumer_key=consumer["key"], consumer_ref=consumer["ref"],
                    shell_key=shell["key"], shell_ref=shell["ref"],
                    order=(row.get("finished_tick", 10**18),
                           consumer["row"].get("finished_tick", 10**18),
                           dumps(shell["ref"]), dumps(consumer["ref"]))))
    unique = {}
    for row in candidates:
        token = (row["consumer_ref"], row["shell_ref"], row["return_refs"])
        unique.setdefault(token, row)
    return tuple(sorted(unique.values(), key=lambda row: row["order"]))


class AutonomousClosureController:
    VERSION = "ft-honest-closure-discovery-v1"

    def __init__(self, cycle, engine, actor, demand):
        if (cycle.phase != "complete" or cycle.terminal is None
                or cycle.terminal.get("settlement") is None):
            raise ValueError("accepted settled autonomous cycle required")
        if type(demand) is not Demand or cycle.actor != actor or cycle.required != demand.record():
            raise ValueError("exact settled cycle actor and demand required")
        self.cycle = cycle
        self.actor = actor
        self.demand = demand
        self.ledger = RetentionLedger(ContentBridge(engine))
        self.events = []
        self.used = set()
        self.phase = "open"

    def step(self, engine, *, scan_limit=256, interrupted=False):
        if type(scan_limit) is not int or not 1 <= scan_limit <= 4096 or type(interrupted) is not bool:
            raise ValueError("bounded integer scan and exact interruption flag required")
        if self.ledger.engine is not engine:
            raise ValueError("closure evidence must belong to the paired native engine")
        if self.phase == "closed":
            return deepcopy(self.events[-1])
        candidates = discover_candidates(engine, self.actor, self.demand)[:scan_limit]
        for candidate in candidates:
            token = (candidate["consumer_ref"], candidate["shell_ref"])
            if (token in self.used or any(candidate["consumer_ref"] in prior
                                          or candidate["shell_ref"] in prior
                                          for prior in self.used)):
                continue
            shell = self.ledger.shell_state(self.actor, self.demand, candidate["shell_key"])
            if not shell["clear"]:
                continue
            self.used.add(token)
            row = self.ledger.expose(self.actor, self.demand, candidate["kept"],
                candidate["return_keys"], candidate["shell_key"], candidate["consumer_key"],
                interrupted=interrupted)
            event = dict(index=len(self.events), kind="closure_exposure",
                candidate=deepcopy(candidate), retention=deepcopy(row), closed=row["closed"])
            self.events.append(event)
            if row["closed"]:
                self.phase = "closed"
            return deepcopy(event)
        event = dict(index=len(self.events), kind="closure_wait", candidates=len(candidates),
            closed=False, reason="no_unused_valid_paid_exposure")
        self.events.append(event)
        return deepcopy(event)

    def checkpoint(self, engine):
        if self.ledger.engine is not engine:
            raise ValueError("paired native engine required")
        return dumps(dict(version=self.VERSION,
            native_sha256=sha256(engine.checkpoint().encode()).hexdigest(),
            cycle_sha256=sha256(self.cycle.checkpoint(engine).encode()).hexdigest(),
            actor=self.actor, demand=self.demand.record(), phase=self.phase,
            used=tuple(sorted(self.used, key=dumps)), events=self.events,
            retention_events=self.ledger.events))

    @classmethod
    def restore(cls, text, cycle, engine):
        data = loads(text)
        required = {"version", "native_sha256", "cycle_sha256", "actor", "demand",
                    "phase", "used", "events", "retention_events"}
        if (set(data) != required or data["version"] != cls.VERSION
                or data["native_sha256"] != sha256(engine.checkpoint().encode()).hexdigest()
                or data["cycle_sha256"] != sha256(cycle.checkpoint(engine).encode()).hexdigest()):
            raise ValueError("exact paired autonomous-closure checkpoint required")
        result = cls(cycle, engine, data["actor"], Demand(**data["demand"]))
        result.phase = data["phase"]; result.used = set(data["used"]); result.events = data["events"]
        result.ledger.events = data["retention_events"]
        for row in result.ledger.events:
            token = (row["consumer"], row["shell"]["operation"])
            result.ledger.exposures.add(token)
            key = (row["actor"], row["demand"]["family"], row["demand"]["context"], row["demand"]["cue"])
            result.ledger.windows[key] = dict(signature=(row["kept"], row["demand"]),
                                               hold=row["hold"], last=row)
            tm = type_map(result.ledger.bridge.tim(row["actor"]))
            result.ledger.history.setdefault(row["actor"], {tm["native_perspective"]})
            if row["closed"]:
                result.ledger.history[row["actor"]].add(row["crossed"])
        if any(row["index"] != i for i, row in enumerate(result.events)):
            raise ValueError("invalid autonomous-closure event order")
        if result.phase == "closed" and not result.ledger.events[-1]["closed"]:
            raise ValueError("closed checkpoint lacks honest closure")
        return result
