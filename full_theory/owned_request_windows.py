"""Complete declared bounded owned-content request grammar, never a choice."""
from hashlib import sha256
from itertools import combinations
from hle_unified.selection_records import dumps, loads, fields_of, demand_value
from hle_unified.workflow_selection_records import WorkflowSelectionRequest, demand_value as workflow_need
from hle_unified.self_content import decode
from .demand_controller import IntegratedDemandController
from .demand_requests import form_request
from .fresh_task_intake_audit import audit_fresh_task_intake


def digest(text): return sha256(text.encode()).hexdigest()


def owned_request_windows(native, original, source, binding, intake):
    i=loads(intake)
    if i.get('receipt') is None: raise ValueError('completed paid task intake required')
    audit_fresh_task_intake(native,original,source,binding,intake)
    actor=i['actor'];view=native.participant_view(actor);owned=view._bindings[i['task']]
    controller=IntegratedDemandController.restore(i['controller_prefix'])
    demands=controller.effective_demands();key=dumps((actor,owned.ref))
    if key in demands:raise ValueError('fresh unregistered task required')
    payload=(demand_value if i['setting']=='canonical' else workflow_need)(decode(owned.content[0].object))
    fresh=dict(actor=actor,binding=owned.ref,receipt=owned.receipt,context=owned.context,
        cue=owned.cue,target=owned.target,relation=owned.content[0].relation,payload=payload,
        raw_payload=owned.content[0].object,first_seen=controller.ledger.turn,
        admitted_at=controller.ledger.turn,status='pending',reason=None)
    demands[key]=fresh
    request,formation=form_request(view,demands)
    if formation['selected']!=key:raise ValueError('fresh task must be oldest current pending need')
    inventory=tuple(formation['content'])
    if i['setting']=='canonical':
        if request is None:raise ValueError('canonical owned request required')
        requests=[fields_of(request)]
    else:
        if not inventory or formation['reason'] not in ('ready_for_native_comparison','workflow_content_bound_exceeded'):
            raise ValueError('paid owned workflow inventory required')
        requests=[]
        for size in range(1,min(8,len(inventory))+1):
            for subset in combinations(inventory,size):
                r=WorkflowSelectionRequest(key='ft-request-window:'+digest(key+dumps(subset)),
                    actor=actor,context=owned.context,cue=owned.cue,target=owned.target,
                    demand=owned.ref,accessible=subset)
                requests.append(fields_of(r))
    return dumps(dict(version='ft-owned-request-windows-v1',policy='owned-accessible-window-domain-v2',
        setting=i['setting'],actor=actor,native_sha256=digest(native.checkpoint()),
        source_sha256=digest(source),binding_sha256=digest(binding),intake_sha256=digest(intake),
        controller_prefix=i['controller_prefix'],fresh_demand=fresh,original_formation=formation,
        content_inventory=inventory,requests=requests,declared_domain_complete=True,
        native_view_probed=False,comparison_paid=False,execution_authorized=False,td5_admitted=False,
        history_choice=False,receipt_scope='intake_only'))
