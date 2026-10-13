"""Independent FT5.2a reconstruction; imports no native binding or ledger."""
from hashlib import sha256

from hle import model_a
from hle_unified.material import attrs
from hle_unified.selection_records import dumps, loads

from .reserve_audit import audit_reserve


def _job(engine, actor, row):
    if type(row) is not dict or set(row) != {"key", "operation", "status"}:
        raise ValueError("invalid native evidence row")
    key = row["key"]
    if type(key) is not str or not key or (actor, key) not in engine._jobs:
        raise ValueError("native job identity unavailable")
    status = engine.job_status(actor, key)
    if (row["operation"] != engine._jobs[actor, key] or row["status"] != status
            or status.get("status") != "succeeded"
            or type(status.get("required")) is not int or status["required"] <= 0
            or status.get("completed") != status["required"]
            or type(status.get("spent")) is not int or status["spent"] < status["required"]):
        raise ValueError("native payment or completion differs")
    return status


def audit_native_reserve(engine, checkpoint):
    data = loads(checkpoint)
    required = {"version", "native_sha256", "actor", "reserve", "admissions",
                "preparation_bindings", "replenishment_bindings", "used_jobs",
                "used_packets", "used_receipts"}
    if (type(data) is not dict or set(data) != required
            or data["version"] != "ft-native-reserve-binding-v1"
            or data["native_sha256"] != sha256(engine.checkpoint().encode()).hexdigest()):
        raise ValueError("invalid paired native reserve checkpoint")
    reserve_report = audit_reserve(data["reserve"])
    reserve = loads(data["reserve"])
    actor = data["actor"]
    if reserve["actor"] != actor:
        raise ValueError("native and reserve actor differ")
    if (set(data["admissions"]) != set(reserve["demands"])
            or set(data["preparation_bindings"]) != set(reserve["demands"])):
        raise ValueError("native admission inventory differs")

    preparation_jobs = set()
    complete = 0
    for demand_id, admission in data["admissions"].items():
        if (type(admission) is not dict
                or set(admission) != {"preexisting_jobs", "journal_count", "preparation"}
                or type(admission["journal_count"]) is not int
                or admission["journal_count"] < 0
                or admission["preparation"] != reserve["demands"][demand_id]["preparation"]):
            raise ValueError("admission boundary or obligation differs")
        rows = data["preparation_bindings"][demand_id]
        if type(rows) is not list or len(rows) > admission["preparation"]:
            raise ValueError("preparation exceeds obligation")
        for row in rows:
            status = _job(engine, actor, row)
            key = row["key"]
            if (key in admission["preexisting_jobs"] or key in preparation_jobs
                    or status.get("started_tick", -1) < admission["journal_count"]):
                raise ValueError("pre-admission or duplicate preparation evidence")
            preparation_jobs.add(key)
        complete += len(rows) == admission["preparation"]

    replenishment_jobs = set()
    packets = set()
    receipts = set()
    reserve_events = reserve["events"]
    tim = attrs(engine.world.resolve(engine._profiles[actor]))["tim"]
    for row in data["replenishment_bindings"]:
        expected = {"token_id", "packet_key", "packet", "uptake", "native", "reserve_event"}
        if type(row) is not dict or set(row) != expected:
            raise ValueError("invalid replenishment binding")
        packet_key = row["packet_key"]
        native = row["native"]
        status = _job(engine, actor, native)
        packet = row["packet"]
        uptake = row["uptake"]
        if (type(packet_key) is not str or not packet_key
                or native["key"] != "ft:read:" + packet_key
                or status.get("kind") != "read"
                or set(packet) != {"receiver", "output", "aspect"}
                or set(uptake) != {"actor", "source", "receipt", "seat"}
                or packet["receiver"] != actor or uptake["actor"] != actor
                or packet["output"] != uptake["source"] or uptake["seat"] != 5
                or model_a.position_of(tim, packet["aspect"]) != 5
                or native["operation"] != uptake["receipt"]):
            raise ValueError("replenishment is not exact paid A5 uptake")
        receipt_key = dumps(uptake["receipt"])
        receipt_id = "native-a5:" + sha256(receipt_key.encode()).hexdigest()
        event = row["reserve_event"]
        if (event not in reserve_events or event.get("kind") != "replenishment"
                or event.get("token_id") != row["token_id"]
                or event.get("receipt", {}).get("identity") != receipt_id
                or event.get("receipt", {}).get("actor") != actor
                or event.get("receipt", {}).get("seat") != 5
                or event.get("receipt", {}).get("paid") is not True):
            raise ValueError("reserve replenishment differs from native receipt")
        if (native["key"] in replenishment_jobs or packet_key in packets or receipt_key in receipts):
            raise ValueError("duplicate replenishment evidence")
        replenishment_jobs.add(native["key"]); packets.add(packet_key); receipts.add(receipt_key)

    if preparation_jobs & replenishment_jobs:
        raise ValueError("one native job credited to two reserve roles")
    if (tuple(sorted(preparation_jobs | replenishment_jobs)) != tuple(data["used_jobs"])
            or tuple(sorted(packets)) != tuple(data["used_packets"])
            or tuple(sorted(receipts)) != tuple(data["used_receipts"])):
        raise ValueError("used native evidence inventory differs")
    return dict(passed=True, actor=actor, policy=reserve["policy"],
                reserve_balance=reserve_report["balance"], demands=len(data["admissions"]),
                preparation_jobs=len(preparation_jobs), complete_preparations=complete,
                replenishments=len(data["replenishment_bindings"]))
