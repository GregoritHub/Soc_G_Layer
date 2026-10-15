"""Current paid-owned native proposal inventory, never an execution authority.

This prerequisite deliberately leaves TD5 admission and history-based enactment
to a later versioned controller. Native proposal eligibility is not admission.
"""
from hashlib import sha256
from hle_unified.selection_records import dumps, loads, fields_of
from .demand_controller import IntegratedDemandController
from .demand_requests import form_request
from .social_feedback_binding_audit import audit_social_feedback_binding


def owned_proposal_domain(engine, source, binding):
    audit_social_feedback_binding(engine, source, binding)
    before = engine.checkpoint()
    old = loads(source)
    controller = IntegratedDemandController.restore(old['demand_controller'])
    request, formation = form_request(engine.participant_view(old['actor']),
                                      controller.effective_demands())
    snapshot = None
    rows = []
    nominee = None
    required = 0
    if request is not None:
        if old['setting'] == 'canonical':
            snapshot = engine.selection_view(request)
            rows, nominee = engine._select_policy(snapshot)
            required = 1 + snapshot['scanned'] + snapshot['foreign_total'] + 33 + sum(r['examined'] for r in rows)
        else:
            snapshot = engine.workflow_selection_view(request)
            if snapshot.get('policy') != 'c7-workflow-selection-v4':
                raise ValueError('explicit all-cell workflow v4 required')
            rows, nominee = engine._workflow_policy(snapshot)
            required = 1 + len(snapshot['items']) + len(rows) + sum(r['examined'] for r in rows)
    complete = request is None or not (snapshot.get('truncated', False)
        or snapshot.get('foreign_total', 0) > len(snapshot.get('foreign', ()))
        or any(row['deferred'] for row in rows))
    expected = list(range(33 if old['setting'] == 'canonical' else 32)) if request else []
    if [r['cell'] for r in rows] != expected:
        raise ValueError('native cell domain omitted or reordered')
    if engine.checkpoint() != before:
        raise ValueError('proposal inventory mutated native state')
    return dumps(dict(version='ft-owned-proposal-domain-v1', actor=old['actor'],
        setting=old['setting'], native_sha256=sha256(before.encode()).hexdigest(),
        source_sha256=sha256(source.encode()).hexdigest(), binding_sha256=sha256(binding.encode()).hexdigest(),
        formation=formation, request=None if request is None else fields_of(request),
        snapshot=snapshot, candidates=rows, native_nominee=nominee,
        comparison_required=required, comparison_paid=False, cell_domain_complete=True,
        bounded_search_complete=complete, execution_authorized=False))
