"""Independent saved-prefix, native payment, observation and state-machine audit."""
from functools import lru_cache
from hashlib import sha256
from hle_unified.compact import unseal, ValuePool
from hle_unified.material import OperationStore, attrs
from hle_unified.operations import NativeAccess, address
from hle_unified.records import Material
from hle_unified.operation_records import OperationRequest
from hle_unified.selection_records import dumps, loads
from hle_unified.development_audit import audit as native_audit
from hle_unified.workflow_selection_audit import extent as old_extent


def digest(text): return sha256(text.encode()).hexdigest()


@lru_cache(maxsize=2)
def baseline(text,schema):
    data=unseal(text,schema); world=OperationStore.restore(data['world'])
    access=NativeAccess.restore(data['access'])
    return data,tuple(world.journal()),access


def audit_owned_material_inspection(engine,original,capacity,text):
    def require(ok,why):
        if not ok: raise ValueError('owned inspection audit: '+why)
    c=loads(capacity); d=loads(text); actor=c['actor']; context=c['required']['context']
    require(digest(capacity) in ('2d5315881624aa63d3420e922a1e5b20afe99f3550901047fac2d2f38201a476',
                                '0889c7bacec30519d432c7cdc71f80ea5d2b5089ca26b32cb2cc4d329185d8d0'),
            'registered exact accepted capacity')
    require(c['comparison_settled'] and digest(original)==c['native_sha256'],'accepted input pairing')
    require(d['source_native_sha256']==digest(original) and all(d[k] is False for k in
            ('main_execution_authorized','comparison_paid','td5_admitted','history_choice','skill_acquired')),
            'source identity and no unauthorized claims')
    data,prior,access=baseline(original,engine.SCHEMA); v=access.view(actor)
    ids={p.source.identity for p in v.snapshot.particulars
         if p.category=='name' or (p.address.key=='quantity' and type(p.value) is int)}
    require(len(ids)<=128,'inventory bound')
    plan=tuple(sorted((max((p.source for p in v.snapshot.particulars if p.source.identity==i),
                          key=lambda r:r.revision) for i in ids),key=dumps))
    require(d['plan']==plan,'exact fixed owned plan')
    current=unseal(engine.checkpoint(),engine.SCHEMA)
    require(current['initial']==data['initial'] and current['law']==data['law'],'unchanged native setup')
    txs=tuple(engine.world.journal()); require(txs[:len(prior)]==prior,'immutable journal prefix')
    pool=ValuePool(engine._registry()); pool.load_nodes(data['nodes'])
    old_commands=tuple(pool.get(pool.import_token(t)) for t in data['commands'])
    commands=tuple(engine._pool.get(t) for t in engine._events)
    require(commands[:len(old_commands)]==old_commands,'immutable command prefix')
    old_access=tuple(access.pool.get(t) for t in access._events)
    require(tuple(engine.access.pool.get(t) for t in engine.access._events)[:len(old_access)]==old_access,'access prefix')
    final_view=engine.participant_view(actor)
    require(final_view.snapshot.bindings==v.snapshot.bindings and final_view.snapshot.acquired==v.snapshot.acquired,
            'no binding, demand, retention or skill mutation')
    heads0={x.ref.identity:x for tx in prior for x in tx.versions}
    heads1={x.ref.identity:x for tx in txs for x in tx.versions}
    require(all(heads1[i]==x for i,x in heads0.items() if x.facet(Material) is not None),'no physical effect')
    require(all(x.ref.identity.namespace.startswith('u4.') for tx in txs[len(prior):] for x in tx.versions),
            'no profile/cursor/route/source revisions')
    old_jobs={ (attrs(x).get('actor'),attrs(x).get('key')):attrs(x) for x in heads0.values()
               if attrs(x).get('record_type')=='operation'}
    def extent(op):
        if op.get('ftwc') or op.get('ftpc'):
            known=old_jobs.get((op['actor'],op['key']))
            require(known is not None and all(op[k]==known[k] for k in ('required','route_prepare','route_execute')),
                    'accepted comparison extent remains exact')
        else: old_extent(op)
    native_audit(txs,extent_check=extent,extended_flags=('c1','c2','c3','c4','c6','c7w','c7ws','ftpc','ftwc'))
    expected_commands=[]; end=len(prior); item=0; phase='inspect' if plan else 'complete'; receipts=[]
    def heads(n): return {x.ref.identity:x for tx in txs[:n] for x in tx.versions}
    def wallet(h):
        ws=[attrs(x) for x in h.values() if attrs(x).get('record_type')=='wallet' and attrs(x).get('actor')==actor]
        require(len(ws)==1,'unique actor wallet'); return ws[0]
    for number,event in enumerate(d['events']):
        require(set(event)=={'index','item','phase','action','before','after','job','work_limit','rejection',
                            'status','wallet_before','wallet_after','debit'},'exact event fields')
        require(phase in ('inspect','read') and item<len(plan),'no work after terminal')
        base='ft-skill-inspect:'+digest(original)+':'+str(item); key=base+':'+phase
        cid=key+':step:'+str(number); before=heads(end)
        require(event['index']==number and event['item']==item and event['phase']==phase and event['job']==key
                and event['before']==end and type(event['after']) is int and end<=event['after']<=len(txs),'event sequence')
        q=event['work_limit']; require(type(q) is int and q>0,'work quantum')
        after=heads(event['after']); bw=wallet(before); aw=wallet(after)
        require(event['wallet_before']==bw and event['wallet_after']==aw and
                event['debit']=={u:bw[u]-aw[u] for u in ('energy','time')},'wallet projection')
        identity=address('u4.operation',actor,key).identity
        prev=attrs(before[identity]) if identity in before else {}
        if event['rejection'] is not None:
            require(event['action']=='step' and phase=='inspect' and not prev and event['after']==end
                    and event['rejection']=='material input role required' and event['status']=='rejected'
                    and before[plan[item].identity].facet(Material) is None and bw==aw,'exact nonmaterial rejection')
            item+=1
        else:
            require(identity in after,'saved job'); op=attrs(after[identity])
            require(op['actor']==actor and op['primitive']==phase and op['context']==context
                    and op['required']==(3 if phase=='inspect' else 2) and op['spent']==op['completed']
                    and event['status']==op['status'],'native extent and identity')
            delta=op['completed']-prev.get('completed',0)
            require(0<=delta<=q and event['debit']==dict(energy=delta,time=delta),'exact paid work')
            if event['action']=='cancel':
                require(prev and op['status']=='cancelled' and delta==0,'cancel without refund')
                expected_commands.append(('cancel',cid+':cancel',actor,key)); phase='cancelled'
            else:
                require(event['action']=='step','action')
                if not prev:
                    if phase=='inspect':
                        request=OperationRequest(key,actor,phase,context,target=plan[item],
                            evidence=tuple(p.address for p in v.resolve(plan[item])))
                    else:
                        inspect=attrs(before[address('u4.operation',actor,base+':inspect').identity])
                        require(inspect['status']=='succeeded','inspect before read')
                        expected_commands.append(('deliver_event',base+':delivery',inspect['result'],actor))
                        request=OperationRequest(key,actor,'read',context,delivery=base+':delivery')
                    expected_commands.append(('start',cid+':start',request))
                if prev.get('status') not in ('ready','succeeded','failed','cancelled'):
                    expected_commands.append(('advance',cid+':work',actor,key,q))
                if op['status']=='succeeded':
                    require(op['completed']==op['required'],'settlement fully paid')
                    expected_commands.append(('commit',cid+':commit',actor,key))
                    if phase=='inspect': phase='read'
                    else:
                        receipts.append(dict(index=item,inspect_job=base+':inspect',read_job=key))
                        item+=1; phase='inspect'
                else: require(op['status'] in ('partial','waiting'),'partial without credit')
        end=event['after']
        if item==len(plan): phase='complete'
    require(end==len(txs),'no unaccounted native suffix')
    require(tuple(x[0] for x in commands[len(old_commands):])==tuple(expected_commands),'exact allowed commands')
    old_details=v.snapshot.particulars; new_details=final_view.snapshot.particulars
    require(new_details[:len(old_details)]==old_details,'owned particular prefix')
    expected_deliveries={'ft-skill-inspect:'+digest(original)+':'+str(r['index'])+':delivery' for r in receipts}
    actual_deliveries={p.address.delivery for p in new_details[len(old_details):]}
    require(actual_deliveries==expected_deliveries,'only completed paid reads expose observation')
    for delivery in expected_deliveries:
        details=tuple(p for p in new_details[len(old_details):] if p.address.delivery==delivery)
        observation=address('u4.observation',delivery,actor)
        require(all(p.source==observation for p in details) and
                {p.address.key:p.value for p in details}==attrs(heads1[observation.identity]),'exact observation facts')
    expected=dict(version='ft-owned-material-inspection-a1-v1',actor=actor,context=context,
        task=c['preparation']['task'],source_native_sha256=digest(original),capacity_sha256=digest(capacity),
        expected_native_sha256=digest(engine.checkpoint()),start_count=len(prior),plan=plan,index=item,
        phase=phase,events=d['events'],receipts=receipts,main_execution_authorized=False,comparison_paid=False,
        td5_admitted=False,history_choice=False,skill_acquired=False)
    require(dumps(d)==dumps(expected),'exact adapter, progress and authority fields')
    return dict(passed=True,phase=phase,inventory=len(plan),receipts=len(receipts),
                rejected=sum(e['rejection'] is not None for e in d['events']),
                energy=sum(e['debit']['energy'] for e in d['events']),time=sum(e['debit']['time'] for e in d['events']))
