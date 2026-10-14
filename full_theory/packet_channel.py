"""FT7.1a ordered bounded transport; native ContentBridge owns paid uptake."""
from copy import deepcopy
from hashlib import sha256

from hle import model_a
from hle.relations import landing_position
from hle_unified.records import ObjectId
from hle_unified.selection_records import dumps, loads
from .content import ContentBridge


def identity(actor):
    return actor.namespace, actor.key


def order(row):
    return (row["due"], identity(row["sender"]), row["sender_sequence"],
            identity(row["receiver"]), row["key"])


class PacketChannel:
    VERSION = "ft-ordered-paid-packet-channel-v1"

    def __init__(self, engine, participants):
        participants = tuple(sorted(participants, key=identity))
        if (not 1 <= len(participants) <= 2 or len(set(participants)) != len(participants)
                or any(type(p) is not ObjectId or p not in engine._profiles for p in participants)):
            raise ValueError("one or two exact native participants required")
        self.participants = participants
        self.bridge = ContentBridge(engine)
        self.turn = 0
        self.sequences = {p: 0 for p in participants}
        self.queue = {}
        self.events = []

    def emit(self, key, sender, operation_key, receiver, output=None):
        if sender not in self.participants or receiver not in self.participants:
            raise ValueError("packet must stay inside the declared participant channel")
        if type(key) is not str or not key or key in self.queue or len(self.queue) >= 8:
            raise ValueError("unused packet identity within eight-packet bound required")
        packet = self.bridge.emit(key, sender, operation_key, receiver, output)
        row = dict(key=key, due=self.turn+1, sender=sender, receiver=receiver,
                   sender_sequence=self.sequences[sender], status="queued")
        self.sequences[sender] += 1
        self.queue[key] = row
        source = self.bridge.completed(sender, operation_key)
        receiver_seat = model_a.position_of(self.bridge.tim(receiver), packet["aspect"])
        self.events.append(dict(index=len(self.events), kind="emit", turn=self.turn,
            queue=deepcopy(row), packet=deepcopy(packet), sender_seat=source["seat"],
            receiver_seat=receiver_seat,
            relation_landing=landing_position(self.bridge.tim(sender), source["seat"], self.bridge.tim(receiver))))
        return deepcopy(row)

    def step(self, *, available, work_limit=1):
        if type(work_limit) is not int or work_limit < 1:
            raise ValueError("positive exact paid-work bound required")
        available = tuple(sorted(available, key=identity))
        if len(set(available)) != len(available) or any(p not in self.participants for p in available):
            raise ValueError("availability cannot introduce a channel participant")
        self.turn += 1
        ready = sorted((r for r in self.queue.values() if r["due"] <= self.turn
                        and r["status"] != "delivered"), key=order)
        before = len(self.bridge.events)
        results = []
        for row in ready:
            if row["receiver"] not in available:
                results.append(dict(key=row["key"], status="waiting", receipt=None))
                continue
            receipt = self.bridge.receive(row["key"], row["receiver"], quantum=work_limit)
            row["status"] = "delivered" if receipt is not None else "partial"
            results.append(dict(key=row["key"], status=row["status"], receipt=deepcopy(receipt)))
        event = dict(index=len(self.events), kind="step", turn=self.turn,
            available=available, work_limit=work_limit, ready=tuple(r["key"] for r in ready),
            results=tuple(results), bridge_before=before, bridge_after=len(self.bridge.events))
        self.events.append(event)
        return deepcopy(event)

    def checkpoint(self):
        engine = self.bridge.engine
        profiles = tuple((actor, engine._profiles[actor], self.bridge.tim(actor)) for actor in self.participants)
        return dumps(dict(version=self.VERSION, native_sha256=sha256(engine.checkpoint().encode()).hexdigest(),
            participants=self.participants, profiles=profiles, turn=self.turn,
            sequences=tuple((p, self.sequences[p]) for p in self.participants),
            queue=tuple(deepcopy(self.queue[k]) for k in sorted(self.queue)), events=deepcopy(self.events),
            bridge=dict(events=deepcopy(self.bridge.events), packets=deepcopy(self.bridge.packets),
                receipts=deepcopy(self.bridge.receipts),
                kept=tuple((actor, seat, value) for (actor, seat), value in sorted(self.bridge.kept.items())),
                charge=tuple((actor, seat, value) for (actor, seat), value in sorted(self.bridge.charge.items())))))

    @classmethod
    def restore(cls, text, engine):
        data = loads(text)
        if data.get("version") != cls.VERSION or data.get("native_sha256") != sha256(engine.checkpoint().encode()).hexdigest():
            raise ValueError("exact paired native channel checkpoint required")
        from .packet_channel_audit import audit_packet_channel
        audit_packet_channel(tuple(engine.world.journal()), text, engine.checkpoint())
        result = cls(engine, data["participants"])
        result.turn = data["turn"]
        result.sequences = dict(data["sequences"])
        result.queue = {r["key"]:deepcopy(r) for r in data["queue"]}
        result.events = deepcopy(data["events"])
        bridge = data["bridge"]
        result.bridge.events = deepcopy(bridge["events"])
        result.bridge.packets = deepcopy(bridge["packets"])
        result.bridge.receipts = deepcopy(bridge["receipts"])
        result.bridge.kept = {(actor, seat):value for actor, seat, value in bridge["kept"]}
        result.bridge.charge = {(actor, seat):value for actor, seat, value in bridge["charge"]}
        return result
