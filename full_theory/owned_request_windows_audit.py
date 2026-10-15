"""Independent bit-mask reconstruction of every declared owned request window."""
from functools import lru_cache
from hashlib import sha256
from hle_unified.selection_records import dumps,loads,fields_of,SelectionRequest,demand_value
from hle_unified.workflow_selection_records import WorkflowSelectionRequest,demand_value as workflow_need
from hle_unified.self_content import decode
from .fresh_task_intake_audit import audit_fresh_task_intake


@lru_cache(maxsize=2)
def source_proof(native,original,source,binding,intake,setting):
    from hle_unified.selection_execution import SelectionEngine
    from hle_unified.workflow_selection_execution import WorkflowFinalSelectionEngine
    cls=SelectionEngine if setting=='canonical' else WorkflowFinalSelectionEngine
    return audit_fresh_task_intake(cls.restore(native),cls.restore(original),source,binding,intake)


def audit_owned_request_windows(native,original,source,binding,intake,text):
    def require(ok,why):
        if not ok:raise ValueError('owned request window audit: '+why)
    d=loads(text);i=loads(intake);s=loads(source);actor=s['actor']
    digest=lambda text:sha256(text.encode()).hexdigest()
    require(i['receipt'] is not None,'settled intake')
    require((d['native_sha256'],d['source_sha256'],d['binding_sha256'],d['intake_sha256'])==
        (digest(native.checkpoint()),digest(source),digest(binding),digest(intake)),'exact pairing')
    source_proof(native.checkpoint(),original.checkpoint(),source,binding,intake,s['setting'])
    view=native.participant_view(actor);b=view._bindings[i['task']]
    c=loads(s['demand_controller']);ledger=loads(c['ledger']);key=dumps((actor,b.ref))
    require(d['controller_prefix']==s['demand_controller']==i['controller_prefix'],'old controller prefix')
    require(key not in ledger['demands'] and actor not in native._locks,'fresh unlocked owned task')
    heads={}
    for x in view.snapshot.bindings:
        if x.actor==actor and (x.ref.identity not in heads or x.ref.revision>heads[x.ref.identity].ref.revision):heads[x.ref.identity]=x
    for x in heads.values():
        if x.ref==b.ref or x.endorsement.value in ('retracted','disputed'):continue
        if any(p.relation in ('c6.need','c7ws.need') for p in x.content):
            older=dumps((actor,x.ref));require(older in ledger['demands'] and older in c['outcomes'],'no older unresolved current need skipped')
    receipt=view.receipt(b.receipt)
    require(receipt is not None and receipt.actor==actor and receipt.complete
        and receipt.operation=='bind' and receipt.spent==receipt.required==3,'fresh paid task binding')
    payload=(demand_value if s['setting']=='canonical' else workflow_need)(decode(b.content[0].object))
    fresh=dict(actor=actor,binding=b.ref,receipt=b.receipt,context=b.context,cue=b.cue,target=b.target,
        relation=b.content[0].relation,payload=payload,raw_payload=b.content[0].object,
        first_seen=ledger['turn'],admitted_at=ledger['turn'],status='pending',reason=None)
    require(d['fresh_demand']==fresh,'fresh demand fields')
    common=dict(actor=actor,context=b.context,cue=b.cue,target=b.target,demand=b.ref)
    original_key='ft-request:'+digest(key);inventory=[]
    if s['setting']=='workflow':
        for x in heads.values():
            paid=view.receipt(x.receipt)
            if (x.endorsement.value not in ('retracted','disputed') and len(x.content)==1
                and x.content[0].relation=='c7w.data' and (x.context,x.cue,x.target)==(b.context,b.cue,b.target)
                and paid is not None and paid.complete and paid.actor==actor and paid.spent>=paid.required):
                inventory.append(x.ref)
        inventory.sort(key=dumps);require(bool(inventory),'nonempty observed paid content')
        original_request=None if len(inventory)>8 else WorkflowSelectionRequest(key=original_key,**common,accessible=tuple(inventory))
        # Bit masks, not the builder's combinations iterator, independently enumerate the grammar.
        subsets=[]
        for mask in range(1,1<<len(inventory)):
            positions=tuple(j for j in range(len(inventory)) if mask & (1<<j))
            if len(positions)<=8:subsets.append(positions)
        subsets.sort(key=lambda x:(len(x),x))
        requests=[]
        for positions in subsets:
            refs=tuple(inventory[j] for j in positions)
            requests.append(fields_of(WorkflowSelectionRequest(key='ft-request-window:'+digest(key+dumps(refs)),
                **common,accessible=refs)))
    else:
        original_request=SelectionRequest(key=original_key,**common);requests=[fields_of(original_request)]
    formation=dict(policy='owned-native-request-v1',actor=actor,selected=key,
        request=None if original_request is None else fields_of(original_request),
        reason='workflow_content_bound_exceeded' if original_request is None else 'ready_for_native_comparison',
        rejected=[],content=tuple(inventory))
    require(d['original_formation']==formation,'unchanged v1 formation including bound rejection')
    require(d['content_inventory']==tuple(inventory) and d['requests']==requests,'all and only legal owned request windows')
    require(set(d)=={'version','policy','setting','actor','native_sha256','source_sha256','binding_sha256','intake_sha256',
        'controller_prefix','fresh_demand','original_formation','content_inventory','requests','declared_domain_complete',
        'native_view_probed','comparison_paid','execution_authorized','td5_admitted','history_choice','receipt_scope'},'schema')
    require(d['version']=='ft-owned-request-windows-v1' and d['policy']=='owned-accessible-window-domain-v2'
        and d['setting']==s['setting'] and d['actor']==actor and d['declared_domain_complete'] is True
        and d['receipt_scope']=='intake_only' and all(d[k] is False for k in
        ('native_view_probed','comparison_paid','execution_authorized','td5_admitted','history_choice')),'honest unpaid no-authority scope')
    return dict(passed=True,inventory=len(inventory),requests=len(requests),native_request_bound=8,
        original_formation_reason=formation['reason'],source_prefix_exact=True,native_unchanged=True,
        comparison_paid=False,execution_authorized=False,td5_admitted=False,history_choice=False)
