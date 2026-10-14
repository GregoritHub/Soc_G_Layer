"""Independent FT5.2b1 reserve candidate reconstruction."""
from hashlib import sha256

from hle_unified.selection_records import loads

from .native_reserve_audit import audit_native_reserve
from .route_policy_audit import audit_route_policy


NAMES = ("retained", "ordinary", "n", "cp", "support", "defer")


def audit_reserve_candidates(engine, checkpoint):
    data = loads(checkpoint)
    required = {"version", "native_sha256", "actor", "binding",
                "route_policy", "attempts", "events"}
    native_text = engine.checkpoint()
    if (type(data) is not dict or set(data) != required
            or data["version"] != "ft-reserve-candidate-readiness-v1"
            or data["native_sha256"] != sha256(native_text.encode()).hexdigest()):
        raise ValueError("invalid paired reserve candidate checkpoint")
    binding_report = audit_native_reserve(engine, data["binding"])
    route_report = audit_route_policy(engine.world.journal(), engine.access.checkpoint(),
                                      data["route_policy"], native_text)
    binding = loads(data["binding"])
    reserve = loads(binding["reserve"])
    if data["actor"] != binding["actor"] or data["actor"] != reserve["actor"]:
        raise ValueError("candidate actor differs from reserve binding")
    attempts = {(row["actor"], row["key"]): row for row in data["attempts"]}
    if len(attempts) != len(data["attempts"]):
        raise ValueError("duplicate candidate attempt")
    route = loads(data["route_policy"])
    route_attempts = {(row["actor"], row["key"]): row for row in route["attempts"]}
    preparation = 0
    delegated = 0
    observed_bound = {}
    for index, event in enumerate(data["events"]):
        if event.get("index") != index:
            raise ValueError("candidate event order differs")
        key = (event.get("actor"), event.get("key"))
        attempt = attempts.get(key)
        if attempt is None or set(attempt) != {"actor", "key", "request", "demand",
                                             "reserve_id", "initial_route_plan", "policy"}:
            raise ValueError("candidate event lacks exact attempt")
        reserve_id = attempt["reserve_id"]
        admission = binding["admissions"].get(reserve_id)
        rows = binding["preparation_bindings"].get(reserve_id)
        if admission is None or rows is None or reserve_id not in reserve["demands"]:
            raise ValueError("candidate lacks reserve admission")
        required_units = admission["preparation"]
        final_bound = len(rows)
        bound = event.get("preparation_bound")
        prior_bound = observed_bound.get(key, 0)
        if (type(bound) is not int or not prior_bound <= bound <= final_bound
                or bound > required_units):
            raise ValueError("preparation binding history is not monotone")
        observed_bound[key] = bound
        remaining = required_units - bound
        plan = attempt["initial_route_plan"] if remaining else route_attempts.get(key)
        if plan is None:
            raise ValueError("ready candidate lacks native route plan")
        options = tuple(plan["options"])
        provisional = plan["selected"]
        if (tuple(row.get("name") for row in options) != NAMES
                or any("forbidden" in row for row in options)
                or provisional != next(row for row in options if row["eligible"])):
            raise ValueError("native route visibility or priority differs")
        common = (event.get("policy") == reserve["policy"] == attempt["policy"]
                  and event.get("reserve_balance") == reserve["balance"]
                  and event.get("load") == attempt["demand"]["load"]
                  and event.get("reserve_id") == reserve_id
                  and event.get("preparation_required") == required_units
                  and event.get("preparation_bound") == bound
                  and event.get("preparation_remaining") == remaining
                  and tuple(event.get("route_options", ())) == options
                  and event.get("provisional_native_selection") == provisional
                  and event.get("native_overhead") == provisional["overhead"]
                  and event.get("reserve_preparation_units") == remaining)
        if not common:
            raise ValueError("candidate policy, readiness or cost fields differ")
        if remaining:
            if (event.get("selected_candidate") != "preparation"
                    or event.get("phase") != "preparation"
                    or event.get("route_event") is not None
                    or event.get("before") != event.get("after")):
                raise ValueError("scarce reserve did not select non-mutating preparation")
            preparation += 1
        else:
            route_event = event.get("route_event")
            if (type(route_event) is not dict
                    or event.get("selected_candidate") != provisional["name"]
                    or route_event.get("selected") != provisional["name"]
                    or event.get("phase") != route_event.get("phase")):
                raise ValueError("ready reserve did not delegate exact native selection")
            delegated += 1
    for key, attempt in attempts.items():
        reserve_id = attempt["reserve_id"]
        if observed_bound.get(key) != len(binding["preparation_bindings"][reserve_id]):
            raise ValueError("terminal preparation observation differs from bound evidence")
    return dict(passed=True, policy=reserve["policy"], attempts=len(attempts),
                events=len(data["events"]), preparation_events=preparation,
                delegated_events=delegated, binding=binding_report, route=route_report)
