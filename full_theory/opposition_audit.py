"""Independent reconstruction of the declared TD5 opposition sequence."""
from hashlib import sha256

from hle.development_structure import portage
from hle.model_a import fields as seat_fields, position
from hle_unified.material import attrs
from hle_unified.operations import address
from hle_unified.selection_records import loads

from .content import FACETS
from .orientation_audit import audit_orientation
from .retention import Demand
from .route_execution_audit import audit_native_turns
from .route_means_audit import audit_route_means


OBLIGATION = "opposition:cp-n-v1"
MOVES = ("cp", "n")


def _covered(seat, requirements):
    return set(requirements) <= set(FACETS[:seat_fields(seat)["dimensionality"]])


def audit_opposition(transactions, access_text, checkpoint, native_text):
    data = loads(checkpoint)
    txs = tuple(transactions)
    required = {"version", "native_sha256", "relay", "attempts", "events",
                "native_controller", "orientation_controller"}
    if (set(data) != required or data["version"] != "ft-td5-opposition-cp-n-v1"
            or data["native_sha256"] != sha256(native_text.encode()).hexdigest()):
        raise ValueError("opposition paired source mismatch")
    native = audit_native_turns(txs, access_text, data["native_controller"], native_text)
    orientation = audit_orientation(txs, access_text,
                                    data["orientation_controller"], native_text)
    attempts = {(row["actor"], row["key"]): row for row in data["attempts"]}
    if len(attempts) != len(data["attempts"]):
        raise ValueError("duplicate opposition attempt")
    heads = {version.ref.identity: version for tx in txs for version in tx.versions}
    native_attempts = {(row["actor"], row["key"]): row
                       for row in loads(data["native_controller"])["attempts"]}
    orientation_attempts = {(row["actor"], row["key"]): row
                            for row in loads(data["orientation_controller"])["attempts"]}
    relay = {}
    completed = 0
    deferred = 0
    for attempt in data["attempts"]:
        request = attempt["request"]
        demand = Demand(**attempt["demand"])
        if (request["actor"] != attempt["actor"] or request["key"] != attempt["key"]
                or (request["context"], request["cue"], request["target"])
                   != (demand.context, demand.cue, demand.target)
                or attempt["setting"] != demand.family
                or attempt["obligation"] != OBLIGATION
                or OBLIGATION not in demand.obligations or tuple(attempt["moves"]) != MOVES):
            raise ValueError("opposition declaration or scope differs")
        inventory = attempt["inventory"]
        audit_route_means(txs[:inventory["at_tick"]], inventory)
        origin = inventory["active_seat"]
        cp = portage(origin, "cp")
        final = portage(cp, "n")
        if (attempt["origin_seat"] != origin
                or attempt["origin_dimension"] != seat_fields(origin)["dimensionality"]
                or attempt["final_target"] != final or final != portage(origin, "a")):
            raise ValueError("opposition geometry differs")
        cp_option = next(row for row in inventory["options"] if row["name"] == "cp")
        expected = (
            (0, "cp", request["key"] + ":opposition:0:cp", origin, cp,
             bool(cp_option["eligible"] and _covered(cp, demand.requirements))),
            (1, "n", request["key"] + ":opposition:1:n", cp, final,
             _covered(final, demand.requirements)),
        )
        if len(attempt["legs"]) != 2:
            raise ValueError("opposition requires exactly two legs")
        for leg, row in zip(attempt["legs"], expected):
            index, move, key, leg_origin, target, eligible = row
            if ((leg["index"], leg["move"], leg["key"], leg["origin_seat"],
                 leg["target_seat"], leg["eligible"])
                    != (index, move, key, leg_origin, target, eligible)):
                raise ValueError("opposition leg geometry or admission differs")
        eligible = all(row[-1] for row in expected)
        if not eligible:
            if (attempt["status"] != "deferred" or attempt["current_leg"] != 0
                    or attempt["traversal"] is not None
                    or any(leg["traversal"] is not None for leg in attempt["legs"])):
                raise ValueError("ineligible opposition claimed progress")
            deferred += 1
            continue
        seen_finished = None
        for index, leg in enumerate(attempt["legs"]):
            traversal = leg["traversal"]
            if traversal is None:
                if any(later["traversal"] is not None for later in attempt["legs"][index + 1:]):
                    raise ValueError("opposition skipped an unfinished leg")
                continue
            key = leg["key"]
            pair = (attempt["actor"], key)
            if pair not in native_attempts:
                raise ValueError("opposition leg lacks native attempt")
            selection_id = address("u4.operation", attempt["actor"], key).identity
            movement_id = address("u4.operation", attempt["actor"], key + ":movement").identity
            if selection_id not in heads or movement_id not in heads:
                raise ValueError("opposition leg lacks linked native work")
            selection = attrs(heads[selection_id])
            movement = attrs(heads[movement_id])
            if (selection["status"] != "succeeded" or selection["completed"] != selection["required"]
                    or selection["spent"] != selection["required"]
                    or movement["status"] != "succeeded"
                    or movement["completed"] != movement["required"]
                    or movement["spent"] != movement["required"]
                    or movement.get("steps_completed") != movement.get("route_count")
                    or traversal["index"] != index or traversal["move"] != leg["move"]
                    or traversal["request_key"] != key
                    or traversal["origin_seat"] != leg["origin_seat"]
                    or traversal["target_seat"] != leg["target_seat"]
                    or traversal["selection"] != heads[selection_id].ref
                    or traversal["movement"] != heads[movement_id].ref
                    or traversal["content_processed"] is not True
                    or traversal["dimensionality_changed"] is not False
                    or traversal["completion_claim"] is not False):
                raise ValueError("opposition leg is not exact paid native work")
            if seen_finished is not None and selection["started_tick"] < seen_finished:
                raise ValueError("opposition native legs are not consecutive")
            seen_finished = movement["finished_tick"]
            if index == 0:
                ticket = leg["orientation_ticket"]
                if (pair not in orientation_attempts or ticket is None
                        or traversal["orientation"] != ticket
                        or ticket["energy"] != 2 or ticket["time"] != 2
                        or ticket["origin_seat"] != origin or ticket["target_seat"] != cp
                        or ticket["demand"] != request["demand"]
                        or ticket["traversal_claim"] is not False):
                    raise ValueError("opposition cp leg lacks its exact paid fee")
            elif leg["orientation_ticket"] is not None or traversal["orientation"] is not None:
                raise ValueError("opposition n leg claims an orientation fee")
        traversal = attempt["traversal"]
        if traversal is not None:
            legs = tuple(row["traversal"] for row in attempt["legs"])
            if (attempt["current_leg"] != 2 or attempt["status"] != "complete"
                    or any(row is None for row in legs)
                    or traversal["moves"] != MOVES or traversal["legs"] != legs
                    or traversal["origin_seat"] != origin
                    or traversal["final_target"] != final
                    or traversal["opposition"] is not True
                    or traversal["content_processed"] is not True
                    or traversal["dimensionality_changed"] is not False
                    or traversal["completion_claim"] is not False):
                raise ValueError("false completed opposition traversal")
            if position(origin)[0] != position(final)[0]:
                raise ValueError("opposition changed directive coordinate")
            relay[attempt["actor"]] = final
            completed += 1
    if dict(data["relay"]) != relay:
        raise ValueError("opposition relay checkpoint differs")
    if any(row["index"] != index or row["completion_claim"] is not False
           for index, row in enumerate(data["events"])):
        raise ValueError("invalid opposition event order")
    return dict(passed=True, attempts=len(attempts), events=len(data["events"]),
                completed=completed, deferred=deferred, native=native,
                orientation=orientation, sequence=MOVES,
                completion_claim=False, autonomous_cycle_pending=True)
