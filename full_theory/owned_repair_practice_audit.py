"""Independent reconstruction of the fixed owned practice panel and paid effects."""
from functools import lru_cache
from hashlib import sha256
from hle_unified.compact import unseal, ValuePool
from hle_unified.material import OperationStore, attrs
from hle_unified.operations import NativeAccess, address
from hle_unified.records import Procedure, Material
from hle_unified.particulars import AcquiredUse
from hle_unified.operation_records import OperationRequest
from hle_unified.selection_records import dumps, loads
from hle_unified.development_audit import audit as native_audit
from hle_unified.workflow_selection_audit import extent as old_extent


def digest(text): return sha256(text.encode()).hexdigest()


@lru_cache(maxsize=1)
def baseline(text,schema):
    data=unseal(text,schema)
    return data,tuple(OperationStore.restore(data['world']).journal()),NativeAccess.restore(data['access'])


def independent_plan(view,actor,context):
    # Deliberately does not import the controller or its generator.
    details={}
    for p in view.snapshot.particulars:details.setdefault(p.source,{})[p.address.key]=p.value
    eligible=[]
    for ref,fields in details.items():
        for value in fields.values():
            if type(value) is Procedure and (value.executor,value.inputs,value.preconditions,value.steps,value.effects)==(
                'u4.repair.v1',('target','tool','stock'),(),(),()) and not view.can_use(ref,context):
                eligible.append(ref)
    if not eligible:return None,()
    procedure=min(set(eligible),key=dumps);latest={}
    for ref,fields in details.items():
        if (ref.identity.namespace=='u4.observation' and fields.get('primitive')=='inspect'
            and fields.get('outcome')=='succeeded' and fields.get('actor')==actor and fields.get('context')==context
            and fields.get('target') is not None):latest[fields['target'].identity]=fields
    targets=[];tools=[];stocks=[]
    for fields in latest.values():
        if (fields.get('owner'),fields.get('custodian'))!=(actor,actor):continue
        ref=fields['target'];condition=fields.get('condition')
        if condition=='damaged':targets.append(ref)
        elif condition=='serviceable':tools.append(ref)
        elif condition=='stock' and type(fields.get('available')) is int and fields['available']>0:
            if details.get(ref,{}).get('purpose','repair')=='repair':stocks.append(ref)
    rows=[]
    for target in targets:
        for tool in tools:
            for stock in stocks:
                if target.identity!=tool.identity and target.identity!=stock.identity and tool.identity!=stock.identity:
                    rows.append((target,tool,stock))
    if len(rows)>512:raise ValueError('audit practice bound')
    return procedure,tuple(sorted(rows,key=dumps))


