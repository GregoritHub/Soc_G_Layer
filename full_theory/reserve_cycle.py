"""FT5.2b2 autonomous reserve settlement over accepted FT4/FT5 interfaces."""
from copy import deepcopy
from dataclasses import replace
from hashlib import sha256

from hle_unified import model_g
from hle_unified.crossing_records import CrossingRequest
from hle_unified.selection_records import SelectionRequest, dumps, fields_of, loads
from hle_unified.workflow_records import WorkflowRequest
from hle_unified.workflow_selection_records import WorkflowSelectionRequest

from .content import ContentBridge
from .demand_controller import IntegratedDemandController
from .native_reserve import NativeReserveBinding
from .reserve import ReserveLedger
from .reserve_candidates import ReserveCandidateController
from .retention import Demand


TERMINAL = ("complete", "deferred", "failed", "cancelled", "rejected", "interrupted")
CANONICAL_DOMAIN = {"I": "personal", "IT": "observation", "WE": "shared", "ITS": "system"}
WORKFLOW_DOMAIN = {"I": "personal", "IT": "activity", "WE": "shared", "ITS": "system"}


def _native_hash(engine):
    return sha256(engine.checkpoint().encode()).hexdigest()


def _same_scope(request, demand):
    family = "workflow" if type(request) is WorkflowSelectionRequest else "canonical"
    return (demand.family, demand.context, demand.cue, demand.target) == (
        family, request.context, request.cue, request.target)


def _support_request(engine, request, demand):
    """Add only support coordinates discovered in the actor's owned native view."""
    if not demand.support_allowed:
        return request
    state = (engine.workflow_selection_view(request) if type(request) is WorkflowSelectionRequest
             else engine.selection_view(request))
    candidates = []
    for item in state["items"]:
        data = item["data"]
        if (data.get("kind") == "reply" and data.get("speaker") in demand.support_allowed
                and data.get("receiver") == request.actor and data.get("group") is not None
                and data.get("context") == request.context and data.get("target") == request.target
                and data.get("consent") is True):
            candidates.append((dumps(item["ref"]), data["speaker"], data["group"]))
    if not candidates:
        return request
    _, peer, group = min(candidates)
    return replace(request, peer=peer, group=group)


