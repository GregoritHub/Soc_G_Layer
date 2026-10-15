"""Non-opposed TD5 choice over owned evidence and unchanged native work.

The relay is an integration state, not the native executor cursor.  A relay
edge is recorded only after the selected native movement actually succeeds.
"""
from copy import deepcopy
from hashlib import sha256

from hle.model_a import fields as seat_fields
from hle_unified.material import attrs
from hle_unified.operations import address
from hle_unified.selection_records import SelectionRequest, fields_of, dumps, loads
from hle_unified.workflow_selection_records import WorkflowSelectionRequest

from .content import FACETS
from .orientation import PaidOrientation
from .retention import Demand
from .route_execution import NativeRouteController
from .route_means import inventory_route_means


TERMINAL = ("complete", "deferred", "failed", "cancelled", "rejected")
SOCIAL = ("share", "coordinate", "educate", "identify", "mobilize",
          "institutionalize", "commune")


def _covered(seat, requirements):
    return set(requirements) <= set(FACETS[:seat_fields(seat)["dimensionality"]])


def _native_view(engine, request):
    if type(request) is SelectionRequest:
        return "canonical", engine.selection_view(request)
    if type(request) is WorkflowSelectionRequest:
        return "workflow", engine.workflow_selection_view(request)
    raise ValueError("exact route-free native request required")


def _consent(state, request, demand):
    if request.peer is None or request.group is None or request.peer not in demand.support_allowed:
        return None
    rows = []
    for item in state["items"]:
        data = item["data"]
        if (data.get("kind") == "reply" and data.get("speaker") == request.peer
                and data.get("receiver") == request.actor and data.get("group") == request.group
                and data.get("context") == request.context and data.get("target") == request.target
                and data.get("consent") is True):
            rows.append(dict(ref=item["ref"], data=data))
    return min(rows, key=lambda row: dumps(row["ref"])) if rows else None


