"""Independent reconstruction of cp fees, distinct from traversal/completion."""
from hashlib import sha256
from hle.model_a import position, BY_POSITION, position_of
from hle_unified.material import attrs
from hle_unified.records import Account
from hle_unified.operations import address
from hle_unified.particulars import DetailAddress
from hle_unified.selection_records import loads
from hle_unified.selection_audit import audit as canonical_audit
from hle_unified.workflow_selection_audit import audit as workflow_audit
from .fulfillment_audit import _snapshot
from .route_means_audit import audit_route_means


def audit_orientation(transactions,access_text,checkpoint,native_text):
    data=loads(checkpoint);txs=tuple(transactions)
    if set(data)!={'version','native_sha256','attempts','events'} or data['version']!='ft-cp-orientation-v1' or data['native_sha256']!=sha256(native_text.encode()).hexdigest():
        raise ValueError('paired orientation source mismatch')
    settings={a['setting'] for a in data['attempts']}
    if 'canonical' in settings:canonical_audit(txs,access_text)
    if 'workflow' in settings:workflow_audit(txs,access_text)
    attempts={(a['actor'],a['key']):a for a in data['attempts']}
    if len(attempts)!=len(data['attempts']):raise ValueError('duplicate orientation identity')
    all_versions={v.ref:v for tx in txs for v in tx.versions}
    for a in attempts.values():
        r=a['request'];snap=_snapshot(a['admission_view'])
        inventory=a['inventory'];audit_route_means(txs[:inventory['at_tick']],inventory)
        if inventory['request']!=r or inventory['view']!=a['admission_view'] or inventory['active_seat']!=a['origin_seat'] or inventory['tim']!=a['tim'] or not inventory['options'][2]['eligible']:
            raise ValueError('fee admission differs from native owned means inventory')
        binding=next((b for b in snap.bindings if b.ref==r['demand']),None)
        if binding is None or binding.actor!=r['actor'] or binding.context!=r['context'] or binding.cue!=r['cue'] or binding.target.identity!=r['target'].identity or binding.endorsement.value in ('retracted','disputed'):
            raise ValueError('orientation source is not current owned scope')
        receipt=next((x for x in snap.receipts if x.ref==binding.receipt),None)
        if receipt is None or not receipt.complete or receipt.actor!=r['actor']:raise ValueError('unpaid task evidence')
        source=all_versions.get(r['demand']);account=None if source is None else source.facet(Account)
        if account is None or account.holder!=r['actor'] or account.content!=binding.content or a['payload']!=binding.content[0].object:
            raise ValueError('orientation source differs from owned task')
        expected_path=('facets',str(source.facets.index(account)),'content','0','object')
        if a['path']!=expected_path or a['job']!=r['key']+':cp-orientation' or a['delivery']!='ft-cp-delivery:'+r['key']:
            raise ValueError('wrong exact source selector or fee identity')
        p=position(a['origin_seat']);target=BY_POSITION[(p[0],p[1],1-p[2])]
        if a['target_seat']!=target:raise ValueError('cp must preserve accepting/value and flip ring')
    paid={};end=0;tickets=0
    for i,e in enumerate(data['events']):
        if e['index']!=i or not end<=e['before']<=e['after']<=len(txs):raise ValueError('invalid read event order')
        end=e['after'];a=attempts.get((e['actor'],e['key']))
        if a is None or e['job']!=a['job']:raise ValueError('unrelated read job')
        def heads(n):return {v.ref.identity:v for tx in txs[:n] for v in tx.versions}
        b,h=heads(e['before']),heads(e['after']);actor=e['actor']
        def wallet(heads):
            rows=[attrs(v) for v in heads.values() if attrs(v).get('record_type')=='wallet' and attrs(v).get('actor')==actor]
            if len(rows)!=1:raise ValueError('missing exact wallet')
            return rows[0]
        bw,aw=wallet(b),wallet(h);deltas={u:bw[u]-aw[u] for u in ('energy','time')}
        ref=address('u4.operation',actor,a['job']).identity
        if ref not in h:raise ValueError('missing native read')
        d=attrs(h[ref]);old={} if ref not in b else attrs(b[ref])
        dt=d['completed']-old.get('completed',0)
        if e['wallet_before']!=bw or e['wallet_after']!=aw or e['debit']!=deltas or deltas!=dict(energy=dt,time=dt) or not 0<=dt<=e['work_limit']:
            raise ValueError('read fee differs from native payment')
        if (d['primitive']!='read' or d['required']!=2 or d['spent']!=d['completed']
            or d['input.0']!=a['request']['demand'] or d['delivery']!=a['delivery'] or d['context']!=a['request']['context'] or e['status']!=d['status']):
            raise ValueError('fee is not exact task read')
        snap=_snapshot(e['view']);binding=next((x for x in snap.bindings if x.ref==a['request']['demand']),None)
        latest=max((x.ref.revision for x in snap.bindings if x.ref.identity==a['request']['demand'].identity),default=-1)
        current=binding is not None and latest==binding.ref.revision and binding.endorsement.value not in ('retracted','disputed')
        particular=next((x for x in snap.particulars if x.address==DetailAddress(a['delivery'],'ft.cp.task')),None)
        # Reconstruct the actor's actual cursor after all committed paid work,
        # including unrelated intervening work, without importing progress().
        cursor=None;tim=None
        for tx in txs[:e['after']]:
            for version in tx.versions:
                row=attrs(version)
                if row.get('actor')!=actor:continue
                if 'initial_active' in row:
                    tim=row['tim']
                    if cursor is None:cursor=row['initial_active']
                if row.get('route_count') and row.get('completed',0)>0:
                    cursor=row['active_start'];left=max(0,row['completed']-row['recall_units']);stop=False
                    for n in range(row['route_count']):
                        prefix='route.'+str(n)+'.';hop=0
                        while prefix+'charges.'+str(hop) in row:
                            price=row[prefix+'charges.'+str(hop)]
                            if left<price:stop=True;break
                            left-=price;cursor=row[prefix+'path.'+str(hop+1)];hop+=1
                        if stop or left<row[prefix+'content_units']:break
                        left-=row[prefix+'content_units'];cursor=row[prefix+'element']
        current=current and tim==a['tim'] and cursor is not None and position_of(tim,cursor)==a['origin_seat']
        ready=d['status']=='succeeded' and d['completed']==2 and current
        if ready:
            if particular is None or particular.source!=a['request']['demand'] or particular.value!=a['payload'] or particular.path!=a['path']:
                raise ValueError('paid orientation lacks exact processed payload')
            expected=dict(job=a['job'],operation=h[ref].ref,actor=actor,demand=a['request']['demand'],delivery=a['delivery'],
                energy=2,time=2,origin_seat=a['origin_seat'],target_seat=a['target_seat'],traversal_claim=False,completion_claim=False)
            if e['ticket']!=expected:raise ValueError('ticket differs from paid read')
            tickets+=1
        elif e['ticket'] is not None:raise ValueError('partial/withdrawn/failed read grants no ticket')
        paid[(actor,a['key'])]=d['completed']
    if set(paid)!=set(attempts):raise ValueError('missing attempt events')
    return dict(passed=True,turns=len(data['events']),attempts=len(attempts),paid_time=sum(paid.values()),
                paid_energy=sum(paid.values()),ticket_observations=tickets,traversal_claim=False)
