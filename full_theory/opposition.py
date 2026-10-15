"""Declared, paid TD5 opposition as consecutive cp then n relay moves.

The structural relay and the native processing cursor remain distinct.  Each
relay leg is committed only after its own native movement succeeds.
"""
from copy import deepcopy
from dataclasses import replace
from hashlib import sha256

from hle.development_structure import portage
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


OBLIGATION = "opposition:cp-n-v1"
MOVES = ("cp", "n")
TERMINAL = ("complete", "deferred", "failed", "cancelled", "rejected")


def _covered(seat, requirements):
    return set(requirements) <= set(FACETS[:seat_fields(seat)["dimensionality"]])


class OppositionRouteController:
    VERSION = "ft-td5-opposition-cp-n-v1"

    def __init__(self):
        self.relay = {}
        self.attempts = []
        self.events = []
        self.native = NativeRouteController()
        self.orientation = PaidOrientation()

    def _attempt(self, request):
        return next((row for row in self.attempts
                     if (row["actor"], row["key"]) == (request.actor, request.key)), None)

    def _admit(self, engine, request, demand):
        if type(request) not in (SelectionRequest, WorkflowSelectionRequest):
            raise ValueError("exact route-free native request required")
        if (type(demand) is not Demand
                or (demand.context, demand.cue, demand.target) !=
                   (request.context, request.cue, request.target)):
            raise ValueError("same-scope FT3 demand required")
        if OBLIGATION not in demand.obligations:
            raise ValueError("exact declared opposition obligation required")
        inventory = inventory_route_means(engine, request)
        origin = inventory["active_seat"]
        if self.relay.get(request.actor, origin) != origin:
            raise ValueError("relay/native seam must be reconciled before opposition")
        cp = portage(origin, "cp")
        final = portage(cp, "n")
        if final != portage(origin, "a"):
            raise ValueError("declared sequence is not the opposition portage")
        cp_option = next(row for row in inventory["options"] if row["name"] == "cp")
        legs = [
            dict(index=0, move="cp", key=request.key + ":opposition:0:cp",
                 origin_seat=origin, target_seat=cp,
                 eligible=bool(cp_option["eligible"] and _covered(cp, demand.requirements)),
                 reason=("declared_cp_leg" if cp_option["eligible"] and _covered(cp, demand.requirements)
                         else cp_option["reason"] if not cp_option["eligible"]
                         else "intermediate_dimensionality_insufficient"),
                 status="pending", orientation_ticket=None, traversal=None),
            dict(index=1, move="n", key=request.key + ":opposition:1:n",
                 origin_seat=cp, target_seat=final,
                 eligible=_covered(final, demand.requirements),
                 reason=("declared_n_leg" if _covered(final, demand.requirements)
                         else "final_dimensionality_insufficient"),
                 status="pending", orientation_ticket=None, traversal=None),
        ]
        eligible = all(row["eligible"] for row in legs)
        return dict(actor=request.actor, key=request.key, request=fields_of(request),
            setting=inventory["setting"], demand=demand.record(), obligation=OBLIGATION,
            inventory=inventory, origin_seat=origin,
            origin_dimension=seat_fields(origin)["dimensionality"],
            moves=MOVES, legs=legs, current_leg=0, final_target=final,
            status="admitted" if eligible else "deferred",
            reason="declared_opposition_available" if eligible else
                   next(row["reason"] for row in legs if not row["eligible"]),
            traversal=None)

    def step(self, engine, request, demand, *, work_limit=1):
        if type(work_limit) is not int or work_limit < 1:
            raise ValueError("positive integer opposition work bound required")
        attempt = self._attempt(request)
        demand_record = demand.record() if type(demand) is Demand else None
        if attempt is not None and (attempt["request"] != fields_of(request)
                                    or attempt["demand"] != demand_record):
            raise ValueError("opposition attempt identity cannot change")
        if attempt is None:
            attempt = self._admit(engine, request, demand)
            self.attempts.append(attempt)
        before = len(engine.world.journal())
        phase = attempt["status"]
        native_event = None
        orientation_event = None
        leg_index = min(attempt["current_leg"], len(attempt["legs"]) - 1)
        leg = attempt["legs"][leg_index]
        if phase not in TERMINAL:
            child = replace(request, key=leg["key"])
            if leg["move"] == "cp" and leg["orientation_ticket"] is None:
                orientation_event = self.orientation.step(engine, child, work_limit=work_limit)
                leg["orientation_ticket"] = orientation_event["ticket"]
                phase = attempt["status"] = "native" if leg["orientation_ticket"] else "orientation"
            else:
                native_event = self.native.step(engine, child, work_limit=work_limit)
                state = native_event["state"]
                if state == "movement_complete":
                    movement = engine.job_status(request.actor, child.key + ":movement")
                    ticket = leg["orientation_ticket"]
                    if leg["move"] == "cp" and (ticket is None
                            or ticket["origin_seat"] != leg["origin_seat"]
                            or ticket["target_seat"] != leg["target_seat"]):
                        raise ValueError("exact cp fee must precede opposition movement")
                    traversal = dict(index=leg_index, move=leg["move"], actor=request.actor,
                        demand=request.demand, request_key=child.key,
                        origin_seat=leg["origin_seat"], target_seat=leg["target_seat"],
                        origin_dimension=seat_fields(leg["origin_seat"])["dimensionality"],
                        target_dimension=seat_fields(leg["target_seat"])["dimensionality"],
                        selection=engine._jobs[request.actor, child.key],
                        movement=engine._jobs[request.actor, child.key + ":movement"],
                        movement_output=movement.get("binding") or movement.get("result"),
                        orientation=ticket, content_processed=True,
                        dimensionality_changed=False, completion_claim=False)
                    leg["traversal"] = traversal
                    leg["status"] = "complete"
                    attempt["current_leg"] += 1
                    if attempt["current_leg"] == len(attempt["legs"]):
                        attempt["traversal"] = dict(actor=request.actor,
                            demand=request.demand, obligation=OBLIGATION, moves=MOVES,
                            origin_seat=attempt["origin_seat"],
                            final_target=attempt["final_target"],
                            legs=tuple(deepcopy(row["traversal"]) for row in attempt["legs"]),
                            opposition=True, content_processed=True,
                            dimensionality_changed=False, completion_claim=False)
                        self.relay[request.actor] = attempt["final_target"]
                        phase = attempt["status"] = "complete"
                    else:
                        phase = attempt["status"] = "between_legs"
                elif state in ("deferred", "failed", "cancelled", "native_rejected"):
                    leg["status"] = state
                    phase = attempt["status"] = "deferred" if state == "deferred" else "failed"
                else:
                    leg["status"] = "native"
                    phase = attempt["status"] = "native"
        event = dict(index=len(self.events), actor=request.actor, key=request.key,
            leg_index=leg_index, move=leg["move"], before=before,
            after=len(engine.world.journal()), work_limit=work_limit,
            phase=phase, orientation_event=orientation_event,
            native_event=native_event, leg_traversal=deepcopy(leg["traversal"]),
            opposition_traversal=deepcopy(attempt["traversal"]),
            completion_claim=False)
        self.events.append(event)
        return deepcopy(event)

    def checkpoint(self, engine):
        return dumps(dict(version=self.VERSION,
            native_sha256=sha256(engine.checkpoint().encode()).hexdigest(),
            relay=tuple(sorted(self.relay.items(), key=lambda row: dumps(row[0]))),
            attempts=self.attempts, events=self.events,
            native_controller=self.native.checkpoint(engine),
            orientation_controller=self.orientation.checkpoint(engine)))

    @classmethod
    def restore(cls, text, engine):
        data = loads(text)
        required = {"version", "native_sha256", "relay", "attempts", "events",
                    "native_controller", "orientation_controller"}
        if (set(data) != required or data["version"] != cls.VERSION
                or data["native_sha256"] != sha256(engine.checkpoint().encode()).hexdigest()):
            raise ValueError("exact paired opposition checkpoint required")
        if any(row["index"] != index for index, row in enumerate(data["events"])):
            raise ValueError("invalid opposition event order")
        result = cls()
        result.relay = dict(data["relay"])
        result.attempts = data["attempts"]
        result.events = data["events"]
        result.native = NativeRouteController.restore(data["native_controller"], engine)
        result.orientation = PaidOrientation.restore(data["orientation_controller"], engine)
        return result
