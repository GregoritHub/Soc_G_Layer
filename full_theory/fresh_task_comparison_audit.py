"""Independent fresh-task request, native comparison and payment audit."""
from copy import deepcopy
from functools import lru_cache
from hashlib import sha256
from hle_unified.selection_records import (loads, dumps, fields_of, SelectionRequest, demand_value)
from hle_unified.workflow_selection_records import WorkflowSelectionRequest, demand_value as workflow_need
from hle_unified.self_content import decode
from hle_unified.selection_audit import reference as canonical_reference
from hle_unified.workflow_selection_audit import reference as workflow_reference
from hle_unified.operation_records import OperationRequest
from hle_unified.material import attrs
from hle_unified.operations import address
from hle_unified.compact import unseal
from hle_unified.records import Account
from hle_unified.development_audit import audit as audit_native
from hle_unified.workflow_selection_audit import extent as previous_extent
from .owned_proposal_domain_audit import _snapshot
from .fresh_task_intake_audit import audit_fresh_task_intake


@lru_cache(maxsize=2)
def intake_proof(native, original, source, binding, intake, setting):
    # Only restore the accepted native records; never import the new executor.
    from hle_unified.selection_execution import SelectionEngine
    from hle_unified.workflow_selection_execution import WorkflowFinalSelectionEngine
    cls = SelectionEngine if setting == 'canonical' else WorkflowFinalSelectionEngine
    return audit_fresh_task_intake(cls.restore(native), cls.restore(original), source, binding, intake)


def audit_fresh_domain(native, original, source, binding, intake, domain):
    def require(ok, why):
        if not ok: raise ValueError('fresh request audit: '+why)
    d = loads(domain); i = loads(intake); s = loads(source)
    require(i['receipt'] is not None, 'settled intake')
    require(d['native_sha256'] == sha256(native.checkpoint().encode()).hexdigest()
        and d['source_sha256'] == sha256(source.encode()).hexdigest()
        and d['binding_sha256'] == sha256(binding.encode()).hexdigest()
        and d['intake_sha256'] == sha256(intake.encode()).hexdigest(), 'exact input pairing')
    intake_proof(native.checkpoint(), original.checkpoint(), source, binding, intake, s['setting'])
    actor = s['actor']; view = native.participant_view(actor); owned = view._bindings[i['task']]
    c = loads(s['demand_controller']); ledger = loads(c['ledger'])
    require(d['controller_prefix'] == s['demand_controller'] == i['controller_prefix'], 'immutable original controller')
    key = dumps((actor, owned.ref))
    require(key not in ledger['demands'] and actor not in native._locks, 'fresh unlocked task')
    for b in view._heads.values():
        if b.endorsement.value in ('retracted','disputed') or b.ref == owned.ref: continue
        if any(p.relation in ('c6.need','c7ws.need') for p in b.content):
            prior_key = dumps((actor,b.ref))
            require(prior_key in ledger['demands'] and prior_key in c['outcomes'], 'no skipped older current need')
    paid = view.receipt(owned.receipt)
    require(paid is not None and paid.complete and paid.actor == actor
        and paid.operation == 'bind' and paid.spent == paid.required == 3, 'current paid owned fresh task')
    payload = (demand_value if s['setting'] == 'canonical' else workflow_need)(decode(owned.content[0].object))
    fresh = dict(actor=actor,binding=owned.ref,receipt=owned.receipt,context=owned.context,
        cue=owned.cue,target=owned.target,relation=owned.content[0].relation,payload=payload,
        raw_payload=owned.content[0].object,first_seen=ledger['turn'],admitted_at=ledger['turn'],
        status='pending',reason=None)
    require(d['fresh_demand'] == fresh, 'exact new demand extension')
    common = dict(key='ft-request:'+sha256(key.encode()).hexdigest(),actor=actor,
        context=owned.context,cue=owned.cue,target=owned.target,demand=owned.ref)
    content = []
    if s['setting'] == 'workflow':
        for b in view._heads.values():
            receipt = view.receipt(b.receipt)
            if (b.endorsement.value not in ('retracted','disputed') and len(b.content)==1
                and b.content[0].relation=='c7w.data' and (b.context,b.cue,b.target)==(owned.context,owned.cue,owned.target)
                and receipt is not None and receipt.complete and receipt.actor==actor and receipt.spent>=receipt.required):
                content.append(b.ref)
        content.sort(key=dumps);require(1<=len(content)<=8,'bounded owned workflow content')
        request = WorkflowSelectionRequest(**common,accessible=tuple(content))
    else: request = SelectionRequest(**common)
    formation = dict(policy='owned-native-request-v1',actor=actor,selected=key,
        request=fields_of(request),reason='ready_for_native_comparison',rejected=[],content=tuple(content))
    require(d['request']==fields_of(request) and d['formation']==formation, 'route-free original-role request')
    snap = _snapshot(native,view,request,s['setting'])
    require(d['snapshot']==snap, 'independently reconstructed current owned snapshot')
    if s['setting']=='canonical':
        refs = [dict(canonical_reference(snap,k),cell=k) for k in range(33)]
        required=1+snap['scanned']+snap['foreign_total']+33+sum(x['examined'] for x in refs)
        nominee=min((x for x in refs if x['eligible'] and x['score']>0),
            key=lambda x:(-x['score'],x['cell'],dumps(x['inputs'])),default=None)
    else:
        refs,nominee=workflow_reference(snap)
        required=1+len(snap['items'])+len(refs)+sum(x['examined'] for x in refs)
    rows=d['candidates']
    require(len(rows)==len(refs) and [x['cell'] for x in rows]==list(range(len(refs))), 'all cells retained')
    for row,ref in zip(rows,refs):
        require(all(row.get(k)==v for k,v in ref.items()) and isinstance(row.get('reason'),str) and row['reason'], 'exact native reference comparison')
    selected=None if nominee is None else rows[nominee['cell']]
    complete=not(snap.get('truncated',False) or snap.get('foreign_total',0)>len(snap.get('foreign',())) or any(x['deferred'] for x in refs))
    require(d['native_nominee']==selected and d['comparison_required']==required and d['bounded_search_complete']==complete, 'nominee, extent and search bounds')
    require(set(d)=={'version','actor','setting','native_sha256','source_sha256','binding_sha256',
        'intake_sha256','controller_prefix','fresh_demand','formation','request','snapshot','candidates',
        'native_nominee','comparison_required','comparison_paid','cell_domain_complete','bounded_search_complete',
        'execution_authorized','td5_admitted','history_choice'}, 'schema')
    require(d['version']=='ft-fresh-task-comparison-domain-v1' and d['actor']==actor and d['setting']==s['setting']
        and d['cell_domain_complete'] is True and all(d[k] is False for k in
        ('comparison_paid','execution_authorized','td5_admitted','history_choice')), 'comparison-only scope')
    return dict(passed=True,cells=len(refs),required=required,bounded_search_complete=complete)


