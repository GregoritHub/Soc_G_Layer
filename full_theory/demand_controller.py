"""Integrated demand state over native engines; execution remains native-owned."""
from copy import deepcopy

from hle_unified.material import attrs
from hle_unified.operations import address, indexed
from hle_unified.selection_records import dumps, loads

from .demands import DemandLedger
from .demand_requests import form_request


def _paid(data, *, routed=False):
    if (data.get("status") != "succeeded" or data.get("completed") != data.get("required")
            or data.get("spent", -1) < data.get("required", 0)):
        return False
    return not routed or (data.get("route_count", 0) > 0
                          and data.get("steps_completed") == data.get("route_count"))


def _output(data):
    return data.get("binding") or data.get("result")


class IntegratedDemandController:
    VERSION = "ft-integrated-demand-v1"

    def __init__(self):
        self.ledger = DemandLedger()
        self.events = []
        self.outcomes = {}

    def effective_demands(self):
        result = deepcopy(self.ledger.demands)
        for key, event in self.outcomes.items():
            if key in result and result[key]["status"] == "pending":
                result[key].update(status="fulfilled", fulfilled_at=event["controller_index"],
                                   outcome=event["consumer_output"])
        return result

    def cycle(self, engine, actor, historical_state, *, limit=128):
        scan = self.ledger.scan(engine, actor, historical_state, limit=limit)
        view = engine.participant_view(actor)
        request, row = form_request(view, self.effective_demands())
        event = dict(kind="cycle", controller_index=len(self.events), actor=actor,
            scan_turn=scan["turn"], pressure=deepcopy(scan["pressure"]),
            view=view.bytes(), request=deepcopy(row))
        self.events.append(event)
        return request, deepcopy(event)

    def settle(self, engine, demand_key, selection_key, movement_key, consumer_key):
        if demand_key in self.outcomes:
            return deepcopy(self.outcomes[demand_key])
        demand = self.ledger.demands.get(demand_key)
        if demand is None or demand["status"] != "pending":
            raise ValueError("current pending admitted demand required")
        view = engine.participant_view(demand["actor"])
        current = view._heads.get(demand["binding"].identity)
        if (current is None or current.ref != demand["binding"]
                or current.endorsement.value in ("retracted", "disputed")
                or current.content[0].object != demand["raw_payload"]):
            raise ValueError("demand is no longer current owned evidence")
        selection = engine.job_status(demand["actor"], selection_key)
        movement = engine.job_status(demand["actor"], movement_key)
        consumer = engine.job_status(demand["actor"], consumer_key)
        if movement_key != selection_key + ":movement":
            raise ValueError("movement is not the selected native child key")
        if not _paid(selection) or selection.get("input.0") != demand["binding"]:
            raise ValueError("fully paid comparison of this exact demand required")
        if not _paid(movement, routed=True):
            raise ValueError("fully paid realized native movement required")
        namespace = "c7ws.decision" if selection.get("c7ws") else "c6.decision"
        decision = attrs(engine.world.resolve(address(namespace, demand["actor"], selection_key)))
        if (decision.get("status") != "launched" or decision.get("failure") is not None
                or decision.get("completion_claim") is not False
                or decision.get("operation") != engine._jobs[demand["actor"], selection_key]):
            raise ValueError("exact non-completion selection decision required")
        if selection.get("c7ws"):
            if (decision.get("child") is None
                    or decision["child"].identity != engine._jobs[demand["actor"], movement_key].identity):
                raise ValueError("workflow decision differs from native child")
        else:
            admission_ref = engine.world.head(decision["admission"].identity).ref
            admission = attrs(engine.world.resolve(admission_ref))
            if (not _paid(admission) or admission.get("route_count", 0) < 1
                    or admission.get("requested_route") != decision.get("recipe")
                    or decision.get("recipe") != movement.get("recipe_key")):
                raise ValueError("canonical admission differs from selected movement")
        produced = _output(movement)
        consumed = indexed(consumer, "input.")
        movement_target = movement.get("content_target", movement.get("target"))
        consumer_target = consumer.get("content_target", consumer.get("target"))
        if (produced is None or not _paid(consumer, routed=True) or produced not in consumed
                or _output(consumer) is None or movement.get("actor") != demand["actor"]
                or consumer.get("actor") != demand["actor"]
                or movement.get("context") != demand["context"]
                or consumer.get("context") != demand["context"]
                or movement_target != demand["target"] or consumer_target != demand["target"]):
            raise ValueError("later exact paid same-scope consumption required")
        event = dict(kind="settlement", controller_index=len(self.events), actor=demand["actor"],
            demand=demand_key, selection_key=selection_key, movement_key=movement_key,
            consumer_key=consumer_key, movement_output=produced,
            consumer_output=_output(consumer), view=view.bytes(),
            journal_count=len(engine.world.journal()), outcome="fulfilled")
        self.events.append(event)
        self.outcomes[demand_key] = event
        return deepcopy(event)

    def checkpoint(self):
        return dumps(dict(version=self.VERSION, ledger=self.ledger.checkpoint(),
                          events=self.events, outcomes=self.outcomes))

    @classmethod
    def restore(cls, text):
        data = loads(text)
        if data.pop("version") != cls.VERSION or set(data) != {"ledger", "events", "outcomes"}:
            raise ValueError("invalid integrated demand checkpoint")
        result = cls()
        result.ledger = DemandLedger.restore(data["ledger"])
        result.events = data["events"]
        result.outcomes = data["outcomes"]
        if any(e["controller_index"] != i for i, e in enumerate(result.events)):
            raise ValueError("invalid controller event order")
        return result
