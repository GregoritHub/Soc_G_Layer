"""Independent FT4.2b2b1 reconstruction; imports no route-policy controller."""
from hashlib import sha256

from hle.model_a import fields as seat_fields
from hle_unified.material import attrs
from hle_unified.operations import address
from hle_unified.selection_records import loads

from .content import FACETS
from .orientation_audit import audit_orientation
from .retention import Demand, no_easier
from .retention_audit import audit_retention
from .route_execution_audit import audit_native_turns
from .route_means_audit import audit_route_means


SOCIAL = ("share", "coordinate", "educate", "identify", "mobilize",
          "institutionalize", "commune")


def _covered(seat, requirements):
    return set(requirements) <= set(FACETS[:seat_fields(seat)["dimensionality"]])


def audit_route_policy(transactions, access_text, checkpoint, native_text):
    data = loads(checkpoint); txs = tuple(transactions)
    required = {"version","native_sha256","relay","attempts","events",
                "native_controller","orientation_controller"}
    if (set(data) != required or data["version"] != "ft-td5-route-policy-v1"
            or data["native_sha256"] != sha256(native_text.encode()).hexdigest()):
        raise ValueError("route-policy paired source mismatch")
    native = audit_native_turns(txs,access_text,data["native_controller"],native_text)
    orientation = audit_orientation(txs,access_text,data["orientation_controller"],native_text)
    attempts={(a["actor"],a["key"]):a for a in data["attempts"]}
    if len(attempts)!=len(data["attempts"]):raise ValueError("duplicate route attempt")
    heads={v.ref.identity:v for tx in txs for v in tx.versions}
    relay={}; traversals=0; supports=0; retained=0; cp=0
    for a in data["attempts"]:
        request=a["request"]; demand=Demand(**a["demand"])
        if (request["actor"]!=a["actor"] or request["key"]!=a["key"]
                or (request["context"],request["cue"],request["target"])!=(demand.context,demand.cue,demand.target)
                or a["setting"]!=demand.family):raise ValueError("route scope differs")
        audit_route_means(txs[:a["inventory"]["at_tick"]],a["inventory"])
        if a["inventory"]["active_seat"]!=a["origin_seat"] or a["origin_dimension"]!=seat_fields(a["origin_seat"])["dimensionality"]:
            raise ValueError("relay origin differs from native inventory")
        cert=None
        if a["retention_events"]:
            audit_retention(txs,a["retention_events"])
            for row in a["retention_events"]:
                if row.get("kind")=="certificate" and any(x["key"]==row["key"] and x["eligible"] for x in a["retained"]):
                    if row["actor"]==a["actor"] and no_easier(Demand(**row["scope"]),demand):cert=row
        support=a["support"]
        if support is not None:
            d=support["data"]
            if (support["ref"] is None or d.get("kind")!="reply" or d.get("speaker")!=request.get("peer")
                    or d.get("receiver")!=a["actor"] or d.get("group")!=request.get("group")
                    or d.get("context")!=demand.context or d.get("target")!=demand.target
                    or d.get("consent") is not True or request.get("peer") not in demand.support_allowed):
                raise ValueError("support is not exact allowed consent")
        native_options={x["name"]:x for x in a["inventory"]["options"]}
        expected=[]
        ok=cert is not None and _covered(a["origin_seat"],demand.requirements)
        expected.append(("retained",ok,a["origin_seat"]))
        for name in ("ordinary","n","cp"):
            row=native_options[name];expected.append((name,bool(row["eligible"] and _covered(row["target_seat"],demand.requirements)),row["target_seat"]))
        expected.extend((("support",support is not None,a["origin_seat"]),("defer",True,a["origin_seat"])))
        got=[(x["name"],x["eligible"],x["target_seat"]) for x in a["options"]]
        if got!=expected or a["selected"]!=next(x for x in a["options"] if x["eligible"]):
            raise ValueError("TD5 priority or facet admission differs")
        traversal=a["traversal"]
        if traversal is None:continue
        means=a["selected"]["name"];actor=a["actor"];key=a["key"]
        movement_id=address("u4.operation",actor,key+":movement").identity
        selection_id=address("u4.operation",actor,key).identity
        if movement_id not in heads or selection_id not in heads:raise ValueError("missing linked native work")
        movement=attrs(heads[movement_id]);selection=attrs(heads[selection_id])
        if (movement["status"]!="succeeded" or movement["completed"]!=movement["required"]
                or movement.get("steps_completed")!=movement.get("route_count")
                or selection["status"]!="succeeded" or traversal["selection"]!=heads[selection_id].ref
                or traversal["movement"]!=heads[movement_id].ref or traversal["means"]!=means
                or traversal["origin_seat"]!=a["origin_seat"] or traversal["target_seat"]!=a["selected"]["target_seat"]
                or traversal["target_dimension"]!=seat_fields(traversal["target_seat"])["dimensionality"]
                or traversal["dimensionality_changed"] is not False or traversal["completion_claim"] is not False
                or traversal["content_processed"] is not True):raise ValueError("false relay/native traversal")
        ns="c7ws.decision" if a["setting"]=="workflow" else "c6.decision"
        decision=attrs(heads[address(ns,actor,key).identity])
        if decision["status"]!="launched":raise ValueError("relay precedes native launch")
        if means=="support":
            if not any(name in decision["recipe"] for name in SOCIAL) or traversal["support"]!=support or traversal["supported"] is not True:
                raise ValueError("support did not launch consenting social work")
            supports+=1
        elif traversal["supported"] is not False:raise ValueError("unsupported route labeled supported")
        if means=="cp":
            ticket=traversal["orientation"]
            if (ticket is None or ticket!=a["orientation_ticket"] or ticket["demand"]!=request["demand"]
                    or ticket["origin_seat"]!=a["origin_seat"] or ticket["target_seat"]!=traversal["target_seat"]
                    or ticket["traversal_claim"] is not False):raise ValueError("cp traversal lacks exact fee")
            cp+=1
        elif traversal["orientation"] is not None:raise ValueError("non-cp route claims orientation fee")
        retained+=int(means=="retained");traversals+=1;relay[actor]=traversal["target_seat"]
    if dict(data["relay"])!=relay:raise ValueError("relay checkpoint differs from completed traversals")
    if any(e["index"]!=i or e["completion_claim"] is not False for i,e in enumerate(data["events"])):
        raise ValueError("invalid policy event order")
    return dict(passed=True,attempts=len(attempts),events=len(data["events"]),traversals=traversals,
                retained=retained,cp=cp,supports=supports,native=native,orientation=orientation,
                completion_claim=False,opposition_pending=True)
