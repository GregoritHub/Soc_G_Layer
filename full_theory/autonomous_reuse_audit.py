"""Independent reconstruction of later retained-route reuse."""
from hashlib import sha256

from hle_unified.selection_records import loads

from .autonomous_capability_audit import audit_autonomous_capability
from .fulfillment_audit import audit_fulfillment
from .route_policy_audit import audit_route_policy


def audit_autonomous_reuse(transactions, access_text, checkpoint, native_checkpoint):
    data = loads(checkpoint)
    required = {"version", "native_sha256", "actor", "certificate_key",
        "capability_checkpoint", "closure_checkpoint", "cycle_checkpoint",
        "capability_native_checkpoint", "capability_access_checkpoint",
        "certified_journal_count", "prior_need_refs", "retention",
        "demand_controller", "route_policy", "required", "request", "phase",
        "consumer_key", "events", "terminal"}
    if (set(data) != required or data["version"] != "ft-autonomous-retained-reuse-v1"
            or data["native_sha256"] != sha256(native_checkpoint.encode()).hexdigest()):
        raise ValueError("autonomous-reuse paired source mismatch")
    txs = tuple(transactions)
    boundary = data["certified_journal_count"]
    if type(boundary) is not int or not 0 < boundary <= len(txs):
        raise ValueError("invalid capability certification boundary")
    capability = audit_autonomous_capability(txs[:boundary],
        data["capability_access_checkpoint"], data["capability_checkpoint"],
        data["closure_checkpoint"], data["cycle_checkpoint"],
        data["capability_native_checkpoint"])
    if not capability["certified"]:
        raise ValueError("reuse does not follow accepted capability certification")
    retention = data["retention"]
    if data["certificate_key"] not in retention["certificates"]:
        raise ValueError("bound certificate is absent from retained evidence")
    fulfillment = audit_fulfillment(txs, access_text, data["demand_controller"])
    route = audit_route_policy(txs, access_text, data["route_policy"], native_checkpoint)
    events = data["events"]
    if any(row.get("index") != i for i, row in enumerate(events)):
        raise ValueError("non-contiguous autonomous-reuse events")
    if not events or events[0]["kind"] not in ("scan", "terminal"):
        raise ValueError("reuse did not begin with an owned later-demand scan")
    if data["request"] is not None:
        request = data["request"]["fields"]
        if events[0]["request"] != request or request["demand"] in data["prior_need_refs"]:
            raise ValueError("request is not a post-certification owned need")
    terminal = data["terminal"]
    if terminal is not None and terminal != events[-1]:
        raise ValueError("autonomous-reuse terminal differs from history")
    attempts = loads(data["route_policy"])["attempts"]
    if len(attempts) > 1:
        raise ValueError("one later demand may create at most one route attempt")
    selected = None if not attempts else attempts[0]["selected"]["name"]
    if attempts and tuple(attempts[0]["retention_events"]) != tuple(retention["events"]):
        raise ValueError("route choice did not use the checkpoint retention evidence")
    if data["phase"] == "complete":
        if (terminal is None or terminal["consumer"] is None or terminal["settlement"] is None
                or fulfillment["fulfilled"] != 1 or len(attempts) != 1
                or attempts[0]["status"] != "complete"):
            raise ValueError("complete reuse lacks one paid route and settlement")
        traversal = attempts[0]["traversal"]
        settlement = terminal["settlement"]
        request_key = data["request"]["fields"]["key"]
        expected_reason = ("settled_after_applicable_retained_choice"
                           if selected == "retained" else "settled_after_nonretained_choice")
        if (terminal["reason"] != expected_reason
                or settlement["selection_key"] != request_key
                or settlement["movement_key"] != request_key + ":movement"
                or settlement["consumer_key"] != data["consumer_key"]
                or settlement["movement_output"] != traversal["movement_output"]
                or terminal["consumer"]["inputs"] != (traversal["movement_output"],)
                or terminal["consumer"]["output"] != settlement["consumer_output"]):
            raise ValueError("later choice, output consumption or settlement links differ")
        retained_rows = attempts[0]["retained"]
        bound = next((row for row in retained_rows
                      if row["key"] == data["certificate_key"]), None)
        if selected == "retained":
            if (bound is None or bound["eligible"] is not True
                    or attempts[0]["selected"]["certificate"] != data["certificate_key"]
                    or traversal["means"] != "retained"):
                raise ValueError("retained reuse lacks exact applicable certificate")
        elif bound is not None and bound["eligible"]:
            raise ValueError("applicable retained evidence was skipped")
    elif fulfillment["fulfilled"]:
        raise ValueError("non-complete reuse cannot claim fulfillment")
    return dict(passed=True, phase=data["phase"], selected=selected,
        retained=selected == "retained", revoked=data["certificate_key"] in retention["revoked"],
        capability=capability, fulfillment=fulfillment, route=route, events=len(events))
