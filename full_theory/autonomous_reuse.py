"""Later autonomous use of an accepted, evidence-backed capability."""
from copy import deepcopy
from hashlib import sha256

from hle_unified.crossing_records import CrossingRequest
from hle_unified.selection_records import SelectionRequest, dumps, fields_of, loads
from hle_unified.workflow_records import WorkflowRequest
from hle_unified.workflow_selection_records import WorkflowSelectionRequest

from .content import ContentBridge
from .demand_controller import IntegratedDemandController
from .retention import Demand, RetentionLedger
from .route_policy import IntegratedRoutePolicy


TERMINAL = ("complete", "deferred", "failed", "cancelled", "rejected")
CANONICAL_DOMAIN = {"I": "personal", "IT": "observation", "WE": "shared", "ITS": "system"}
WORKFLOW_DOMAIN = {"I": "personal", "IT": "activity", "WE": "shared", "ITS": "system"}


def _same_scope(request, demand):
    return (demand.family, demand.context, demand.cue, demand.target) == (
        "workflow" if type(request) is WorkflowSelectionRequest else "canonical",
        request.context, request.cue, request.target)


def _copy_ledger(source, engine):
    result = RetentionLedger(ContentBridge(engine))
    result.history = deepcopy(source.history)
    result.windows = deepcopy(source.windows)
    result.exposures = deepcopy(source.exposures)
    result.certificates = deepcopy(source.certificates)
    result.revoked = deepcopy(source.revoked)
    result.events = deepcopy(source.events)
    return result


def _ledger_record(ledger):
    history = tuple(sorted(((actor, tuple(sorted(values)))
                            for actor, values in ledger.history.items()), key=dumps))
    windows = tuple(sorted(ledger.windows.items(), key=dumps))
    return dict(history=history, windows=windows,
        exposures=tuple(sorted(ledger.exposures, key=dumps)),
        certificates=ledger.certificates, revoked=ledger.revoked, events=ledger.events)


def _restore_ledger(record, engine):
    ledger = RetentionLedger(ContentBridge(engine))
    ledger.history = {actor: set(values) for actor, values in record["history"]}
    ledger.windows = dict(record["windows"])
    ledger.exposures = set(record["exposures"])
    ledger.certificates = record["certificates"]
    ledger.revoked = record["revoked"]
    ledger.events = record["events"]
    return ledger


def _owned_need_refs(engine, actor):
    result = []
    for binding in engine.participant_view(actor).snapshot.bindings:
        if len(binding.content) == 1 and binding.content[0].relation in ("c6.need", "c7ws.need"):
            result.append(binding.ref)
    return tuple(sorted(set(result), key=dumps))


