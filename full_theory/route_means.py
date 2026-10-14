"""Owned structural route means before paid selection or execution."""
from dataclasses import fields

from hle.development_structure import lap, portage
from hle.model_a import element_at, fields as seat_fields, position_of
from hle_unified.selection_records import SelectionRequest
from hle_unified.workflow_selection_records import WorkflowSelectionRequest


POLICY = "owned-structural-means-v1"
CP_ENERGY = 2
CP_TIME = 2


def _request_fields(request):
    return {field.name: getattr(request, field.name) for field in fields(request)}


def inventory_route_means(engine, request):
    """Inventory lawful geometry and overhead; never choose or execute a route."""
    view = engine.participant_view(request.actor)
    binding = view._bindings.get(request.demand)
    receipt = None if binding is None else view.receipt(binding.receipt)
    current = None if binding is None else view._heads.get(binding.ref.identity)
    if (binding is None or current is None or current.ref != binding.ref
            or binding.actor != request.actor or binding.context != request.context
            or binding.cue != request.cue or binding.target.identity != request.target.identity
            or binding.endorsement.value in ("retracted", "disputed")
            or receipt is None or receipt.actor != request.actor or not receipt.complete
            or receipt.spent < receipt.required):
        raise ValueError("current paid actor-owned demand required")
    if type(request) is SelectionRequest:
        state = engine.selection_view(request)
        setting = "canonical"
    elif type(request) is WorkflowSelectionRequest:
        state = engine.workflow_selection_view(request)
        setting = "workflow"
    else:
        raise ValueError("exact route-free native request required")
    actor = request.actor
    if state["request"] != _request_fields(request):
        raise ValueError("native actor view differs from request")
    tim, active = state["tim"], state["cursor"]
    seat = position_of(tim, active)
    wallet = dict(energy=state["wallet"][0], time=state["wallet"][1])

    def option(name, target, energy, time, eligible=True, reason="structurally_available"):
        return dict(name=name, origin_seat=seat, origin_element=active,
            target_seat=target, target_element=element_at(tim, target),
            origin_fields=seat_fields(seat), target_fields=seat_fields(target),
            overhead=dict(energy=energy, time=time), eligible=bool(eligible), reason=reason,
            content_cost_separate=name != "defer", completion_claim=False)

    ordinary = option("ordinary", lap(seat), 0, 0)
    compensated = option("n", portage(seat, "n"), 0, 0,
        reason="reference_n_portage; native_content_unpriced_here")
    cp_target = portage(seat, "cp")
    cp_ok = wallet["energy"] >= CP_ENERGY and wallet["time"] >= CP_TIME
    cp = option("cp", cp_target, CP_ENERGY, CP_TIME, cp_ok,
        "orientation_read_affordable" if cp_ok else "insufficient_wallet_for_orientation_read")
    cp.update(orientation_read=request.key + ":cp-orientation",
        conjugated_lap=portage(lap(cp_target), "cp"),
        reverse_lap=lap(lap(lap(seat))))
    deferred = option("defer", seat, 0, 0, True,
        "no_mean_selected_before_paid_choice")
    return dict(policy=POLICY, setting=setting, at_tick=len(engine.world.journal()),
        actor=actor, demand=request.demand, request=_request_fields(request),
        view=view.bytes(), tim=tim, active_element=active,
        active_seat=seat, wallet=wallet, options=(ordinary, compensated, cp, deferred),
        selected=None, completion_claim=False)
