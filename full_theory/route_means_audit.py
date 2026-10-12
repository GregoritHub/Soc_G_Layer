"""Independent FT4.2a reconstruction from raw journal and participant bytes."""
from hle.development_structure import lap, portage
from hle.model_a import element_at, fields as seat_fields, position_of
from hle_unified.compact import unseal, ValuePool
from hle_unified.material import attrs
from hle_unified.operations import indexed
from hle_unified.particulars import record_registry


def audit_route_means(transactions, row):
    if row.get("policy") != "owned-structural-means-v1":
        raise ValueError("FT4.2a audit: wrong policy")
    request = row.get("request", {})
    actor = row.get("actor")
    if (row.get("selected") is not None or row.get("completion_claim") is not False
            or request.get("actor") != actor or request.get("demand") != row.get("demand")
            or any(key in request for key in ("recipe", "route", "elements"))):
        raise ValueError("FT4.2a audit: request or non-choice boundary changed")
    raw = unseal(row["view"], "hle-unified-participant-value-v1")
    pool = ValuePool(record_registry()); pool.load_nodes(raw["nodes"])
    snapshot = pool.get(pool.import_token(raw["root"]))
    bindings = {binding.ref: binding for binding in snapshot.bindings}
    heads = {}
    for candidate in snapshot.bindings:
        if candidate.ref.identity not in heads or candidate.ref.revision > heads[candidate.ref.identity].ref.revision:
            heads[candidate.ref.identity] = candidate
    receipts = {receipt.ref: receipt for receipt in snapshot.receipts}
    binding = bindings.get(row["demand"])
    receipt = None if binding is None else receipts.get(binding.receipt)
    relation = "c6.need" if row.get("setting") == "canonical" else "c7ws.need"
    if (snapshot.actor != actor or binding is None or heads.get(binding.ref.identity) != binding or binding.actor != actor
            or binding.ref != request.get("demand") or binding.context != request.get("context")
            or binding.cue != request.get("cue") or binding.target.identity != request.get("target").identity
            or binding.endorsement.value in ("retracted", "disputed") or len(binding.content) != 1
            or binding.content[0].relation != relation or receipt is None or receipt.actor != actor
            or not receipt.complete or receipt.spent < receipt.required):
        raise ValueError("FT4.2a audit: demand is not current paid owned evidence")

    txs = tuple(transactions)
    if row.get("at_tick") != len(txs):
        raise ValueError("FT4.2a audit: journal boundary differs")
    profile = None; wallet = None; cursor = None
    for transaction in txs:
        for version in transaction.versions:
            data = attrs(version)
            if data.get("actor") != actor:
                continue
            if "tim" in data and "initial_active" in data:
                profile = data
                cursor = data["initial_active"] if cursor is None else cursor
            if data.get("record_type") == "wallet":
                wallet = dict(energy=data["energy"], time=data["time"])
            if "route_count" in data and data.get("completed", 0) > 0:
                left = max(0, data["completed"] - data["recall_units"])
                cursor = data["active_start"]
                stopped = False
                for i in range(data["route_count"]):
                    for j, charge in enumerate(indexed(data, "route." + str(i) + ".charges.")):
                        if left < charge:
                            stopped = True; break
                        left -= charge; cursor = data["route." + str(i) + ".path." + str(j + 1)]
                    if stopped:
                        break
                    cost = data["route." + str(i) + ".content_units"]
                    if left < cost:
                        break
                    left -= cost; cursor = data["route." + str(i) + ".element"]
    if profile is None or wallet is None or cursor is None:
        raise ValueError("FT4.2a audit: missing native profile, wallet or cursor")
    tim = profile["tim"]; seat = position_of(tim, cursor)
    if (row.get("tim"), row.get("active_element"), row.get("active_seat"), row.get("wallet")) != (tim, cursor, seat, wallet):
        raise ValueError("FT4.2a audit: native state snapshot differs")

    def expected(name, target, energy, time, eligible, reason):
        return dict(name=name, origin_seat=seat, origin_element=cursor,
            target_seat=target, target_element=element_at(tim, target),
            origin_fields=seat_fields(seat), target_fields=seat_fields(target),
            overhead=dict(energy=energy, time=time), eligible=eligible, reason=reason,
            content_cost_separate=name != "defer", completion_claim=False)
    ordinary = expected("ordinary", lap(seat), 0, 0, True, "structurally_available")
    n = expected("n", portage(seat, "n"), 0, 0, True,
        "reference_n_portage; native_content_unpriced_here")
    cp_ok = wallet["energy"] >= 2 and wallet["time"] >= 2
    cp_target = portage(seat, "cp")
    cp = expected("cp", cp_target, 2, 2, cp_ok,
        "orientation_read_affordable" if cp_ok else "insufficient_wallet_for_orientation_read")
    cp.update(orientation_read=request["key"] + ":cp-orientation",
        conjugated_lap=portage(lap(cp_target), "cp"), reverse_lap=lap(lap(lap(seat))))
    deferred = expected("defer", seat, 0, 0, True, "no_mean_selected_before_paid_choice")
    if row.get("options") != (ordinary, n, cp, deferred):
        raise ValueError("FT4.2a audit: geometry, overhead or reasons differ")
    return dict(passed=True, setting=row["setting"], options=4, cp_affordable=cp_ok,
        completion_claim=False)
