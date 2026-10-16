"""Independent A9 journal, owned-root, geometry and complete-domain reconstruction."""
import json
from hashlib import sha256
from pathlib import Path
from functools import lru_cache
from hle.development_structure import lap, portage
from hle.model_a import fields, position_of
from hle_unified.compact import unseal
from hle_unified.material import OperationStore, attrs
from hle_unified.operations import NativeAccess, indexed
from hle_unified.selection_records import loads, dumps
from .content import FACETS

@lru_cache(maxsize=2)
def reconstruct(native, domain, capacity, setting):
    def sha(x):
        if type(x) is not str:raise ValueError('serialized input')
        return sha256(x.encode()).hexdigest()
    def check(ok,why):
        if not ok:raise ValueError('A9 audit: '+why)
    p=json.loads((Path(__file__).resolve().parents[1]/'contracts/ft/FT7_Universal_TD5_Veto_A9_Protocol_v1.json').read_text())['inputs'].get(setting)
    check(p is not None and [sha(native),sha(domain),sha(capacity)]==[p[k] for k in ('native_sha256','domain_sha256','capacity_sha256')],'input triple')
    d,c=loads(domain),loads(capacity);actor=d['actor'];req=c['required']
    check(c['actor']==actor and d['setting']==setting and req['family']==setting,'actor and setting')
    check(d['source_sha256']==c['source_sha256'] and d['binding_sha256']==c['binding_sha256']
        and sha(d['controller_prefix'])==c['controller_prefix_sha256'],'accepted provenance')
    raw=unseal(native,loads(native)['schema']);world=OperationStore.restore(raw['world']);access=NativeAccess.restore(raw['access'])
    before=(world.checkpoint(),access.checkpoint());view=access.view(actor);snap=view.snapshot
    check(sha(view.bytes())==d['view_sha256'],'current view')
    bindings={b.ref:b for b in snap.bindings};heads={b.ref.identity:b for b in snap.bindings}
    receipts={r.ref:r for r in snap.receipts};first=d['windows'][0]
    fixed=('actor','context','cue','target','demand')
    for window in d['windows']:
        for k in fixed:check(window[k]==first[k],'full window invariant '+k)
    check(first['actor']==actor and first['demand']==c['inventory']['request']['demand']
        and all(first[k]==req[k] for k in ('context','cue','target')),'same task requirements')
    b=bindings.get(first['demand']);r=receipts.get(b.receipt) if b else None
    check(b is not None and heads.get(b.ref.identity)==b and b.actor==actor
        and (b.context,b.cue,b.target)==(first['context'],first['cue'],first['target'])
        and b.endorsement.value not in ('retracted','disputed') and r is not None
        and r.actor==actor and r.complete and r.spent>=r.required,'current paid task')
    names=d['role_order'];check(len(set(names))==len(names) and set(names)==set(d['pools'])
        and all(n in ('stock','tool','repair_stock','procedure','relation','peer','group') for n in names),'role axes')
    sizes=[len(d['windows'])];total=sizes[0]
    for name in names:
        n=len(d['pools'][name]);check(n>0,'nonempty role');sizes.append(n);total*=n
    check(tuple(sizes)==d['radices'] and total==d['assignments']==p['assignments'],'all product cells')
    profile=None;cursor=None
    for tx in world.journal():
        for v in tx.versions:
            a=attrs(v)
            if a.get('actor')!=actor:continue
            if v.ref.identity.namespace=='u5.profile':
                profile=a
                if cursor is None:cursor=a['initial_active']
            if 'route_count' in a and a.get('completed',0)>0:
                remaining=max(0,a['completed']-a['recall_units']);cursor=a['active_start'];halt=False
                for i in range(a['route_count']):
                    for j,charge in enumerate(indexed(a,'route.'+str(i)+'.charges.')):
                        if remaining<charge:halt=True;break
                        remaining-=charge;cursor=a['route.'+str(i)+'.path.'+str(j+1)]
                    if halt:break
                    cost=a['route.'+str(i)+'.content_units']
                    if remaining<cost:break
                    remaining-=cost;cursor=a['route.'+str(i)+'.element']
    check(profile is not None and cursor is not None,'journal cursor')
    origin=position_of(profile['tim'],cursor)
    queue=[v.ref for v in heads.values() if v.context==req['context'] and v.cue==req['cue']]
    seen=set();visited=[];index=0
    while index<len(queue) and len(visited)<32:
        ref=queue[index];index+=1
        if ref in seen or ref not in bindings or bindings[ref].context!=req['context']:continue
        seen.add(ref);visited.append(ref);queue.extend(bindings[ref].links)
    truncated=any(x not in seen and x in bindings and bindings[x].context==req['context'] for x in queue[index:])
    missing=lambda seat:bool(set(req['requirements'])-set(FACETS[:fields(seat)['dimensionality']]))
    blocked={'retained':bool(truncated or missing(origin)),'ordinary':missing(lap(origin)),
        'n':missing(portage(origin,'n')),'cp':missing(portage(origin,'cp')),'support':len(req['support_allowed'])==0}
    certs=[]
    for row in c['retained']:
        ref=row['certificate']['binding']
        owned=(ref in bindings and bindings[ref].endorsement.value not in ('retracted','disputed')) or any(x.source==ref for x in snap.particulars)
        certs.append(dict(key=row['key'],binding=ref,owned=owned,visited=ref in visited))
    geo=tuple((n,s,fields(s)['dimensionality']) for n,s in (('retained',origin),('ordinary',lap(origin)),('n',portage(origin,'n')),('cp',portage(origin,'cp'))))
    veto=not any(flag is False for flag in blocked.values())
    expected=dict(version='ft-universal-td5-veto-a9-v1',setting=setting,actor=actor,
        native_sha256=sha(native),domain_sha256=sha(domain),capacity_sha256=sha(capacity),
        view_sha256=sha(view.bytes()),required=req,task=b.ref,receipt=b.receipt,
        tim=profile['tim'],cursor=cursor,origin_seat=origin,geometry=geo,
        recall=dict(limit=32,visited=tuple(visited),truncated=truncated),certificates=tuple(certs),
        factor_sizes=tuple(sizes),role_order=names,covered_assignments=total,scope_fields=fixed,
        blocked=blocked,all_work_ineligible=veto,status='all_work_vetoed' if veto else 'unresolved_requires_full_admission',
        comparison_can_be_skipped_for_deferral=veto,domain_pruned=False,native_unchanged=True,
        may_launch=False,comparison_paid=False,execution_authorized=False,td5_admitted=False,
        history_choice=False,completion_claim=False,parent_accepted=False)
    check(before==(world.checkpoint(),access.checkpoint()),'native immutability')
    return dumps(expected)

def audit(native, domain, capacity, setting, text):
    expected=reconstruct(native,domain,capacity,setting)
    if dumps(loads(text))!=expected:raise ValueError('A9 audit: exact universal veto proof')
    row=loads(expected)
    return dict(passed=True,setting=setting,assignments=row['covered_assignments'],
        all_work_ineligible=row['all_work_ineligible'],recall_count=len(row['recall']['visited']),
        truncated=row['recall']['truncated'],native_unchanged=True)
