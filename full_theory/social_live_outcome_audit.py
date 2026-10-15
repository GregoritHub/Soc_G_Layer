"""Independent suffix outcome audit; no runtime, executor or selector imports."""
from hashlib import sha256
from hle_unified import codec
from hle_unified.selection_records import dumps, loads
from hle_unified.material import attrs
from hle_unified.conditioning_audit import ELEMENTS, completed_use
from .social_feedback_binding_audit import audit_social_feedback_binding
from .social_reuse_audit import audit_social_reuse
from .reserve_audit import audit_reserve
from .use_history_audit import audit_use_history


def audit_social_live_outcome(engine, original, source, binding, checkpoint):
    d,r,b = loads(checkpoint),loads(source),loads(binding)
    fields = {'version','native_sha256','cycle','actor','source_sha256','binding_sha256',
        'start','prefix_sha256','history_prefix','reserve_prefix','history','reserve',
        'pending_start','windows','events','completion','status'}
    def require(ok,why):
        if not ok:raise ValueError('live outcome audit: '+why)
    digest = lambda text: sha256(text.encode()).hexdigest()
    require(set(d)==fields and d['version']=='ft-post-social-live-outcome-v1','schema')
    audit_social_feedback_binding(original,source,binding)
    txs,old = tuple(engine.world.journal()),tuple(original.world.journal())
    require(d['native_sha256']==digest(engine.checkpoint()) and d['actor']==r['actor']
        and d['source_sha256']==digest(source) and d['binding_sha256']==digest(binding), 'pairing')
    require(d['start']==len(old) and txs[:len(old)]==old
        and d['prefix_sha256']==digest(codec.dumps(old)), 'immutable native prefix')
    require(d['history_prefix']==b['history'] and d['reserve_prefix']==b['reserve'], 'immutable ledgers')
    admission=b['reserve_bindings'][-1]
    require(r['phase'] in ('route','consumer','deferred') and admission['completion'] is None,
        'uncompleted original admission')
    require(r['phase']=='deferred' or admission['admission']['preparation']==0, 'preparation debt')
    audit_social_reuse(engine,d['cycle'])
    current=loads(d['cycle'])
    mutable={'native_sha256','route_policy','demand_controller','phase','consumer_key','events','terminal'}
    require(all(current[k]==r[k] for k in r if k not in mutable), 'source immutable fields')
    require(current['events'][:len(r['events'])]==r['events'], 'old cycle events')
    extra=current['events'][len(r['events']):]
    require(len(extra)==len(d['events']), 'one event per actual step')
    def wallet(at):
        rows=[attrs(v) for t in txs[:at] for v in t.versions
              if attrs(v).get('record_type')=='wallet' and attrs(v).get('actor')==d['actor']]
        require(bool(rows),'wallet absent')
        return {k:rows[-1][k] for k in ('energy','time')}
    at=len(old);phase=r['phase']
    for i,(event,actual) in enumerate(zip(d['events'],extra)):
        require(set(event)=={'index','before','after','phase_before','phase','work_limit',
            'wallet_before','wallet_after','debit','status'},'step schema')
        end=event['after']
        require(event['index']==i and event['before']==at and at<=end<=len(txs)
            and event['phase_before']==phase and event['phase']==actual['phase']
            and type(event['work_limit']) is int and event['work_limit']>0, 'step order')
        if actual['kind']=='route':
            require((actual['route']['before'],actual['route']['after'],actual['route']['work_limit'])
                ==(at,end,event['work_limit']),'actual native route window')
        elif actual['consumer'] is not None:
            require(actual['consumer']['before']['energy']-actual['consumer']['after']['energy']
                ==wallet(at)['energy']-wallet(end)['energy'],'actual consumer debit')
        require(event['wallet_before']==wallet(at) and event['wallet_after']==wallet(end)
            and event['debit']=={k:wallet(at)[k]-wallet(end)[k] for k in ('energy','time')}
            and all(v>=0 for v in event['debit'].values()),'native wallet debit')
        expected='complete' if actual['phase']=='complete' else 'failed' if actual['kind']=='terminal' else 'pending'
        require(event['status']==expected and (i==len(extra)-1 or expected=='pending'),'outcome order')
        at=end;phase=actual['phase']
    require(at==len(txs),'unaccounted suffix')
    status='deferred' if r['phase']=='deferred' else ('complete' if phase=='complete' else
        'failed' if current['terminal'] is not None else 'pending')
    require(d['status']==status,'outcome status')
    old_r,new_r=loads(b['reserve']),loads(d['reserve'])
    old_h,new_h=loads(b['history']),loads(d['history'])
    audit_reserve(d['reserve'])
    if status in ('pending','deferred'):
        require(d['history']==b['history'] and d['reserve']==b['reserve'] and not d['windows']
            and d['completion'] is None and d['pending_start']==len(old),'premature credit')
        audit_use_history(d['history'],txs[:len(old)])
    else:
        require(d['pending_start']==len(txs),'terminal pending boundary')
        audit_use_history(d['history'],txs)
        require(new_h['base']==old_h['base'] and new_h['events'][:len(old_h['events'])]==old_h['events']
            and new_h['event_count']==len(new_h['events']), 'old history rewritten or evicted')
        require(new_r['events'][:len(old_r['events'])]==old_r['events'],'old reserve events')
        if status=='complete':
            q=r['request']['fields'];key=q['key']
            changes=new_r['events'][len(old_r['events']):]
            require(len(changes)==1 and d['completion']==changes[0], 'one completion')
            ev=changes[0]
            require(ev['kind']=='completion' and ev['demand_id']==key and ev['completion_kind']=='independent'
                and ev['load']==r['required']['load'] and ev['delta']==-min(old_r['balance'],max(1,ev['load'])),
                'actual admitted completion')
            op=attrs(engine.world.resolve(engine._jobs[d['actor'],current['consumer_key']]))
            require(op['status']=='succeeded' and op['required']>0 and op['spent']>=op['required']
                and op['completed']==op['required'],'paid downstream completion')
        else:
            require(d['reserve']==b['reserve'] and d['completion'] is None,'failed completion credit')
        expected=[];left=len(old);base=completed_use(txs[:left])[1][d['actor']]
        for end in range(left+1,len(txs)+1):
            counts=completed_use(txs[:end])[1][d['actor']]
            if max(counts[e]-base[e] for e in ELEMENTS)>9:
                require(end-1>left,'atomic outcome exceeds bound')
                expected.append((left,end-1));left=end-1
                base=completed_use(txs[:left])[1][d['actor']]
                require(max(counts[e]-base[e] for e in ELEMENTS)<=9,'atomic outcome exceeds bound')
        if left<len(txs):expected.append((left,len(txs)))
        events=new_h['events'][len(old_h['events']):]
        require(len(expected)==len(d['windows'])==len(events),'exact suffix windows')
        tag='independent' if status=='complete' else 'failed'
        for (start,end),window,event in zip(expected,d['windows'],events):
            require(window==dict(start=start,end=end,tag=tag,event=event)
                and (event['journal_before']['count'],event['journal_after']['count'])==(start,end),'window identity')
            before=completed_use(txs[:start])[1][d['actor']];after=completed_use(txs[:end])[1][d['actor']]
            outcome=dict(status='succeeded' if status=='complete' else 'failed',supported=False,rehearsal=False,
                demand_id=r['request']['fields']['key'],route_id=r['request']['fields']['key'])
            rows=tuple(dict(identity=f"{event['turn']}:{e}:{i}",element=e,tag=tag,outcome=outcome)
                for e in ELEMENTS for i in range(after[e]-before[e]))
            require(event['classifications']==rows,'suffix exact paid-use credit')
    return dict(passed=True,status=status,source_prefix_exact=True,old_history_unchanged=True,
        new_history_windows=len(d['windows']),reserve_before=old_r['balance'],reserve_after=new_r['balance'],
        native_debit={k:sum(e['debit'][k] for e in d['events']) for k in ('energy','time')},
        pending=status=='pending',choice_causality=False)
