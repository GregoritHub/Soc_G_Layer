"""Independent FT5.2b2 autonomous completion/interruption reconstruction."""
from hashlib import sha256

from hle_unified import model_g
from hle_unified.selection_records import loads

from .fulfillment_audit import audit_fulfillment
from .native_reserve_audit import audit_native_reserve
from .route_policy_audit import audit_route_policy


NAMES = ("retained", "ordinary", "n", "cp", "support", "defer")


def _paid_job(engine, actor, row):
    if type(row) is not dict or set(row) != {"key", "operation", "status"}:
        raise ValueError("invalid interruption paid-job evidence")
    key = row["key"]
    if (actor, key) not in engine._jobs:
        raise ValueError("interruption job is absent")
    status = engine.job_status(actor, key)
    if (row["operation"] != engine._jobs[actor, key] or row["status"] != status
            or type(status.get("spent")) is not int or status["spent"] <= 0):
        raise ValueError("interruption lacks exact positively paid native work")
    return status


def _candidate_state(engine, text):
    candidate = loads(text)
    required = {"version", "native_sha256", "actor", "binding",
                "route_policy", "attempts", "events"}
    native = engine.checkpoint()
    if (type(candidate) is not dict or set(candidate) != required
            or candidate["version"] != "ft-reserve-candidate-readiness-v1"
            or candidate["native_sha256"] != sha256(native.encode()).hexdigest()):
        raise ValueError("invalid paired reserve candidate state")
    binding_report = audit_native_reserve(engine, candidate["binding"])
    route_report = audit_route_policy(engine.world.journal(), engine.access.checkpoint(),
                                      candidate["route_policy"], native)
    binding = loads(candidate["binding"])
    reserve = loads(binding["reserve"])
    route = loads(candidate["route_policy"])
    attempts = {(row["actor"], row["key"]): row for row in candidate["attempts"]}
    route_attempts = {(row["actor"], row["key"]): row for row in route["attempts"]}
    if len(attempts) != len(candidate["attempts"]):
        raise ValueError("duplicate reserve candidate attempt")
    admissions = {event["demand_id"]: event for event in reserve["events"]
                  if event.get("kind") == "admission"}
    observed = {}
    for index, event in enumerate(candidate["events"]):
        if event.get("index") != index:
            raise ValueError("candidate event order differs")
        key = (event.get("actor"), event.get("key"))
        attempt = attempts.get(key)
        if attempt is None:
            raise ValueError("candidate event lacks its attempt")
        reserve_id = attempt["reserve_id"]
        admission = binding["admissions"].get(reserve_id)
        reserve_admission = admissions.get(reserve_id)
        rows = binding["preparation_bindings"].get(reserve_id)
        if admission is None or reserve_admission is None or rows is None:
            raise ValueError("candidate lacks exact reserve admission")
        required_units = admission["preparation"]
        bound = event.get("preparation_bound")
        prior = observed.get(key, 0)
        if (type(bound) is not int or not prior <= bound <= len(rows)
                or bound > required_units):
            raise ValueError("candidate preparation history differs")
        observed[key] = bound
        remaining = required_units - bound
        plan = attempt["initial_route_plan"] if remaining else route_attempts.get(key)
        if plan is None:
            raise ValueError("ready candidate lacks native route plan")
        options = tuple(plan["options"])
        selected = plan["selected"]
        if (tuple(row.get("name") for row in options) != NAMES
                or any("forbidden" in row for row in options)
                or selected != next(row for row in options if row["eligible"])):
            raise ValueError("candidate route visibility or priority differs")
        if (event.get("policy") != reserve["policy"] == attempt["policy"]
                or event.get("reserve_balance") != reserve_admission["balance_after"]
                or event.get("load") != attempt["demand"]["load"]
                or event.get("reserve_id") != reserve_id
                or event.get("preparation_required") != required_units
                or event.get("preparation_remaining") != remaining
                or tuple(event.get("route_options", ())) != options
                or event.get("provisional_native_selection") != selected
                or event.get("native_overhead") != selected["overhead"]
                or event.get("reserve_preparation_units") != remaining):
            raise ValueError("candidate policy, readiness or cost fields differ")
        if remaining:
            if (event.get("selected_candidate") != "preparation"
                    or event.get("phase") != "preparation"
                    or event.get("route_event") is not None
                    or event.get("before") != event.get("after")):
                raise ValueError("preparation candidate differs")
        elif (type(event.get("route_event")) is not dict
              or event.get("selected_candidate") != selected["name"]
              or event["route_event"].get("selected") != selected["name"]
              or event.get("phase") != event["route_event"].get("phase")):
            raise ValueError("delegated native candidate differs")
    return candidate, binding, reserve, route, binding_report, route_report