def audit_fresh_paid_comparison(engine, source_engine, original, source, binding, intake, domain):
    def require(ok, why):
        if not ok:raise ValueError('paid comparison audit: '+why)
    audit_fresh_domain(source_engine,original,source,binding,intake,domain)
    d=loads(domain);r=d['request'];actor=d['actor'];required=d['comparison_required']
    require(r is not None and required>0,'pending owned request')
    key='ft-owned-comparison:fresh:'+sha256(intake.encode()).hexdigest()[:24]
    old=tuple(source_engine.world.journal());txs=tuple(engine.world.journal())
    require(txs[:len(old)]==old,'exact original journal prefix')
    access=unseal(engine.access.checkpoint(),engine.access.SCHEMA)
    source_access=unseal(source_engine.access.checkpoint(),source_engine.access.SCHEMA)
    require(set(access)==set(source_access)=={'world','nodes','events'} and
        access['nodes']==source_access['nodes'] and access['events']==source_access['events'],
        'participant access nodes and events unchanged')
    require(access['world']==engine.world.checkpoint() and source_access['world']==source_engine.world.checkpoint(),
        'access paired with exact respective native world')
    def extent(op):
        if not op.get('ftpc'):return previous_extent(op)
        require(op['required']==required and op['route_prepare']==required and
            op['route_execute']==0 and op['primitive']=='bind','exact paid extent')
    audit_native(txs,extent_check=extent,extended_flags=('c1','c2','c3','c4','c6','c7w','c7ws','ftpc'))
    heads={v.ref.identity:v for tx in old for v in tx.versions}
    wallets=[v for v in heads.values() if attrs(v).get('record_type')=='wallet' and attrs(v).get('actor')==actor]
    require(len(wallets)==1,'one original wallet');wallet=wallets[0];initial_wallet=attrs(wallet)
    opid=address('u4.operation',actor,key).identity
    snapref=address('ftpc.snapshot',actor,key);rowsref=address('ftpc.candidates',actor,key)
    resultref=address('ftpc.result',actor,key)
    require(all(i not in heads for i in (opid,snapref.identity,rowsref.identity,resultref.identity)),'fresh identities')
    base=fields_of(OperationRequest(key,actor,'bind',r['context']))
    base.pop('participants');base.pop('evidence')
    base.update(record_type='operation',ftpc=True,primitive='bind',policy='ft-owned-paid-comparison-v1',
        setting=d['setting'],required=required,route_prepare=required,route_execute=0,
        snapshot=snapref,candidates=rowsref,scanned=d['snapshot'].get('scanned',len(d['snapshot']['items'])),
        foreign_count=d['snapshot'].get('foreign_total',0),candidate_count=len(d['candidates']),
        evaluated=sum(x['examined'] for x in d['candidates']),
        **{'participant.0':actor,'lock.0':actor,'input.0':r['demand'],'dependency.0':source_engine.law})
    previous=None;receipts=0;result=None
    for index,tx in enumerate(txs[len(old):],len(old)):
        versions={v.ref.identity:v for v in tx.versions}
        require(len(versions)==len(tx.versions) and opid in versions,'one registered comparison per suffix transaction')
        job=versions[opid];op=attrs(job)
        dynamic={'completed','spent','status','failure','result','started_tick'}
        if op['status'] in ('succeeded','failed','cancelled'):dynamic.add('finished_tick')
        require(set(op)==set(base)|dynamic and all(op[k]==v for k,v in base.items()),'exact operation fields')
        require(op['started_tick']==len(old),'fresh start tick')
        pd={} if previous is None else attrs(previous)
        delta=op['completed']-pd.get('completed',0)
        allowed={opid}
        if previous is None:
            require(index==len(old) and op['status']=='pending' and op['completed']==op['spent']==0 and
                op['failure'] is None and op['result'] is None,'unpaid initial state')
            allowed|={snapref.identity,rowsref.identity}
            require(attrs(versions[snapref.identity])=={'payload':dumps(d['snapshot'])} and
                loads(attrs(versions[rowsref.identity])['payload'])==d['candidates'] and
                set(attrs(versions[rowsref.identity]))=={'payload'},'exact scoped snapshot and full ballot')
        elif op['status'] in ('partial','waiting','ready'):
            require(pd['status'] in ('pending','partial','waiting') and op['failure'] is None and op['result'] is None,
                'valid paid work transition')
            if delta:allowed.add(wallet.ref.identity)
        else:
            require(delta==0 and op['finished_tick']==index and op['status'] in ('succeeded','cancelled'),
                'registered terminal transition')
            event=versions.get(op['result'].identity)
            require(event is not None and event.facet(Account).at.tick==index,'native event chronology')
            expected_event=dict(actor=actor,primitive='bind',context=r['context'],outcome=op['status'],
                operation=previous.ref,event=event.ref,**{'participant.0':actor})
            if d['setting']=='workflow':expected_event['workflow_tick']=index
            require(attrs(event)==expected_event,'exact terminal event')
            allowed.add(event.ref.identity)
            if op['status']=='succeeded':
                require(pd['status']=='ready' and op['completed']==op['spent']==required,'fully paid settlement')
                receipt_rows=[v for v in tx.versions if v.ref.identity.namespace=='u4.receipt']
                require(len(receipt_rows)==1,'one completion receipt');receipt=receipt_rows[0];receipts+=1
                require(attrs(receipt)==dict(actor=actor,operation='bind',work_key=key,required=required,
                    completed=required,spent=required,**{'input.0':r['demand']}),'exact receipt fields')
                result=versions.get(resultref.identity);require(result is not None,'settled comparison result')
                rd=attrs(result)
                require(set(rd)=={'operation','receipt','policy','payload'} and rd['operation']==job.ref and
                    rd['receipt']==receipt.ref and rd['policy']==base['policy'],'result native pairing')
                require(loads(rd['payload'])==dict(candidates=d['candidates'],native_nominee=d['native_nominee'],
                    comparison_paid=True,comparison_required=required,execution_authorized=False),'result is comparison only')
                allowed|={receipt.ref.identity,result.ref.identity}
            else:require(pd['status'] in ('pending','partial','waiting','ready'),'cancel active only')
        require(set(versions)==allowed,'no hidden operation, movement, content or history writes')
        require(job.ref.revision==(1 if previous is None else previous.ref.revision+1),'exact job revisions')
        for v in tx.versions:heads[v.ref.identity]=v
        previous=job
    final={} if previous is None else attrs(previous);spent=final.get('spent',0)
    after=attrs(heads[wallet.ref.identity]);expected_wallet=dict(initial_wallet)
    expected_wallet.update(energy=initial_wallet['energy']-spent,time=initial_wallet['time']-spent)
    require(after==expected_wallet,'exact native debit without refund or default change')
    require(receipts==int(final.get('status')=='succeeded') and (result is not None)==bool(receipts),'no early result or duplicate credit')
    original_commands = tuple(source_engine._pool.get(t) for t in source_engine._events)
    commands = tuple(engine._pool.get(t) for t in engine._events)
    require(commands[:len(original_commands)] == original_commands, 'exact native command prefix')
    suffix = tuple(x[0] for x in commands[len(original_commands):])
    require(bool(suffix) == bool(previous), 'command and journal suffix agree')
    if suffix:
        require(suffix[0][0]=='start' and suffix[0][1]==key+':start', 'exact fresh start')
        request_fields = fields_of(suffix[0][2])
        require(set(request_fields)=={'key','request'} and request_fields['key']==key
            and fields_of(request_fields['request'])==r, 'exact command request')
        for cmd in suffix[1:]:
            require(cmd[0] in ('advance','commit','cancel') and cmd[2:4]==(actor,key), 'comparison-only command')
        require(sum(c[0]=='commit' for c in suffix)==int(final.get('status')=='succeeded')
            and sum(c[0]=='cancel' for c in suffix)==int(final.get('status')=='cancelled'), 'terminal command uniqueness')
    return dict(passed=True,status=final.get('status','before'),required=required,spent=spent,
        native_cost=dict(energy=spent,time=spent),receipts=receipts,new_transactions=len(txs)-len(old),
        source_prefix_exact=True,access_unchanged=True,reserve_history_unchanged=True,execution_authorized=False,td5_admitted=False,history_choice=False)
