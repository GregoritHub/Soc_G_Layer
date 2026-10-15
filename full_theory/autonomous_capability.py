"""Deterministic certification of paid capability after honest closure."""
from copy import deepcopy
from hashlib import sha256

from hle_unified.development_values import attrs as development_attrs
from hle_unified.material import attrs
from hle_unified.selection_records import dumps, loads

from .content import ContentBridge, semantic_scope
from .retention import Demand, RetentionLedger


def _paid(row, actor):
    return (row.get("actor") == actor and row.get("status", "succeeded") == "succeeded"
            and row.get("required", 0) > 0 and row.get("completed") == row.get("required")
            and row.get("spent", 0) >= row.get("required", 0))


def _jobs(engine, actor):
    rows = []
    for (owner, key), ref in engine._jobs.items():
        if owner == actor:
            row = attrs(engine.world.head(ref.identity))
            rows.append(dict(key=key, ref=ref, row=row))
    return tuple(sorted(rows, key=lambda item: (
        item["row"].get("finished_tick", 10**18),
        item["row"].get("started_tick", 10**18), dumps(item["ref"]))))


def discover_capability_candidates(engine, actor, demand):
    """Return certifiable native capacities in committed stable order."""
    if type(demand) is not Demand:
        raise ValueError("exact FT3 demand required")
    jobs = _jobs(engine, actor)
    paid = tuple(item for item in jobs if _paid(item["row"], actor))
    practices = {row["ref"]: row for row in engine.development_view(actor)["practices"]}
    candidates = []
    for capacity in engine.development_view(actor)["capacities"]:
        if ((capacity["context"], capacity["cue"]) != (demand.context, demand.cue)
                or demand.load > capacity["max_load"]):
            continue
        operation = attrs(engine.world.head(capacity["operation"].identity))
        if not _paid(operation, actor):
            continue
        try:
            examples = tuple(practices[ref] for ref in capacity["examples"])
        except KeyError:
            continue
        if (len(examples) < 2 or any(not row["independent"] or row["supported"] for row in examples)
                or len({row["event"] for row in examples}) != len(examples)
                or len({target.identity for row in examples for target in row["targets"]}) < 2):
            continue
        chosen = []
        used = set()
        for example in examples:
            practice = attrs(engine.world.head(example["operation"].identity))
            response = development_attrs(engine.world.resolve(example["response"]))
            response_job = attrs(engine.world.head(response["operation"].identity))
            eligible = []
            for item in paid:
                row = item["row"]
                try:
                    scope = semantic_scope(engine, row)
                except ValueError:
                    continue
                if (item["ref"] not in used and not row.get("u8") and row.get("route_count", 0) > 0
                        and row.get("context") == demand.context and scope in example["targets"]
                        and response_job["finished_tick"] <= row["started_tick"]
                        and row["finished_tick"] <= practice["finished_tick"]):
                    eligible.append(item)
            if not eligible:
                chosen = []
                break
            selected = eligible[0]
            chosen.append(selected)
            used.add(selected["ref"])
        if len(chosen) != len(examples):
            continue
        use_refs = tuple(item["ref"] for item in chosen)
        use_keys = tuple(item["key"] for item in chosen)
        order = (operation.get("finished_tick", 10**18), dumps(capacity["ref"]),
                 tuple(dumps(ref) for ref in use_refs))
        candidates.append(dict(capacity_ref=capacity["ref"], capacity_operation=capacity["operation"],
            examples=tuple(capacity["examples"]), content_use_keys=use_keys,
            content_use_refs=use_refs, max_load=capacity["max_load"], order=order))
    return tuple(sorted(candidates, key=lambda row: row["order"]))


def _copy_ledger(source, engine):
    result = RetentionLedger(ContentBridge(engine))
    result.history = deepcopy(source.history)
    result.windows = deepcopy(source.windows)
    result.exposures = deepcopy(source.exposures)
    result.certificates = deepcopy(source.certificates)
    result.revoked = deepcopy(source.revoked)
    result.events = deepcopy(source.events)
    return result


