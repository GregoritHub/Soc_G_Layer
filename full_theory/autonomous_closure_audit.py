"""Independent reconstruction for FT4.3b1; imports no closure controller."""
from hashlib import sha256

from hle_unified.material import attrs
from hle_unified.selection_records import loads

from .autonomous_cycle_audit import audit_autonomous_cycle
from .historical import type_map
from .retention_audit import audit_retention


def audit_autonomous_closure(transactions, access_text, closure_checkpoint,
                             cycle_checkpoint, native_checkpoint):
    data = loads(closure_checkpoint)
    required = {"version", "native_sha256", "cycle_sha256", "actor", "demand",
                "phase", "used", "events", "retention_events"}
    if (set(data) != required or data["version"] != "ft-honest-closure-discovery-v1"
            or data["native_sha256"] != sha256(native_checkpoint.encode()).hexdigest()
            or data["cycle_sha256"] != sha256(cycle_checkpoint.encode()).hexdigest()):
        raise ValueError("autonomous-closure paired source mismatch")
    cycle = audit_autonomous_cycle(transactions, access_text, cycle_checkpoint, native_checkpoint)
    if cycle["phase"] != "complete" or not cycle["settled"]:
        raise ValueError("honest closure does not follow settled autonomous work")
    retention = audit_retention(transactions, data["retention_events"])
    txs = tuple(transactions)
    versions = {version.ref: version for tx in txs for version in tx.versions}
    heads = {version.ref.identity: version for tx in txs for version in tx.versions}
    exposure_events = [row for row in data["events"] if row["kind"] == "closure_exposure"]
    if len(exposure_events) != len(data["retention_events"]):
        raise ValueError("discovery and retention event counts differ")
    previous_order = None
    used = set()
    for event, row in zip(exposure_events, data["retention_events"]):
        if event["retention"] != row or event["closed"] != row["closed"]:
            raise ValueError("discovered exposure differs from retained event")
        candidate = event["candidate"]
        token = (candidate["consumer_ref"], candidate["shell_ref"])
        if (token in used or token not in set(data["used"])
                or any(candidate["consumer_ref"] in prior or candidate["shell_ref"] in prior
                       for prior in used)):
            raise ValueError("duplicate or missing discovered evidence")
        used.add(token)
        consumer = attrs(heads[candidate["consumer_ref"].identity])
        shell = attrs(heads[candidate["shell_ref"].identity])
        if (candidate["consumer_ref"] not in versions or candidate["shell_ref"] not in versions
                or row["consumer"] != candidate["consumer_ref"]
                or row["shell"]["operation"] != candidate["shell_ref"]
                or shell.get("purpose") != "encounter" or shell.get("target") != data["demand"]["target"]
                or consumer.get("context") != data["demand"]["context"]):
            raise ValueError("forged consumer, Shell or scope link")
        chain = []
        for ref in candidate["return_refs"]:
            if ref not in versions:
                raise ValueError("missing return work")
            operation = attrs(heads[ref.identity]); chain.append(operation)
        if not chain or tuple((item.get("binding") or item.get("result")) for item in chain) != candidate["kept"]:
            raise ValueError("kept content differs from paid return outputs")
        tm = type_map(chain[0]["tim"])
        if chain[0].get("origin") != tm["complementary_perspective"] or chain[-1].get("destination") != tm["native_perspective"]:
            raise ValueError("return path does not cross complement to native")
        for left, right in zip(chain, chain[1:]):
            inputs = tuple(value for key, value in right.items() if key.startswith("input."))
            if left.get("destination") != right.get("origin") or (left.get("binding") or left.get("result")) not in inputs:
                raise ValueError("return successor did not consume predecessor output")
        order = tuple(candidate["order"])
        if previous_order is not None and order < previous_order:
            raise ValueError("candidate chronology was reordered")
        previous_order = order
    closed = bool(data["retention_events"] and data["retention_events"][-1]["closed"])
    if (data["phase"] == "closed") != closed:
        raise ValueError("closure phase differs from reconstructed continuity")
    return dict(passed=True, phase=data["phase"], closed=closed,
                exposures=len(exposure_events), cycle=cycle, retention=retention)
