"""Independent complete request-window/payment audit; no new executor or selector."""
from hashlib import sha256
from collections import OrderedDict
from hle_unified.selection_records import SelectionRequest,fields_of,dumps,loads
from hle_unified.workflow_selection_records import WorkflowSelectionRequest
from hle_unified.records import Account
from hle_unified.operation_records import OperationRequest
from hle_unified.operations import address
from hle_unified.material import attrs
from hle_unified.compact import unseal
from hle_unified.development_audit import audit as audit_native
from hle_unified.workflow_selection_audit import extent as previous_extent,reference as workflow_reference
from hle_unified.selection_audit import reference as canonical_reference
from .owned_proposal_domain_audit import _snapshot
from .owned_request_windows_audit import audit_owned_request_windows
from .paid_role_comparison_audit import snapshot_digest

def digest(text):return sha256(text.encode()).hexdigest()

_REFERENCE_CACHE=OrderedDict()

def reconstruct(old,original,source,binding,intake,windows):
    audit_owned_request_windows(old,original,source,binding,intake,windows)
    cache_key=(digest(old.checkpoint()),windows)
    if cache_key in _REFERENCE_CACHE:
        _REFERENCE_CACHE.move_to_end(cache_key)
        return loads(_REFERENCE_CACHE[cache_key])
    d=loads(windows);view=old.participant_view(d['actor']);output=[]
    cls=SelectionRequest if d['setting']=='canonical' else WorkflowSelectionRequest
    for ordinal,fields in enumerate(d['requests']):
        r=cls(**fields)
        try:s=_snapshot(old,view,r,d['setting'])
        except ValueError as error:
            output.append(dict(ordinal=ordinal,request_sha256=digest(dumps(fields)),rejection=str(error),
                required=1,snapshot_sha256=None,candidates=(),nominee=None));continue
        if d['setting']=='canonical':
            rows=[dict(canonical_reference(s,i),cell=i) for i in range(33)]
            nominee=min((x for x in rows if x['eligible'] and x['score']>0),
                key=lambda x:(-x['score'],x['cell'],dumps(x['inputs'])),default=None)
            required=1+s['scanned']+s['foreign_total']+33+sum(x['examined'] for x in rows)
        else:
            rows,nominee=workflow_reference(s)
            required=1+len(s['items'])+len(rows)+sum(x['examined'] for x in rows)
        keys=(('cell','recipe','origin','destination','face','inputs','eligible','benefit','grounding',
              'effort','score','examined','deferred') if d['setting']=='canonical' else
              ('cell','recipe','inputs','eligible','priority','preference','effort','coverage','examined','deferred'))
        output.append(dict(ordinal=ordinal,request_sha256=digest(dumps(fields)),rejection=None,
            required=required,snapshot_sha256=snapshot_digest(s,d['setting']),
            candidates=tuple({k:x[k] for k in keys} for x in rows),
            nominee=None if nominee is None else nominee['cell']))
    _REFERENCE_CACHE[cache_key]=dumps(output)
    while len(_REFERENCE_CACHE)>2:_REFERENCE_CACHE.popitem(last=False)
    return output

