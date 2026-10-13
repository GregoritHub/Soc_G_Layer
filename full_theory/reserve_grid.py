"""Prospectively frozen FT5.3b demand order and reserve-grid execution."""
from copy import deepcopy
from hashlib import sha256
from itertools import product

from hle_unified.selection_records import SelectionRequest
from hle_unified.workflow_selection_records import WorkflowSelectionRequest

from .native_reserve import NativeReserveBinding
from .reserve import POLICIES, ReserveLedger
from .reserve_candidates import ReserveCandidateController
from .retention import Demand


SETTINGS = ("canonical", "workflow")
INITIAL_RESERVES = (0, 4, 8)
LOADS = (1, 2, 4)
TOKEN_INVENTORIES = (0, 2)
WALLET_MODELS = ("legacy-r4", "grade-v1")
BUDGET_CLASSES = ("ample", "scarce")
BUDGETS = {
    "ample": {"canonical": 200000, "workflow": 200000},
    "scarce": {"canonical": 87, "workflow": 55},
}
GRID_CELL_COUNT = 432


def no_easier(left, right):
    """True when ``left`` is no easier than ``right`` in the TD4 order."""
    if type(left) is not Demand or type(right) is not Demand:
        raise ValueError("two exact demands required")
    return (
        (left.family, left.context, left.cue, left.target)
        == (right.family, right.context, right.cue, right.target)
        and set(left.requirements) >= set(right.requirements)
        and set(left.obligations) >= set(right.obligations)
        and set(left.alternatives) <= set(right.alternatives)
        and left.load >= right.load
        and left.deadline <= right.deadline
        and set(left.support_allowed) <= set(right.support_allowed)
    )


def demand_relation(left, right):
    """Return the exact partial-order relation without scalarization."""
    left_right = no_easier(left, right)
    right_left = no_easier(right, left)
    if left_right and right_left:
        return "equivalent"
    if left_right:
        return "harder"
    if right_left:
        return "easier"
    return "incomparable"


def grid_axes():
    rows = []
    for values in product(SETTINGS, POLICIES, INITIAL_RESERVES, LOADS,
                          TOKEN_INVENTORIES, WALLET_MODELS, BUDGET_CLASSES):
        rows.append(dict(zip(("setting", "policy", "initial_reserve", "load",
                              "token_inventory", "wallet_model", "budget_class"), values)))
    if len(rows) != GRID_CELL_COUNT:
        raise AssertionError("frozen FT5.3b grid size differs")
    return tuple(rows)


def cell_identity(axes):
    required = ("setting", "policy", "initial_reserve", "load", "token_inventory",
                "wallet_model", "budget_class")
    if type(axes) is not dict or tuple(axes) != required:
        raise ValueError("ordered exact grid axes required")
    return "ft5.3b:" + ":".join(str(axes[name]) for name in required)


def _setting(request):
    if type(request) is SelectionRequest:
        return "canonical"
    if type(request) is WorkflowSelectionRequest:
        return "workflow"
    raise ValueError("exact native request required")


def run_grid_cell(engine, request, demand, axes, *, work_limit=1):
    """Run one actual reserve-conditioned candidate admission/step."""
    if type(demand) is not Demand or type(work_limit) is not int or work_limit != 1:
        raise ValueError("exact demand and frozen unit work limit required")
    identity = cell_identity(axes)
    setting = _setting(request)
    if axes not in grid_axes() or axes["setting"] != setting or demand.family != setting:
        raise ValueError("cell is outside the frozen grid or demand setting")
    if demand.load != axes["load"]:
        raise ValueError("demand load differs from frozen cell")
    if engine.resource_model != axes["wallet_model"]:
        raise ValueError("actual native wallet model differs from grid coordinate")
    wallet_before = deepcopy(engine.wallet(request.actor))
    expected_budget = BUDGETS[axes["budget_class"]][setting]
    if (wallet_before.get("initial_energy"), wallet_before.get("initial_time")) != (
            expected_budget, expected_budget):
        raise ValueError("actual finite native budget differs from grid coordinate")
    tokens = tuple(identity + ":token:" + str(index)
                   for index in range(axes["token_inventory"]))
    ledger = ReserveLedger(request.actor, axes["policy"],
                           initial=axes["initial_reserve"], tokens=tokens)
    controller = ReserveCandidateController(engine, NativeReserveBinding(engine, ledger))
    native_before = sha256(engine.checkpoint().encode()).hexdigest()
    event = controller.step(engine, request, demand, work_limit=work_limit)
    checkpoint = controller.checkpoint(engine)
    native_after = sha256(engine.checkpoint().encode()).hexdigest()
    return {
        "version": "ft5.3b-reserve-grid-cell-v1",
        "cell_id": identity,
        "axes": deepcopy(axes),
        "demand": demand.record(),
        "work_limit": work_limit,
        "wallet_before": wallet_before,
        "wallet_after": deepcopy(engine.wallet(request.actor)),
        "native_before_sha256": native_before,
        "native_after_sha256": native_after,
        "candidate_event": event,
        "candidate_checkpoint": checkpoint,
    }


def select_release_policy(reports, *, paid_recovery_predecessor=True):
    """Apply the frozen TD4 election; never optimize from observed outcomes."""
    expected = tuple(cell_identity(axes) for axes in grid_axes())
    rows = tuple(reports)
    observed = tuple(row.get("cell_id") for row in rows if type(row) is dict)
    reasons = []
    if not paid_recovery_predecessor:
        reasons.append("FT5.3a paid recovery predecessor is not accepted")
    if len(rows) != GRID_CELL_COUNT:
        reasons.append("grid is incomplete")
    if len(set(observed)) != len(observed):
        reasons.append("grid contains duplicate identities")
    if set(observed) != set(expected):
        reasons.append("grid identity set differs from frozen Cartesian product")
    if any(row.get("passed") is not True for row in rows if type(row) is dict):
        reasons.append("one or more independently audited cells failed")
    if reasons:
        return {"status": "held", "selected": None,
                "alternatives": POLICIES, "reasons": tuple(reasons)}
    return {"status": "selected", "selected": "load-v1",
            "alternatives": POLICIES,
            "reasons": ("complete frozen grid passed",
                        "load-v1 is the prospectively declared minimal non-null candidate",
                        "C13 and TD4 theoretical realism remain open")}
