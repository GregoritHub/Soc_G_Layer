"""Independent training reconstruction from native records and owned snapshots.

No controller, selector, development policy, executor or scheduler imports.
"""
import json
from hashlib import sha256
from hle_unified import codec
from hle_unified.compact import unseal,CompactStore
from hle_unified.material import attrs
from hle_unified.development_values import attrs as devattrs
from hle_unified.records import Account
from hle_unified.self_content import decode
from hle_unified.development_audit import audit as audit_development
from hle_unified.selection_records import dumps,loads
from .fulfillment_audit import _snapshot
from .content_audit import audit_content


def _known(snapshot,versions,target,context):
    grouped={}
    for p in snapshot.particulars:grouped.setdefault(p.source,{})[p.address.key]=p.value
    latest={}
    for source,row in grouped.items():
        raw=attrs(versions[source])
        if raw.get('schema')=='u7.encounter-facts-v1' and raw.get('receiver')==snapshot.actor and raw.get('target')==target and raw.get('context')==context:
            old=latest.get(source.identity)
            if old is None or old.revision<source.revision:latest[source.identity]=source
    sources=tuple(sorted(latest.values()))
    names={name for source in sources for name in grouped[source]};known={}
    for name in names:
        values={grouped[source][name] for source in sources if name in grouped[source]}
        if len(values)==1:known[name]=next(iter(values))
    return known,sources