class AutonomousReuseController:
    VERSION = "ft-autonomous-retained-reuse-v1"

    def __init__(self, capability, engine):
        if (capability.phase != "certified" or capability.certificate_key is None
                or capability.certificate_key not in capability.ledger.certificates):
            raise ValueError("accepted certified autonomous capability required")
        if capability.ledger.engine is not engine:
            raise ValueError("capability evidence must belong to paired native engine")
        self.actor = capability.actor
        self.certificate_key = capability.certificate_key
        self.capability_checkpoint = capability.checkpoint(engine)
        self.closure_checkpoint = capability.closure.checkpoint(engine)
        self.cycle_checkpoint = capability.closure.cycle.checkpoint(engine)
        self.capability_native_checkpoint = engine.checkpoint()
        self.capability_access_checkpoint = engine.access.checkpoint()
        self.certified_journal_count = len(engine.world.journal())
        self.prior_need_refs = _owned_need_refs(engine, self.actor)
        self.ledger = _copy_ledger(capability.ledger, engine)
        self.demand_controller = IntegratedDemandController()
        self.route_policy = IntegratedRoutePolicy()
        self.required = None
        self.request = None
        self.phase = "scan"
        self.consumer_key = None
        self.events = []
        self.terminal = None

    def _record(self, **values):
        row = dict(index=len(self.events), phase=self.phase, **values)
        self.events.append(row)
        return deepcopy(row)

    def _consumer(self, engine):
        movement_key = self.request.key + ":movement"
        movement = engine.job_status(self.actor, movement_key)
        output = movement.get("binding") or movement.get("result")
        if output is None:
            raise ValueError("completed retained traversal must expose exact native output")
        evidence = tuple(p.address for p in engine.participant_view(self.actor).resolve(self.request.target))
        if not evidence:
            raise ValueError("same-scope paid evidence required for later consumption")
        self.consumer_key = self.request.key + ":retained-consumer"
        destination = movement["destination"]
        common = dict(key=self.consumer_key, actor=self.actor, context=self.request.context,
            cue=self.request.cue, inputs=(output,), evidence=evidence, target=self.request.target)
        if type(self.request) is SelectionRequest:
            return CrossingRequest(recipe="use-" + CANONICAL_DOMAIN[destination] + "-v1",
                stock=movement.get("stock"), peer=movement.get("peer"),
                group=movement.get("group"), demand=1, **common), output
        if type(self.request) is WorkflowSelectionRequest:
            return WorkflowRequest(recipe="workflow-use-" + WORKFLOW_DOMAIN[destination] + "-v1",
                stock=movement.get("stock"), peer=movement.get("peer"),
                group=movement.get("group"), **common), output
        raise ValueError("exact route-free native request required")

    def step(self, engine, historical_state, demand, *, work_limit=1):
        if type(demand) is not Demand or type(work_limit) is not int or work_limit < 1:
            raise ValueError("exact later demand and positive integer work bound required")
        if self.ledger.engine is not engine:
            raise ValueError("reuse evidence must belong to paired native engine")
        if self.terminal is not None:
            return deepcopy(self.terminal)
        if self.required is not None and self.required != demand.record():
            raise ValueError("later autonomous demand identity cannot change")
        self.required = demand.record()

        if self.phase == "scan":
            request, cycle = self.demand_controller.cycle(engine, self.actor, historical_state)
            if request is None:
                self.phase = "deferred"
                self.terminal = self._record(kind="terminal", reason=cycle["request"]["reason"],
                    request=None, route=None, consumer=None, settlement=None)
                return deepcopy(self.terminal)
            if not _same_scope(request, demand):
                raise ValueError("formed request differs from declared later demand")
            if request.demand in self.prior_need_refs:
                raise ValueError("reuse demand must arise after capability certification")
            self.request = request
            self.phase = "route"
            return self._record(kind="scan", reason=cycle["request"]["reason"],
                request=fields_of(request), route=None, consumer=None, settlement=None)

        if self.phase == "route":
            route = self.route_policy.step(engine, self.request, demand,
                retention=self.ledger, certificate_keys=(self.certificate_key,),
                work_limit=work_limit)
            if route["phase"] == "complete":
                self.phase = "consumer"
            elif route["phase"] in TERMINAL:
                self.phase = route["phase"]
                self.terminal = self._record(kind="terminal", reason=route["phase"],
                    request=fields_of(self.request), route=route, consumer=None, settlement=None)
                return deepcopy(self.terminal)
            return self._record(kind="route", reason=route["phase"],
                request=fields_of(self.request), route=route, consumer=None, settlement=None)

        if self.phase == "consumer":
            request, movement_output = self._consumer(engine)
            consumer = ContentBridge(engine).execute(
                request, quantum=work_limit, consumed=(movement_output,))
            if consumer["status"] == "succeeded":
                demand_key = self.demand_controller.events[0]["request"]["selected"]
                settlement = self.demand_controller.settle(engine, demand_key,
                    self.request.key, self.request.key + ":movement", self.consumer_key)
                self.phase = "complete"
                selected = self.route_policy.attempts[0]["selected"]["name"]
                self.terminal = self._record(kind="terminal",
                    reason=("settled_after_applicable_retained_choice" if selected == "retained"
                            else "settled_after_nonretained_choice"),
                    request=fields_of(self.request), route=self.route_policy.events[-1],
                    consumer=consumer, settlement=settlement)
                return deepcopy(self.terminal)
            if consumer["status"] in ("failed", "cancelled"):
                self.phase = "failed"
                self.terminal = self._record(kind="terminal", reason=consumer["status"],
                    request=fields_of(self.request), route=self.route_policy.events[-1],
                    consumer=consumer, settlement=None)
                return deepcopy(self.terminal)
            return self._record(kind="consumer", reason=consumer["status"],
                request=fields_of(self.request), route=self.route_policy.events[-1],
                consumer=consumer, settlement=None)
        raise ValueError("invalid autonomous-reuse phase")

    def checkpoint(self, engine):
        request = None if self.request is None else dict(
            setting="workflow" if type(self.request) is WorkflowSelectionRequest else "canonical",
            fields=fields_of(self.request))
        return dumps(dict(version=self.VERSION,
            native_sha256=sha256(engine.checkpoint().encode()).hexdigest(),
            actor=self.actor, certificate_key=self.certificate_key,
            capability_checkpoint=self.capability_checkpoint,
            closure_checkpoint=self.closure_checkpoint, cycle_checkpoint=self.cycle_checkpoint,
            capability_native_checkpoint=self.capability_native_checkpoint,
            capability_access_checkpoint=self.capability_access_checkpoint,
            certified_journal_count=self.certified_journal_count,
            prior_need_refs=self.prior_need_refs, retention=_ledger_record(self.ledger),
            demand_controller=self.demand_controller.checkpoint(),
            route_policy=self.route_policy.checkpoint(engine), required=self.required,
            request=request, phase=self.phase, consumer_key=self.consumer_key,
            events=self.events, terminal=self.terminal))

    @classmethod
    def restore(cls, text, engine):
        data = loads(text)
        required = {"version", "native_sha256", "actor", "certificate_key",
            "capability_checkpoint", "closure_checkpoint", "cycle_checkpoint",
            "capability_native_checkpoint", "capability_access_checkpoint",
            "certified_journal_count", "prior_need_refs", "retention",
            "demand_controller", "route_policy", "required", "request", "phase",
            "consumer_key", "events", "terminal"}
        if (set(data) != required or data["version"] != cls.VERSION
                or data["native_sha256"] != sha256(engine.checkpoint().encode()).hexdigest()):
            raise ValueError("exact paired autonomous-reuse checkpoint required")
        result = cls.__new__(cls)
        for name in ("actor", "certificate_key", "capability_checkpoint",
                     "closure_checkpoint", "cycle_checkpoint", "capability_native_checkpoint",
                     "capability_access_checkpoint", "certified_journal_count",
                     "prior_need_refs", "required", "phase", "consumer_key", "events", "terminal"):
            setattr(result, name, data[name])
        result.ledger = _restore_ledger(data["retention"], engine)
        result.demand_controller = IntegratedDemandController.restore(data["demand_controller"])
        result.route_policy = IntegratedRoutePolicy.restore(data["route_policy"], engine)
        result.request = None
        if data["request"] is not None:
            constructor = (WorkflowSelectionRequest if data["request"]["setting"] == "workflow"
                           else SelectionRequest)
            result.request = constructor(**data["request"]["fields"])
        if any(row["index"] != i for i, row in enumerate(result.events)):
            raise ValueError("invalid autonomous-reuse event order")
        if result.terminal is not None and result.terminal != result.events[-1]:
            raise ValueError("terminal event differs from autonomous-reuse history")
        return result
