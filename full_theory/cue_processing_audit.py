"""Independent owned fact domain, command/payment/effect/prefix reconstruction."""
from hashlib import sha256
from pathlib import Path
import json
from hle_unified.records import ObjectRef
from hle_unified.particulars import DetailAddress
from hle_unified.shell_records import EncounterRequest
from hle_unified.selection_records import loads,dumps
from hle_unified.material import attrs
from hle_unified.operations import address
from hle_unified.cognitive_routes import progress
from hle_unified.development_audit import audit as audit_native
from hle_unified.workflow_selection_audit import extent as prior_extent
FIELDS=('trigger','available','safe','requires_partner','willing','approval_required','approved','feedback','recommended')
def digest(t):return sha256(t.encode()).hexdigest()
def domain(view,actor,context):
    groups={}
    for p in view.snapshot.particulars:groups.setdefault(p.source,{})[p.address.key]=p.value
    rows=[(ref,d) for ref,d in groups.items() if d.get('schema')=='u7.encounter-facts-v1' and d.get('receiver')==actor and d.get('context')==context and type(d.get('target')) is ObjectRef]
    targets=sorted({d['target'] for _,d in rows},key=dumps)
    if len(targets)>16:raise ValueError('audit bounded owned domain')
    result=[]
    for target in targets:
        latest={}
        for ref,data in rows:
            if data['target']!=target:continue
            if ref.identity not in latest or latest[ref.identity][0].revision<ref.revision:latest[ref.identity]=(ref,data)
        sources=tuple(sorted(ref for ref,_ in latest.values()));known={}
        for k in FIELDS:
            values={data[k] for _,data in latest.values() if k in data}
            if len(values)==1:
                value=next(iter(values));typ=ObjectRef if k=='trigger' else str if k in ('feedback','recommended') else bool
                if type(value) is typ:known[k]=value
        evidence=tuple((p.address.delivery,p.address.key) for source in sources for p in view.snapshot.particulars if p.source==source)
        result.append(dict(target=target,known=known,sources=sources,evidence=evidence))
    return tuple(result)
