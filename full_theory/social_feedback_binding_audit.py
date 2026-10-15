"""Independent post-social receipt reconstruction; no controller imports."""
from hashlib import sha256
from hle_unified.selection_records import dumps, loads
from hle_unified.material import attrs
from hle_unified.development_values import attrs as development_attrs
from hle_unified.conditioning_audit import ELEMENTS, completed_use
from .reserve_audit import audit_reserve
from .use_history_audit import audit_use_history
from .social_reuse_audit import audit_social_reuse


def audit_social_feedback_binding(engine, source, checkpoint):
    d = loads(checkpoint); r = loads(source); txs = tuple(engine.world.journal())
    fields = {'version','actor','native_sha256','reuse_sha256','social_prefix_sha256',
        'reserve_prefix','history_prefix','reserve','history','windows','reserve_bindings'}
    if set(d) != fields or d['version'] != 'ft-post-social-reserve-history-binding-v1':
        raise ValueError('exact post-social binding contract required')
    if d['native_sha256'] != sha256(engine.checkpoint().encode()).hexdigest() or d['reuse_sha256'] != sha256(source.encode()).hexdigest() or d['actor'] != r['actor']:
        raise ValueError('native/source pairing differs')
    audit_social_reuse(engine, source)
    closure = loads(r['prefix_checkpoint']); t = loads(closure['training_checkpoint'])
    peer = loads(t['prefix_peer']); social = loads(peer['social'])
    old_reserve = loads(loads(loads(social['cycle'])['candidates'])['binding'])['reserve']
    if d['social_prefix_sha256'] != sha256(t['prefix_peer'].encode()).hexdigest() or d['reserve_prefix'] != old_reserve or d['history_prefix'] != social['history']:
        raise ValueError('immutable social ledgers replaced')
    prior_r = loads(old_reserve); prior_h = loads(social['history'])
    if (prior_r['actor'],prior_h['actor'],prior_r['policy'],prior_h['policy']) != (d['actor'],d['actor'],'load-v1','success-v1'):
        raise ValueError('owned policy prefix differs')
    audit_reserve(old_reserve); audit_use_history(social['history'],txs[:prior_h['journal_count']])
    now_r = loads(d['reserve']); now_h = loads(d['history'])
    audit_reserve(d['reserve']); audit_use_history(d['history'],txs)
    if now_r['events'][:len(prior_r['events'])] != prior_r['events'] or now_h['events'][:len(prior_h['events'])] != prior_h['events']:
        raise ValueError('old ledger events are not an exact prefix')
    for key in ('actor','policy','initial','capacity','tokens','consumed_tokens','seen_receipts','seen_attempts'):
        if now_r[key] != prior_r[key]:raise ValueError('reserve inherited fields changed')
    for key in ('actor','policy','elements','score_cap','decay_idle','recent_limit','tim','base'):
        if now_h[key] != prior_h[key]:raise ValueError('history inherited fields changed')
    versions = {v.ref:v for tx in txs for v in tx.versions}
    episodes = []; start = None
    for event in t['events']:
        if event['phase_before'] == 'respond' and start is None:start = event['before']
        if event['phase_before'] != 'practice' or event['work']['status'] != 'succeeded':continue
        op = event['work']['operation']; native = attrs(versions[op])
        practice = development_attrs(versions[native['development']])
        if not practice['independent'] or native['purpose'] != 'practice' or native['actor'] != d['actor'] or native.get('status') != 'succeeded' or native.get('required',0) <= 0 or native.get('completed') != native['required'] or native.get('spent',0) < native['required']:
            raise ValueError('independent episode lacks exact paid native practice')
        if not start <= native['started_tick'] < native['finished_tick'] < event['after']:
            raise ValueError('practice receipt escapes native outcome window')
        episodes.append((start,event['after'],op)); start = None
    if len(episodes) != 2 or t['phase'] != 'complete':raise ValueError('exact two training outcomes required')
    attempts = loads(r['route_policy'])['attempts']
    if len(attempts) != 1:raise ValueError('one later owned route inventory required')
    admission = attempts[0]['inventory']['at_tick']; later_id = r['request']['fields']['key']
    identity = 'ft-post-social:' + sha256(source.encode()).hexdigest()[:20]
    expected = [(prior_h['journal_count'],episodes[0][0],'preparation','rehearsal',identity+':preparation')]
    expected += [(a,b,'independent-practice','independent',identity+':practice:'+str(i)) for i,(a,b,op) in enumerate(episodes)]
    expected += [(episodes[-1][1],admission,'preparation','rehearsal',identity+':later-preparation'),
        (admission,len(txs),'later-use','independent' if r['phase']=='complete' else 'failed' if r['phase'] in ('deferred','failed','cancelled') else 'rehearsal',later_id)]
    semantic = expected; expected = []
    for begin,end,kind,tag,demand_id in semantic:
        if not 0 <= begin <= end <= len(txs):raise ValueError('semantic interval escapes journal')
        left = begin; baseline = completed_use(txs[:left])[1][d['actor']]
        for at in range(begin+1,end+1):
            counts = completed_use(txs[:at])[1][d['actor']]
            if max(counts[e]-baseline[e] for e in ELEMENTS) > 9:
                if at-1 <= left:raise ValueError('atomic native transaction exceeds observer bound')
                expected.append((left,at-1,kind,tag,demand_id));left=at-1
                baseline=completed_use(txs[:left])[1][d['actor']]
                if max(counts[e]-baseline[e] for e in ELEMENTS)>9:raise ValueError('atomic native transaction exceeds observer bound')
        if left<end:expected.append((left,end,kind,tag,demand_id))
    if now_h['event_count'] != len(now_h['events']):raise ValueError('immutable history prefix was evicted')
    if len(d['windows']) != len(expected) or now_h['event_count']-prior_h['event_count'] != len(expected):
        raise ValueError('accounting window domain differs')
    new_events = now_h['events'][len(prior_h['events']):]
    for row,spec,event in zip(d['windows'],expected,new_events):
        a,b,kind,tag,demand_id = spec
        if set(row) != {'kind','start','end','tag','demand_id','event'} or (row['start'],row['end'],row['kind'],row['tag'],row['demand_id'],row['event']) != (a,b,kind,tag,demand_id,event):
            raise ValueError('window receipt or outcome classification differs')
        if (event['journal_before']['count'],event['journal_after']['count']) != (a,b):raise ValueError('native window boundary differs')
        _,before = completed_use(txs[:a]); _,after = completed_use(txs[:b])
        expected_rows = []
        outcome = dict(status='failed' if tag=='failed' else 'succeeded',supported=False,rehearsal=tag=='rehearsal',demand_id=demand_id,route_id=demand_id)
        for element in ELEMENTS:
            for ordinal in range(after[d['actor']][element]-before[d['actor']][element]):
                expected_rows.append(dict(identity=f"{event['turn']}:{element}:{ordinal}",element=element,tag=tag,outcome=outcome))
        if event['classifications'] != tuple(expected_rows):raise ValueError('paid-use delta omitted, duplicated or misclassified')
    bindings = d['reserve_bindings']
    if len(bindings) != 3:raise ValueError('exact reserve outcome receipt domain required')
    events = now_r['events'][len(prior_r['events']):]; cursor=0
    expected_receipts = [(identity+':practice:'+str(i),a,b,op,t['scope']['load'],True) for i,(a,b,op) in enumerate(episodes)]
    completed = r['phase']=='complete'
    consumer = engine._jobs[d['actor'],r['consumer_key']] if completed else None
    expected_receipts.append((later_id,admission,len(txs),consumer,r['required']['load'],completed))
    for row,(demand_id,a,b,op,load,complete) in zip(bindings,expected_receipts):
        if set(row) != {'demand_id','start','end','operation','admission','completion'} or (row['demand_id'],row['start'],row['end'],row['operation']) != (demand_id,a,b,op):raise ValueError('reserve native receipt differs')
        admit = events[cursor]; cursor += 1
        if row['admission'] != admit or admit['kind'] != 'admission' or admit['demand_id'] != demand_id or admit['load'] != load:
            raise ValueError('reserve admission differs from unchanged demand')
        if complete:
            if admit['preparation'] != 0:raise ValueError('unpaid preparation debt hidden by completion')
            finished = events[cursor];cursor += 1
            native = attrs(versions[op])
            if native.get('status') != 'succeeded' or native.get('required',0)<=0 or native.get('completed') != native['required'] or native.get('spent',0)<native['required']:
                raise ValueError('reserve completion lacks paid native receipt')
            if row['completion'] != finished or finished['kind'] != 'completion' or finished['demand_id'] != demand_id or finished['completion_kind'] != 'independent':raise ValueError('reserve completion differs')
        elif row['completion'] is not None:raise ValueError('unfinished outcome supplied completion debit')
    if cursor != len(events):raise ValueError('extra reserve credit, interruption or debit')
    return dict(passed=True,independent=True,native_unchanged=True,source_prefix_exact=True,
        training_outcomes=2,later_completed=completed,reserve_before=prior_r['balance'],
        reserve_after=now_r['balance'],preparation_debt=bindings[-1]['admission']['preparation'],
        history_scores=now_h['scores'],windows=len(expected),choice_causality=False)
