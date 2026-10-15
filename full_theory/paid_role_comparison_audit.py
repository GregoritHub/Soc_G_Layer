"""Independent full role comparison/payment reconstruction, no selector imports."""
from hashlib import sha256
from itertools import product
from collections import OrderedDict
from hle_unified import codec
from hle_unified.selection_records import SelectionRequest,fields_of,dumps,loads
from hle_unified.workflow_selection_records import WorkflowSelectionRequest,WorkflowCapacitySelectionRequest
from hle_unified.records import Procedure,Account
from hle_unified.operation_records import OperationRequest,SIGNATURES
from hle_unified.operations import address
from hle_unified.material import attrs
from hle_unified.compact import unseal
from hle_unified.development_audit import audit as audit_native
from hle_unified.workflow_selection_audit import extent as previous_extent,reference as workflow_reference
from hle_unified.selection_audit import reference as canonical_reference
from .owned_proposal_domain_audit import _snapshot
from .owned_role_domain_audit import audit_role_payload


def digest(text):return sha256(text.encode()).hexdigest()


def snapshot_digest(value,setting):
    if setting=='canonical':return digest(dumps(value))
    def canonical(node):
        kind=type(node)
        if kind is dict:
            if not all(type(key) is str for key in node):raise ValueError('snapshot key type')
            entries=tuple((key,canonical(item)) for key,item in sorted(node.items()))
            return 'map',entries
        if kind in (tuple,list):return ('tuple' if kind is tuple else 'list',tuple(map(canonical,node)))
        return 'leaf',node
    return digest(codec.dumps(canonical(value)))


_REFERENCE_CACHE=OrderedDict()


def reconstruct(old,roles,prepared):
    d=loads(roles);p=loads(prepared);view=old.participant_view(d['request']['actor'])
    audit_role_payload(view.snapshot,p['request'],d['setting'],len(p['receipts'])==p['required'],roles,
        digest(old.checkpoint()),digest(prepared),digest(view.bytes()))
    if not d['settled']:raise ValueError('settled role source required')
    cache_key=(digest(old.checkpoint()),roles,prepared)
    if cache_key in _REFERENCE_CACHE:
        _REFERENCE_CACHE.move_to_end(cache_key)
        return loads(_REFERENCE_CACHE[cache_key])
    output=[]
    for ordinal,values in enumerate(product(*(d['pools'][n] for n in d['role_order']))):
        fields=dict(d['request']);fields.update((n,v['value']) for n,v in zip(d['role_order'],values))
        fields['key']='ft-owned-roles:'+d['preparation_sha256']+':'+str(ordinal)
        if d['setting']=='canonical':r=SelectionRequest(**fields)
        elif fields.get('procedure') is not None:r=WorkflowCapacitySelectionRequest(**fields)
        else:
            fields.pop('procedure',None);r=WorkflowSelectionRequest(**fields)
        rejection=None;definition=None
        if d['setting']=='workflow' and fields.get('procedure') is not None:
            definitions=[x.value for x in view.resolve(fields['procedure']) if type(x.value) is Procedure]
            if len(definitions)!=1:rejection='paid exact care procedure required'
            else:
                q=definitions[0]
                if q.executor!='u4.care.v1' or q.inputs!=SIGNATURES['care'] or q.steps or q.preconditions or q.effects:
                    rejection='supported native care procedure required'
                else:definition={k:getattr(q,k) for k in ('executor','inputs','preconditions','steps','effects')}
        if rejection is not None:
            output.append(dict(ordinal=ordinal,request_sha256=digest(dumps(fields)),rejection=rejection,
                required=1,snapshot_sha256=None,candidates=(),nominee=None));continue
        s=_snapshot(old,view,r,d['setting'])
        if d['setting']=='canonical':
            rows=[dict(canonical_reference(s,i),cell=i) for i in range(33)]
            nominee=min((x for x in rows if x['eligible'] and x['score']>0),
                key=lambda x:(-x['score'],x['cell'],dumps(x['inputs'])),default=None)
            required=1+s['scanned']+s['foreign_total']+33+sum(x['examined'] for x in rows)
        else:
            if definition is not None:
                s['procedure']=definition;s['acquired']=tuple((a.procedure,a.context,a.receipt)
                    for a in view.snapshot.acquired if a.procedure==fields['procedure'] and a.context==r.context)
            rows,nominee=workflow_reference(s)
            required=1+len(s['items'])+len(rows)+sum(x['examined'] for x in rows)
        keys=(('cell','recipe','origin','destination','face','inputs','eligible','benefit','grounding',
              'effort','score','examined','deferred') if d['setting']=='canonical' else
              ('cell','recipe','inputs','eligible','priority','preference','effort','coverage','examined','deferred'))
        output.append(dict(ordinal=ordinal,request_sha256=digest(dumps(fields)),rejection=None,
            required=required,snapshot_sha256=snapshot_digest(s,d['setting']),candidates=tuple({k:x[k] for k in keys} for x in rows),
            nominee=None if nominee is None else nominee['cell']))
    _REFERENCE_CACHE[cache_key]=dumps(output)
    while len(_REFERENCE_CACHE)>2:_REFERENCE_CACHE.popitem(last=False)
    return output


