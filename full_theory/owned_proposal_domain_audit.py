"""Independent owned proposal reconstruction; no selector/executor imports."""
from hashlib import sha256
from hle_unified.selection_records import dumps, loads, SelectionRequest, fields_of
from hle_unified.workflow_selection_records import WorkflowSelectionRequest
from hle_unified.selection_audit import reference as canonical_reference
from hle_unified.workflow_selection_audit import reference as workflow_reference
from hle_unified.self_content import decode
from hle_unified.material import attrs
from .social_feedback_binding_audit import audit_social_feedback_binding


def _request(view, source):
    controller = loads(source['demand_controller'])
    ledger = loads(controller['ledger'])
    actor = source['actor']
    heads = {}
    for b in view.snapshot.bindings:
        if b.actor == actor and (b.ref.identity not in heads or b.ref.revision > heads[b.ref.identity].ref.revision):
            heads[b.ref.identity] = b
    waiting = sorted((k, d) for k, d in ledger['demands'].items()
        if d['actor'] == actor and d['status'] == 'pending' and k not in controller['outcomes'])
    waiting.sort(key=lambda pair: (pair[1]['first_seen'], pair[0]))
    rejected = []
    for key, d in waiting:
        b = heads.get(d['binding'].identity)
        paid = view.receipt(d['receipt'])
        valid = b is not None and b.ref == d['binding'] and b.receipt == d['receipt']
        valid = valid and b.endorsement.value not in ('retracted', 'disputed') and len(b.content) == 1
        valid = valid and (b.actor,b.context,b.cue,b.target)==(actor,d['context'],d['cue'],d['target'])
        valid = valid and (b.content[0].relation,b.content[0].object)==(d['relation'],d['raw_payload'])
        valid = valid and paid is not None and paid.complete and paid.spent >= paid.required
        if not valid:
            rejected.append(dict(demand=key, reason='need_not_current_paid_owned')); continue
        common=dict(key='ft-request:'+sha256(key.encode()).hexdigest(),actor=actor,
            context=d['context'],cue=d['cue'],target=d['target'],demand=d['binding'])
        content=[]
        if d['relation']=='c7ws.need':
            for x in heads.values():
                receipt=view.receipt(x.receipt)
                if (x.endorsement.value not in ('retracted','disputed') and len(x.content)==1
                    and x.content[0].relation=='c7w.data'
                    and (x.context,x.cue,x.target)==(d['context'],d['cue'],d['target'])
                    and receipt is not None and receipt.complete and receipt.actor==actor
                    and receipt.spent>=receipt.required):content.append(x.ref)
            content.sort(key=dumps)
            if not 1<=len(content)<=8:
                why='no_owned_workflow_content' if not content else 'workflow_content_bound_exceeded'
                return None,dict(policy='owned-native-request-v1',actor=actor,selected=key,
                    request=None,reason=why,rejected=rejected,content=tuple(content))
            request=WorkflowSelectionRequest(**common,accessible=tuple(content))
        elif d['relation']=='c6.need':request=SelectionRequest(**common)
        else:
            rejected.append(dict(demand=key,reason='unsupported_need'));continue
        return request,dict(policy='owned-native-request-v1',actor=actor,selected=key,
            request=fields_of(request),reason='ready_for_native_comparison',rejected=rejected,content=tuple(content))
    return None,dict(policy='owned-native-request-v1',actor=actor,selected=None,
        request=None,reason='no_current_pending_need',rejected=rejected,content=())


