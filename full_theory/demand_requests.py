"""Versioned route-free native request formation from current owned demand."""
from hashlib import sha256
from hle_unified.selection_records import SelectionRequest, fields_of, dumps
from hle_unified.workflow_selection_records import WorkflowSelectionRequest


def form_request(view, demands):
    actor=view.snapshot.actor
    heads={}
    for b in view.snapshot.bindings:
        if b.actor==actor and (b.ref.identity not in heads or b.ref.revision>heads[b.ref.identity].ref.revision):
            heads[b.ref.identity]=b
    pending=sorted(((key,d) for key,d in demands.items() if d['actor']==actor and d['status']=='pending'),
                   key=lambda item:(item[1]['first_seen'],item[0]))
    rejected=[]
    for key,d in pending:
        b=heads.get(d['binding'].identity)
        receipt=view.receipt(d['receipt'])
        if (b is None or b.ref!=d['binding'] or b.receipt!=d['receipt']
                or b.endorsement.value in ('retracted','disputed') or len(b.content)!=1
                or (b.actor,b.context,b.cue,b.target)!=(actor,d['context'],d['cue'],d['target'])
                or (b.content[0].relation,b.content[0].object)!=(d['relation'],d['raw_payload'])
                or receipt is None or not receipt.complete or receipt.spent<receipt.required):
            rejected.append(dict(demand=key,reason='need_not_current_paid_owned'));continue
        common=dict(key='ft-request:'+sha256(key.encode()).hexdigest(),actor=actor,
            context=d['context'],cue=d['cue'],target=d['target'],demand=d['binding'])
        content=[]
        if d['relation']=='c7ws.need':
            for owned in heads.values():
                paid=view.receipt(owned.receipt)
                if (owned.endorsement.value not in ('retracted','disputed') and len(owned.content)==1
                        and owned.content[0].relation=='c7w.data'
                        and (owned.context,owned.cue,owned.target)==(d['context'],d['cue'],d['target'])
                        and paid is not None and paid.complete and paid.actor==actor and paid.spent>=paid.required):
                    content.append(owned.ref)
            content.sort(key=dumps)
            if not 1<=len(content)<=8:
                reason='no_owned_workflow_content' if not content else 'workflow_content_bound_exceeded'
                return None,dict(policy='owned-native-request-v1',actor=actor,selected=key,
                    request=None,reason=reason,rejected=rejected,content=tuple(content))
            request=WorkflowSelectionRequest(**common,accessible=tuple(content))
        elif d['relation']=='c6.need':
            request=SelectionRequest(**common)
        else:
            rejected.append(dict(demand=key,reason='unsupported_need'));continue
        return request,dict(policy='owned-native-request-v1',actor=actor,selected=key,
            request=fields_of(request),reason='ready_for_native_comparison',rejected=rejected,content=tuple(content))
    return None,dict(policy='owned-native-request-v1',actor=actor,selected=None,request=None,
        reason='no_current_pending_need',rejected=rejected,content=())
