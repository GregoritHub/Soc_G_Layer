"""Fresh paid task -> owned request -> separately paid native comparison.

No new selector, role, skill, admission or live history-choice authority.
"""
from copy import deepcopy
from hashlib import sha256
from hle_unified.selection_records import dumps, loads, fields_of, demand_value
from hle_unified.workflow_selection_records import demand_value as workflow_need
from hle_unified.self_content import decode
from .demand_controller import IntegratedDemandController
from .demand_requests import form_request
from .fresh_task_intake_audit import audit_fresh_task_intake
from .owned_paid_comparison import (PaidCanonicalComparisonEngine,
    PaidWorkflowComparisonEngine, PaidComparisonRequest)


def digest(text): return sha256(text.encode()).hexdigest()


def prepare_fresh_comparison(native, original, source, binding, intake):
    d = loads(intake)
    if d.get('receipt') is None:
        raise ValueError('completed paid task intake required')
    audit_fresh_task_intake(native, original, source, binding, intake)
    actor = d['actor']; view = native.participant_view(actor)
    owned = view._bindings[d['task']]
    controller = IntegratedDemandController.restore(d['controller_prefix'])
    demands = controller.effective_demands()
    key = dumps((actor, owned.ref))
    if key in demands: raise ValueError('fresh unregistered task required')
    payload = decode(owned.content[0].object)
    payload = (demand_value if d['setting'] == 'canonical' else workflow_need)(payload)
    fresh = dict(actor=actor, binding=owned.ref, receipt=owned.receipt,
        context=owned.context, cue=owned.cue, target=owned.target,
        relation=owned.content[0].relation, payload=payload,
        raw_payload=owned.content[0].object, first_seen=controller.ledger.turn,
        admitted_at=controller.ledger.turn, status='pending', reason=None)
    demands[key] = fresh
    request, formation = form_request(view, demands)
    if request is None or formation['selected'] != key or request.demand != owned.ref:
        raise ValueError('new task must be oldest current pending owned request')
    cls = PaidCanonicalComparisonEngine if d['setting'] == 'canonical' else PaidWorkflowComparisonEngine
    engine = cls.from_native(native.checkpoint())
    snapshot, rows, nominee, required = engine._comparison_view(request)
    expected = list(range(33 if d['setting'] == 'canonical' else 32))
    if [r['cell'] for r in rows] != expected: raise ValueError('full bounded cell domain required')
    complete = not (snapshot.get('truncated', False)
        or snapshot.get('foreign_total', 0) > len(snapshot.get('foreign', ()))
        or any(r['deferred'] for r in rows))
    domain = dumps(dict(version='ft-fresh-task-comparison-domain-v1', actor=actor,
        setting=d['setting'], native_sha256=digest(native.checkpoint()),
        source_sha256=digest(source), binding_sha256=digest(binding), intake_sha256=digest(intake),
        controller_prefix=d['controller_prefix'], fresh_demand=fresh,
        formation=formation, request=fields_of(request), snapshot=snapshot,
        candidates=rows, native_nominee=nominee, comparison_required=required,
        comparison_paid=False, cell_domain_complete=True, bounded_search_complete=complete,
        execution_authorized=False, td5_admitted=False, history_choice=False))
    paid = PaidComparisonRequest('ft-owned-comparison:fresh:'+digest(intake)[:24], request)
    return engine, paid, domain
