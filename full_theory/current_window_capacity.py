"""Current structural capacity across paid windows, not full cost admission."""
from copy import deepcopy
from hashlib import sha256
from hle_unified.selection_records import dumps, loads, SelectionRequest
from hle_unified.workflow_selection_records import WorkflowSelectionRequest
from hle_unified.self_content import decode
from .autonomous_reuse import _restore_ledger
from .retention import Demand
from .reserve import ReserveLedger, preparation
from .route_policy import IntegratedRoutePolicy
from .paid_window_comparison_audit import audit_paid_windows


def digest(text):
    return sha256(text.encode()).hexdigest()


def current_window_capacity(engine, old, original, source, binding, intake, windows):
    before = engine.checkpoint()
    proof = audit_paid_windows(engine, old, original, source, binding, intake, windows)
    s, b, i, w = map(loads, (source, binding, intake, windows))
    actor = s['actor']
    result = dict(version='ft-current-window-capacity-v1', setting=s['setting'], actor=actor,
        native_sha256=digest(before), original_sha256=digest(original.checkpoint()),
        source_sha256=digest(source), binding_sha256=digest(binding),
        intake_sha256=digest(intake), windows_sha256=digest(windows),
        comparison_status=proof['status'], comparison_settled=proof['status']=='succeeded',
        controller_prefix_sha256=digest(s['demand_controller']),
        retention_prefix_sha256=digest(dumps(s['retention'])),
        reserve_prefix_sha256=digest(b['reserve']), history_prefix_sha256=digest(b['history']),
        required=None, inventory=None, means=(), retained=(), windows=(), preparation=None,
        selected=None, execution_authorized=False, td5_admitted=False, history_choice=False,
        full_operand_cost_domain=False, completion_claim=False, prefixes_mutated=False)
    if result['comparison_settled']:
        view = engine.participant_view(actor)
        if (actor in engine._locks or view.bytes()!=old.participant_view(actor).bytes()
                or engine._profiles!=old._profiles or engine._cursors!=old._cursors):
            raise ValueError('exact unlocked post-comparison native inputs required')
        fresh = view._bindings[i['task']]
        prior = original.participant_view(actor)._bindings[s['request']['fields']['demand']]
        payload, previous = decode(fresh.content[0].object), decode(prior.content[0].object)
        field = 'weights' if s['setting']=='canonical' else 'priorities'
        expected = dict(previous, **{field:tuple(10 if i['mask'] & (1<<j) else 0 for j in range(4))})
        if payload!=expected:
            raise ValueError('exact priority-only fresh-task bridge required')
        demand = Demand(**s['required'])
        if (demand.family,demand.context,demand.cue,demand.target)!=(
                s['setting'],fresh.context,fresh.cue,fresh.target):
            raise ValueError('unchanged conjunctive demand scope required')
        requests = w['requests']; first = requests[0]
        ignored = {'key','accessible'} if s['setting']=='workflow' else {'key'}
        common = {k:v for k,v in first.items() if k not in ignored}
        roles = ('stock','tool','repair_stock','procedure','relation','peer','group')
        for fields in requests:
            if ({k:v for k,v in fields.items() if k not in ignored}!=common
                    or any(fields.get(k) is not None for k in roles)):
                raise ValueError('capacity factorization requires exact common scope and absent roles')
        cls = SelectionRequest if s['setting']=='canonical' else WorkflowSelectionRequest
        policy = IntegratedRoutePolicy()
        policy.relay = dict(loads(s['route_policy'])['relay'])
        retention = _restore_ledger(deepcopy(s['retention']), engine)
        admission = policy._admit(engine, cls(**first), demand, retention, tuple(sorted(retention.certificates)))
        inventory = deepcopy(admission['inventory'])
        inventory['view_sha256'] = digest(inventory.pop('view'))
        reserve = ReserveLedger.restore(b['reserve'])
        identity = dumps((actor,fresh.ref))
        if reserve.actor!=actor or reserve.policy!='load-v1' or identity in reserve.demands:
            raise ValueError('fresh task and exact current owned reserve required')
        due = preparation(reserve.policy,reserve.balance,demand.load)
        result.update(required=demand.record(), inventory=inventory,
            means=admission['options'], retained=admission['retained'],
            windows=tuple(dict(ordinal=n,request_sha256=digest(dumps(fields))) for n,fields in enumerate(requests)),
            preparation=dict(demand_id=identity, task=fresh.ref, policy=reserve.policy,
                reserve=reserve.balance, load=demand.load, units=due, energy=2*due, time=2*due,
                intake_credit=0, comparison_credit=0, receipt=None, admitted=False))
    if engine.checkpoint()!=before:
        raise ValueError('capacity bridge mutated native state')
    return dumps(result)