def audit_social_training(engine,checkpoint):
    d=loads(checkpoint);native=engine.checkpoint();txs=tuple(engine.world.journal())
    expected={'version','native_sha256','actor','setting','scope','prefix_native','prefix_peer','prefix_count','start_count','phase','index','plan','events','work','response','observation','delivery','capacity','terminal'}
    if set(d)!=expected or d['version']!='ft-owned-social-training-v1' or d['native_sha256']!=sha256(native.encode()).hexdigest():raise ValueError('training/native pairing differs')
    peer=loads(d['prefix_peer']);raw=json.loads(d['prefix_native']);payload=unseal(d['prefix_native'],raw['schema']);prefix=CompactStore.restore(payload['world']).journal()
    if len(prefix)!=d['prefix_count'] or tuple(txs[:len(prefix)])!=tuple(prefix):raise ValueError('immutable social prefix differs')
    if peer['native_sha256']!=sha256(d['prefix_native'].encode()).hexdigest() or peer['phase']!='complete' or (peer['actor'],peer['setting'],peer['required'])!=(d['actor'],d['setting'],d['scope']):raise ValueError('training lacks exact social completion')
    social=loads(peer['social']);history=loads(social['history'])
    if any(history['scores'].values()):raise ValueError('supported prefix granted independent credit')
    versions={v.ref:v for tx in txs for v in tx.versions};heads={}
    for tx in prefix:
        for v in tx.versions:heads[v.ref.identity]=v
    def paid(ref):
        r=attrs(versions[ref])
        if r.get('status')!='succeeded' or not r.get('required') or r.get('spent',0)<r['required'] or r.get('completed')!=r['required']:raise ValueError('unpaid claimed training effect')
        return r
    if not d['events']:
        if d['phase']!='discover' or d['plan'] is not None or d['work'] or d['capacity'] is not None or d['index']!=0 or d['terminal'] is not None or d['start_count'] is not None:raise ValueError('forged initial training state')
        audit_development(txs)
        return dict(passed=True,independent=True,phase='discover',episodes=0,content_uses=0,paid_observations=0,independent_practices=0,native_capacity=False)
    if type(d['start_count']) is not int or not d['prefix_count']<=d['start_count']<=len(txs):raise ValueError('invalid training discovery boundary')
    for tx in txs[d['prefix_count']:d['start_count']]:
        for v in tx.versions:
            r=attrs(v)
            if r.get('u8') and r.get('purpose') in ('respond','practice','reorganize','reown'):raise ValueError('supplied training response/practice/capacity before discovery')
            heads[v.ref.identity]=v
    snapshot=_snapshot(d['events'][0]['view'])
    if snapshot.actor!=d['actor']:raise ValueError('foreign discovery snapshot')
    patterns=sorted((v.ref for v in heads.values() if v.ref.identity.namespace=='u7.pattern' and (attrs(v).get('owner'),attrs(v).get('context'),attrs(v).get('cue'))==(d['actor'],d['scope']['context'],d['scope']['cue'])),key=dumps)
    found=[]
    if patterns:
        p=attrs(versions[patterns[0]]);bindings={b.ref:b for b in snapshot.bindings}
        for v in heads.values():
            r=attrs(v)
            if r.get('actor')!=d['actor'] or r.get('record_type')!='operation' or r.get('status')!='succeeded' or not r.get('route_count') or r.get('u8') or r.get('context')!=d['scope']['context'] or r.get('destination') not in ('I','ITS'):continue
            output=r.get('binding') or r.get('result');target=r.get('content_target',r.get('target'))
            if output is None or output not in bindings:continue
            binding=bindings[output]
            if len(binding.content)!=1 or binding.content[0].relation!=('c3.data' if d['setting']=='canonical' else 'c7w.data'):continue
            try:body=decode(binding.content[0].object)
            except ValueError:continue
            kinds=({'I':('intention','personal_policy'),'ITS':('model','rule')} if d['setting']=='canonical' else {'I':('intention','personal'),'ITS':('system','rule')})
            if body.get('kind') not in kinds[r['destination']]:continue
            account=versions[output].facet(Account)
            if r.get('binding') is not None and (account is None or account.holder!=d['actor'] or account.referent!=target or account.content!=binding.content or not account.content or any((x.subject,x.context)!=(target,r['context']) for x in account.content)):continue
            known,sources=_known(snapshot,versions,target,d['scope']['context'])
            if not sources or known.get('trigger')!=p['trigger'] or known.get('partner') is None or not any(x.source==target for x in snapshot.particulars):continue
            paid(v.ref);found.append(dict(target=target,source=output,source_operation=v.ref,destination=r['destination'],partner=known['partner']))
    chosen={}
    for row in sorted(found,key=lambda row:dumps((row['target'],row['source']))):chosen.setdefault(row['target'].identity,row)
    expected_plan=dict(pattern=patterns[0],episodes=tuple(list(chosen.values())[:2])) if patterns and len(chosen)>=2 else None
    if d['plan']!=expected_plan:raise ValueError('owned discovery order or scope differs')
    audit_content(txs,d['work']);development=audit_development(txs)
    phase='discover';index=0;offset=d['start_count'];works=[];responses=[];uses=[];practices=[];observations=[]
    for i,event in enumerate(d['events']):
        if event['index']!=i or event['before']!=offset or event['phase_before']!=phase or not offset<=event['after']<=len(txs):raise ValueError('training event order differs')
        s=_snapshot(event['view'])
        if s.actor!=d['actor']:raise ValueError('foreign request snapshot')
        before_versions={v.ref:v for tx in txs[:offset] for v in tx.versions}
        for detail in s.particulars:
            if detail.source not in before_versions:raise ValueError('future detail in owned snapshot')
        work=event['work'];req=event['request']
        if phase=='discover':
            if work is not None or req is not None or event['after']!=offset:raise ValueError('discovery fabricated work')
            phase='respond' if expected_plan else 'deferred'
        elif work is None:
            if phase!='organize' or req is not None or event['after']!=offset or len([r for r in practices if devattrs(versions[r])['independent']])>=2:raise ValueError('fabricated unqualified training')
            phase='unqualified'
        else:
            works.append(work);r=attrs(versions[work['operation']]);q=req['fields'];episode=expected_plan['episodes'][min(index,1)]
            key='ft-social-training:'+sha256(dumps((d['actor'],d['prefix_count'])).encode()).hexdigest()[:16]+':'+str(index)+':'+('organize' if phase=='organize' else phase)
            if (q['actor'],q['key'],q['context'])!=(d['actor'],key,d['scope']['context']) or (r['actor'],r['key'],r['context'])!=(q['actor'],q['key'],q['context']):raise ValueError('actual native training identity differs')
            if req['type']=='DevelopmentRequest':
                if q['purpose']!=('reorganize' if phase=='organize' else phase) or q['pattern']!=expected_plan['pattern'] or q['cue']!=d['scope']['cue']:raise ValueError('development purpose or scope differs')
                targets=(expected_plan['episodes'][0]['target'],) if phase=='organize' else (episode['target'],)
                if q['targets']!=targets or r['pattern']!=q['pattern'] or r['purpose']!=q['purpose'] or r['target.0']!=targets[0]:raise ValueError('native training targets differ')
                if phase=='respond':
                    known,sources=_known(s,before_versions,episode['target'],q['context'])
                    evidence=tuple((p.address.delivery,p.address.key) for source in sources for p in s.particulars if p.source==source)
                    if q['evidence']!=evidence or q['partner']!=known.get('partner'):raise ValueError('response opportunity differs')
            if phase=='content':
                recipe=('use-' if d['setting']=='canonical' else 'workflow-use-')+('personal' if episode['destination']=='I' else 'system')+'-v1'
                if q['recipe']!=recipe or r['recipe_key']!=recipe or q['inputs']!=(episode['source'],) or work['consumed']!=q['inputs'] or r['source.0']!=episode['source']:raise ValueError('actual training content operand differs')
                if responses and paid(responses[-1])['finished_tick']>r['started_tick']:raise ValueError('content precedes response')
            if work['status']=='succeeded':
                paid(work['operation'])
                if phase=='respond':responses.append(work['operation']);phase='content'
                elif phase=='content':uses.append(work['operation']);phase='observe'
                elif phase=='observe':
                    if r['primitive']!='read' or r['delivery']!=q['delivery']:raise ValueError('observation lacks paid read')
                    observations.append(work['operation']);phase='practice'
                elif phase=='practice':
                    pr=r['development'];row=devattrs(versions[pr]);event_ref=paid(responses[-1])['result']
                    if row['event']!=event_ref or row['observation']!=q['observation'] or r['observation']!=q['observation'] or paid(uses[-1])['finished_tick']>r['started_tick'] or attrs(versions[q['observation']])['event']!=event_ref:raise ValueError('practice not bound to own response/content/observation')
                    practices.append(pr);index+=1;phase='respond' if index<2 else 'organize'
                else:
                    cap=r['development'];row=devattrs(versions[cap])
                    if d['capacity']!=cap or row['examples']!=tuple(practices) or row['max_load']!=1 or any(not devattrs(versions[pr])['independent'] for pr in practices):raise ValueError('capacity lacks exact independent examples')
                    phase='complete'
            elif work['status'] in ('failed','cancelled'):phase='failed'
        if event['phase']!=phase or event['episode_index']!=index:raise ValueError('training phase or episode count differs')
        offset=event['after']
    if d['phase']!=phase or d['index']!=index or d['work']!=works or offset!=len(txs):raise ValueError('training terminal/delegated evidence differs')
    if (d['terminal'] is not None)!=(phase in ('complete','unqualified','deferred','failed')) or d['terminal'] is not None and d['terminal']!=d['events'][-1]:raise ValueError('training terminal differs')
    if phase!='complete' and d['capacity'] is not None:raise ValueError('noncomplete training fabricated capacity')
    return dict(passed=True,independent=True,phase=phase,episodes=index,content_uses=len(uses),paid_observations=len(observations),independent_practices=sum(devattrs(versions[p])['independent'] for p in practices),native_capacity=d['capacity'] is not None,development=development,claim='native guarded response training only; FT closure/reuse/feedback pending')
