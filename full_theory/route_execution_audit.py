"""Raw native turn reconstruction; no selector, scheduler or executor imports."""
from hashlib import sha256
from hle_unified.material import attrs
from hle_unified.operations import address
from hle_unified.selection_records import loads
from hle_unified.selection_audit import audit as canonical_audit
from hle_unified.workflow_selection_audit import audit as workflow_audit
from hle_unified.energy_audit import resource_model, debit as energy_debit


def audit_native_turns(transactions, access_text, checkpoint, native_text):
    data=loads(checkpoint);txs=tuple(transactions)
    if (set(data)!={'version','native_sha256','attempts','events'} or data['version']!='ft-native-turn-v1'
            or data['native_sha256']!=sha256(native_text.encode()).hexdigest()):
        raise ValueError('paired checkpoint mismatch')
    settings={a['setting'] for a in data['attempts']}
    # These inherited independent auditors rebuild all native candidate choices,
    # access receipts, operations and raw debits, not just the turn summaries.
    if 'canonical' in settings: canonical_audit(txs,access_text)
    if 'workflow' in settings: workflow_audit(txs,access_text)
    model=resource_model(txs);previous_end=0;seen={};total=dict(energy=0,time=0)
    for i,event in enumerate(data['events']):
        if (event['index']!=i or type(event['before']) is not int or type(event['after']) is not int
                or not previous_end<=event['before']<=event['after']<=len(txs)
                or event['completion_claim'] is not False):
            raise ValueError('invalid event boundary/order or completion claim')
        previous_end=event['after'];actor=event['actor'];r=event['request'];key=r['key']
        if r['actor']!=actor or event['setting'] not in ('canonical','workflow'):
            raise ValueError('turn request identity differs')
        def heads(n):return {v.ref.identity:v for tx in txs[:n] for v in tx.versions}
        before=heads(event['before']);after=heads(event['after'])
        def wallet(h):
            found=[attrs(v) for v in h.values() if attrs(v).get('record_type')=='wallet' and attrs(v).get('actor')==actor]
            if len(found)!=1:raise ValueError('exact actor wallet required')
            return found[0]
        b,a=wallet(before),wallet(after)
        expected={unit:b[unit]-a[unit] for unit in ('energy','time')}
        if event['wallet_before']!=b or event['wallet_after']!=a or event['debit']!=expected or min(expected.values())<0:
            raise ValueError('turn debit differs from raw wallet')
        paid=dict(energy=0,time=0);advanced=set();h=dict(before)
        for tx in txs[event['before']:event['after']]:
            for v in tx.versions:
                d=attrs(v);old={} if v.ref.identity not in h else attrs(h[v.ref.identity])
                if d.get('record_type')=='operation' and d.get('completed',0)>old.get('completed',0):
                    if d['actor']!=actor or d['key'] not in (key,key+':admission',key+':movement'):
                        raise ValueError('turn advanced foreign or unrelated work')
                    advanced.add(d['key']);dt=d['completed']-old.get('completed',0)
                    paid['time']+=dt;paid['energy']+=dt if model=='legacy-r4' else energy_debit(d,old)
                h[v.ref.identity]=v
        if paid!=expected or len(advanced)>1 or paid['time']>event['work_limit']:
            raise ValueError('payment or one-job work bound violated')
        if event['job'] is not None and event['job'] not in (key,key+':admission',key+':movement'):
            raise ValueError('claimed child is unrelated')
        if advanced and advanced!={event['job']}:
            raise ValueError('claimed child differs from paid child')
        parent_ref=address('u4.operation',actor,key).identity
        parent=attrs(after[parent_ref]) if parent_ref in after else None
        if parent is not None:
            if parent.get('input.0')!=r['demand'] or parent.get('actor')!=actor:
                raise ValueError('comparison demand/actor mismatch')
            seen[(actor,key)]=(r,event['setting'])
        def job(k):
            ref=address('u4.operation',actor,k).identity
            return None if ref not in after else attrs(after[ref])
        child=job(key+':movement');admission=job(key+':admission')
        ns='c7ws.decision' if event['setting']=='workflow' else 'c6.decision'
        did=address(ns,actor,key).identity;decision=None if did not in after else attrs(after[did])
        if child is not None:
            if parent is None or parent['status']!='succeeded' or parent['completed']!=parent['required'] or not decision or decision['status']!='launched':
                raise ValueError('child precedes paid choice')
            if event['setting']=='workflow':
                if decision['child'].identity!=address('u4.operation',actor,key+':movement').identity:
                    raise ValueError('wrong workflow child')
            elif not admission or admission['status']!='succeeded' or admission['requested_route']!=decision['recipe'] or child['recipe_key']!=decision['recipe']:
                raise ValueError('wrong canonical admission or child')
        state=event['state']
        if state=='movement_complete' and (child is None or child['status']!='succeeded' or child['completed']!=child['required'] or child['steps_completed']!=child['route_count']):
            raise ValueError('unpaid or absent completed movement')
        if state=='deferred' and (decision is None or decision['status']!='deferred' or child is not None):
            raise ValueError('false deferral')
        if event['action']=='observe' and event['after']!=event['before']:
            raise ValueError('terminal observation changed native state')
        for unit in total:total[unit]+=expected[unit]
    attempts={(x['actor'],x['key']):(x['request'],x['setting']) for x in data['attempts']}
    if len(attempts)!=len(data['attempts']) or seen!=attempts:raise ValueError('attempt index mismatch')
    return dict(passed=True,turns=len(data['events']),attempts=len(attempts),debits=total,
                completion_claim=False,scope='native bridge only; full means priority pending')
