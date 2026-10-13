"""Independent reconstruction of FT5.3b reserve-grid cells."""
from hashlib import sha256

from hle_unified.selection_records import loads

from .reserve import preparation
from .reserve_candidates_audit import audit_reserve_candidates
from .reserve_grid import (BUDGETS, GRID_CELL_COUNT, cell_identity, grid_axes)


def audit_grid_cell(engine, cell):
    required = {"version", "cell_id", "axes", "demand", "work_limit",
                "wallet_before", "wallet_after", "native_before_sha256",
                "native_after_sha256", "candidate_event", "candidate_checkpoint"}
    if (type(cell) is not dict or set(cell) != required
            or cell["version"] != "ft5.3b-reserve-grid-cell-v1"
            or cell["work_limit"] != 1):
        raise ValueError("exact FT5.3b grid cell required")
    axes = cell["axes"]
    if axes not in grid_axes() or cell["cell_id"] != cell_identity(axes):
        raise ValueError("grid cell identity or axes differ")
    candidate = loads(cell["candidate_checkpoint"])
    binding = loads(candidate["binding"])
    reserve = loads(binding["reserve"])
    if (engine.resource_model != axes["wallet_model"]
            or reserve["policy"] != axes["policy"]
            or reserve["initial"] != axes["initial_reserve"]
            or len(reserve["tokens"]) != axes["token_inventory"]):
        raise ValueError("actual model, policy, reserve or tokens differ")
    budget = BUDGETS[axes["budget_class"]][axes["setting"]]
    before = cell["wallet_before"]
    if (before.get("initial_energy"), before.get("initial_time")) != (budget, budget):
        raise ValueError("actual initial wallet differs from frozen budget")
    if cell["wallet_after"] != engine.wallet(candidate["actor"]):
        raise ValueError("grid wallet after differs from native engine")
    native_after = sha256(engine.checkpoint().encode()).hexdigest()
    if candidate["native_sha256"] != native_after or cell["native_after_sha256"] != native_after:
        raise ValueError("grid native after identity differs")
    if len(candidate["events"]) != 1 or candidate["events"][0] != cell["candidate_event"]:
        raise ValueError("grid must contain one exact candidate step")
    event = candidate["events"][0]
    if event.get("load") != axes["load"] or event.get("policy") != axes["policy"]:
        raise ValueError("candidate axes differ")
    expected_preparation = preparation(axes["policy"], axes["initial_reserve"], axes["load"])
    if (event.get("preparation_required") != expected_preparation
            or event.get("preparation_remaining") != expected_preparation
            or reserve["balance"] != axes["initial_reserve"]
            or len(reserve["events"]) != 1
            or reserve["events"][0].get("kind") != "admission"):
        raise ValueError("admission preparation or reserve arithmetic differs")
    if len(event.get("route_options", ())) != 6:
        raise ValueError("native route inventory was hidden")
    candidate_report = audit_reserve_candidates(engine, cell["candidate_checkpoint"])
    if expected_preparation:
        if (event.get("phase") != "preparation"
                or cell["native_before_sha256"] != cell["native_after_sha256"]
                or cell["wallet_before"] != cell["wallet_after"]):
            raise ValueError("unpaid preparation changed native or reserve state")
    return {
        "passed": True,
        "cell_id": cell["cell_id"],
        "axes": axes,
        "preparation": expected_preparation,
        "phase": event["phase"],
        "selected_candidate": event["selected_candidate"],
        "reserve_balance": reserve["balance"],
        "wallet_delta": {
            unit: cell["wallet_before"][unit] - cell["wallet_after"][unit]
            for unit in ("energy", "time")
        },
        "candidate": candidate_report,
    }


def audit_complete_grid(reports):
    rows = tuple(reports)
    expected = {cell_identity(axes) for axes in grid_axes()}
    identities = [row.get("cell_id") for row in rows if type(row) is dict]
    if (len(rows) != GRID_CELL_COUNT or len(set(identities)) != GRID_CELL_COUNT
            or set(identities) != expected or any(row.get("passed") is not True for row in rows)):
        raise ValueError("complete independently passing frozen grid required")
    paired = {}
    for row in rows:
        axes = row["axes"]
        key = tuple((name, value) for name, value in axes.items()
                    if name != "token_inventory")
        signature = (row["preparation"], row["phase"], row["selected_candidate"],
                     row["reserve_balance"], row["wallet_delta"])
        paired.setdefault(key, {})[axes["token_inventory"]] = signature
    if (len(paired) != GRID_CELL_COUNT // 2
            or any(set(values) != {0, 2} or values[0] != values[2]
                   for values in paired.values())):
        raise ValueError("unused token inventory changed an admission outcome")
    return {"passed": True, "cells": len(rows), "token_pairs": len(paired)}
