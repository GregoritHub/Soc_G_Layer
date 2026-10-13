"""FT5.2a binding of reserve evidence to already-paid native work."""
from copy import deepcopy
from hashlib import sha256

from hle import model_a
from hle_unified.material import attrs
from hle_unified.selection_records import dumps, loads

from .reserve import ReserveLedger


def _identity(value, name):
    if type(value) is not str or not value:
        raise ValueError(name + " must be a nonempty string identity")
    return value


def _native_hash(engine):
    return sha256(engine.checkpoint().encode()).hexdigest()


def _job(engine, actor, key):
    key = _identity(key, "native job")
    if (actor, key) not in engine._jobs:
        raise ValueError("authoritative native job is absent")
    status = engine.job_status(actor, key)
    if (status.get("status") != "succeeded"
            or type(status.get("required")) is not int or status["required"] <= 0
            or status.get("completed") != status["required"]
            or type(status.get("spent")) is not int
            or status["spent"] < status["required"]):
        raise ValueError("distinct fully paid succeeded native job required")
    return dict(key=key, operation=engine._jobs[actor, key], status=deepcopy(status))


class NativeReserveBinding:
    VERSION = "ft-native-reserve-binding-v1"

    def __init__(self, engine, ledger):
        if type(ledger) is not ReserveLedger:
            raise ValueError("exact FT5.1 reserve ledger required")
        engine.wallet(ledger.actor)
        self.actor = ledger.actor
        self.ledger = ledger
        self.admissions = {}
        self.preparation_bindings = {}
        self.replenishment_bindings = []
        self.used_jobs = set()
        self.used_packets = set()
        self.used_receipts = set()

    def admit(self, engine, demand_id, load):
        demand_id = _identity(demand_id, "demand")
        if demand_id in self.admissions:
            raise ValueError("native admission identity already recorded")
        before = tuple(sorted(key for actor, key in engine._jobs if actor == self.actor))
        event = self.ledger.admit(demand_id, load)
        self.admissions[demand_id] = dict(preexisting_jobs=before,
            journal_count=len(engine.world.journal()), preparation=event["preparation"])
        self.preparation_bindings[demand_id] = []
        return deepcopy(event)

    def bind_preparation(self, engine, demand_id, operation_keys):
        demand_id = _identity(demand_id, "demand")
        if demand_id not in self.admissions:
            raise ValueError("native admission boundary required")
        if type(operation_keys) not in (tuple, list) or not operation_keys:
            raise ValueError("one or more native preparation jobs required")
        keys = tuple(_identity(value, "native job") for value in operation_keys)
        if len(keys) != len(set(keys)):
            raise ValueError("duplicate preparation job")
        rows = self.preparation_bindings[demand_id]
        obligation = self.admissions[demand_id]["preparation"]
        if len(rows) + len(keys) > obligation:
            raise ValueError("preparation binding exceeds exact obligation")
        before = engine.checkpoint()
        additions = []
        for key in keys:
            if key in self.admissions[demand_id]["preexisting_jobs"]:
                raise ValueError("pre-admission work cannot satisfy preparation")
            if key in self.used_jobs:
                raise ValueError("native work identity already bound")
            additions.append(_job(engine, self.actor, key))
            if additions[-1]["status"].get("started_tick", -1) < self.admissions[demand_id]["journal_count"]:
                raise ValueError("pre-admission work cannot satisfy preparation")
        if engine.checkpoint() != before:
            raise ValueError("binding must not mutate or reprice native work")
        rows.extend(additions)
        self.used_jobs.update(keys)
        return dict(demand_id=demand_id, required=obligation, bound=len(rows),
                    remaining=obligation - len(rows), complete=len(rows) == obligation,
                    demand_status=self.ledger.demands[demand_id]["status"])

    def replenish_from_uptake(self, engine, bridge, token_id, packet_key):
        token_id = _identity(token_id, "token")
        packet_key = _identity(packet_key, "packet")
        if getattr(bridge, "engine", None) is not engine:
            raise ValueError("uptake bridge must belong to paired native engine")
        if packet_key not in bridge.packets or packet_key not in bridge.receipts:
            raise ValueError("completed exact paid uptake required")
        packet = bridge.packets[packet_key]
        uptake = bridge.receipts[packet_key]
        if (packet.get("receiver") != self.actor or uptake.get("actor") != self.actor
                or uptake.get("source") != packet.get("output")
                or uptake.get("seat") != 5
                or model_a.position_of(attrs(engine.world.resolve(engine._profiles[self.actor]))["tim"],
                                       packet.get("aspect")) != 5):
            raise ValueError("exact same-actor A5 uptake required")
        job_key = "ft:read:" + packet_key
        native = _job(engine, self.actor, job_key)
        if native["operation"] != uptake.get("receipt") or native["status"].get("kind") != "read":
            raise ValueError("uptake receipt differs from authoritative paid native read")
        receipt_key = dumps(uptake["receipt"])
        if (job_key in self.used_jobs or packet_key in self.used_packets
                or receipt_key in self.used_receipts):
            raise ValueError("native replenishment evidence already bound")
        before = engine.checkpoint()
        receipt_id = "native-a5:" + sha256(receipt_key.encode()).hexdigest()
        reserve_event = self.ledger.replenish(token_id, dict(identity=receipt_id,
            actor=self.actor, token_id=token_id, source="external", seat=5,
            status="succeeded", paid=True))
        if engine.checkpoint() != before:
            raise ValueError("replenishment binding must not charge native work twice")
        row = dict(token_id=token_id, packet_key=packet_key,
            packet=dict(receiver=packet["receiver"], output=packet["output"],
                        aspect=packet["aspect"]),
            uptake=dict(actor=uptake["actor"], source=uptake["source"],
                        receipt=uptake["receipt"], seat=uptake["seat"]),
            native=native, reserve_event=reserve_event)
        self.replenishment_bindings.append(row)
        self.used_jobs.add(job_key)
        self.used_packets.add(packet_key)
        self.used_receipts.add(receipt_key)
        return deepcopy(row)

    def checkpoint(self, engine):
        return dumps(dict(version=self.VERSION, native_sha256=_native_hash(engine),
            actor=self.actor, reserve=self.ledger.checkpoint(),
            admissions=self.admissions,
            preparation_bindings=self.preparation_bindings,
            replenishment_bindings=self.replenishment_bindings,
            used_jobs=tuple(sorted(self.used_jobs)),
            used_packets=tuple(sorted(self.used_packets)),
            used_receipts=tuple(sorted(self.used_receipts))))

    @classmethod
    def restore(cls, text, engine):
        data = loads(text)
        required = {"version", "native_sha256", "actor", "reserve", "admissions",
                    "preparation_bindings", "replenishment_bindings", "used_jobs",
                    "used_packets", "used_receipts"}
        if (type(data) is not dict or set(data) != required
                or data["version"] != cls.VERSION
                or data["native_sha256"] != _native_hash(engine)):
            raise ValueError("exact paired native reserve checkpoint required")
        ledger = ReserveLedger.restore(data["reserve"])
        if ledger.actor != data["actor"]:
            raise ValueError("reserve and native actor differ")
        result = cls(engine, ledger)
        result.admissions = data["admissions"]
        result.preparation_bindings = data["preparation_bindings"]
        result.replenishment_bindings = data["replenishment_bindings"]
        result.used_jobs = set(data["used_jobs"])
        result.used_packets = set(data["used_packets"])
        result.used_receipts = set(data["used_receipts"])
        for rows in result.preparation_bindings.values():
            for row in rows:
                if _job(engine, result.actor, row["key"]) != row:
                    raise ValueError("preparation native state differs")
        for row in result.replenishment_bindings:
            if _job(engine, result.actor, row["native"]["key"]) != row["native"]:
                raise ValueError("replenishment native state differs")
        if result.checkpoint(engine) != text:
            raise ValueError("native reserve checkpoint differs from exact restoration")
        return result
