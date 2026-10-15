"""Independent FT7.1a clock, scope and receipt reconstruction.

Imports no packet adapter, executor or scheduler.
"""
from hashlib import sha256
from hle import model_a
from hle.relations import landing_position
from hle_unified.material import attrs
from hle_unified.records import Occurrence
from hle_unified.self_content import decode
from hle_unified.selection_records import loads
from .content_audit import audit_content


def audit_packet_channel(transactions, checkpoint, native_checkpoint):
    d = loads(checkpoint)
    fields = {"version", "native_sha256", "participants", "profiles", "turn", "sequences", "queue", "events", "bridge"}
    if (set(d) != fields or d["version"] != "ft-ordered-paid-packet-channel-v1"
            or d["native_sha256"] != sha256(native_checkpoint.encode()).hexdigest()):
        raise ValueError("channel/native pairing differs")
    participants = d["participants"]
    ident = lambda p:(p.namespace,p.key)
    if (type(participants) is not tuple or not 1 <= len(participants) <= 2
            or len(set(participants)) != len(participants)
            or tuple(sorted(participants,key=ident)) != participants):
        raise ValueError("invalid bounded participant domain")
    versions = {v.ref:v for tx in transactions for v in tx.versions}
    tim = {}
    for actor, ref, name in d["profiles"]:
        if (actor not in participants or actor in tim or ref not in versions
                or attrs(versions[ref]).get("tim") != name
                or attrs(versions[ref]).get("actor") != actor):
            raise ValueError("native profile binding differs")
        tim[actor] = name
    if set(tim) != set(participants):
        raise ValueError("native profile domain differs")
    bridge = d["bridge"]
    if set(bridge) != {"events","packets","receipts","kept","charge"}:
        raise ValueError("bridge state fields differ")
    content_audit = audit_content(transactions, bridge["events"])
    turn, sequence, queue, packets, receipts = 0, dict.fromkeys(participants,0), {}, {}, {}
    bridge_offset = 0
    for index, event in enumerate(d["events"]):
        if event.get("index") != index:
            raise ValueError("channel event indices differ")
        if event["kind"] == "emit":
            if set(event) != {"index","kind","turn","queue","packet","sender_seat","receiver_seat","relation_landing"} or event["turn"] != turn:
                raise ValueError("emission turn or fields differ")
            p = event["packet"]; key=p["key"]; sender=p["sender"]; receiver=p["receiver"]
            if key in queue or len(queue) >= 8 or sender not in participants or receiver not in participants:
                raise ValueError("emission domain differs")
            source=versions.get(p["output"])
            if source is None:
                raise ValueError("exact raw packet output missing")
            if source.occurrence==Occurrence.ACTUAL_EVENT:
                parties=tuple(v for k,v in attrs(source).items() if k.startswith("participant."))
                if receiver not in parties:
                    raise ValueError("raw event excludes packet recipient")
            elif p["output"].identity.namespace in ("c2.message","c3.message","c4.message","c7w.message"):
                body=decode(attrs(source)["payload"])
                parties=body.get("participants",()) or (body.get("speaker"),body.get("receiver"))
                if receiver not in parties:
                    raise ValueError("raw public payload excludes packet recipient")
            elif receiver!=sender:
                raise ValueError("private own realization cannot cross owners")
            expected = dict(key=key,due=turn+1,sender=sender,receiver=receiver,sender_sequence=sequence[sender],status="queued")
            if event["queue"] != expected:
                raise ValueError("emission schedule differs")
            sender_seat=model_a.position_of(tim[sender],p["aspect"])
            receiver_seat=model_a.position_of(tim[receiver],p["aspect"])
            if (event["sender_seat"],event["receiver_seat"],event["relation_landing"]) != (sender_seat,receiver_seat,landing_position(tim[sender],sender_seat,tim[receiver])):
                raise ValueError("unchanged relation landing differs")
            if bridge["events"][bridge_offset] != dict(kind="emit",packet=p):
                raise ValueError("emission lacks exact bridge evidence")
            bridge_offset+=1;sequence[sender]+=1;queue[key]=expected;packets[key]=p
        elif event["kind"] == "step":
            if set(event) != {"index","kind","turn","available","work_limit","ready","results","bridge_before","bridge_after"}:
                raise ValueError("step fields differ")
            turn+=1
            available=event["available"]
            if (event["turn"]!=turn or type(event["work_limit"]) is not int or event["work_limit"]<1
                    or tuple(sorted(available,key=ident))!=available or len(set(available))!=len(available)
                    or any(p not in participants for p in available) or event["bridge_before"]!=bridge_offset):
                raise ValueError("step clock, availability or bridge prefix differs")
            ready=sorted((r for r in queue.values() if r["due"]<=turn and r["status"]!="delivered"),
                         key=lambda r:(r["due"],ident(r["sender"]),r["sender_sequence"],ident(r["receiver"]),r["key"]))
            if event["ready"]!=tuple(r["key"] for r in ready) or len(event["results"])!=len(ready):
                raise ValueError("ready delivery order differs")
            segment=bridge["events"][bridge_offset:event["bridge_after"]]
            if not bridge_offset<=event["bridge_after"]<=len(bridge["events"]):
                raise ValueError("bridge suffix bounds differ")
            for row,result in zip(ready,event["results"]):
                if set(result)!={"key","status","receipt"} or result["key"]!=row["key"]:
                    raise ValueError("delivery result differs")
                key=row["key"]
                related=[e for e in segment if e.get("packet")==key]
                if row["receiver"] not in available:
                    if result!={"key":key,"status":"waiting","receipt":None} or related:
                        raise ValueError("withdrawal manufactured delivery")
                elif result["status"]=="partial":
                    if result["receipt"] is not None or related!=[dict(kind="uptake_partial",packet=key,actor=row["receiver"])]:
                        raise ValueError("partial uptake manufactured knowledge")
                    row["status"]="partial"
                elif result["status"]=="delivered":
                    receipt=result["receipt"]
                    if related!=[receipt] or receipt is None or receipt.get("kind")!="uptake" or receipt["actor"]!=row["receiver"]:
                        raise ValueError("delivery lacks exact paid receipt")
                    expected_seat=model_a.position_of(tim[row["receiver"]],packets[key]["aspect"])
                    cap=("experience","norms","situation","time")[:model_a.fields(expected_seat)["dimensionality"]]
                    if receipt["seat"]!=expected_seat or receipt["facets"]!=tuple(f for f in cap if f in packets[key]["facets"]):
                        raise ValueError("receipt changed receiver facet cap")
                    row["status"]="delivered";receipts[key]=receipt
                else:
                    raise ValueError("unknown delivery status")
            # Native read rows belong only to ready, available recipients.
            allowed={r["receiver"] for r in ready if r["receiver"] in available}
            if any(e.get("actor") not in allowed for e in segment if e["kind"]=="native_work"):
                raise ValueError("unavailable participant was charged")
            bridge_offset=event["bridge_after"]
        else:
            raise ValueError("unknown channel event")
    expected_kept={};expected_charge={}
    for receipt in receipts.values():
        key=(receipt["actor"],receipt["seat"])
        expected_kept[key]=(receipt["content"],receipt["facets"],receipt["receipt"])
        expected_charge[key]=receipt["facets"]
    if (d["turn"]!=turn or dict(d["sequences"])!=sequence
            or d["queue"]!=tuple(queue[k] for k in sorted(queue))
            or bridge["packets"]!=packets or bridge["receipts"]!=receipts
            or bridge_offset!=len(bridge["events"])
            or bridge["kept"]!=tuple((a,s,v) for (a,s),v in sorted(expected_kept.items()))
            or bridge["charge"]!=tuple((a,s,v) for (a,s),v in sorted(expected_charge.items()))):
        raise ValueError("terminal channel state differs from evidence")
    return dict(passed=True,independent=True,turns=turn,packets=len(packets),paid_uptakes=len(receipts),
        pending=len(packets)-len(receipts),native_content_audit=content_audit["passed"],
        scope="paid transport only; autonomous coupling and social retention remain pending")
