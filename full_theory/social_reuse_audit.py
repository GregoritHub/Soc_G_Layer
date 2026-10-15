"""Saved unsupported requalification and reuse reconstruction, without selectors."""
import json
from hashlib import sha256
from hle_unified.selection_records import dumps,loads
from hle_unified.compact import unseal
from hle_unified.material import OperationStore,attrs
from hle_unified.records import Account
from hle_unified.cognitive_records import reference
from hle_unified.operations import NativeAccess
from .retention import Demand, no_easier
from hle_unified.development_audit import audit as audit_development
from hle_unified.workflow_selection_audit import extent as inherited_extent
from .retention_audit import audit_retention
from .content_audit import audit_content
from .fulfillment_audit import audit_fulfillment,_snapshot
from .route_policy_audit import audit_route_policy
from .social_training_audit import _known


def audit_social_reuse(engine,checkpoint):
    d=loads(checkpoint);txs=tuple(engine.world.journal())
    expected={'version','native_sha256','actor','setting','prefix_checkpoint','prefix_native','prefix_count',
        'source_certificate_key','certificate_key','requalification_demand','plan','qualification_events',
        'qualification_work','qualification_index','qualified_native','qualified_access','ready_boundary',
        'prior_need_refs','retention','demand_controller','route_policy','required','request','phase',
        'consumer_key','events','terminal','organization'}
    def require(ok,reason):
        if not ok:raise ValueError('social reuse audit: '+reason)
    def journal(native):
        return tuple(OperationStore.restore(unseal(native,json.loads(native)['schema'])['world']).journal())
    require(set(d)==expected and d['version']=='ft-unsupported-social-reuse-v1'
        and d['native_sha256']==sha256(engine.checkpoint().encode()).hexdigest(),'schema/native pairing')
    prefix=journal(d['prefix_native']);old=loads(d['prefix_checkpoint'])
    require(len(prefix)==d['prefix_count'] and txs[:len(prefix)]==prefix
        and old['native_sha256']==sha256(d['prefix_native'].encode()).hexdigest()
        and old['phase']=='certified' and (old['actor'],old['setting'])==(d['actor'],d['setting']),'immutable accepted closure')
    require(d['source_certificate_key']==old['certificate_key'] and d['plan']==old['plan']
        and d['requalification_demand']==dict(old['demand'],support_allowed=()),'stricter no-support demand')
    versions={v.ref:v for tx in txs for v in tx.versions}
    def paid(ref):
        r=attrs(versions[ref]);require(r.get('actor')==d['actor'] and r.get('status')=='succeeded'
            and r.get('required',0)>0 and r.get('spent',0)>=r['required'] and r.get('completed')==r['required'],'paid work')
        return r
    dem=d['requalification_demand'];plan=d['plan'];phase='qualify-use';offset=d['prefix_count'];index=0;works=[];exposures=[];certs=[]
    certificate_key=None;ready=None;prior=None
    for i,event in enumerate(d['qualification_events']):
        require(event['index']==i and event['phase_before']==phase and event['before']==offset
            and offset<=event['after']<=len(txs),'qualification event order')
        s=_snapshot(event['view']);require(s.actor==d['actor'],'foreign owned view')
        past={v.ref:v for tx in txs[:offset] for v in tx.versions}
        require(all(p.source in past for p in s.particulars),'future evidence')
        key='ft-no-support:'+sha256(dumps((d['actor'],d['prefix_count'])).encode()).hexdigest()[:16]+':'+str(index)+':'
        work=event['work'];request=event['request']
        if phase in ('qualify-use','qualify-shell'):
            require(work is not None and request is not None,'missing paid qualification')
            q=request['fields'];r=attrs(versions[work['operation']]);works.append(work)
            kind=phase.split('-')[1]
            require((q['key'],q['actor'],q['context'],q['cue'],q['target'])==(key+kind,d['actor'],dem['context'],dem['cue'],dem['target'])
                and (r['key'],r['actor'],r['context'])==(q['key'],q['actor'],q['context'])
                and work['status']==r['status'],'actual qualification identity')
            if kind=='use':
                recipe=('use-' if d['setting']=='canonical' else 'workflow-use-')+('personal' if plan['destination']=='I' else 'system')+'-v1'
                require(q['recipe']==r['recipe_key']==recipe and q['inputs']==work['consumed']==(plan['source'],)
                    and r['source.0']==plan['source'],'exact qualified source')
            else:
                known,sources=_known(s,past,dem['target'],dem['context'])
                evidence=tuple((p.address.delivery,p.address.key) for source in sources for p in s.particulars if p.source==source)
                require(request['type']=='EncounterRequest' and q['evidence']==evidence and q['demand'] is True
                    and q['route']=='engage' and q['carrier']==(known.get('partner') or dem['target'])
                    and r['purpose']=='encounter','full current Shell qualification')
            if work['status']=='succeeded':paid(work['operation']);phase='qualify-shell' if kind=='use' else 'qualify-expose'
            elif work['status'] in ('failed','cancelled'):phase='qualification-failed'
        elif phase=='qualify-expose':
            row=event['exposure'];require(work is None and request is None and offset==event['after'],'exposure fabricated work')
            require(row is not None and row['actor']==d['actor'] and row['demand']==dem and row['kept']==plan['kept']
                and row['returns']==plan['return_refs'] and row['interrupted'] is False and row['at_tick']==offset,'qualification exposure links')
            use=paid(row['consumer']);shell=paid(row['shell']['operation'])
            require(use['key']==key+'use' and shell['key']==key+'shell' and use['finished_tick']<=shell['started_tick'],'paid qualification chronology')
            exposures.append(row);index+=1;phase='qualify-use' if index<2 else 'qualify-certify' if row['closed'] else 'qualification-open'
        elif phase=='qualify-certify':
            require(work is None and request is None and offset==event['after'],'certificate fabricated work')
            original=old['ledger']['certificates'][old['certificate_key']]
            certificate_key='ft-no-support-certificate:'+sha256(dumps((d['actor'],dem,d['prefix_count'])).encode()).hexdigest()[:20]
            cert=event['certificate']
            require(cert is not None and cert==dict(original,key=certificate_key,scope=dict(dem,load=original['scope']['load']),closure=exposures[-1]),'exact independent stricter certificate')
            certs.append(cert);ready=offset
            prior=tuple(sorted({b.ref for b in s.bindings if len(b.content)==1 and b.content[0].relation in ('c6.need','c7ws.need')},key=dumps))
            phase='organize'
        else:require(False,'qualification after terminal')
        require(event['phase']==phase and event['episode_index']==index,'qualification phase')
        if event['phase_before']!='qualify-expose':require(event['exposure'] is None,'extra exposure')
        if event['phase_before']!='qualify-certify':require(event['certificate'] is None,'extra certificate')
        offset=event['after']
    require(d['qualification_index']==index and d['qualification_work']==works and d['certificate_key']==certificate_key
        and d['ready_boundary']==ready and d['prior_need_refs']==prior,'qualification final state')
    audit_development(txs,extent_check=inherited_extent,extended_flags=('c1','c2','c3','c4','c6','c7w','c7ws'))
    audit_content(txs,[w for w in works if attrs(versions[w['operation']]).get('c3') or attrs(versions[w['operation']]).get('c7w')])
    retained_events=d['retention']['events'];base=old['ledger']['events']+exposures+certs
    require(retained_events[:len(base)]==base,'retention prefix changed')
    extra=retained_events[len(base):]
    require(len(extra)<=1 and all(x['kind']=='certificate_revoked' and x['key']==certificate_key and x['reason'] for x in extra),'unregistered retention mutation')
    retention=audit_retention(txs,retained_events)
    require(d['retention']['history']==tuple(sorted(retention['history'],key=dumps)),'history changed')
    expected_certs=dict(old['ledger']['certificates']);expected_certs.update({c['key']:c for c in certs})
    require(d['retention']['certificates']==expected_certs and d['retention']['revoked']=={x['key']:x['reason'] for x in extra},'certificate/revocation map')
    windows=dict(old['ledger']['windows']);seen=set(old['ledger']['exposures'])
    for row in exposures:
        windows[d['actor'],dem['family'],dem['context'],dem['cue']]=dict(signature=(row['kept'],dem),hold=row['hold'],last=row)
        seen.add((row['consumer'],row['shell']['operation']))
    require(d['retention']['windows']==tuple(sorted(windows.items(),key=dumps)) and d['retention']['exposures']==tuple(sorted(seen,key=dumps)),'derived retention state')
    if ready is not None:
        require(journal(d['qualified_native'])==txs[:ready],'immutable qualification boundary')
    else:
        require(d['qualified_native'] is None and d['qualified_access'] is None and not d['events'] and d['phase']==phase,'premature reuse')
    organization=d['organization']
    if organization is not None:
        require(ready is not None,'organization before certification')
        snapshot=_snapshot(organization['view'])
        require(snapshot.actor==d['actor'],'organization actor')
        qualified_access=NativeAccess.restore(d['qualified_access'])
        require(qualified_access.view(d['actor']).bytes()==organization['view'],'exact complete qualified organization snapshot')
        heads={}
        for b in snapshot.bindings:
            if b.ref.identity not in heads or b.ref.revision>heads[b.ref.identity].ref.revision:
                heads[b.ref.identity]=b
        required_refs=tuple(sorted((b.ref for b in heads.values()
            if (b.cue,b.context)==(dem['cue'],dem['context']) and b.ref.identity.namespace=='workshop'
            and not any(p.relation=='u8.reorganize' and type(p.object) is int and p.object>0 for p in b.content)),key=dumps))
        require(organization['refs']==required_refs and organization['cue']==reference('suit:Wand'),'exact organization domain')
        qualified_versions={v.ref:v for tx in txs[:ready] for v in tx.versions}
        require(all(b.ref in qualified_versions and qualified_versions[b.ref].facet(Account).content==b.content
                    for b in snapshot.bindings),'organization uses qualified owned content')
        index=0;read_complete=False;org_cost=0
        for event in organization['events']:
            work=event['work'];record=attrs(versions[work['operation']])
            require(record['actor']==d['actor'] and record['context']==dem['context']
                    and record['started_tick']>=ready and work['status']==record['status'],'organization paid work identity')
            if event['kind']=='read':
                require(record['primitive']=='read' and record['input.0']==organization['cue'],'actual archive cue read')
                read_complete=work['status']=='succeeded'
            else:
                require(read_complete and index<len(required_refs) and event['original']==required_refs[index],'organization revision order')
                original=versions[event['original']];revised=versions[event['revised']]
                require(revised.ref.identity==original.ref.identity and revised.ref.revision==original.ref.revision+1
                    and revised.previous==original.ref and revised.facets==original.facets
                    and revised.writer==original.writer and revised.label==original.label and revised.roles==original.roles
                    and revised.occurrence==original.occurrence and revised.lifecycle==original.lifecycle
                    and attrs(revised)==dict(attrs(original),cue=organization['cue']),'cue-only revision preserves content/history')
                require(record['primitive']=='bind' and record['binding']==revised.ref
                    and tuple((record['evidence.delivery.'+str(i)],record['evidence.key.'+str(i)]) for i in range(len(heads[original.ref.identity].particulars)))==tuple((a.delivery,a.key) for a in heads[original.ref.identity].particulars),'exact organization bind')
                if work['status']=='succeeded':index+=1
            if work['status']=='succeeded':paid(work['operation'])
            org_cost+=work['before']['energy']-work['after']['energy']
        require(index==organization['index'] and organization['complete']==(read_complete and index==len(required_refs)),'organization completion')
        if organization['complete']:
            require(organization['events'] and org_cost>0,'organization cannot be free')
            require(d['phase']!='organize','completed organization phase')
    else:
        require(not d['events'] and d['phase'] in ('organize',phase),'later reuse before organization')
    fulfillment=audit_fulfillment(txs,engine.access.checkpoint(),d['demand_controller'])
    route=audit_route_policy(txs,engine.access.checkpoint(),d['route_policy'],engine.checkpoint())
    events=d['events'];attempts=loads(d['route_policy'])['attempts']
    require(all(row['index']==i for i,row in enumerate(events)) and len(attempts)<=1,'reuse event order')
    if d['request'] is not None:
        q=d['request']['fields'];require(events and events[0]['request']==q and q['demand'] not in prior,'post-certificate need')
        require(q['demand'] not in {v.ref for tx in txs[:ready] for v in tx.versions},'old need cannot be relabeled new')
        require(d['required']['support_allowed']==(),'unsupported later demand required')
    if attempts:
        require(tuple(attempts[0]['retention_events'])==tuple(retained_events),'choice used other retention evidence')
        require(organization is not None and organization['complete'],'choice before complete paid organization')
        snapshot=_snapshot(attempts[0]['inventory']['view']);bindings={b.ref:b for b in snapshot.bindings};heads={}
        for b in snapshot.bindings:
            if b.ref.identity not in heads or b.ref.revision>heads[b.ref.identity].ref.revision:heads[b.ref.identity]=b
        required=Demand(**d['required']);queue=[b.ref for b in heads.values() if (b.cue,b.context)==(required.cue,required.context)]
        roots=len(queue);seen=set();visited=[];cursor=0
        while cursor<len(queue) and len(visited)<32:
            ref=queue[cursor];cursor+=1;b=bindings.get(ref)
            if ref in seen or b is None or b.context!=required.context:continue
            seen.add(ref);visited.append(ref);queue.extend(b.links)
        truncated=any(r not in seen and r in bindings and bindings[r].context==required.context for r in queue[cursor:])
        cert=expected_certs[certificate_key]
        reason=('revoked_evidence' if certificate_key in d['retention']['revoked'] else
            'outside_trained_demand_bounds' if not no_easier(Demand(**cert['scope']),required) else
            'no_present_access' if cert['binding'] not in bindings or bindings[cert['binding']].endorsement.value in ('retracted','disputed') else
            'not_recalled' if truncated or cert['binding'] not in visited else 'owned_recalled_scoped_capacity')
        require(attempts[0]['retained'][0]['reason']==reason
            and attempts[0]['retained'][0]['eligible']==(reason=='owned_recalled_scoped_capacity'),'independent bounded recall eligibility')

    selected=None if not attempts else attempts[0]['selected']['name']
    terminal=d['terminal'];require(terminal is None or events and terminal==events[-1],'reuse terminal')
    if d['phase']=='complete':
        require(terminal is not None and terminal['consumer'] is not None and terminal['settlement'] is not None
            and fulfillment['fulfilled']==1 and len(attempts)==1 and attempts[0]['status']=='complete','complete paid reuse')
        tr=attempts[0]['traversal'];settlement=terminal['settlement'];q=d['request']['fields']
        require(settlement['selection_key']==q['key'] and settlement['movement_key']==q['key']+':movement'
            and settlement['consumer_key']==d['consumer_key'] and settlement['movement_output']==tr['movement_output']
            and terminal['consumer']['inputs']==(tr['movement_output'],)
            and terminal['consumer']['output']==settlement['consumer_output'],'exact downstream use and settlement')
        bound=next((r for r in attempts[0]['retained'] if r['key']==certificate_key),None)
        if selected=='retained':require(bound is not None and bound['eligible'] and attempts[0]['selected']['certificate']==certificate_key and tr['means']=='retained','applicable retained choice')
        elif bound is not None:
            option=next(r for r in attempts[0]['options'] if r['name']=='retained')
            require(not option['eligible'],'skipped eligible retained choice')
    else:require(not fulfillment['fulfilled'],'unfulfilled claimed completion')
    return dict(passed=True,phase=d['phase'],qualification_exposures=len(exposures),qualified=bool(certs),selected=selected,
        retained=selected=='retained',revoked=certificate_key in d['retention']['revoked'],fulfilled=fulfillment['fulfilled'],organization_revisions=0 if organization is None else organization['index'],
        recall=None if not attempts else dict(roots=roots,visited=len(visited),truncated=truncated,reason=reason))