class AutonomousCapabilityController:
    VERSION = "ft-autonomous-capability-discovery-v1"

    def __init__(self, closure, engine):
        if closure.phase != "closed" or not closure.ledger.events[-1]["closed"]:
            raise ValueError("accepted honest closure required")
        if closure.ledger.engine is not engine:
            raise ValueError("closure evidence must belong to paired native engine")
        self.closure = closure
        self.actor = closure.actor
        self.demand = closure.demand
        self.ledger = _copy_ledger(closure.ledger, engine)
        self.events = []
        self.phase = "open"
        self.certificate_key = None

    def step(self, engine, *, scan_limit=256):
        if type(scan_limit) is not int or not 1 <= scan_limit <= 4096:
            raise ValueError("bounded positive scan limit required")
        if self.ledger.engine is not engine:
            raise ValueError("capability evidence must belong to paired native engine")
        if self.phase == "certified":
            return deepcopy(self.events[-1])
        candidates = discover_capability_candidates(engine, self.actor, self.demand)[:scan_limit]
        if not candidates:
            event = dict(index=len(self.events), kind="capability_wait", candidates=(),
                         certified=False, reason="no_certifiable_paid_capacity")
            self.events.append(event)
            return deepcopy(event)
        selected = candidates[0]
        token = dumps(dict(actor=self.actor, demand=self.demand.record()))
        key = "ft-capability:" + sha256(token.encode()).hexdigest()[:20]
        certificate = self.ledger.certify(key, self.actor, self.demand,
            selected["capacity_ref"], selected["content_use_keys"])
        summaries = tuple(dict(capacity_ref=row["capacity_ref"],
                               content_use_refs=row["content_use_refs"], order=row["order"])
                          for row in candidates)
        event = dict(index=len(self.events), kind="capability_certificate",
            candidates=summaries, selected=deepcopy(selected), certificate=deepcopy(certificate),
            certified=True, reason="owned_paid_independent_capacity")
        self.events.append(event)
        self.phase = "certified"
        self.certificate_key = key
        return deepcopy(event)

    def checkpoint(self, engine):
        if self.ledger.engine is not engine:
            raise ValueError("paired native engine required")
        return dumps(dict(version=self.VERSION,
            native_sha256=sha256(engine.checkpoint().encode()).hexdigest(),
            closure_sha256=sha256(self.closure.checkpoint(engine).encode()).hexdigest(), actor=self.actor,
            demand=self.demand.record(), phase=self.phase,
            certificate_key=self.certificate_key, events=self.events,
            retention_events=self.ledger.events))

    @classmethod
    def restore(cls, text, closure, engine):
        data = loads(text)
        required = {"version", "native_sha256", "closure_sha256", "actor", "demand",
                    "phase", "certificate_key", "events", "retention_events"}
        anchor = sha256(closure.checkpoint(engine).encode()).hexdigest()
        if (set(data) != required or data["version"] != cls.VERSION
                or data["native_sha256"] != sha256(engine.checkpoint().encode()).hexdigest()
                or data["closure_sha256"] != anchor or data["actor"] != closure.actor
                or data["demand"] != closure.demand.record()):
            raise ValueError("exact paired autonomous-capability checkpoint required")
        result = cls(closure, engine)
        prefix = len(result.ledger.events)
        if data["retention_events"][:prefix] != result.ledger.events:
            raise ValueError("capability checkpoint changed closure evidence")
        result.ledger.events = data["retention_events"]
        for row in data["retention_events"][prefix:]:
            if row.get("kind") == "certificate":
                result.ledger.certificates[row["key"]] = row
            elif row.get("kind") == "certificate_revoked":
                result.ledger.revoked[row["key"]] = row["reason"]
            else:
                raise ValueError("unexpected post-closure retention event")
        result.phase = data["phase"]
        result.certificate_key = data["certificate_key"]
        result.events = data["events"]
        if any(row["index"] != i for i, row in enumerate(result.events)):
            raise ValueError("invalid autonomous-capability event order")
        if result.phase == "certified" and result.certificate_key not in result.ledger.certificates:
            raise ValueError("certified checkpoint lacks exact certificate")
        return result
