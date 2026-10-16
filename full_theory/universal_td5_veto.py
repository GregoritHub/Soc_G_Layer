"""A9 sufficient TD5 veto over a complete domain; never a comparison receipt."""
import json
from hashlib import sha256
from math import prod
from pathlib import Path
from hle.development_structure import lap, portage
from hle.model_a import position_of, fields
from hle_unified.compact import unseal
from hle_unified.material import OperationStore, attrs
from hle_unified.operations import NativeAccess
from hle_unified.cognitive_routes import progress
from hle_unified.selection_records import loads, dumps
from .content import FACETS

PROTOCOL=Path(__file__).resolve().parents[1]/'contracts/ft/FT7_Universal_TD5_Veto_A9_Protocol_v1.json'
ROLES=frozenset(('stock','tool','repair_stock','procedure','relation','peer','group'))

def digest(text):
    if type(text) is not str: raise ValueError('exact serialized input required')
    return sha256(text.encode()).hexdigest()

def structural_veto(origin, requirements, truncated, support):
    if type(origin) is not int or not 1<=origin<=8 or type(truncated) is not bool:
        raise ValueError('exact seat and recall flag')
    if type(requirements) is not tuple or not requirements or len(set(requirements))!=len(requirements) or not set(requirements)<=set(FACETS):
        raise ValueError('exact conjunctive facets')
    if type(support) is not tuple: raise ValueError('exact support bounds')
    covered=lambda seat:set(requirements)<=set(FACETS[:fields(seat)['dimensionality']])
    return dict(retained=truncated or not covered(origin),ordinary=not covered(lap(origin)),
        n=not covered(portage(origin,'n')),cp=not covered(portage(origin,'cp')),support=not support)

def analyze(native, domain, capacity, setting):
    p=json.loads(PROTOCOL.read_text())['inputs'].get(setting)
    if p is None or tuple(map(digest,(native,domain,capacity)))!=tuple(p[k] for k in ('native_sha256','domain_sha256','capacity_sha256')):
        raise ValueError('exact accepted triple required')
    d,c=loads(domain),loads(capacity);actor=d['actor'];required=c['required']
    if (d['setting']!=setting or c['actor']!=actor or d['source_sha256']!=c['source_sha256']
        or d['binding_sha256']!=c['binding_sha256'] or digest(d['controller_prefix'])!=c['controller_prefix_sha256']):
        raise ValueError('unchanged scope and controller provenance')
    state=unseal(native,loads(native)['schema']);world=OperationStore.restore(state['world']);access=NativeAccess.restore(state['access'])
    before=(world.checkpoint(),access.checkpoint());view=access.view(actor)
    if digest(view.bytes())!=d['view_sha256']:raise ValueError('exact current owned view')
    first=d['windows'][0];invariant=('actor','context','cue','target','demand')
    for w in d['windows']:
        if any(w[k]!=first[k] for k in invariant):raise ValueError('non-invariant domain scope')
    if (first['actor']!=actor or any(first[k]!=required[k] for k in ('context','cue','target'))
        or first['demand']!=c['inventory']['request']['demand'] or required['family']!=setting):
        raise ValueError('unchanged conjunctive demand')
    task=view._bindings.get(first['demand']);receipt=None if task is None else view.receipt(task.receipt)
    if (task is None or view._heads.get(task.ref.identity)!=task or task.actor!=actor
        or (task.context,task.cue,task.target)!=(first['context'],first['cue'],first['target'])
        or task.endorsement.value in ('disputed','retracted') or receipt is None
        or receipt.actor!=actor or not receipt.complete or receipt.spent<receipt.required):
        raise ValueError('current paid owned need')
    names=d['role_order']
    if len(set(names))!=len(names) or set(names)!=set(d['pools']) or not set(names)<=ROLES:
        raise ValueError('invariant role axes only')
    sizes=(len(d['windows']),)+tuple(len(d['pools'][n]) for n in names)
    if any(n<1 for n in sizes) or sizes!=d['radices'] or prod(sizes)!=d['assignments'] or d['assignments']!=p['assignments']:
        raise ValueError('complete product required')
    profile=None;cursor=None
    for tx in world.journal():
        for v in tx.versions:
            a=attrs(v)
            if a.get('actor')!=actor:continue
            if v.ref.identity.namespace=='u5.profile':
                profile=a;cursor=a['initial_active'] if cursor is None else cursor
            if 'route_count' in a and a.get('completed',0)>0:cursor=progress(a)[0]
    if profile is None or cursor is None:raise ValueError('current paid native cursor')
    origin=position_of(profile['tim'],cursor);recall=view.traverse(required['cue'],required['context'])
    blocked=structural_veto(origin,required['requirements'],recall.truncated,required['support_allowed'])
    certs=tuple(dict(key=r['key'],binding=r['certificate']['binding'],
        owned=(r['certificate']['binding'] in view._bindings and view._bindings[r['certificate']['binding']].endorsement.value not in ('retracted','disputed')) or bool(view.resolve(r['certificate']['binding'])),
        visited=r['certificate']['binding'] in recall.visited) for r in c['retained'])
    geometry=tuple((name,seat,fields(seat)['dimensionality']) for name,seat in
        (('retained',origin),('ordinary',lap(origin)),('n',portage(origin,'n')),('cp',portage(origin,'cp'))))
    if before!=(world.checkpoint(),access.checkpoint()):raise ValueError('native mutation')
    all_blocked=all(blocked.values())
    return dumps(dict(version='ft-universal-td5-veto-a9-v1',setting=setting,actor=actor,
        native_sha256=digest(native),domain_sha256=digest(domain),capacity_sha256=digest(capacity),
        view_sha256=digest(view.bytes()),required=required,task=task.ref,receipt=task.receipt,
        tim=profile['tim'],cursor=cursor,origin_seat=origin,geometry=geometry,
        recall=dict(limit=32,visited=recall.visited,truncated=recall.truncated),certificates=certs,
        factor_sizes=sizes,role_order=names,covered_assignments=prod(sizes),scope_fields=invariant,
        blocked=blocked,all_work_ineligible=all_blocked,
        status='all_work_vetoed' if all_blocked else 'unresolved_requires_full_admission',
        comparison_can_be_skipped_for_deferral=all_blocked,domain_pruned=False,native_unchanged=True,
        may_launch=False,comparison_paid=False,execution_authorized=False,td5_admitted=False,
        history_choice=False,completion_claim=False,parent_accepted=False))
