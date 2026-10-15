"""Independent FT7.1b1 packet-to-owned-choice and later use reconstruction.

Imports no audited wrapper, chooser, executor or scheduler. The accepted
reserve auditor receives read-only native record getters from its caller.
"""
from hashlib import sha256
from hle_unified import codec
from hle_unified.conditioning_audit import completed_use
from hle_unified.material import attrs
from hle_unified.selection_records import loads
from hle_unified.selection_records import dumps
from hle_unified.self_content import decode
from .fulfillment_audit import _snapshot
from .packet_channel_audit import audit_packet_channel
from .reserve_cycle_audit import audit_reserve_cycle
from .use_history_audit import audit_use_history


def audit_social_cycle(engine, checkpoint):
    d=loads(checkpoint);native=engine.checkpoint();transactions=tuple(engine.world.journal())
    fields={"version","native_sha256","actor","baseline","packet_key","required","phase","turn","channel","cycle","history","events","terminal"}
    if set(d)!=fields or d["version"]!="ft-packet-mediated-support-cycle-v1" or d["native_sha256"]!=sha256(native.encode()).hexdigest():
        raise ValueError("social/native pairing differs")
    channel=loads(d["channel"]);cycle=loads(d["cycle"]);history=loads(d["history"])
    channel_audit=audit_packet_channel(transactions,d["channel"],native)
    reserve_audit=audit_reserve_cycle(engine,d["cycle"])
    if cycle["actor"]!=d["actor"] or history["actor"]!=d["actor"] or history["policy"]!="success-v1":
        raise ValueError("shared native actor or history election differs")
    candidate=loads(cycle["candidates"]);reserve=loads(loads(candidate["binding"])["reserve"])
    if reserve["policy"]!="load-v1":raise ValueError("reserve election differs")
    baseline=d["baseline"]
    if type(baseline["journal_count"]) is not int or not 0<=baseline["journal_count"]<=len(transactions):
        raise ValueError("baseline journal prefix differs")
    prefix=transactions[:baseline["journal_count"]]
    profiles,counts=completed_use(prefix)
    expected=dict(actor=d["actor"],tim=profiles[d["actor"]],journal_count=len(prefix),
        journal_sha256=sha256(codec.dumps(prefix).encode()).hexdigest(),counts=counts[d["actor"]])
    if baseline!=expected:raise ValueError("raw paid-use baseline differs")
    key=d["packet_key"]
    packets=channel["bridge"]["packets"];receipts=channel["bridge"]["receipts"]
    if len(packets)>(1 if key else 0) or (key is not None and key not in packets):
        raise ValueError("one exact peer packet required")
    if key and (packets[key]["receiver"]!=d["actor"] or packets[key]["sender"]==d["actor"]):
        raise ValueError("peer ownership differs")
    if d["turn"]!=len(d["events"]) or channel["turn"]!=d["turn"]:
        raise ValueError("social/channel turn domain differs")
    if d["terminal"] is not None and (not d["events"] or d["terminal"]!=d["events"][-1]):
        raise ValueError("social terminal event differs")
    steps=[e for e in channel["events"] if e["kind"]=="step"]
    observed_cycle=[];observed_history=[]
    for index,event in enumerate(d["events"]):
        if set(event)!={"index","turn","phase","reason","before","after","intake","cycle_event","history_event","causal_link"}:
            raise ValueError("social step fields differ")
        if event["index"]!=index or event["turn"]!=index+1 or event["intake"]!=steps[index]:
            raise ValueError("social intake order differs")
        if not baseline["journal_count"]<=event["before"]<=event["after"]<=len(transactions):
            raise ValueError("social journal bounds differ")
        if index and event["before"]!=d["events"][index-1]["after"]:
            raise ValueError("social native journal continuity differs")
        status=next((r["status"] for r in event["intake"]["results"] if r["key"]==key),None)
        if event["cycle_event"] is None:
            if status not in ("partial","waiting") or event["phase"]!="intake" or event["reason"]!="pending_paid_peer_uptake" or event["history_event"] is not None or event["causal_link"] is not None:
                raise ValueError("pending uptake fabricated a native cycle")
        else:
            if key and key not in receipts:raise ValueError("native cycle lacks peer uptake")
            observed_cycle.append(event["cycle_event"])
        if event["history_event"] is not None:observed_history.append(event["history_event"])
    if observed_cycle!=cycle["events"] or observed_history!=history["events"]:
        raise ValueError("delegated cycle/history event domain differs")
    if d["required"]!=cycle["required"] and cycle["required"] is not None:
        raise ValueError("scoped demand identity differs")
    if cycle["request"] is not None:
        base_event=loads(cycle["demand_controller"])["events"][0]
        base=base_event["request"]["request"]
        requested=cycle["request"]["fields"]
        bridge=cycle["events"][0].get("public_intake")
        if cycle["request"]["setting"]=="workflow":
            snapshot=_snapshot(base_event["view"])
            found=set()
            for detail in snapshot.particulars:
                if detail.address.key!="payload" or detail.source.identity.namespace!="c7w.message":continue
                body=decode(detail.value)
                if (body.get("context"),body.get("target"))!=(base["context"],base["target"]):continue
                permitted=(body.get("kind")=="offer" and body.get("speaker")==d["actor"]
                    and body.get("receiver") in d["required"]["support_allowed"]) or (
                    body.get("kind")=="reply" and body.get("speaker") in d["required"]["support_allowed"]
                    and body.get("receiver")==d["actor"])
                if permitted:found.add(detail.source)
            before=base["accessible"];after=tuple(sorted(set(before)|found,key=dumps))
            expected_bridge=dict(policy="owned-public-workflow-intake-v1",base_request=base,
                before=before,after=after,added=tuple(ref for ref in after if ref not in before),
                view_sha256=sha256(base_event["view"].encode()).hexdigest())
            if bridge!=expected_bridge or not 1<=len(after)<=8 or requested["accessible"]!=after:
                raise ValueError("paid public workflow intake differs from owned snapshot")
            for field in base:
                if field not in ("accessible","peer","group") and requested[field]!=base[field]:
                    raise ValueError("public intake changed owned request identity")
        elif bridge is not None:
            raise ValueError("canonical request gained a workflow intake bridge")
    history_prefix=transactions[:history["journal_count"]]
    history_audit=audit_use_history(d["history"],history_prefix)
    versions={v.ref:v for tx in transactions for v in tx.versions}
    link=d["terminal"]["causal_link"] if d["terminal"] is not None else None
    if cycle["phase"]=="complete":
        route=loads(candidate["route_policy"]);attempt=route["attempts"][0]
        effect=cycle["effects"][-1];supported=effect["supported"]
        if d["phase"]!="complete" or history["journal_count"]!=len(transactions) or history["turn"]!=1:
            raise ValueError("completed social history boundary differs")
        tag="supported" if supported else "independent"
        if any(row["tag"]!=tag for row in history["events"][0]["classifications"]):
            raise ValueError("completion tag differs from actual traversal")
        if supported:
            if key not in receipts or attempt["support"]["ref"]!=packets[key]["output"]:
                raise ValueError("actual support is not the received peer output")
            receipt=receipts[key];traversal=attempt["traversal"];settlement=cycle["terminal"]["settlement"]
            expected_link=dict(packet=key,sender=packets[key]["sender"],receiver=d["actor"],
                peer_operation=packets[key]["operation"],source=packets[key]["output"],uptake_receipt=receipt["receipt"],
                support=attempt["support"],selection=traversal["selection"],movement=traversal["movement"],
                movement_output=traversal["movement_output"],consumer_key=cycle["consumer_key"],
                consumer_output=settlement["consumer_output"],supported=True,independent_capability=False)
            if link!=expected_link:raise ValueError("peer causal link differs")
            movement=attrs(versions[link["movement"]])
            inputs=tuple(v for k,v in movement.items() if k.startswith("input."))
            if link["source"] not in inputs:raise ValueError("chosen work did not consume exact peer reply")
            consumer=attrs(versions[cycle["terminal"]["consumer"]["operation"]])
            if link["movement_output"] not in tuple(v for k,v in consumer.items() if k.startswith("input.")):
                raise ValueError("later paid use did not consume selected output")
            if effect["completion_kind"]!="supported" or effect["reserve_event"]["delta"]!=-min(1,effect["reserve_event"]["balance_before"]):
                raise ValueError("supported reserve settlement differs")
            if any(history["scores"].values()) or any(history["events"][0]["credit_delta"].values()):
                raise ValueError("supported use manufactured independent conditioning credit")
        elif link is not None:raise ValueError("independent work claims a peer contribution")
    elif link is not None:raise ValueError("incomplete social cycle claims later use")
    if cycle["terminal"] is None:
        if history["event_count"]!=0 or history["journal_count"]!=baseline["journal_count"]:
            raise ValueError("partial or waiting cycle granted completed history")
    elif cycle["phase"]!="complete":
        if any(row["tag"]!="failed" for event in history["events"] for row in event["classifications"]):
            raise ValueError("unsuccessful attempt granted independent history")
    return dict(passed=True,independent=True,phase=d["phase"],packets=channel_audit["packets"],
        paid_uptakes=channel_audit["paid_uptakes"],settled=reserve_audit["fulfilled"],
        supported=link is not None,exact_peer_operand=link is not None,
        reserve_policy=reserve["policy"],conditioning_policy=history["policy"],
        history_paid_bound=history_audit["native_bound"],
        scope="packet-mediated support and paid later use; autonomous peer generation and scoped retention remain pending")