class IntegratedRoutePolicy:
    VERSION = "ft-td5-route-policy-v1"

    def __init__(self):
        self.relay = {}
        self.attempts = []
        self.events = []
        self.native = NativeRouteController()
        self.orientation = PaidOrientation()

    def _attempt(self, request):
        return next((a for a in self.attempts
                     if (a["actor"], a["key"]) == (request.actor, request.key)), None)

    def _admit(self, engine, request, demand, retention, certificate_keys):
        if type(demand) is not Demand or (demand.context, demand.cue, demand.target) != (
                request.context, request.cue, request.target):
            raise ValueError("same-scope FT3 demand required")
        inventory = inventory_route_means(engine, request)
        origin = inventory["active_seat"]
        if self.relay.get(request.actor, origin) != origin:
            raise ValueError("relay/native seam must be reconciled before another choice")
        setting, state = _native_view(engine, request)
        if setting != inventory["setting"]:
            raise ValueError("native setting differs from means inventory")
        retained = []
        retention_events = ()
        if retention is not None:
            if retention.engine is not engine:
                raise ValueError("retention evidence must belong to this native engine")
            retention_events = tuple(deepcopy(retention.events))
            for key in sorted(certificate_keys):
                applicable, reason = retention.applicable(key, request.actor, demand)
                retained.append(dict(key=key, eligible=applicable, reason=reason,
                                     certificate=deepcopy(retention.certificates.get(key))))
        certificate = next((r for r in retained if r["eligible"]), None)
        consent = _consent(state, request, demand)
        native = {row["name"]: row for row in inventory["options"]}

        def structural(name):
            row = native[name]
            enough = _covered(row["target_seat"], demand.requirements)
            eligible = bool(row["eligible"] and enough)
            reason = ("required_facets_available" if eligible else row["reason"]
                      if not row["eligible"] else "target_dimensionality_insufficient")
            return dict(name=name, eligible=eligible, reason=reason,
                        target_seat=row["target_seat"], overhead=row["overhead"])

        retained_ok = certificate is not None and _covered(origin, demand.requirements)
        options = [dict(name="retained", eligible=retained_ok,
                        reason="owned_recalled_scoped_capacity" if retained_ok else
                        "no_applicable_capacity" if certificate is None else
                        "current_dimensionality_insufficient",
                        target_seat=origin, overhead=dict(energy=0, time=0),
                        certificate=None if certificate is None else certificate["key"]),
                   structural("ordinary"), structural("n"), structural("cp"),
                   dict(name="support", eligible=consent is not None,
                        reason="exact_paid_peer_consent" if consent else "no_exact_allowed_consent",
                        target_seat=origin, overhead=dict(energy=0, time=0),
                        support=None if consent is None else consent["ref"]),
                   dict(name="defer", eligible=True, reason="no_feasible_prior_mean",
                        target_seat=origin, overhead=dict(energy=0, time=0))]
        selected = next(row for row in options if row["eligible"])
        return dict(actor=request.actor, key=request.key, request=fields_of(request),
            setting=setting, demand=demand.record(), inventory=inventory, options=tuple(options),
            selected=deepcopy(selected), retained=tuple(retained),
            retention_events=retention_events, support=deepcopy(consent),
            origin_seat=origin, origin_dimension=seat_fields(origin)["dimensionality"],
            status="deferred" if selected["name"] == "defer" else "admitted",
            orientation_ticket=None, traversal=None)

    def step(self, engine, request, demand, *, retention=None, certificate_keys=(), work_limit=1):
        if type(work_limit) is not int or work_limit < 1:
            raise ValueError("positive integer policy work bound required")
        attempt = self._attempt(request)
        record = demand.record() if type(demand) is Demand else None
        if attempt is not None and (attempt["request"] != fields_of(request)
                                    or attempt["demand"] != record):
            raise ValueError("route attempt identity cannot change")
        if attempt is None:
            attempt = self._admit(engine, request, demand, retention, certificate_keys)
            self.attempts.append(attempt)
        before = len(engine.world.journal())
        selected = attempt["selected"]["name"]
        phase = attempt["status"]
        native_event = None
        orientation_event = None
        if phase not in TERMINAL:
            if selected == "cp" and attempt["orientation_ticket"] is None:
                orientation_event = self.orientation.step(engine, request, work_limit=work_limit)
                attempt["orientation_ticket"] = orientation_event["ticket"]
                phase = attempt["status"] = "native" if attempt["orientation_ticket"] else "orientation"
            else:
                native_event = self.native.step(engine, request, work_limit=work_limit)
                state = native_event["state"]
                if state == "movement_complete":
                    namespace = "c7ws.decision" if attempt["setting"] == "workflow" else "c6.decision"
                    decision = attrs(engine.world.resolve(address(namespace, request.actor, request.key)))
                    recipe = decision["recipe"]
                    if selected == "support" and not any(name in recipe for name in SOCIAL):
                        attempt["status"] = phase = "rejected"
                    else:
                        movement = engine.job_status(request.actor, request.key + ":movement")
                        ticket = attempt["orientation_ticket"]
                        if selected == "cp" and (ticket is None or ticket["origin_seat"] != attempt["origin_seat"]
                                or ticket["target_seat"] != attempt["selected"]["target_seat"]):
                            raise ValueError("exact cp fee must precede traversal")
                        target = attempt["selected"]["target_seat"]
                        traversal = dict(actor=request.actor, demand=request.demand, means=selected,
                            origin_seat=attempt["origin_seat"], target_seat=target,
                            origin_dimension=attempt["origin_dimension"],
                            target_dimension=seat_fields(target)["dimensionality"],
                            native_cursor_before=attempt["inventory"]["active_element"],
                            native_cursor_after=engine._cursors[request.actor],
                            selection=engine._jobs[request.actor,request.key],
                            movement=engine._jobs[request.actor,request.key+":movement"],
                            movement_output=movement.get("binding") or movement.get("result"),
                            orientation=ticket, support=attempt["support"],
                            supported=selected == "support", content_processed=True,
                            dimensionality_changed=False, completion_claim=False)
                        attempt["traversal"] = traversal
                        attempt["status"] = phase = "complete"
                        self.relay[request.actor] = target
                elif state in ("deferred", "failed", "cancelled", "native_rejected"):
                    attempt["status"] = phase = "deferred" if state == "deferred" else "failed"
                else:
                    attempt["status"] = phase = "native"
        event = dict(index=len(self.events), actor=request.actor, key=request.key,
            before=before, after=len(engine.world.journal()), work_limit=work_limit,
            phase=phase, selected=selected, orientation_event=orientation_event,
            native_event=native_event, traversal=deepcopy(attempt["traversal"]),
            completion_claim=False)
        self.events.append(event)
        return deepcopy(event)

    def checkpoint(self, engine):
        return dumps(dict(version=self.VERSION,
            native_sha256=sha256(engine.checkpoint().encode()).hexdigest(),
            relay=tuple(sorted(self.relay.items(),key=lambda row:dumps(row[0]))),
            attempts=self.attempts, events=self.events,
            native_controller=self.native.checkpoint(engine),
            orientation_controller=self.orientation.checkpoint(engine)))

    @classmethod
    def restore(cls, text, engine):
        data = loads(text)
        required = {"version","native_sha256","relay","attempts","events",
                    "native_controller","orientation_controller"}
        if (set(data) != required or data["version"] != cls.VERSION
                or data["native_sha256"] != sha256(engine.checkpoint().encode()).hexdigest()):
            raise ValueError("exact paired route-policy checkpoint required")
        if any(row["index"] != i for i,row in enumerate(data["events"])):
            raise ValueError("invalid route-policy event order")
        result = cls(); result.relay = dict(data["relay"]); result.attempts = data["attempts"]
        result.events = data["events"]
        result.native = NativeRouteController.restore(data["native_controller"],engine)
        result.orientation = PaidOrientation.restore(data["orientation_controller"],engine)
        return result