def audit_reserve_cycle(engine, checkpoint):
    data = loads(checkpoint)
    required = {"version", "native_sha256", "actor", "demand_controller", "candidates",
                "required", "request", "phase", "consumer_key", "events", "effects",
                "terminal"}
    native = engine.checkpoint()
    if (type(data) is not dict or set(data) != required
            or data["version"] != "ft-autonomous-reserve-settlement-v1"
            or data["native_sha256"] != sha256(native.encode()).hexdigest()):
        raise ValueError("invalid paired autonomous reserve checkpoint")
    fulfillment = audit_fulfillment(engine.world.journal(), engine.access.checkpoint(),
                                    data["demand_controller"])
    candidate, binding, reserve, route, binding_report, route_report = _candidate_state(
        engine, data["candidates"])
    if data["actor"] != candidate["actor"] or data["actor"] != reserve["actor"]:
        raise ValueError("autonomous reserve actor differs")
    if (any(row.get("index") != i for i, row in enumerate(data["events"]))
            or any(row.get("index") != i for i, row in enumerate(data["effects"]))):
        raise ValueError("autonomous reserve event order differs")
    if data["terminal"] is not None and data["terminal"] != data["events"][-1]:
        raise ValueError("autonomous reserve terminal differs")
    if data["request"] is not None:
        request = data["request"]["fields"]
        if not data["events"] or data["events"][0].get("request") != request:
            raise ValueError("owned request differs from first autonomous event")
    else:
        request = None

    effects = data["effects"]
    terminal = data["terminal"]
    if data["phase"] == "complete":
        if (len(effects) != 1 or terminal is None
                or terminal.get("reason") != "settled_after_paid_consumption_and_reserve"
                or terminal.get("effect") != effects[0] or terminal.get("consumer") is None
                or terminal.get("settlement") is None or request is None):
            raise ValueError("complete autonomous reserve cycle lacks exact terminal links")
        effect = effects[0]
        if effect.get("kind") != "completion":
            raise ValueError("complete cycle lacks completion effect")
        attempts = route["attempts"]
        if len(attempts) != 1 or attempts[0].get("status") != "complete":
            raise ValueError("complete cycle lacks one completed native route")
        traversal = attempts[0].get("traversal")
        settlement = terminal["settlement"]
        supported = traversal.get("supported") is True and traversal.get("means") == "support"
        completion_kind = "supported" if supported else "independent"
        grade = (model_g.grade(traversal["target_seat"])
                 if completion_kind == "independent" and reserve["policy"] == "grade-load-v1"
                 else None)
        reserve_event = reserve["events"][-1]
        consumer = terminal["consumer"]
        if (effect.get("reserve_id") != candidate["attempts"][0]["reserve_id"]
                or effect.get("selected") != traversal["means"]
                or effect.get("supported") != supported
                or effect.get("target_seat") != traversal["target_seat"]
                or effect.get("completion_kind") != completion_kind
                or effect.get("last_paid_grade") != grade
                or effect.get("traversal") != traversal
                or effect.get("settlement") != settlement
                or effect.get("reserve_event") != reserve_event
                or reserve_event.get("kind") != "completion"
                or reserve_event.get("demand_id") != effect["reserve_id"]
                or reserve_event.get("completion_kind") != completion_kind
                or reserve_event.get("last_paid_grade") != grade
                or reserve["demands"][effect["reserve_id"]]["status"] != "completed"):
            raise ValueError("completion kind, grade or reserve effect differs")
        if (effect.get("native_before") != effect.get("native_after")
                or effect.get("native_after") != data["native_sha256"]):
            raise ValueError("completion reserve effect changed native state")
        if (settlement["selection_key"] != request["key"]
                or settlement["movement_key"] != request["key"] + ":movement"
                or settlement["consumer_key"] != data["consumer_key"]
                or settlement["movement_output"] != traversal["movement_output"]
                or consumer["inputs"] != (traversal["movement_output"],)
                or consumer["output"] != settlement["consumer_output"]
                or fulfillment["fulfilled"] != 1):
            raise ValueError("paid consumer settlement links differ")
    elif data["phase"] == "interrupted":
        if (len(effects) != 1 or terminal is None or request is None
                or terminal.get("reason") != "interrupted_actual_paid_work"
                or terminal.get("effect") != effects[0] or terminal.get("settlement") is not None):
            raise ValueError("interrupted cycle lacks exact terminal effect")
        effect = effects[0]
        reserve_event = reserve["events"][-1]
        if (effect.get("kind") != "interruption" or effect.get("reserve_event") != reserve_event
                or reserve_event.get("kind") != "interruption"
                or reserve_event.get("demand_id") != effect.get("reserve_id")
                or reserve_event.get("attempt_id") != effect.get("attempt_id")
                or not effect.get("attempt_id", "").startswith("native-route:")
                or reserve["demands"][effect["reserve_id"]]["status"] != "pending"
                or effect.get("native_before") != effect.get("native_after")
                or effect.get("native_after") != data["native_sha256"]
                or fulfillment["fulfilled"] != 0):
            raise ValueError("interruption identity, pending state or delta link differs")
        jobs = tuple(effect.get("paid_jobs", ()))
        if not jobs:
            raise ValueError("interruption lacks paid native route work")
        allowed = {request["key"], request["key"] + ":movement"}
        if any(row.get("key") not in allowed for row in jobs):
            raise ValueError("interruption credited non-route work")
        for row in jobs:
            _paid_job(engine, data["actor"], row)
    else:
        if effects or fulfillment["fulfilled"]:
            raise ValueError("nonsettled cycle changed reserve or fulfillment")
    return dict(passed=True, phase=data["phase"], policy=reserve["policy"],
        balance=reserve["balance"], effects=len(effects), fulfilled=fulfillment["fulfilled"],
        native_binding=binding_report, route=route_report)
