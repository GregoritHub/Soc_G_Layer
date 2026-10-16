"""Independent A5 owned-path, native-read, saved-field and prefix reconstruction."""
import json
from functools import lru_cache
from hashlib import sha256
from pathlib import Path
from hle_unified.compact import unseal, ValuePool
from hle_unified.material import OperationStore, attrs
from hle_unified.operations import NativeAccess, address
from hle_unified.particulars import Selector, read_path
from hle_unified.operation_records import OperationRequest
from hle_unified.selection_records import dumps, loads
from hle_unified.development_audit import audit as native_audit
from hle_unified.workflow_selection_audit import extent as old_extent


def digest(text): return sha256(text.encode()).hexdigest()


@lru_cache(maxsize=2)
def baseline(text,schema):
    data=unseal(text,schema)
    return data,OperationStore.restore(data['world']),NativeAccess.restore(data['access'])


def audit_observed_field_reads(engine,original,refresh,projection,setting,text):
    def require(ok,why):
        if not ok: raise ValueError('observed field audit: '+why)
    protocol=json.loads((Path(__file__).resolve().parents[1]/'contracts/ft/FT7_Observed_Fields_A5_Protocol_v1.json').read_text())
    entry=protocol['inputs'].get(setting)
    require(entry is not None and all(digest(t)==entry[k] for t,k in
        ((original,'native_sha256'),(refresh,'refresh_sha256'),(projection,'projection_sha256'))),'exact accepted A3/A4 identity')
    c=loads(refresh); p=loads(projection); d=loads(text); actor=c['actor']; context=c['context']
    data,world,access=baseline(original,engine.SCHEMA); view=access.view(actor)
    require(digest(view.bytes())==entry['view_sha256'],'exact input view')
    # Independently enumerate every observed target and its prior directly owned paths.
    refs=set()
    for observation in p['observations']: refs.add(observation['target'])
    require(len(refs)<=128,'target bound'); plan=[]
    for ref in sorted(refs,key=dumps):
        revisions={x.source.revision for x in view.snapshot.particulars
                   if x.source.identity==ref.identity and x.source.revision<=ref.revision}
        if not revisions: continue
        known=[x for x in view.snapshot.particulars if x.source.identity==ref.identity and x.source.revision==max(revisions)]
        by_key={}
        for x in known: by_key.setdefault(x.address.key,set()).add((x.category,x.path))
        require(all(len(v)==1 for v in by_key.values()),'unambiguous owned descriptor')
        selectors=[]; evidence=set()
        for key,values in by_key.items():
            category,path=next(iter(values))
            if any(x.source==ref and x.address.key==key and x.category==category and x.path==path for x in view.snapshot.particulars): continue
            selectors.append((key,category,path))
            evidence.update((x.source,x.address.delivery,x.address.key) for x in known
                            if x.address.key==key and x.category==category and x.path==path)
        require(len(selectors)<=128,'selector bound')
        if selectors: plan.append(dict(target=ref,selectors=tuple(sorted(selectors,key=dumps)),evidence=tuple(sorted(evidence,key=dumps))))
    plan=tuple(plan)
    require(d['plan']==plan and d['source_native_sha256']==digest(original),'exact observed target/path plan')
    require(all(d[k] is False for k in ('main_execution_authorized','comparison_paid','td5_admitted','history_choice','skill_acquired')),'no authority')
    current=unseal(engine.checkpoint(),engine.SCHEMA)
    require(current['initial']==data['initial'] and current['law']==data['law'],'unchanged setup')
    prior=tuple(world.journal()); txs=tuple(engine.world.journal())
    require(txs[:len(prior)]==prior,'native journal prefix')
    pool=ValuePool(engine._registry()); pool.load_nodes(data['nodes'])
    old_commands=tuple(pool.get(pool.import_token(t)) for t in data['commands'])
    commands=tuple(engine._pool.get(t) for t in engine._events)
    require(commands[:len(old_commands)]==old_commands,'command prefix')
    old_access=tuple(access.pool.get(t) for t in access._events)
    require(tuple(engine.access.pool.get(t) for t in engine.access._events)[:len(old_access)]==old_access,'access prefix')
    final=engine.participant_view(actor)
    require(final.snapshot.bindings==view.snapshot.bindings and final.snapshot.acquired==view.snapshot.acquired,'binding/acquired unchanged')
    require(final.snapshot.history[:len(view.snapshot.history)]==view.snapshot.history,'access history prefix')
    h0={x.ref.identity:x for tx in prior for x in tx.versions}
    h1={x.ref.identity:x for tx in txs for x in tx.versions}
    # Only native payment/operation machinery may change; no physical or controller source edit.
    suffix=[x for tx in txs[len(prior):] for x in tx.versions]
    require(all(x.ref.identity.namespace.startswith('u4.') for x in suffix),'no source/profile/material edit')
    require(all(h1[i]==x for i,x in h0.items() if not i.namespace.startswith('u4.')),'all original non-U4 heads exact')
    old_jobs={(attrs(x).get('actor'),attrs(x).get('key')):attrs(x) for x in h0.values() if attrs(x).get('record_type')=='operation'}
    def extent(op):
        if op.get('ftwc') or op.get('ftpc'):
            known=old_jobs.get((op['actor'],op['key']))
            require(known is not None and all(op[k]==known[k] for k in ('required','route_prepare','route_execute')),'old comparison extent')
        else: old_extent(op)
    native_audit(txs,extent_check=extent,extended_flags=('c1','c2','c3','c4','c6','c7w','c7ws','ftpc','ftwc'))
    expected_commands=[]; end=len(prior); item=0; phase='read' if plan else 'complete'; receipts=[]
    def heads(n): return {x.ref.identity:x for tx in txs[:n] for x in tx.versions}
    def wallet(h):
        values=[attrs(x) for x in h.values() if attrs(x).get('record_type')=='wallet' and attrs(x).get('actor')==actor]
        require(len(values)==1,'unique wallet'); return values[0]
    for number,event in enumerate(d['events']):
        require(set(event)=={'index','item','action','before','after','job','work_limit','status','wallet_before','wallet_after','debit'},'exact event fields')
        require(phase=='read' and item<len(plan),'no terminal work')
        base='ft-observed-fields-a5:'+digest(original)+':'+str(item); key=base+':read'; delivery=base+':delivery'
        cid=key+':step:'+str(number); before=heads(end)
        require(event['index']==number and event['item']==item and event['job']==key and event['before']==end
                and type(event['after']) is int and end<=event['after']<=len(txs),'event order')
        q=event['work_limit']; require(type(q) is int and q>0,'exact work bound')
        after=heads(event['after']); bw=wallet(before); aw=wallet(after)
        require(event['wallet_before']==bw and event['wallet_after']==aw
                and event['debit']=={u:bw[u]-aw[u] for u in ('energy','time')},'wallet debit')
        identity=address('u4.operation',actor,key).identity
        prev=attrs(before[identity]) if identity in before else {}; require(identity in after,'saved job')
        op=attrs(after[identity]); delta=op['completed']-prev.get('completed',0)
        require(op['actor']==actor and op['primitive']=='read' and op['context']==context and op['required']==2
                and op['spent']==op['completed'] and event['status']==op['status'],'native read extent')
        require(0<=delta<=q and event['debit']==dict(energy=delta,time=delta),'native payment')
        if event['action']=='cancel':
            require(prev and op['status']=='cancelled' and delta==0,'nonrefundable cancel')
            expected_commands.append(('cancel',cid+':cancel',actor,key)); phase='cancelled'
        else:
            require(event['action']=='step','action')
            if not prev:
                target=plan[item]['target']; selectors=tuple(Selector(*s) for s in plan[item]['selectors'])
                expected_commands.extend((('disclose',delivery,actor,target,selectors,target),
                    ('start',cid+':start',OperationRequest(key,actor,'read',context,delivery=delivery))))
            if prev.get('status') not in ('ready','succeeded','failed','cancelled'):
                expected_commands.append(('advance',cid+':work',actor,key,q))
            if op['status']=='succeeded':
                require(op['completed']==2,'complete paid read')
                expected_commands.append(('commit',cid+':commit',actor,key))
                receipts.append(dict(index=item,delivery=delivery,read_job=key)); item+=1
            else: require(op['status'] in ('partial','waiting'),'partial stage')
        end=event['after']
        if item==len(plan): phase='complete'
    require(end==len(txs),'no extra native suffix')
    require(tuple(x[0] for x in commands[len(old_commands):])==tuple(expected_commands),'exact allowed native commands')
    old_details=view.snapshot.particulars; details=final.snapshot.particulars
    require(details[:len(old_details)]==old_details,'particular prefix')
    added=details[len(old_details):]; expected_details=[]
    for receipt in receipts:
        row=plan[receipt['index']]; target=row['target']; delivery=receipt['delivery']; source=world.resolve(target)
        for key,category,path in row['selectors']:
            expected_details.append((delivery,key,category,target,target,path,read_path(source,path,actor),source.occurrence))
        reads=final.work_receipts('read',delivery)
        require(len(reads)==1 and reads[0].actor==actor and reads[0].inputs==(target,)
                and reads[0].required==reads[0].completed==reads[0].spent==2,'exact actor paid receipt')
    actual=[(x.address.delivery,x.address.key,x.category,x.source,x.subject,x.path,x.value,x.occurrence) for x in added]
    require(actual==expected_details,'exact completed source field paths; no early or invented fields')
    new_receipts=final.snapshot.receipts[len(view.snapshot.receipts):]
    require(final.snapshot.receipts[:len(view.snapshot.receipts)]==view.snapshot.receipts and len(new_receipts)==len(receipts),'only new completed read receipts')
    expected=dict(version='ft-observed-field-reads-a5-v1',actor=actor,context=context,setting=setting,
        source_native_sha256=digest(original),refresh_sha256=digest(refresh),projection_sha256=digest(projection),
        expected_native_sha256=digest(engine.checkpoint()),start_count=len(prior),plan=plan,index=item,phase=phase,
        events=d['events'],receipts=receipts,main_execution_authorized=False,comparison_paid=False,
        td5_admitted=False,history_choice=False,skill_acquired=False)
    require(dumps(d)==dumps(expected),'exact adapter state')
    return dict(passed=True,phase=phase,targets=len(plan),selectors=[len(x['selectors']) for x in plan],
        receipts=len(receipts),new_fields=len(added),energy=sum(x['debit']['energy'] for x in d['events']),
        time=sum(x['debit']['time'] for x in d['events']),prefixes_exact=True,physical_unchanged=True,
        acquired_preserved=True,no_authority=True)