def audit_paid_windows(engine,old,original,source,binding,intake,windows):
    def require(ok,why):
        if not ok:raise ValueError('paid window audit: '+why)
    rows=reconstruct(old,original,source,binding,intake,windows)
    d=loads(windows);f=d['fresh_demand'];r=dict(context=f['context'],demand=f['binding']);actor=d['actor'];key='ft-window-comparison:'+digest(windows)
    required=sum(x['required'] for x in rows);before=tuple(old.world.journal());txs=tuple(engine.world.journal())
    require(txs[:len(before)]==before,'exact accepted native prefix')
    oldwire=unseal(old.checkpoint(),old.SCHEMA);wire=unseal(engine.checkpoint(),engine.SCHEMA)
    # Native checkpoints carry a complete ordered command log; no unrelated suffix is permitted below.
    require(set(oldwire)==set(wire),'native envelope fields')
    commands=tuple(engine._pool.get(t) for t in engine._events)
    original_commands=tuple(old._pool.get(t) for t in old._events)
    require(commands[:len(original_commands)]==original_commands,'exact command prefix')
    suffix=commands[len(original_commands):]
    require(len(suffix)==len(txs)-len(before),'one native command per suffix transaction')
    for index,(command,_) in enumerate(suffix):
        kind=command[0]
        if index==0:
            require(kind=='start' and command[1]==key+':start' and len(command)==3,'exact start command')
            q=command[2]
            require(type(q).__name__=='WindowComparisonRequest' and set(fields_of(q))=={'key','windows','evidence'} and
                (q.key,q.windows,q.evidence)==(key,windows,(original.checkpoint(),source,binding,intake)),
                'exact window request and immutable source proof')
        elif kind=='advance':
            require(len(command)==5 and command[2:4]==(actor,key) and type(command[4]) is int and command[4]>0,'exact advance domain')
            current=attrs(next(v for v in txs[len(before)+index-1].versions if v.ref.identity==address('u4.operation',actor,key).identity))
            require(command[1]==key+':work:'+str(current['completed'])+':'+str(command[4]),'exact paid command identity')
        else:require(kind in ('commit','cancel') and command==(kind,key+':'+kind,actor,key),'no unrelated suffix commands')
    a=unseal(old.access.checkpoint(),old.access.SCHEMA);z=unseal(engine.access.checkpoint(),engine.access.SCHEMA)
    require(set(a)==set(z)=={'world','nodes','events'} and a['nodes']==z['nodes'] and a['events']==z['events'],
        'unchanged paid access')
    require(z['world']==engine.world.checkpoint(),'paired access world')
    def extent(op):
        if op.get('ftwc'):
            require(op['required']==required and op['route_prepare']==required and op['route_execute']==0,
                'full window comparison extent')
        elif op.get('ftpc'):
            require(op['required']==1+op['scanned']+op['foreign_count']+op['candidate_count']+op['evaluated'],
                'old comparison extent unchanged')
        else:previous_extent(op)
    audit_native(txs,extent_check=extent,extended_flags=('c1','c2','c3','c4','c6','c7w','c7ws','ftpc','ftwc'))
    heads={v.ref.identity:v for tx in before for v in tx.versions}
    wallets=[v for v in heads.values() if attrs(v).get('record_type')=='wallet' and attrs(v).get('actor')==actor]
    require(len(wallets)==1,'one current wallet');wallet=wallets[0];initial=attrs(wallet)
    opid=address('u4.operation',actor,key).identity;snap=address('ftwc.snapshot',actor,key)
    ballot=address('ftwc.candidates',actor,key);resultref=address('ftwc.result',actor,key)
    base=fields_of(OperationRequest(key,actor,'bind',r['context']));base.pop('participants');base.pop('evidence')
    base.update(record_type='operation',ftwc=True,primitive='bind',policy='ft-paid-owned-window-comparison-v1',setting=d['setting'],
        required=required,route_prepare=required,route_execute=0,snapshot=snap,candidates=ballot,windows=len(rows),
        **{'participant.0':actor,'lock.0':actor,'input.0':r['demand'],'dependency.0':old.law})
    require(all(i not in heads for i in (opid,snap.identity,ballot.identity,resultref.identity)),'fresh work')
    previous=None;receipts=0;result=None
    for index,tx in enumerate(txs[len(before):],len(before)):
        versions={v.ref.identity:v for v in tx.versions};require(len(versions)==len(tx.versions) and opid in versions,'exact job suffix')
        job=versions[opid];op=attrs(job);dynamic={'completed','spent','status','failure','result','started_tick'}
        if op['status'] in ('succeeded','cancelled'):dynamic.add('finished_tick')
        require(set(op)==set(base)|dynamic and all(op[k]==v for k,v in base.items()),'exact operation fields')
        require(op['started_tick']==len(before),'start chronology');pd={} if previous is None else attrs(previous)
        delta=op['completed']-pd.get('completed',0);allowed={opid}
        if previous is None:
            require(index==len(before) and op['status']=='pending' and op['completed']==op['spent']==0 and
                op['result'] is None and op['failure'] is None,'unpaid initial state')
            allowed|={snap.identity,ballot.identity}
            require(attrs(versions[snap.identity])==dict(windows_sha256=digest(windows),
                view_sha256=digest(old.participant_view(actor).bytes()),profile=old._profiles[actor],cursor=old._cursors[actor]),'exact snapshot')
            require(attrs(versions[ballot.identity])=={'payload':dumps(rows)},'full independently reconstructed ballot')
        elif op['status'] in ('partial','waiting','ready'):
            require(pd['status'] in ('pending','partial','waiting') and op['result'] is None and op['failure'] is None,'paid progress')
            if delta:allowed.add(wallet.ref.identity)
        else:
            require(delta==0 and op['status'] in ('succeeded','cancelled') and op['finished_tick']==index,'terminal transition')
            event=versions[op['result'].identity];allowed.add(event.ref.identity)
            ev=dict(actor=actor,primitive='bind',context=r['context'],outcome=op['status'],operation=previous.ref,
                event=event.ref,**{'participant.0':actor})
            if d['setting']=='workflow':ev['workflow_tick']=index
            require(attrs(event)==ev and event.facet(Account).at.tick==index,'exact terminal event')
            if op['status']=='succeeded':
                require(pd['status']=='ready' and op['completed']==op['spent']==required,'fully paid settlement')
                found=[v for v in tx.versions if v.ref.identity.namespace=='u4.receipt'];require(len(found)==1,'one receipt')
                receipt=found[0];receipts+=1
                require(attrs(receipt)==dict(actor=actor,operation='bind',work_key=key,required=required,completed=required,
                    spent=required,**{'input.0':r['demand']}),'exact receipt')
                result=versions[resultref.identity]
                require(attrs(result)==dict(operation=job.ref,receipt=receipt.ref,policy=base['policy'],payload=dumps(dict(
                    windows=rows,required=required,comparison_paid=True,execution_authorized=False,
                    td5_admitted=False,history_choice=False))),'exact result with no execution authority')
                allowed|={receipt.ref.identity,resultref.identity}
        require(set(versions)==allowed,'no unrelated suffix versions')
        require(job.ref.revision==(1 if previous is None else previous.ref.revision+1),'exact job revisions')
        heads.update(versions);previous=job
    final={} if previous is None else attrs(previous);spent=final.get('spent',0);expected_wallet=dict(initial)
    expected_wallet.update(energy=initial['energy']-spent,time=initial['time']-spent)
    require(attrs(heads[wallet.ref.identity])==expected_wallet,'exact debit without refund')
    require(receipts==int(final.get('status')=='succeeded'),'no early or duplicate receipt')
    return dict(passed=True,status=final.get('status','before'),windows=len(rows),
        rejected=sum(x['rejection'] is not None for x in rows),required=required,spent=spent,receipts=receipts,
        execution_authorized=False,history_choice=False)

