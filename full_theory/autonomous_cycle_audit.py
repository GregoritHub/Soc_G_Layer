"""Independent FT4.3a reconstruction; imports no autonomous controller."""
from hashlib import sha256

from hle_unified.selection_records import loads

from .fulfillment_audit import audit_fulfillment
from .route_policy_audit import audit_route_policy


def audit_autonomous_cycle(transactions, access_text, cycle_checkpoint, native_checkpoint):
    data = loads(cycle_checkpoint)
    required = {"version", "native_sha256", "demand_controller", "route_policy",
                "actor", "required", "request", "phase", "consumer_key",
                "events", "terminal"}
    if set(data) != required or data.pop("version") != "ft-autonomous-cycle-assembly-v1":
        raise ValueError("invalid autonomous-cycle checkpoint")
    if data["native_sha256"] != sha256(native_checkpoint.encode()).hexdigest():
        raise ValueError("autonomous cycle is not paired to this native checkpoint")
    fulfillment = audit_fulfillment(transactions, access_text, data["demand_controller"])
    route = audit_route_policy(transactions, access_text, data["route_policy"], native_checkpoint)
    events = data["events"]
    if any(row.get("index") != i for i, row in enumerate(events)):
        raise ValueError("non-contiguous autonomous-cycle events")
    if not events or events[0]["kind"] != "scan":
        if data["phase"] == "deferred" and events and events[0]["kind"] == "terminal":
            return dict(passed=True, phase="deferred", fulfillment=fulfillment, route=route)
        raise ValueError("cycle did not originate in an owned demand scan")
    if data["request"] is None or events[0]["request"] != data["request"]["fields"]:
        raise ValueError("formed request differs from checkpoint request")
    terminal = data["terminal"]
    if terminal is not None and terminal != events[-1]:
        raise ValueError("terminal index differs")
    if data["phase"] == "complete":
        if (terminal is None or terminal["reason"] != "settled_after_paid_consumption"
                or terminal["consumer"] is None or terminal["settlement"] is None):
            raise ValueError("complete cycle lacks paid consumer settlement")
        attempts = loads(data["route_policy"])["attempts"]
        if len(attempts) != 1 or attempts[0]["status"] != "complete":
            raise ValueError("complete cycle lacks one completed autonomous route")
        traversal = attempts[0]["traversal"]
        settlement = terminal["settlement"]
        request_key = data["request"]["fields"]["key"]
        if (settlement["selection_key"] != request_key
                or settlement["movement_key"] != request_key + ":movement"
                or settlement["consumer_key"] != data["consumer_key"]
                or settlement["movement_output"] != traversal["movement_output"]
                or terminal["consumer"]["output"] != settlement["consumer_output"]):
            raise ValueError("route, consumer and settlement links differ")
        if terminal["consumer"]["inputs"] != (traversal["movement_output"],):
            raise ValueError("consumer did not use the exact movement output")
    elif fulfillment["fulfilled"]:
        raise ValueError("non-complete cycle cannot claim fulfillment")
    return dict(passed=True, phase=data["phase"], fulfillment=fulfillment, route=route,
                events=len(events), settled=fulfillment["fulfilled"])