def audit_paid_roles(engine,old,roles,prepared):
    def require(ok,why):
        if not ok:raise ValueError('paid role audit: '+why)
    rows=reconstruct(old,roles,prepared)
    d=loads(roles);r=d['request'];actor=r['actor'];key='ft-role-comparison:'+digest(roles)
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
            require(type(q).__name__=='RoleComparisonRequest' and set(fields_of(q))=={'key','roles','prepared','evidence'} and
                (q.key,q.roles,q.prepared)==(key,roles,prepared) and type(q.evidence) is tuple and len(q.evidence)==7,
                'bound role request and immutable source proof')
            p=loads(prepared)
            require(tuple(digest(x) for x in q.evidence)==tuple(p[n] for n in (
                'source_native_sha256','source_sha256','binding_sha256','domain_sha256',
                'comparison_native_sha256','operands_sha256','admission_sha256')),'all original source identities')
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
        if op.get('ftrc'):
            require(op['required']==required and op['route_prepare']==required and op['route_execute']==0,
                'full role comparison extent')
        elif op.get('ftpc'):
            require(op['required']==1+op['scanned']+op['foreign_count']+op['candidate_count']+op['evaluated'],
                'old comparison extent unchanged')
        else:previous_extent(op)
    audit_native(txs,extent_check=extent,extended_flags=('c1','c2','c3','c4','c6','c7w','c7ws','ftpc','ftrc'))
    heads={v.ref.identity:v for tx in before for v in tx.versions}
    wallets=[v for v in heads.values() if attrs(v).get('record_type')=='wallet' and attrs(v).get('actor')==actor]
    require(len(wallets)==1,'one current wallet');wallet=wallets[0];initial=attrs(wallet)
    opid=address('u4.operation',actor,key).identity;snap=address('ftrc.snapshot',actor,key)
    ballot=address('ftrc.candidates',actor,key);resultref=address('ftrc.result',actor,key)
    base=fields_of(OperationRequest(key,actor,'bind',r['context']));base.pop('participants');base.pop('evidence')
    base.update(record_type='operation',ftrc=True,primitive='bind',policy='ft-paid-owned-role-comparison-v1',setting=d['setting'],
        required=required,route_prepare=required,route_execute=0,snapshot=snap,candidates=ballot,assignments=len(rows),
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
            require(attrs(versions[snap.identity])==dict(roles_sha256=digest(roles),
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
                    assignments=rows,required=required,comparison_paid=True,execution_authorized=False,
                    td5_admitted=False,history_choice=False))),'exact result with no execution authority')
                allowed|={receipt.ref.identity,resultref.identity}
        require(set(versions)==allowed,'no unrelated suffix versions')
        require(job.ref.revision==(1 if previous is None else previous.ref.revision+1),'exact job revisions')
        heads.update(versions);previous=job
    final={} if previous is None else attrs(previous);spent=final.get('spent',0);expected_wallet=dict(initial)
    expected_wallet.update(energy=initial['energy']-spent,time=initial['time']-spent)
    require(attrs(heads[wallet.ref.identity])==expected_wallet,'exact debit without refund')
    require(receipts==int(final.get('status')=='succeeded'),'no early or duplicate receipt')
    return dict(passed=True,status=final.get('status','before'),assignments=len(rows),
        rejected=sum(x['rejection'] is not None for x in rows),required=required,spent=spent,receipts=receipts,
        execution_authorized=False,history_choice=False)