class ReserveAutonomousController:
    VERSION = "ft-autonomous-reserve-settlement-v1"

    def __init__(self, engine, ledger):
        if type(ledger) is not ReserveLedger:
            raise ValueError("exact FT5.1 reserve ledger required")
        self.actor = ledger.actor
        self.demand_controller = IntegratedDemandController()
        self.candidates = ReserveCandidateController(engine, NativeReserveBinding(engine, ledger))
        self.required = None
        self.request = None
        self.phase = "scan"
        self.consumer_key = None
        self.events = []
        self.effects = []
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
        self.consumer_key = self.request.key + ":reserve-consumer"
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

    def _reserve_id(self):
        attempt = self.candidates._attempt(self.request)
        if attempt is None:
            raise ValueError("reserve candidate admission required")
        return attempt["reserve_id"]

    def _complete_reserve(self, engine, settlement):
        route = self.candidates.route_policy._attempt(self.request)
        traversal = None if route is None else route.get("traversal")
        if traversal is None or route.get("status") != "complete":
            raise ValueError("actual completed native traversal required")
        supported = traversal.get("supported") is True and traversal.get("means") == "support"
        completion_kind = "supported" if supported else "independent"
        policy = self.candidates.binding.ledger.policy
        grade = (model_g.grade(traversal["target_seat"])
                 if completion_kind == "independent" and policy == "grade-load-v1" else None)
        native_before = _native_hash(engine)
        reserve_event = self.candidates.binding.ledger.complete(
            self._reserve_id(), completion_kind, last_paid_grade=grade)
        native_after = _native_hash(engine)
        if native_before != native_after:
            raise ValueError("reserve settlement changed native engine state")
        effect = dict(index=len(self.effects), kind="completion", reserve_id=self._reserve_id(),
            selected=traversal["means"], supported=supported,
            target_seat=traversal["target_seat"], completion_kind=completion_kind,
            last_paid_grade=grade, settlement=deepcopy(settlement),
            traversal=deepcopy(traversal), reserve_event=reserve_event,
            native_before=native_before, native_after=native_after)
        self.effects.append(effect)
        return deepcopy(effect)

    def step(self, engine, historical_state, demand, *, work_limit=1):
        if type(demand) is not Demand or type(work_limit) is not int or work_limit < 1:
            raise ValueError("exact demand and positive integer work bound required")
        if self.terminal is not None:
            return deepcopy(self.terminal)
        if self.required is not None and self.required != demand.record():
            raise ValueError("autonomous reserve demand identity cannot change")
        self.required = demand.record()

        if self.phase == "scan":
            request, cycle = self.demand_controller.cycle(engine, self.actor, historical_state)
            if request is None:
                self.phase = "deferred"
                self.terminal = self._record(kind="terminal", reason=cycle["request"]["reason"],
                    request=None, candidate=None, consumer=None, settlement=None, effect=None)
                return deepcopy(self.terminal)
            if not _same_scope(request, demand):
                raise ValueError("formed request differs from declared same-scope demand")
            self.request = _support_request(engine, request, demand)
            self.phase = "route"
            return self._record(kind="scan", reason=cycle["request"]["reason"],
                request=fields_of(self.request), candidate=None, consumer=None,
                settlement=None, effect=None)

        if self.phase == "route":
            candidate = self.candidates.step(engine, self.request, demand, work_limit=work_limit)
            if candidate["phase"] == "complete":
                self.phase = "consumer"
            elif candidate["phase"] in TERMINAL:
                self.phase = candidate["phase"]
                self.terminal = self._record(kind="terminal", reason=candidate["phase"],
                    request=fields_of(self.request), candidate=candidate, consumer=None,
                    settlement=None, effect=None)
                return deepcopy(self.terminal)
            return self._record(kind="route", reason=candidate["phase"],
                request=fields_of(self.request), candidate=candidate, consumer=None,
                settlement=None, effect=None)

        if self.phase == "consumer":
            request, movement_output = self._consumer(engine)
            consumer = ContentBridge(engine).execute(request, quantum=work_limit,
                                                     consumed=(movement_output,))
            if consumer["status"] == "succeeded":
                demand_key = self.demand_controller.events[0]["request"]["selected"]
                settlement = self.demand_controller.settle(engine, demand_key, self.request.key,
                    self.request.key + ":movement", self.consumer_key)
                effect = self._complete_reserve(engine, settlement)
                self.phase = "complete"
                self.terminal = self._record(kind="terminal",
                    reason="settled_after_paid_consumption_and_reserve",
                    request=fields_of(self.request), candidate=self.candidates.events[-1],
                    consumer=consumer, settlement=settlement, effect=effect)
                return deepcopy(self.terminal)
            if consumer["status"] in ("failed", "cancelled"):
                self.phase = "failed"
                self.terminal = self._record(kind="terminal", reason=consumer["status"],
                    request=fields_of(self.request), candidate=self.candidates.events[-1],
                    consumer=consumer, settlement=None, effect=None)
                return deepcopy(self.terminal)
            return self._record(kind="consumer", reason=consumer["status"],
                request=fields_of(self.request), candidate=self.candidates.events[-1],
                consumer=consumer, settlement=None, effect=None)

        raise ValueError("invalid autonomous reserve phase")

    def bind_preparation(self, engine, operation_keys):
        if self.phase != "route" or self.request is None:
            raise ValueError("active autonomous preparation phase required")
        return self.candidates.bind_preparation(engine, operation_keys)

    def replenish(self, engine, bridge, token_id, packet_key):
        if (self.phase != "interrupted" or self.terminal is None
                or not self.effects or self.effects[-1].get("kind") != "interruption"):
            raise ValueError("one actual paid interruption is required before recovery")
        request = fields_of(self.request)
        reserve_id = self._reserve_id()
        route = self.candidates.route_policy._attempt(self.request)
        if route is None:
            raise ValueError("interrupted native route attempt is absent")
        native_before = _native_hash(engine)
        binding = self.candidates.binding.replenish_from_uptake(
            engine, bridge, token_id, packet_key)
        native_after = _native_hash(engine)
        if native_before != native_after:
            raise ValueError("reserve recovery changed native engine state")
        effect = dict(index=len(self.effects), kind="replenishment",
            reserve_id=reserve_id, request=request,
            route_key=route["request"]["key"], token_id=token_id,
            packet_key=packet_key, binding=binding,
            native_before=native_before, native_after=native_after)
        self.effects.append(effect)
        self.phase = "recovered"
        self.terminal = None
        return self._record(kind="recovery", reason="paid_external_a5_uptake",
            request=request, candidate=self.candidates.events[-1], consumer=None,
            settlement=None, effect=effect)

    def restart(self, engine):
        if (self.phase != "recovered" or self.terminal is not None
                or not self.effects or self.effects[-1].get("kind") != "replenishment"):
            raise ValueError("new paid replenishment is required before restart")
        reserve_id = self._reserve_id()
        route = self.candidates.route_policy._attempt(self.request)
        if route is None or route.get("status") in TERMINAL:
            raise ValueError("one resumable interrupted native route attempt required")
        before = _native_hash(engine)
        request = fields_of(self.request)
        self.phase = "route"
        row = self._record(kind="restart", reason="resume_existing_paid_native_attempt",
            request=request, candidate=self.candidates.events[-1], consumer=None,
            settlement=None, effect=dict(reserve_id=reserve_id,
                route_key=route["request"]["key"], request=request,
                replenishment_index=self.effects[-1]["index"], native_sha256=before))
        if _native_hash(engine) != before:
            raise ValueError("restart changed native engine state")
        return row

    def interrupt(self, engine):
        if self.terminal is not None:
            if self.phase == "interrupted":
                return deepcopy(self.terminal)
            raise ValueError("settled terminal cycle cannot be interrupted")
        if self.phase != "route" or self.request is None or not self.candidates.events:
            raise ValueError("active delegated native route work required")
        latest = self.candidates.events[-1]
        if latest.get("route_event") is None or latest.get("selected_candidate") == "preparation":
            raise ValueError("preparation alone is not interruptible route work")
        paid_jobs = []
        for key in (self.request.key, self.request.key + ":movement"):
            if (self.actor, key) not in engine._jobs:
                continue
            status = engine.job_status(self.actor, key)
            if type(status.get("spent")) is int and status["spent"] > 0:
                paid_jobs.append(dict(key=key, operation=engine._jobs[self.actor, key],
                                      status=deepcopy(status)))
        if not paid_jobs:
            raise ValueError("actual positively paid native route work required")
        attempt_id = "native-route:" + sha256(dumps((self.actor, self.request.key)).encode()).hexdigest()
        native_before = _native_hash(engine)
        reserve_event = self.candidates.binding.ledger.interrupt(self._reserve_id(), attempt_id)
        native_after = _native_hash(engine)
        if native_before != native_after:
            raise ValueError("reserve interruption changed native engine state")
        effect = dict(index=len(self.effects), kind="interruption", reserve_id=self._reserve_id(),
            attempt_id=attempt_id, paid_jobs=tuple(paid_jobs), reserve_event=reserve_event,
            native_before=native_before, native_after=native_after)
        self.effects.append(effect)
        self.phase = "interrupted"
        self.terminal = self._record(kind="terminal", reason="interrupted_actual_paid_work",
            request=fields_of(self.request), candidate=latest, consumer=None,
            settlement=None, effect=effect)
        return deepcopy(self.terminal)

    def checkpoint(self, engine):
        request = None if self.request is None else dict(
            setting="workflow" if type(self.request) is WorkflowSelectionRequest else "canonical",
            fields=fields_of(self.request))
        return dumps(dict(version=self.VERSION, native_sha256=_native_hash(engine), actor=self.actor,
            demand_controller=self.demand_controller.checkpoint(),
            candidates=self.candidates.checkpoint(engine), required=self.required,
            request=request, phase=self.phase, consumer_key=self.consumer_key,
            events=self.events, effects=self.effects, terminal=self.terminal))

    @classmethod
    def restore(cls, text, engine):
        data = loads(text)
        required = {"version", "native_sha256", "actor", "demand_controller", "candidates",
                    "required", "request", "phase", "consumer_key", "events", "effects",
                    "terminal"}
        if (type(data) is not dict or set(data) != required or data["version"] != cls.VERSION
                or data["native_sha256"] != _native_hash(engine)):
            raise ValueError("exact paired autonomous reserve checkpoint required")
        result = cls.__new__(cls)
        result.actor = data["actor"]
        result.demand_controller = IntegratedDemandController.restore(data["demand_controller"])
        result.candidates = ReserveCandidateController.restore(data["candidates"], engine)
        if result.candidates.actor != result.actor:
            raise ValueError("autonomous reserve actor differs")
        result.required = data["required"]
        result.request = None
        if data["request"] is not None:
            constructor = (WorkflowSelectionRequest if data["request"]["setting"] == "workflow"
                           else SelectionRequest)
            result.request = constructor(**data["request"]["fields"])
        result.phase = data["phase"]
        result.consumer_key = data["consumer_key"]
        result.events = data["events"]
        result.effects = data["effects"]
        result.terminal = data["terminal"]
        if (any(row["index"] != i for i, row in enumerate(result.events))
                or any(row["index"] != i for i, row in enumerate(result.effects))
                or (result.terminal is not None and result.terminal != result.events[-1])):
            raise ValueError("autonomous reserve event order differs")
        if result.checkpoint(engine) != text:
            raise ValueError("autonomous reserve checkpoint differs from exact restoration")
        return result
