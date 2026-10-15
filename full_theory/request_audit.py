"""Independent formation reconstruction; input ledger is admission-audited first.

Consumes saved participant observations, never the request generator or engine.
"""
from hashlib import sha256
from hle_unified.compact import unseal, ValuePool
from hle_unified.particulars import record_registry
from hle_unified.selection_records import dumps


def audit_request(view_text, demands, row):
    raw=unseal(view_text,'hle-unified-participant-value-v1')
    pool=ValuePool(record_registry());pool.load_nodes(raw['nodes'])
    snapshot=pool.get(pool.import_token(raw['root']))
    actor=snapshot.actor
    receipts={r.ref:r for r in snapshot.receipts}
    ordered=sorted((b for b in snapshot.bindings if b.actor==actor),key=lambda b:b.ref.revision)
    latest={b.ref.identity:b for b in ordered}
    pending=sorted((k for k,d in demands.items() if d['actor']==actor and d['status']=='pending'),
                   key=lambda k:(demands[k]['first_seen'],k))
    rejected=[];expected=None
    for key in pending:
        d=demands[key];b=latest.get(d['binding'].identity);receipt=receipts.get(d['receipt'])
        valid=(b is not None and b.ref==d['binding'] and b.receipt==d['receipt']
            and b.endorsement.value not in ('retracted','disputed') and len(b.content)==1
            and (b.actor,b.context,b.cue,b.target)==(actor,d['context'],d['cue'],d['target'])
            and (b.content[0].relation,b.content[0].object)==(d['relation'],d['raw_payload'])
            and receipt is not None and receipt.complete and receipt.spent>=receipt.required)
        if not valid:
            rejected.append(dict(demand=key,reason='need_not_current_paid_owned'));continue
        request=dict(key='ft-request:'+sha256(key.encode()).hexdigest(),actor=actor,
            context=d['context'],cue=d['cue'],target=d['target'],demand=d['binding'])
        content=()
        if d['relation']=='c7ws.need':
            found=[]
            for b in latest.values():
                r=receipts.get(b.receipt)
                if (b.endorsement.value not in ('retracted','disputed') and len(b.content)==1
                        and b.content[0].relation=='c7w.data'
                        and (b.context,b.cue,b.target)==(d['context'],d['cue'],d['target'])
                        and r is not None and r.complete and r.actor==actor and r.spent>=r.required):
                    found.append(b.ref)
            content=tuple(sorted(found,key=dumps))
            if len(content)==0 or len(content)>8:
                expected=dict(policy='owned-native-request-v1',actor=actor,selected=key,request=None,
                    reason='no_owned_workflow_content' if not content else 'workflow_content_bound_exceeded',
                    rejected=rejected,content=content);break
            request.update(accessible=content,stock=None,relation=None,peer=None,group=None,alternatives=64)
        elif d['relation']=='c6.need':
            request.update(stock=None,tool=None,repair_stock=None,procedure=None,peer=None,group=None,
                           limit=128,alternatives=64)
        else:
            rejected.append(dict(demand=key,reason='unsupported_need'));continue
        expected=dict(policy='owned-native-request-v1',actor=actor,selected=key,request=request,
            reason='ready_for_native_comparison',rejected=rejected,content=content);break
    if expected is None:
        expected=dict(policy='owned-native-request-v1',actor=actor,selected=None,request=None,
            reason='no_current_pending_need',rejected=rejected,content=())
    if row!=expected:
        raise ValueError('native request differs from current paid owned observation')
    return dict(passed=True,formed=row['request'] is not None,reason=row['reason'])