def audit(engine,original,windows,text):
    def require(ok,why):
        if not ok:raise ValueError('cue processing audit: '+why)
    d=loads(text);w=loads(windows);entry=json.loads((Path(__file__).resolve().parents[1]/'contracts/ft/FT7_Cue_Processing_A12D_Protocol_v1.json').read_text())['inputs'].get(w['setting'])
    require(entry is not None and (digest(original.checkpoint()),digest(windows))==(entry['native_sha256'],entry['windows_sha256']),'exact accepted source')
    required={'version','actor','setting','context','cue','task','source_native_sha256','source_windows_sha256','expected_native_sha256','start_count','plan','index','phase','events','results','reserve','history','controller_prefix','comparison_paid','execution_authorized','td5_admitted','history_choice','independent_credit','clearance_claim','skill_acquired'}
    require(set(d)==required and d['version']=='ft-owned-cue-processing-a12d-v1','schema')
    actor=w['actor'];task=w['fresh_demand'];view=original.participant_view(actor);plan=domain(view,actor,task['context'])
    require((d['actor'],d['setting'],d['context'],d['cue'],d['task'])==(actor,w['setting'],task['context'],task['cue'],task['binding']),'scope')
    require(d['plan']==plan and d['source_native_sha256']==digest(original.checkpoint()) and d['source_windows_sha256']==digest(windows) and d['expected_native_sha256']==digest(engine.checkpoint()),'source/domain/native binding')
    require((d['reserve'],d['history'],d['controller_prefix'])==(w['reserve'],w['history'],w['controller_prefix']),'immutable reserve/history/controller')
    require(all(d[k] is False for k in ('comparison_paid','execution_authorized','td5_admitted','history_choice','independent_credit','clearance_claim','skill_acquired')),'no credit, mastery, clearance or execution authority')
    prior=tuple(original.world.journal());txs=tuple(engine.world.journal());require(d['start_count']==len(prior) and txs[:len(prior)]==prior,'exact original journal prefix')
    oldcommands=tuple(original._pool.get(t) for t in original._events);commands=tuple(engine._pool.get(t) for t in engine._events);require(commands[:len(oldcommands)]==oldcommands,'exact command prefix')
    require(engine._initial==original._initial and engine.law==original.law and engine.resource_model==original.resource_model and engine._profiles==original._profiles,'native configuration unchanged')
    allowed_extents={attrs(v)['required'] for tx in prior for v in tx.versions if attrs(v).get('record_type')=='operation' and attrs(v).get('ftwc')}
    def extent(op):
        if op.get('ftwc'):require(op['required'] in allowed_extents and op['route_prepare']==op['required'] and op['route_execute']==0,'unchanged immutable prior comparison extent')
        else:prior_extent(op)
    audit_native(txs,extent_check=extent,extended_flags=('c1','c2','c3','c4','c6','c7w','c7ws','ftpc','ftwc'))
    def heads(end):return {v.ref.identity:v for tx in txs[:end] for v in tx.versions}
    def wallet(h):
        values=[attrs(v) for v in h.values() if attrs(v).get('record_type')=='wallet' and attrs(v).get('actor')==actor];require(len(values)==1,'one wallet');return values[0]
    end=len(prior);index=0;phase='active' if plan else 'complete';results=[];expected=[];cursor=original._cursors[actor];spent=0
    for n,event in enumerate(d['events']):
        fields={'index','item','job','before','after','work_limit','commit_ready','cancel','status','wallet_before','wallet_after','debit','cursor_before','cursor_after'}
        require(set(event)==fields and phase=='active' and event['index']==n and event['item']==index and event['before']==end and type(event['after']) is int and end<event['after']<=len(txs),'contiguous active event')
        require(type(event['work_limit']) is int and event['work_limit']>0 and type(event['commit_ready']) is bool and type(event['cancel']) is bool,'exact quantum and flags')
        row=plan[index];key='ft-cue-processing:'+digest(original.checkpoint())+':'+str(index);cid=key+':step:'+str(n);require(event['job']==key,'deterministic job order')
        identity=address('u4.operation',actor,key).identity;before=heads(end);after=heads(event['after']);require(identity in after,'actual native job');op=attrs(after[identity]);previous=attrs(before[identity]) if identity in before else {}
        if not previous:
            require(not event['cancel'] and (actor,key) not in original._jobs,'fresh native work')
            request=EncounterRequest(key,actor,row['target'],task['context'],task['cue'],row['target'],ObjectRef(actor,1),tuple(DetailAddress(*a) for a in row['evidence']))
            expected.append(('start',cid+':start',request))
        require(op.get('u7') is True and (op['actor'],op['context'],op['cue'],op['target'],op['carrier'],op['bearer'],op['requested_route'],op['demand'])==(actor,task['context'],task['cue'],row['target'],row['target'],ObjectRef(actor,1),'engage',True),'exact paid native encounter request')
        bw=wallet(before);aw=wallet(after);delta=op['completed']-previous.get('completed',0)
        require(event['wallet_before']==bw and event['wallet_after']==aw and event['debit']=={u:bw[u]-aw[u] for u in ('energy','time')}==dict(energy=delta,time=delta) and 0<=delta<=event['work_limit'],'actual native debit')
        require(event['cursor_before']==cursor,'cursor prefix')
        if event['cancel']:
            require(previous and op['status']=='cancelled' and delta==0,'cancellation retains debit');expected.append(('cancel',cid+':cancel',actor,key));phase='cancelled'
        else:
            if previous.get('status')!='ready':expected.append(('advance',cid+':work',actor,key,event['work_limit']));cursor=progress(op)[0]
            if op['status'] in ('succeeded','failed'):
                require(event['commit_ready'] and op['completed']==op['spent']==op['required'],'complete paid settlement');expected.append(('commit',cid+':commit',actor,key))
                encounter=op.get('encounter');data=None if encounter is None else attrs(after[encounter.identity]);results.append(dict(index=index,job=key,status=op['status'],encounter=encounter,intent=None if data is None else data['route'],reason=None if data is None else data['reason'],failure=op.get('failure')))
                if op['status']=='failed':phase='failed'
                else:
                    index+=1
                    if index==len(plan):phase='complete'
            elif op['status']=='ready':require(not event['commit_ready'] and op['completed']==op['required'],'uncommitted ready gives no completed result')
            else:require(op['status'] in ('partial','waiting'),'registered partial status')
        require(event['status']==op['status'] and event['cursor_after']==cursor,'actual status/cursor progress')
        spent+=delta;end=event['after']
    require(end==len(txs) and tuple(x[0] for x in commands[len(oldcommands):])==tuple(expected),'no unrelated native suffix')
    require((d['index'],d['phase'],d['results'])==(index,phase,results),'exact actual results and terminal state')
    cursors=dict(original._cursors);cursors[actor]=cursor;require(engine._cursors==cursors,'actual final native cursor')
    oldaccess=tuple(original.access.pool.get(t) for t in original.access._events);access=tuple(engine.access.pool.get(t) for t in engine.access._events);require(access[:len(oldaccess)]==oldaccess,'original access prefix')
    replay=type(engine).restore(engine.checkpoint());require(tuple(replay.world.journal())==txs and replay.access.checkpoint()==engine.access.checkpoint() and replay._cursors==engine._cursors,'exact native/access/cursor replay')
    require(engine.participant_view(actor)._bindings[task['binding']]==view._bindings[task['binding']],'original owned task exact')
    return dict(passed=True,setting=w['setting'],phase=phase,targets=len(plan),completed=index,spent=spent,energy=spent,time=spent,source_prefix_exact=True,reserve_history_unchanged=True,clearance_claim=False,skill_acquired=False,comparison_paid=False,execution_authorized=False,history_choice=False,intents=[x['intent'] for x in results],cursor_before=original._cursors[actor],cursor_after=cursor)
