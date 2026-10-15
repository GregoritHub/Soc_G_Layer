"""Independent demand-cycle and paid outcome reconstruction.

Imports no controller, request generator, selector, scheduler or executor.
"""
from copy import deepcopy

from hle_unified.compact import ValuePool, unseal
from hle_unified.material import attrs
from hle_unified.operations import address, indexed
from hle_unified.particulars import record_registry
from hle_unified.selection_records import loads

from .demand_audit import audit_demands
from .request_audit import audit_request


def _snapshot(text):
    raw = unseal(text, "hle-unified-participant-value-v1")
    pool = ValuePool(record_registry())
    pool.load_nodes(raw["nodes"])
    return pool.get(pool.import_token(raw["root"]))


def _paid(data, routed=False):
    return (data.get("status") == "succeeded"
        and data.get("completed") == data.get("required")
        and data.get("spent", -1) >= data.get("required", 0)
        and (not routed or (data.get("route_count", 0) > 0
             and data.get("steps_completed") == data.get("route_count"))))


def _output(data):
    return data.get("binding") or data.get("result")


def audit_fulfillment(transactions, access_text, checkpoint):
    data = loads(checkpoint)
    if data.pop("version") != "ft-integrated-demand-v1" or set(data) != {"ledger", "events", "outcomes"}:
        raise ValueError("invalid controller checkpoint")
    ledger = loads(data["ledger"])
    if ledger.pop("version") != "owned-demand-admission-v1":
        raise ValueError("invalid embedded admission ledger")
    audit_demands(transactions, access_text, ledger["events"])
    events = data["events"]
    if any(e["controller_index"] != i for i, e in enumerate(events)):
        raise ValueError("non-contiguous controller events")
    scans = {e["turn"]:e for e in ledger["events"]}
    for event in (e for e in events if e["kind"] == "cycle"):
        scan = scans.get(event["scan_turn"])
        if (scan is None or scan["actor"] != event["actor"]
                or scan["pressure"] != event["pressure"]):
            raise ValueError("controller cycle differs from admission observation")
        audit_request(event["view"], scan["demands"], event["request"])
    txs = tuple(transactions)
    outcomes = {}
    for event in (e for e in events if e["kind"] == "settlement"):
        if not 0 < event["journal_count"] <= len(txs) or event["outcome"] != "fulfilled":
            raise ValueError("invalid settlement boundary or outcome")
        versions = {v.ref:v for tx in txs[:event["journal_count"]] for v in tx.versions}
        heads = {}
        for ref in versions:
            if ref.identity not in heads or ref.revision > heads[ref.identity].revision:
                heads[ref.identity] = ref
        def latest(ref):
            current = heads.get(ref.identity)
            if current is None: raise ValueError("missing claimed native object")
            return attrs(versions[current]), current
        demand = ledger["demands"].get(event["demand"])
        if demand is None or demand["status"] != "pending" or demand["actor"] != event["actor"]:
            raise ValueError("settlement lacks pending admitted demand")
        view = _snapshot(event["view"])
        binding = next((b for b in view.bindings if b.ref.identity == demand["binding"].identity
                        and b.ref.revision == max(x.ref.revision for x in view.bindings
                            if x.ref.identity == demand["binding"].identity)), None)
        if (binding is None or binding.ref != demand["binding"]
                or binding.endorsement.value in ("retracted", "disputed")
                or len(binding.content) != 1 or binding.content[0].object != demand["raw_payload"]):
            raise ValueError("settled demand is not current owned evidence")
        actor = event["actor"]
        if event["movement_key"] != event["selection_key"] + ":movement":
            raise ValueError("movement key is not selected child")
        selection, selection_ref = latest(address("u4.operation", actor, event["selection_key"]))
        movement, movement_ref = latest(address("u4.operation", actor, event["movement_key"]))
        consumer, _ = latest(address("u4.operation", actor, event["consumer_key"]))
        if not _paid(selection) or selection.get("input.0") != demand["binding"]:
            raise ValueError("comparison is not exact paid demand work")
        if not _paid(movement, True):
            raise ValueError("movement is not complete paid native work")
        namespace = "c7ws.decision" if selection.get("c7ws") else "c6.decision"
        decision, _ = latest(address(namespace, actor, event["selection_key"]))
        if (decision.get("status") != "launched" or decision.get("failure") is not None
                or decision.get("completion_claim") is not False
                or decision.get("operation") != selection_ref):
            raise ValueError("selection decision does not link paid comparison")
        if selection.get("c7ws"):
            if decision.get("child") is None or decision["child"].identity != movement_ref.identity:
                raise ValueError("workflow child link differs")
        else:
            admission, _ = latest(decision["admission"])
            if (not _paid(admission) or admission.get("route_count", 0) < 1
                    or admission.get("requested_route") != decision.get("recipe")
                    or decision.get("recipe") != movement.get("recipe_key")):
                raise ValueError("canonical admission link differs")
        produced = _output(movement)
        if (produced != event["movement_output"] or produced not in indexed(consumer, "input.")
                or not _paid(consumer, True) or _output(consumer) != event["consumer_output"]
                or movement.get("actor") != actor or consumer.get("actor") != actor
                or movement.get("context") != demand["context"]
                or consumer.get("context") != demand["context"]
                or movement.get("content_target", movement.get("target")) != demand["target"]
                or consumer.get("content_target", consumer.get("target")) != demand["target"]):
            raise ValueError("outcome is not exact later paid same-scope consumption")
        outcomes[event["demand"]] = event
    if outcomes != data["outcomes"]:
        raise ValueError("outcome index differs from reconstructed settlement events")
    effective = deepcopy(ledger["demands"])
    for key, event in outcomes.items():
        if effective[key]["status"] == "pending":
            effective[key].update(status="fulfilled", fulfilled_at=event["controller_index"],
                                  outcome=event["consumer_output"])
    return dict(passed=True, cycles=sum(e["kind"] == "cycle" for e in events),
                fulfilled=len(outcomes), pending=sum(d["status"] == "pending" for d in effective.values()),
                suspended=sum(d["status"] == "suspended" for d in effective.values()))
