"""Independent FT4.3b2a reconstruction; imports no capability controller."""
from hashlib import sha256

from hle_unified.development_values import attrs as development_attrs
from hle_unified.material import attrs
from hle_unified.selection_records import dumps, loads

from .autonomous_closure_audit import audit_autonomous_closure
from .retention_audit import audit_retention


def _paid(row, actor):
    return (row.get("actor") == actor and row.get("status", "succeeded") == "succeeded"
            and row.get("required", 0) > 0 and row.get("completed") == row.get("required")
            and row.get("spent", 0) >= row.get("required", 0))


def _scope(row):
    return row.get("content_target", row.get("target"))


def _raw_candidates(transactions, actor, demand):
    txs = tuple(transactions)
    versions = {version.ref: version for tx in txs for version in tx.versions}
    heads = {version.ref.identity: version for tx in txs for version in tx.versions}
    operations = []
    for version in heads.values():
        row = attrs(version)
        if version.ref.identity.namespace == "u4.operation" and _paid(row, actor):
            operations.append(dict(ref=version.ref, row=row))
    operations.sort(key=lambda item: (item["row"].get("finished_tick", 10**18),
                                      item["row"].get("started_tick", 10**18), dumps(item["ref"])))
    practices = {}
    capacities = []
    for version in heads.values():
        namespace = version.ref.identity.namespace
        if namespace == "u8.practice":
            row = development_attrs(version)
            if row.get("actor") == actor:
                practices[row["ref"]] = row
        elif namespace == "u8.capacity":
            row = development_attrs(version)
            if row.get("actor") == actor:
                capacities.append(row)
    candidates = []
    for capacity in capacities:
        if ((capacity["context"], capacity["cue"]) != (demand["context"], demand["cue"])
                or demand["load"] > capacity["max_load"]):
            continue
        operation = attrs(heads[capacity["operation"].identity])
        if not _paid(operation, actor):
            continue
        try:
            examples = tuple(practices[ref] for ref in capacity["examples"])
        except KeyError:
            continue
        if (len(examples) < 2 or any(not row["independent"] or row["supported"] for row in examples)
                or len({row["event"] for row in examples}) != len(examples)
                or len({target.identity for row in examples for target in row["targets"]}) < 2):
            continue
        chosen = []
        used = set()
        for example in examples:
            practice = attrs(heads[example["operation"].identity])
            response = development_attrs(versions[example["response"]])
            response_job = attrs(heads[response["operation"].identity])
            eligible = [item for item in operations if item["ref"] not in used
                and not item["row"].get("u8") and item["row"].get("route_count", 0) > 0
                and item["row"].get("context") == demand["context"]
                and _scope(item["row"]) in example["targets"]
                and response_job["finished_tick"] <= item["row"]["started_tick"]
                and item["row"]["finished_tick"] <= practice["finished_tick"]]
            if not eligible:
                chosen = []
                break
            chosen.append(eligible[0])
            used.add(eligible[0]["ref"])
        if len(chosen) != len(examples):
            continue
        refs = tuple(item["ref"] for item in chosen)
        order = (operation.get("finished_tick", 10**18), dumps(capacity["ref"]),
                 tuple(dumps(ref) for ref in refs))
        candidates.append(dict(capacity_ref=capacity["ref"], content_use_refs=refs, order=order))
    return tuple(sorted(candidates, key=lambda row: row["order"]))


def audit_autonomous_capability(transactions, access_text, checkpoint,
                                closure_checkpoint, cycle_checkpoint, native_checkpoint):
    data = loads(checkpoint)
    required = {"version", "native_sha256", "closure_sha256", "actor", "demand",
                "phase", "certificate_key", "events", "retention_events"}
    if (set(data) != required or data["version"] != "ft-autonomous-capability-discovery-v1"
            or data["native_sha256"] != sha256(native_checkpoint.encode()).hexdigest()
            or data["closure_sha256"] != sha256(closure_checkpoint.encode()).hexdigest()):
        raise ValueError("autonomous-capability paired source mismatch")
    closure = audit_autonomous_closure(transactions, access_text, closure_checkpoint,
        cycle_checkpoint, native_checkpoint)
    if not closure["closed"]:
        raise ValueError("capability does not follow honest closure")
    retention = audit_retention(transactions, data["retention_events"])
    closure_data = loads(closure_checkpoint)
    prefix = closure_data["retention_events"]
    if data["retention_events"][:len(prefix)] != prefix:
        raise ValueError("capability rewrote closure evidence")
    candidates = _raw_candidates(transactions, data["actor"], data["demand"])
    certified = data["phase"] == "certified"
    certificates = [row for row in data["retention_events"][len(prefix):]
                    if row.get("kind") == "certificate"]
    events = [row for row in data["events"] if row["kind"] == "capability_certificate"]
    if certified:
        if len(certificates) != 1 or len(events) != 1 or not candidates:
            raise ValueError("certified capability lacks unique raw evidence")
        event = events[0]
        summaries = tuple(dict(capacity_ref=row["capacity_ref"],
                               content_use_refs=row["content_use_refs"], order=row["order"])
                          for row in candidates)
        certificate = certificates[0]
        if (event["candidates"] != summaries or event["selected"]["capacity_ref"] != candidates[0]["capacity_ref"]
                or event["selected"]["content_use_refs"] != candidates[0]["content_use_refs"]
                or event["selected"]["order"] != candidates[0]["order"]
                or event["certificate"] != certificate or data["certificate_key"] != certificate["key"]
                or event["certified"] is not True or certificate["claim"] != "guarded_content_participation"
                or certificate["material_competence"] is not False):
            raise ValueError("forged discovery, order or certificate claim")
    elif certificates or events or data["certificate_key"] is not None:
        raise ValueError("open capability checkpoint contains certification")
    if any(row["index"] != i for i, row in enumerate(data["events"])):
        raise ValueError("invalid capability event order")
    return dict(passed=True, phase=data["phase"], certified=certified,
                candidates=len(candidates), certificates=len(certificates),
                closure=closure, retention=retention)
