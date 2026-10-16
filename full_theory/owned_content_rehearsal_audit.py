"""Independent A10 plan, command, payment and native-content reconstruction."""
import json
from functools import lru_cache
from hashlib import sha256
from pathlib import Path
from hle_unified import codec
from hle_unified.compact import unseal,ValuePool
from hle_unified.material import OperationStore,attrs
from hle_unified.operations import NativeAccess,address
from hle_unified.particulars import DetailAddress
from hle_unified.crossing_records import CrossingRequest
from hle_unified.workflow_records import WorkflowRequest
from hle_unified.selection_records import loads,dumps
from hle_unified.development_audit import audit as native_audit
from hle_unified.workflow_selection_audit import extent as old_extent

def digest(text):return sha256(text.encode()).hexdigest()
@lru_cache(maxsize=2)
def baseline(text,schema):
    d=unseal(text,schema);return d,OperationStore.restore(d['world']),NativeAccess.restore(d['access'])

def audit(engine,original,adapter,setting,text):
    def require(ok,why):
        if not ok:raise ValueError('rehearsal audit: '+why)
    p=json.loads((Path(__file__).resolve().parents[1]/'contracts/ft/FT7_Owned_Rehearsal_A10_Protocol_v1.json').read_text())
    e=p['inputs'].get(setting)
    require(e is not None and digest(original)==e['native_sha256'] and digest(adapter)==e['adapter_sha256'],'exact input pair')
    a=loads(adapter);d=loads(text);actor=a['actor'];context=a['context']
    source,world,access=baseline(original,engine.SCHEMA);view=access.view(actor);plan=[]
    # Separate enumeration and payload decoding, no builder/selector/executor imports.
    for b in view.snapshot.bindings:
        if view._heads[b.ref.identity].ref!=b.ref or b.actor!=actor or b.context!=context:continue
        if b.endorsement.value in ('retracted','disputed') or len(b.content)!=1:continue
        if b.content[0].relation!=('c3.data' if setting=='canonical' else 'c7w.data'):continue
        receipt=view.receipt(b.receipt)
        if receipt is None or receipt.actor!=actor or receipt.operation!='bind' or not receipt.complete or receipt.spent<receipt.required:continue
        details=tuple(p for p in view.snapshot.particulars if p.source==b.target)
        if not details:continue
        try:
            raw=codec.loads(b.content[0].object)
            if type(raw) is not tuple or len(dict(raw))!=len(raw):continue
            kind=dict(raw).get('kind')
        except (ValueError,TypeError):continue
        personal=('intention','personal_policy') if setting=='canonical' else ('intention','personal')
        system=('model','rule') if setting=='canonical' else ('system','rule')
        if kind not in personal+system:continue
        recipe=('use-' if setting=='canonical' else 'workflow-use-')+('personal' if kind in personal else 'system')+'-v1'
        plan.append(dict(source=b.ref,target=b.target,context=b.context,cue=b.cue,kind=kind,recipe=recipe,
                         evidence=tuple((x.address.delivery,x.address.key) for x in details)))
    plan=tuple(sorted(plan,key=lambda x:dumps(x['source'])));require(len(plan)<=32 and d['plan']==plan,'complete route-free plan')
    prior=tuple(world.journal());txs=tuple(engine.world.journal())
    require(txs[:len(prior)]==prior,'immutable world prefix')
    now=unseal(engine.checkpoint(),engine.SCHEMA)
    require(now['initial']==source['initial'] and now['law']==source['law'],'immutable setup')
    pool=ValuePool(engine._registry());pool.load_nodes(source['nodes'])
    commands0=tuple(pool.get(pool.import_token(t)) for t in source['commands'])
    commands=tuple(engine._pool.get(t) for t in engine._events)
    require(commands[:len(commands0)]==commands0,'command prefix')
    prior_access=tuple(access.pool.get(t) for t in access._events)
    require(tuple(engine.access.pool.get(t) for t in engine.access._events)[:len(prior_access)]==prior_access,'access prefix')
    final=engine.participant_view(actor)
    for field in ('bindings','particulars','receipts','history'):
        x=getattr(view.snapshot,field);require(getattr(final.snapshot,field)[:len(x)]==x,'immutable owned '+field)
    require(final.snapshot.acquired==view.snapshot.acquired,'no acquisition claim')
    h0={v.ref.identity:v for t in prior for v in t.versions};h1={v.ref.identity:v for t in txs for v in t.versions}
    require(all(h1[k]==v for k,v in h0.items() if not k.namespace.startswith('u4.')),'old non-U4 heads')
    old_jobs={(attrs(v).get('actor'),attrs(v).get('key')):attrs(v) for v in h0.values() if attrs(v).get('record_type')=='operation'}
    def extent(op):
        if op.get('ftwc') or op.get('ftpc'):
            old=old_jobs.get((op['actor'],op['key']))
            require(old is not None and all(op[k]==old[k] for k in ('required','route_prepare','route_execute')),'old payment extent')
        else:old_extent(op)
    native_audit(txs,extent_check=extent,extended_flags=('c1','c2','c3','c4','c6','c7w','c7ws','ftpc','ftwc'))
    def heads(n):return {v.ref.identity:v for t in txs[:n] for v in t.versions}
    def wallet(h):
        w=[attrs(v) for v in h.values() if attrs(v).get('record_type')=='wallet' and attrs(v).get('actor')==actor]
        require(len(w)==1,'unique wallet');return w[0]
    end=len(prior);index=0;phase='rehearse' if plan else 'complete';results=[];expected=[]
    for n,row in enumerate(d['events']):
        require(set(row)=={'index','item','action','before','after','job','work_limit','status','wallet_before','wallet_after','debit'},'event schema')
        require(phase=='rehearse' and index<len(plan),'no terminal work');item=plan[index]
        key='ft-rehearsal-a10:'+digest(original)+':'+str(index);cid=key+':step:'+str(n)
        require((row['index'],row['item'],row['before'],row['job'])==(n,index,end,key),'exact order')
        require(type(row['after']) is int and end<=row['after']<=len(txs),'bounded journal')
        q=row['work_limit'];require(type(q) is int and q>0,'work quantum')
        before=heads(end);after=heads(row['after']);bw=wallet(before);aw=wallet(after)
        ident=address('u4.operation',actor,key).identity
        prev=attrs(before[ident]) if ident in before else {};require(ident in after,'native operation')
        op=attrs(after[ident]);delta=op['completed']-prev.get('completed',0)
        require(row['wallet_before']==bw and row['wallet_after']==aw and row['debit']=={u:bw[u]-aw[u] for u in ('energy','time')},'wallet accounting')
        require(row['debit']==dict(energy=delta,time=delta) and 0<=delta<=q,'native paid units')
        require(op['actor']==actor and op['key']==key and op['context']==item['context'] and op['cue']==item['cue']
            and op['recipe_key']==item['recipe'] and op['source.0']==item['source']
            and op['content_target']==item['target'] and op['spent']==op['completed'] and op['status']==row['status'],'exact semantic request')
        if row['action']=='cancel':
            require(prev and op['status']=='cancelled' and delta==0,'nonrefund cancellation');expected.append(('cancel',cid+':cancel',actor,key));phase='cancelled'
        else:
            require(row['action']=='step','allowed action')
            if not prev:
                typ=CrossingRequest if setting=='canonical' else WorkflowRequest
                request=typ(key,actor,item['recipe'],item['context'],item['cue'],(item['source'],),tuple(DetailAddress(*x) for x in item['evidence']),item['target'])
                expected.append(('start',cid+':start',request))
            if prev.get('status') not in ('ready','succeeded','failed','cancelled'):expected.append(('advance',cid+':work',actor,key,q))
            if op['status'] in ('succeeded','failed'):
                require(op['completed']==op['required'],'fully paid terminal');expected.append(('commit',cid+':commit',actor,key))
                results.append(dict(item=index,job=key,status=op['status']));index+=1
            else:require(op['status'] in ('partial','waiting'),'partial no result')
            if index==len(plan):phase='complete'
        end=row['after']
    require(end==len(txs) and tuple(x[0] for x in commands[len(commands0):])==tuple(expected),'exact native suffix')
    expected_state=dict(version='ft-owned-content-rehearsal-a10-v1',actor=actor,context=context,setting=setting,
        source_native_sha256=digest(original),adapter_sha256=digest(adapter),expected_native_sha256=digest(engine.checkpoint()),
        start_count=len(prior),plan=plan,index=index,phase=phase,events=d['events'],results=results,
        main_execution_authorized=False,comparison_paid=False,td5_admitted=False,history_choice=False,skill_acquired=False,independent_credit=False)
    require(dumps(d)==dumps(expected_state),'exact adapter')
    return dict(passed=True,phase=phase,plan_count=len(plan),results=tuple(x['status'] for x in results),
        energy=sum(x['debit']['energy'] for x in d['events']),time=sum(x['debit']['time'] for x in d['events']),
        prefixes_exact=True,no_authority=True,cursor_native_only=True)
