"""Bounded autonomous assembly of accepted demand and route controllers."""
from copy import deepcopy
from hashlib import sha256

from hle_unified.crossing_records import CrossingRequest
from hle_unified.selection_records import SelectionRequest, dumps, fields_of, loads
from hle_unified.workflow_records import WorkflowRequest
from hle_unified.workflow_selection_records import WorkflowSelectionRequest

from .content import ContentBridge
from .demand_controller import IntegratedDemandController
from .retention import Demand
from .route_policy import IntegratedRoutePolicy


TERMINAL = ("complete", "deferred", "failed", "cancelled", "rejected")
CANONICAL_DOMAIN = {"I": "personal", "IT": "observation", "WE": "shared", "ITS": "system"}
WORKFLOW_DOMAIN = {"I": "personal", "IT": "activity", "WE": "shared", "ITS": "system"}


def _same_scope(request, demand):
    return (demand.family, demand.context, demand.cue, demand.target) == (
        "workflow" if type(request) is WorkflowSelectionRequest else "canonical",
        request.context, request.cue, request.target)


class AutonomousCycleController:
    """Owns request formation, route choice, paid consumption and settlement.

    FT4.3a deliberately ends at settlement.  It does not create closure or a
    capability certificate; those remain the FT4.3b gate.
    """

    VERSION = "ft-autonomous-cycle-assembly-v1"

    def __init__(self):
        self.demand_controller = IntegratedDemandController()
        self.route_policy = IntegratedRoutePolicy()
        self.actor = None
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
            raise ValueError("completed traversal must expose an exact native output")
        evidence = tuple(p.address for p in engine.participant_view(self.actor).resolve(self.request.target))
        if not evidence:
            raise ValueError("same-scope paid evidence required for autonomous consumption")
        self.consumer_key = self.request.key + ":autonomous-consumer"
        destination = movement["destination"]
        common = dict(key=self.consumer_key, actor=self.actor, context=self.request.context,
                      cue=self.request.cue, inputs=(output,), evidence=evidence,
                      target=self.request.target)
        if type(self.request) is SelectionRequest:
            return CrossingRequest(recipe="use-" + CANONICAL_DOMAIN[destination] + "-v1",
                stock=movement.get("stock"), peer=movement.get("peer"),
                group=movement.get("group"), demand=1, **common), output
        if type(self.request) is WorkflowSelectionRequest:
            return WorkflowRequest(recipe="workflow-use-" + WORKFLOW_DOMAIN[destination] + "-v1",
                stock=movement.get("stock"), peer=movement.get("peer"),
                group=movement.get("group"), **common), output
        raise ValueError("exact route-free native request required")

    def step(self, engine, actor, historical_state, demand, *, work_limit=1):
        if type(demand) is not Demand or type(work_limit) is not int or work_limit < 1:
            raise ValueError("exact demand and positive integer work bound required")
        if self.terminal is not None:
            return deepcopy(self.terminal)
        if self.actor is not None and (self.actor != actor or self.required != demand.record()):
            raise ValueError("autonomous cycle identity cannot change")
        self.actor = actor
        self.required = demand.record()

        if self.phase == "scan":
            request, cycle = self.demand_controller.cycle(engine, actor, historical_state)
            if request is None:
                self.phase = "deferred"
                self.terminal = self._record(kind="terminal", reason=cycle["request"]["reason"],
                                             request=None, route=None, consumer=None,
                                             settlement=None)
                return deepcopy(self.terminal)
            if not _same_scope(request, demand):
                raise ValueError("formed request differs from declared same-scope demand")
            self.request = request
            self.phase = "route"
            return self._record(kind="scan", reason=cycle["request"]["reason"],
                                request=fields_of(request), route=None,
                                consumer=None, settlement=None)

        if self.phase == "route":
            route = self.route_policy.step(engine, self.request, demand, work_limit=work_limit)
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
            bridge = ContentBridge(engine)
            consumer = bridge.execute(request, quantum=work_limit, consumed=(movement_output,))
            if consumer["status"] == "succeeded":
                demand_key = self.demand_controller.events[0]["request"]["selected"]
                settlement = self.demand_controller.settle(engine, demand_key,
                    self.request.key, self.request.key + ":movement", self.consumer_key)
                self.phase = "complete"
                self.terminal = self._record(kind="terminal", reason="settled_after_paid_consumption",
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

        raise ValueError("invalid autonomous cycle phase")

    def checkpoint(self, engine):
        request = None if self.request is None else dict(
            setting="workflow" if type(self.request) is WorkflowSelectionRequest else "canonical",
            fields=fields_of(self.request))
        return dumps(dict(version=self.VERSION,
            native_sha256=sha256(engine.checkpoint().encode()).hexdigest(),
            demand_controller=self.demand_controller.checkpoint(),
            route_policy=self.route_policy.checkpoint(engine), actor=self.actor,
            required=self.required, request=request, phase=self.phase,
            consumer_key=self.consumer_key, events=self.events, terminal=self.terminal))

    @classmethod
    def restore(cls, text, engine):
        data = loads(text)
        required = {"version", "native_sha256", "demand_controller", "route_policy",
                    "actor", "required", "request", "phase", "consumer_key",
                    "events", "terminal"}
        if (set(data) != required or data["version"] != cls.VERSION
                or data["native_sha256"] != sha256(engine.checkpoint().encode()).hexdigest()):
            raise ValueError("exact paired autonomous-cycle checkpoint required")
        result = cls()
        result.demand_controller = IntegratedDemandController.restore(data["demand_controller"])
        result.route_policy = IntegratedRoutePolicy.restore(data["route_policy"], engine)
        result.actor = data["actor"]
        result.required = data["required"]
        if data["request"] is not None:
            constructor = (WorkflowSelectionRequest if data["request"]["setting"] == "workflow"
                           else SelectionRequest)
            result.request = constructor(**data["request"]["fields"])
        result.phase = data["phase"]
        result.consumer_key = data["consumer_key"]
        result.events = data["events"]
        result.terminal = data["terminal"]
        if any(row["index"] != i for i, row in enumerate(result.events)):
            raise ValueError("invalid autonomous-cycle event order")
        if result.terminal is not None and result.terminal != result.events[-1]:
            raise ValueError("terminal event differs from event history")
        return result

