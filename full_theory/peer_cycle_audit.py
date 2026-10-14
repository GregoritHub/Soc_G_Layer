"""Independent owned-offer/reply causality audit; no runtime policy imports."""
from hashlib import sha256
from hle_unified.selection_records import dumps,loads
from hle_unified.self_content import decode
from hle_unified.material import attrs
from hle_unified.records import Account
from .fulfillment_audit import _snapshot
from .content_audit import audit_content
from .packet_channel_audit import audit_packet_channel
from .social_cycle_audit import audit_social_cycle


def audit_peer_cycle(engine,checkpoint):
    d=loads(checkpoint);native=engine.checkpoint();txs=tuple(engine.world.journal())
    fields={'version','native_sha256','actor','peer','setting','phase','turn','required','offer','sender_view','peer_view','request','reply','channel','production','social','events','terminal'}
    if set(d)!=fields or d['version']!='ft-autonomous-peer-cycle-v1' or d['native_sha256']!=sha256(native.encode()).hexdigest():raise ValueError('peer/native pairing differs')
    if d['actor']==d['peer'] or d['setting'] not in ('canonical','workflow'):raise ValueError('peer domain differs')
    versions={v.ref:v for tx in txs for v in tx.versions};required=d['required']
    def paid(ref):
        if ref not in versions:raise ValueError('missing native receipt')
        r=attrs(versions[ref])
        if r.get('completed')!=r.get('required') or not r.get('required') or r.get('spent',0)<r['required'] or r.get('status','succeeded')!='succeeded':raise ValueError('unpaid native record')
        return r
    channel=loads(d['channel']);ch=audit_packet_channel(txs,d['channel'],native)
    if set(channel['participants'])!={d['actor'],d['peer']}:raise ValueError('channel owner differs')
    offer=d['offer'];request=d['request'];reply=d['reply']
    if offer is not None:
        snapshot=_snapshot(d['sender_view'])
        if snapshot.actor!=d['actor']:raise ValueError('foreign sender observation')
        choices=[];namespace='c3.message' if d['setting']=='canonical' else 'c7w.message'
        for p in snapshot.particulars:
            if p.address.key!='payload' or p.source.identity.namespace!=namespace:continue
            if p.source not in versions or p.value!=attrs(versions[p.source])['payload']:raise ValueError('source snapshot differs from raw content')
            body=decode(p.value)
            if (body.get('kind'),body.get('speaker'),body.get('receiver'),body.get('context'),body.get('target'))!=('offer',d['actor'],d['peer'],required['context'],required['target']):continue
            if d['peer'] not in required['support_allowed']:continue
            for ref,v in versions.items():
                r=attrs(v)
                if r.get('actor')==d['actor'] and r.get('status')=='succeeded' and p.source in tuple(x for k,x in r.items() if k.startswith('public.')):
                    paid(ref);choices.append(dict(output=p.source,operation=ref,key=r['key']))
        if not choices or offer!=min(choices,key=lambda row:dumps((row['output'],row['key'],row['operation'].revision))):raise ValueError('owned offer discovery differs')
        packet=channel['bridge']['packets'].get('peer-offer')
        if packet is None or (packet['output'],packet['operation_key'],packet['sender'],packet['receiver'])!=(offer['output'],offer['key'],d['actor'],d['peer']):raise ValueError('offer transport differs')
    elif channel['bridge']['packets']:raise ValueError('channel fabricates missing offer')
    if offer is None and d['sender_view'] is not None:
        snapshot=_snapshot(d['sender_view'])
        if snapshot.actor!=d['actor']:raise ValueError('foreign empty sender observation')
        for p in snapshot.particulars:
            if p.address.key!='payload' or p.source.identity.namespace not in ('c3.message','c7w.message'):continue
            body=decode(p.value)
            if (body.get('kind'),body.get('speaker'),body.get('receiver'),body.get('context'),body.get('target'))==('offer',d['actor'],d['peer'],required['context'],required['target']) and d['peer'] in required['support_allowed']:
                raise ValueError('owned offer omitted from discovery')
    if request is not None:
        receipt=channel['bridge']['receipts'].get('peer-offer')
        if receipt is None:raise ValueError('peer request lacks paid incoming uptake')
        s=_snapshot(d['peer_view'])
        if s.actor!=d['peer']:raise ValueError('foreign peer observation')
        found=[p for p in s.particulars if p.source==offer['output'] and p.address.key=='payload']
        if len(found)!=1 or found[0].value!=attrs(versions[offer['output']])['payload']:raise ValueError('peer lacks exact paid offer')
        body=decode(found[0].value);receipts={r.ref:r for r in s.receipts};latest={}
        for b in sorted(s.bindings,key=lambda b:b.ref.revision):latest[b.ref.identity]=b
        own=[]
        for b in latest.values():
            if b.actor!=d['peer'] or b.endorsement.value in ('retracted','disputed') or len(b.content)!=1:continue
            if (b.context,b.cue,b.target)!=(required['context'],required['cue'],required['target']):continue
            if b.content[0].relation!=('c3.data' if d['setting']=='canonical' else 'c7w.data'):continue
            r=receipts.get(b.receipt)
            if r is None or not r.complete or r.actor!=d['peer'] or r.spent<r.required:continue
            account=versions[b.ref].facet(Account);raw=paid(b.receipt)
            if account is None or account.holder!=d['peer'] or account.content!=b.content or raw.get('actor')!=d['peer'] or raw.get('input.0')!=b.ref:raise ValueError('peer stance ownership differs')
            if decode(b.content[0].object).get('kind')==('intention' if d['setting']=='canonical' else 'stance'):own.append(b.ref)
        if not own:raise ValueError('peer request lacks independent own stance')
        stance=min(own,key=dumps);evidence=tuple(p.address for p in s.particulars if p.source==required['target'])
        expected=dict(key='ft-peer-reply:'+sha256(dumps((d['peer'],offer['output'],stance)).encode()).hexdigest(),actor=d['peer'],recipe='reply-v1' if d['setting']=='canonical' else 'workflow-reply-v1',context=required['context'],cue=required['cue'],inputs=(offer['output'],stance),evidence=evidence,target=required['target'],stock=None,peer=d['actor'],group=body['group'],elements=())
        if d['setting']=='canonical':expected['demand']=4
        else:expected.update(relation=None,completed=(),clock=0)
        if request!=expected:raise ValueError('peer request differs from owned observation')
    elif d['production'] or reply is not None:raise ValueError('peer work has no owned request')
    if request is None and d['peer_view'] is not None:
        s=_snapshot(d['peer_view']);receipts={r.ref:r for r in s.receipts}
        if s.actor!=d['peer']:raise ValueError('foreign empty peer observation')
        for b in s.bindings:
            r=receipts.get(b.receipt)
            if b.actor==d['peer'] and b.endorsement.value not in ('retracted','disputed') and len(b.content)==1 and (b.context,b.cue,b.target)==(required['context'],required['cue'],required['target']) and b.content[0].relation==('c3.data' if d['setting']=='canonical' else 'c7w.data') and r is not None and r.complete and r.actor==d['peer'] and r.spent>=r.required:
                if decode(b.content[0].object).get('kind')==('intention' if d['setting']=='canonical' else 'stance') and any(p.source==required['target'] for p in s.particulars):raise ValueError('owned stance omitted from request')
    audit_content(txs,d['production'])
    for event in d['production']:
        r=attrs(versions[event['operation']])
        if event['actor']!=d['peer'] or event['key']!=request['key'] or event['inputs']!=request['inputs'] or event['consumed']!=request['inputs']:raise ValueError('peer native work owner or operands differ')
        for field in ('actor','key','recipe','context','cue','peer','group'):
            if r.get('recipe_key' if field=='recipe' else field)!=request[field]:raise ValueError('peer native request identity differs: '+field)
        if tuple(v for k,v in sorted(r.items()) if k.startswith('source.'))!=request['inputs']:raise ValueError('actual peer native inputs differ')
    social_audit=None
    if reply is not None:
        if not d['production']:raise ValueError('reply lacks paid work')
        work=d['production'][-1];r=paid(work['operation'])
        if work['status']!='succeeded' or r.get('public.0')!=reply or r.get('steps_completed')!=r.get('route_count'):raise ValueError('unpaid or fabricated public reply')
        body=decode(attrs(versions[reply])['payload'])
        if (body['kind'],body['speaker'],body['receiver'],body['offer'],body['group'],body['context'],body['target'])!=('reply',d['peer'],d['actor'],offer['output'],request['group'],required['context'],required['target']):raise ValueError('reply content authority differs')
        if d['social'] is None:raise ValueError('produced reply lacks recipient continuation')
        social=loads(d['social']);sc=loads(social['channel'])
        if sc['bridge']['packets'][social['packet_key']]['output']!=reply:raise ValueError('recipient consumes a different reply')
        social_audit=audit_social_cycle(engine,d['social'])
    elif d['social'] is not None:raise ValueError('recipient cycle began before paid reply')
    if d['turn']!=len(d['events']) or d['terminal'] is not None and d['terminal']!=d['events'][-1]:raise ValueError('peer turn/terminal differs')
    phase='offer';channel_steps=[];works=[];social_events=[]
    for i,e in enumerate(d['events']):
        if e['index']!=i or e['turn']!=i+1 or not 0<=e['before']<=e['after']<=len(txs) or i and e['before']!=d['events'][i-1]['after']:raise ValueError('peer event chronology differs')
        available=e['available']
        if len(set(available))!=len(available) or any(a not in channel['participants'] for a in available):raise ValueError('peer event availability differs')
        if phase=='offer':
            reason='sender_unavailable' if d['actor'] not in available else 'no_owned_scoped_offer' if offer is None else 'offer_queued'
            phase='offer' if reason=='sender_unavailable' else 'deferred' if offer is None else 'uptake'
            if e['intake'] or e['peer_work'] or e['social_event']:raise ValueError('offer scan starts extra work')
        elif phase=='uptake':
            if e['intake'] is None or e['peer_work'] or e['social_event']:raise ValueError('offer uptake order differs')
            channel_steps.append(e['intake']);delivered=any(r['status']=='delivered' for r in e['intake']['results'])
            phase='peer' if delivered else 'uptake';reason='offer_received' if delivered else 'pending_paid_offer_uptake'
        elif phase=='peer':
            if e['intake'] or e['social_event']:raise ValueError('peer phase starts extra work')
            if d['peer'] not in available:
                if e['peer_work']:raise ValueError('absent peer was charged')
                reason='peer_unavailable'
            elif e['peer_work'] is None:phase='deferred';reason='no_owned_peer_stance_or_evidence'
            else:
                works.append(e['peer_work']);status=e['peer_work']['status'];reason='paid_peer_partial'
                if status in ('failed','cancelled'):phase='failed';reason='paid_peer_failed'
                elif status=='succeeded':phase='recipient';reason='paid_peer_reply_queued'
        elif phase=='recipient':
            if e['social_event'] is None or e['intake'] or e['peer_work']:raise ValueError('recipient order differs')
            social_events.append(e['social_event']);reason=e['social_event']['reason']
            if e['social_event']['phase'] in ('complete','deferred','failed','cancelled'):phase=e['social_event']['phase']
        else:raise ValueError('work after terminal')
        if e['phase']!=phase or e['reason']!=reason:raise ValueError('peer phase or reason differs')
    if phase!=d['phase'] or channel_steps!=[e for e in channel['events'] if e['kind']=='step'] or works!=d['production'] or social_events!=(loads(d['social'])['events'] if d['social'] is not None else []):raise ValueError('peer delegated event domain differs')
    return dict(passed=True,independent=True,phase=phase,paid_offer_uptakes=ch['paid_uptakes'],peer_work_events=len(works),paid_reply=reply is not None,recipient=social_audit,independent_capability=False,scope='autonomous incoming-offer reply production and supported later use only; FT7.1b2b independent retention/feedback pending')