def _snapshot(engine, view, request, setting):
    r=fields_of(request); actor=request.actor
    def known(ref):return {} if ref is None else {p.address.key:p.value for p in view.resolve(ref)}
    need=decode(view._bindings[request.demand].content[0].object)
    if setting=='workflow':
        items=[]
        # Route-free request formation admits current paid bindings only, never public/raw operands.
        for ref in sorted(request.accessible,key=dumps):
            b=view._heads[ref.identity]
            if b.ref!=ref or b.actor!=actor or len(b.content)!=1 or b.content[0].relation!='c7w.data':
                raise ValueError('unowned workflow input')
            items.append(dict(ref=ref,data=decode(b.content[0].object),
                evidence=tuple((x.delivery,x.key) for x in b.particulars)))
        group=known(request.group).get('payload')
        return dict(request=r,need=need,items=items,target=known(request.target),stock=known(request.stock),
            relation=known(request.relation),group=decode(group) if group else None,
            profile=engine._profiles[actor],tim=attrs(engine.world.resolve(engine._profiles[actor]))['tim'],
            cursor=engine._cursors[actor],wallet=tuple(engine.wallet(actor)[k] for k in ('energy','time')),
            evidence=tuple((p.address.delivery,p.address.key) for p in view.resolve(request.target)),
            policy='c7-workflow-selection-v4',procedure=None,acquired=())
    for key in ('target','stock','tool','repair_stock','group','procedure'):
        ref=r[key]
        if ref is not None:
            r[key]=max((p.source for p in view.lookup(subject=ref.identity) if p.source.identity==ref.identity),
                       key=lambda p:p.revision,default=ref)
    local=[];foreign=[];scanned=0
    for b in view.snapshot.bindings:
        if b.cue!=request.cue or b.target.identity!=request.target.identity or b.endorsement.value in ('retracted','disputed'):continue
        if b.context!=request.context:
            if len(b.content)==1 and b.content[0].relation in ('c3.data','c4.data'):
                v=decode(b.content[0].object)
                if v.get('kind')=='model':foreign.append(dict(ref=b.ref,data=v,binding=True))
            continue
        scanned+=1
        if len(b.content)==1 and b.content[0].relation in ('c2.data','c3.data','c4.data'):
            local.append(dict(ref=b.ref,data=decode(b.content[0].object),binding=True))
    for p in view.lookup(key='payload'):
        if p.source.identity.namespace in ('c2.message','c3.message','c4.message'):
            v=decode(p.value)
            if v.get('target',request.target).identity==request.target.identity and v.get('context',request.context)==request.context:
                scanned+=1;local.append(dict(ref=p.source,data=v,binding=False))
    for p in view.lookup(key='event'):
        if p.source.identity.namespace!='u4.observation':continue
        v=known(p.source);target=v.get('target') or v.get('stock')
        if (v.get('context')==request.context and v.get('actor')==actor and target is not None
            and (r['stock'] is None or target.identity==r['stock'].identity)):
            scanned+=1;local.append(dict(ref=p.source,data=dict(v,kind='observation'),binding=False))
    local=sorted({x['ref']:x for x in local}.values(),key=lambda x:dumps(x['ref']))
    foreign.sort(key=lambda x:dumps(x['ref']))
    group=known(r['group']).get('payload')
    return dict(request=r,need=need,items=local[:request.limit],foreign=foreign[:request.limit],
        foreign_total=len(foreign),total_items=len(local),truncated=len(local)>request.limit,scanned=scanned,
        target=known(r['target']),stock=known(r['stock']),tool=known(r['tool']),repair_stock=known(r['repair_stock']),
        group=decode(group) if group else None,
        acquired=tuple((a.procedure,a.context,a.receipt) for a in view.snapshot.acquired
            if a.procedure==r['procedure'] and a.context==request.context),
        tim=attrs(engine.world.resolve(engine._profiles[actor]))['tim'],profile=engine._profiles[actor],
        cursor=engine._cursors[actor],wallet=tuple(engine.wallet(actor)[k] for k in ('energy','time')),
        evidence=tuple((p.address.delivery,p.address.key) for p in view.lookup(subject=request.target.identity)),
        sources=tuple(dict.fromkeys(p.source for p in view.lookup(subject=request.target.identity))))


def audit_owned_proposal_domain(engine, source, binding, text):
    audit_social_feedback_binding(engine,source,binding)
    d=loads(text);s=loads(source)
    expected_fields={'version','actor','setting','native_sha256','source_sha256','binding_sha256',
        'formation','request','snapshot','candidates','native_nominee','comparison_required',
        'comparison_paid','cell_domain_complete','bounded_search_complete','execution_authorized'}
    if set(d)!=expected_fields or d['version']!='ft-owned-proposal-domain-v1':raise ValueError('domain schema')
    if (d['actor'],d['setting'],d['native_sha256'],d['source_sha256'],d['binding_sha256'])!=(
        s['actor'],s['setting'],sha256(engine.checkpoint().encode()).hexdigest(),sha256(source.encode()).hexdigest(),sha256(binding.encode()).hexdigest()):
        raise ValueError('domain source pairing')
    view=engine.participant_view(s['actor']);r,formation=_request(view,s)
    if d['formation']!=formation or d['request']!=(None if r is None else fields_of(r)):raise ValueError('owned oldest request')
    if d['comparison_paid'] is not False or d['execution_authorized'] is not False or d['cell_domain_complete'] is not True:
        raise ValueError('proposal cannot authorize execution or claim payment')
    if r is None:
        if (d['snapshot'],d['candidates'],d['native_nominee'],d['comparison_required'],d['bounded_search_complete'])!=(None,[],None,0,True):
            raise ValueError('fulfilled/no-request domain must be empty')
        return dict(passed=True,cells=0,comparison_required=0,execution_authorized=False,bounded_search_complete=True)
    snap=_snapshot(engine,view,r,s['setting'])
    if d['snapshot']!=snap:raise ValueError('paid owned snapshot differs')
    if s['setting']=='canonical':
        refs=[dict(canonical_reference(snap,i),cell=i) for i in range(33)]
        required=1+snap['scanned']+snap['foreign_total']+33+sum(x['examined'] for x in refs)
        nominated=min((x for x in refs if x['eligible'] and x['score']>0),
            key=lambda x:(-x['score'],x['cell'],dumps(x['inputs'])),default=None)
    else:
        refs,nominated=workflow_reference(snap)
        required=1+len(snap['items'])+len(refs)+sum(x['examined'] for x in refs)
    rows=d['candidates']
    if len(rows)!=len(refs) or [x['cell'] for x in rows]!=list(range(len(refs))):raise ValueError('complete cell domain required')
    for row,ref in zip(rows,refs):
        if any(row.get(k)!=v for k,v in ref.items()):raise ValueError('candidate reconstruction differs')
        if not isinstance(row.get('reason'),str) or not row['reason']:raise ValueError('every alternative needs reason')
    selected=None if nominated is None else rows[nominated['cell']]
    if d['native_nominee']!=selected or d['comparison_required']!=required:raise ValueError('native nomination or unpaid extent differs')
    complete=not(snap.get('truncated',False) or snap.get('foreign_total',0)>len(snap.get('foreign',())) or any(x['deferred'] for x in refs))
    if type(d['bounded_search_complete']) is not bool or d['bounded_search_complete']!=complete:raise ValueError('false search completeness')
    return dict(passed=True,cells=len(rows),eligible=sum(x['eligible'] for x in refs),
        comparison_required=required,comparison_paid=False,bounded_search_complete=complete,
        native_nominee_cell=None if nominated is None else nominated['cell'],execution_authorized=False)
