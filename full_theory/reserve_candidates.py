"""FT5.2b1 reserve-conditioned readiness over unchanged FT4 route policy."""
from copy import deepcopy
from hashlib import sha256

from hle_unified.selection_records import fields_of, dumps, loads, SelectionRequest
from hle_unified.workflow_selection_records import WorkflowSelectionRequest

from .native_reserve import NativeReserveBinding
from .retention import Demand
from .route_policy import IntegratedRoutePolicy


def _native_hash(engine):
    return sha256(engine.checkpoint().encode()).hexdigest()


def _reserve_id(request):
    return "route-demand:" + sha256(dumps((request.actor, request.demand)).encode()).hexdigest()


class ReserveCandidateController:
    VERSION = "ft-reserve-candidate-readiness-v1"

    def __init__(self, engine, binding):
        if type(binding) is not NativeReserveBinding:
            raise ValueError("exact paid native reserve binding required")
        engine.wallet(binding.actor)
        self.actor = binding.actor
        self.binding = binding
        self.route_policy = IntegratedRoutePolicy()
        self.attempts = []
        self.events = []

    def _attempt(self, request):
        return next((row for row in self.attempts
                     if (row["actor"], row["key"]) == (request.actor, request.key)), None)

    def step(self, engine, request, demand, *, retention=None, certificate_keys=(), work_limit=1):
        if type(request) not in (SelectionRequest, WorkflowSelectionRequest):
            raise ValueError("exact route-free native request required")
        if type(demand) is not Demand or type(work_limit) is not int or work_limit < 1:
            raise ValueError("exact demand and positive work bound required")
        if request.actor != self.actor:
            raise ValueError("reserve and native request actor differ")
        fields = fields_of(request)
        record = demand.record()
        attempt = self._attempt(request)
        if attempt is None:
            reserve_id = _reserve_id(request)
            self.binding.admit(engine, reserve_id, demand.load)
            plan = self.route_policy._admit(engine, request, demand, retention, certificate_keys)
            attempt = dict(actor=request.actor, key=request.key, request=fields,
                demand=record, reserve_id=reserve_id, initial_route_plan=plan,
                policy=self.binding.ledger.policy)
            self.attempts.append(attempt)
        elif (attempt["request"] != fields or attempt["demand"] != record
              or attempt["policy"] != self.binding.ledger.policy):
            raise ValueError("candidate attempt identity cannot change")

        reserve_id = attempt["reserve_id"]
        obligation = self.binding.admissions[reserve_id]["preparation"]
        bound = len(self.binding.preparation_bindings[reserve_id])
        remaining = obligation - bound
        before = len(engine.world.journal())
        if remaining:
            plan = attempt["initial_route_plan"]
            route_event = None
            phase = "preparation"
            selected = "preparation"
        else:
            route_event = self.route_policy.step(engine, request, demand,
                retention=retention, certificate_keys=certificate_keys,
                work_limit=work_limit)
            plan = self.route_policy._attempt(request)
            phase = route_event["phase"]
            selected = route_event["selected"]
        options = tuple(deepcopy(plan["options"]))
        provisional = plan["selected"]
        event = dict(index=len(self.events), actor=self.actor, key=request.key,
            policy=self.binding.ledger.policy, reserve_balance=self.binding.ledger.balance,
            load=demand.load, reserve_id=reserve_id, preparation_required=obligation,
            preparation_bound=bound, preparation_remaining=remaining,
            route_options=options, provisional_native_selection=deepcopy(provisional),
            selected_candidate=selected,
            native_overhead=deepcopy(provisional["overhead"]),
            reserve_preparation_units=remaining, phase=phase,
            before=before, after=len(engine.world.journal()), route_event=route_event)
        self.events.append(event)
        return deepcopy(event)

    def bind_preparation(self, engine, operation_keys):
        active = [row for row in self.attempts
                  if len(self.binding.preparation_bindings[row["reserve_id"]])
                     < self.binding.admissions[row["reserve_id"]]["preparation"]]
        if len(active) != 1:
            raise ValueError("one active preparation obligation required")
        return self.binding.bind_preparation(engine, active[0]["reserve_id"], operation_keys)

    def checkpoint(self, engine):
        return dumps(dict(version=self.VERSION, native_sha256=_native_hash(engine),
            actor=self.actor, binding=self.binding.checkpoint(engine),
            route_policy=self.route_policy.checkpoint(engine), attempts=self.attempts,
            events=self.events))

    @classmethod
    def restore(cls, text, engine):
        data = loads(text)
        required = {"version", "native_sha256", "actor", "binding",
                    "route_policy", "attempts", "events"}
        if (type(data) is not dict or set(data) != required
                or data["version"] != cls.VERSION
                or data["native_sha256"] != _native_hash(engine)):
            raise ValueError("exact paired reserve candidate checkpoint required")
        binding = NativeReserveBinding.restore(data["binding"], engine)
        if binding.actor != data["actor"]:
            raise ValueError("candidate and binding actor differ")
        result = cls.__new__(cls)
        result.actor = data["actor"]
        result.binding = binding
        result.route_policy = IntegratedRoutePolicy.restore(data["route_policy"], engine)
        result.attempts = data["attempts"]
        result.events = data["events"]
        if any(row["index"] != index for index, row in enumerate(result.events)):
            raise ValueError("candidate event order differs")
        if result.checkpoint(engine) != text:
            raise ValueError("candidate checkpoint differs from exact restoration")
        return result