def audit_owned_repair_practice(engine,original,intake,text):
    def require(ok,why):
        if not ok:raise ValueError('owned practice audit: '+why)
    d=loads(text);i=loads(intake);actor=i['actor'];context=i['context']
    require(digest(intake) == {'0eb6ec03ff64f4da8c297527fedb95d71398b7bb066a33f0c080f4881ac7b1d0':'af1b0953418ad0d9bfede22e440cf5de6333c3d5998b866d8867cc007da296a4','50ed4da94e7a03066d5b1099f1fc78f6e0d5ffa60d8af9a0e68b67735294080e':'652d2b82f47264f3e26a5c6ed6bdbafece3e62a85f844f36f06e4642b3ac0497'}.get(digest(original)), 'exact accepted intake identity')
    require(digest(original) in ('0eb6ec03ff64f4da8c297527fedb95d71398b7bb066a33f0c080f4881ac7b1d0',
        '50ed4da94e7a03066d5b1099f1fc78f6e0d5ffa60d8af9a0e68b67735294080e') and
        i['phase']=='complete' and i['expected_native_sha256']==digest(original),'accepted exact source')
    data,prior,access=baseline(original,engine.SCHEMA);view=access.view(actor)
    procedure,plan=independent_plan(view,actor,context)
    require(d['plan']==plan and d['procedure']==procedure,'complete owned plan')
    current=unseal(engine.checkpoint(),engine.SCHEMA);txs=tuple(engine.world.journal())
    require(current['initial']==data['initial'] and current['law']==data['law'] and txs[:len(prior)]==prior,'source prefix')
    pool=ValuePool(engine._registry());pool.load_nodes(data['nodes'])
    old_commands=tuple(pool.get(pool.import_token(t)) for t in data['commands'])
    commands=tuple(engine._pool.get(t) for t in engine._events)
    require(commands[:len(old_commands)]==old_commands,'command prefix')
    old_access=tuple(access.pool.get(t) for t in access._events)
    require(tuple(engine.access.pool.get(t) for t in engine.access._events)[:len(old_access)]==old_access,'access prefix')
    heads0={x.ref.identity:x for tx in prior for x in tx.versions}
    old_jobs={(attrs(x).get('actor'),attrs(x).get('key')):attrs(x) for x in heads0.values() if attrs(x).get('record_type')=='operation'}
    def extent(op):
        if op.get('ftwc') or op.get('ftpc'):
            known=old_jobs.get((op['actor'],op['key']))
            require(known is not None and all(op[k]==known[k] for k in ('required','route_prepare','route_execute')),'old comparison extent')
        else:old_extent(op)
    native_audit(txs,extent_check=extent,extended_flags=('c1','c2','c3','c4','c6','c7w','c7ws','ftpc','ftwc'))
    def heads(n):return {x.ref.identity:x for tx in txs[:n] for x in tx.versions}
    def wallet(h):
        rows=[attrs(x) for x in h.values() if attrs(x).get('record_type')=='wallet' and attrs(x).get('actor')==actor]
        require(len(rows)==1,'wallet identity');return rows[0]
    expected_commands=[];end=len(prior);index=0;phase='practice' if plan else 'exhausted';practice=None
    acquired=False;acquired_rows=list(view.snapshot.acquired);deliveries=set();successful=[];failed=0
    for number,e in enumerate(d['events']):
        require(set(e)=={'index','phase','job','action','before','after','work_limit','status','wallet_before','wallet_after','debit'},'exact event fields')
        require(phase in ('practice','read','acquire') and index<len(plan),'no terminal suffix')
        base='ft-skill-practice:'+digest(original)+':'+str(index);key=base+':'+phase;cid=key+':step:'+str(number)
        require(e['index']==number and e['phase']==phase and e['job']==key and e['before']==end and
            type(e['after']) is int and end<=e['after']<=len(txs),'event sequence')
        q=e['work_limit'];require(type(q) is int and q>0,'work bound')
        before=heads(end);after=heads(e['after']);bw=wallet(before);aw=wallet(after)
        identity=address('u4.operation',actor,key).identity;prev=attrs(before[identity]) if identity in before else {}
        require(identity in after,'job present');op=attrs(after[identity]);delta=op['completed']-prev.get('completed',0)
        require(op['actor']==actor and op['context']==context and op['primitive']==('repair' if phase=='practice' else phase)
            and op['required']=={'practice':6,'read':2,'acquire':3}[phase] and op['spent']==op['completed']
            and op['status']==e['status'],'native identity and extent')
        require(0<=delta<=q and e['wallet_before']==bw and e['wallet_after']==aw and
            e['debit']=={u:bw[u]-aw[u] for u in ('energy','time')}==dict(energy=delta,time=delta),'exact payment')
        if e['action']=='cancel':
            require(prev and op['status']=='cancelled' and delta==0,'nonrefundable cancellation')
            expected_commands.append(('cancel',cid+':cancel',actor,key));phase='cancelled'
        else:
            require(e['action']=='step','event action')
            if not prev:
                if phase=='practice':
                    target,tool,stock=plan[index]
                    evidence=tuple(p.address for p in view.snapshot.particulars if p.source in (target,tool,stock,procedure)
                                   or p.value in (target,tool,stock))
                    r=OperationRequest(key,actor,'repair',context,target=target,tool=tool,stock=stock,evidence=evidence)
                elif phase=='read':
                    practice_op=attrs(before[address('u4.operation',actor,base+':practice').identity])
                    require(practice_op['status'] in ('succeeded','failed'),'practice settled before read')
                    expected_commands.append(('deliver_event',base+':delivery',practice_op['result'],actor))
                    r=OperationRequest(key,actor,'read',context,delivery=base+':delivery')
                else:r=OperationRequest(key,actor,'acquire',context,procedure=procedure,practice=practice)
                expected_commands.append(('start',cid+':start',r))
            if prev.get('status') not in ('ready','succeeded','failed','cancelled'):expected_commands.append(('advance',cid+':work',actor,key,q))
            if op['status'] in ('succeeded','failed'):
                require(op['completed']==op['required'],'fully paid settlement')
                expected_commands.append(('commit',cid+':commit',actor,key))
                if phase=='practice':
                    if op['status']=='succeeded':successful.append(plan[index])
                    else:failed+=1
                    phase='read'
                elif phase=='read':
                    require(op['status']=='succeeded','read cannot be failed')
                    delivery=base+':delivery';deliveries.add(delivery)
                    obs=address('u4.observation',delivery,actor);facts=attrs(after[obs.identity])
                    require(facts['primitive']=='repair' and facts['actor']==actor and facts['context']==context,'owned exact practice observation')
                    if facts['outcome']=='succeeded':practice=facts['event'];phase='acquire'
                    else:
                        require(facts['outcome']=='failed','honest failed practice')
                        index+=1;phase='practice' if index<len(plan) else 'exhausted'
                else:
                    require(op['status']=='succeeded' and practice is not None,'successful acquisition')
                    acquired=True;phase='complete';acquired_rows.append(AcquiredUse(key,procedure,context,address('u4.receipt',cid+':commit')))
            else:require(op['status'] in ('partial','waiting'),'partial progress')
        end=e['after']
    require(end==len(txs) and tuple(x[0] for x in commands[len(old_commands):])==tuple(expected_commands),'exact command suffix')
    final=engine.participant_view(actor);old_details=view.snapshot.particulars;new_details=final.snapshot.particulars
    require(final.snapshot.bindings==view.snapshot.bindings and final.snapshot.acquired==tuple(acquired_rows),'binding and acquisition authority')
    require(new_details[:len(old_details)]==old_details,'owned evidence prefix')
    require({p.address.delivery for p in new_details[len(old_details):]}==deliveries,'only settled read observations')
    final_heads=heads(len(txs))
    for delivery in deliveries:
        observation=address('u4.observation',delivery,actor)
        ps=[p for p in new_details[len(old_details):] if p.address.delivery==delivery]
        require(all(p.source==observation for p in ps) and {p.address.key:p.value for p in ps}==attrs(final_heads[observation.identity]),'exact paid observation')
    changed_materials={r.identity for row in successful for r in row}
    require(all(final_heads[k]==v for k,v in heads0.items() if v.facet(Material) is not None and k not in changed_materials),'unrelated materials unchanged')
    require(all(x.ref.identity.namespace.startswith('u4.') or x.ref.identity in changed_materials
                for tx in txs[len(prior):] for x in tx.versions),'no demand/profile/source changes')
    expected=dict(version='ft-owned-repair-practice-a2-v1',actor=actor,context=context,source_native_sha256=digest(original),
        intake_sha256=digest(intake),expected_native_sha256=digest(engine.checkpoint()),procedure=procedure,plan=plan,index=index,
        phase=phase,events=d['events'],practice=practice,skill_acquired=acquired,main_execution_authorized=False,
        comparison_paid=False,td5_admitted=False,history_choice=False)
    require(dumps(d)==dumps(expected),'exact adapter and authority')
    return dict(passed=True,phase=phase,candidates=len(plan),successful_practices=len(successful),failed_practices=failed,
        acquired=acquired,energy=sum(e['debit']['energy'] for e in d['events']),time=sum(e['debit']['time'] for e in d['events']))
