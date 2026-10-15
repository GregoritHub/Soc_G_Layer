"""Independent paid-role vocabulary reconstruction; imports no new generator."""
from hashlib import sha256
from math import prod
from hle_unified.records import ObjectId, ObjectRef, Procedure
from hle_unified.selection_records import dumps, loads
from hle_unified.self_content import decode
from .compared_preparation_audit import audit_compared_preparation


def audit_role_payload(snapshot, request, setting, settled, text, native_hash, preparation_hash, view_hash):
    def require(ok, why):
        if not ok: raise ValueError('owned role audit: '+why)
    d=loads(text)
    require(set(d)=={'version','setting','native_sha256','preparation_sha256','view_sha256','request',
        'settled','pools','role_order','assignments','coverage','comparison_paid','execution_authorized',
        'td5_admitted','history_choice'},'exact schema')
    require(d['version']=='ft-owned-paid-role-domain-v1' and d['setting']==setting,'version/setting')
    require((d['native_sha256'],d['preparation_sha256'],d['view_sha256'])==
        (native_hash,preparation_hash,view_hash),'exact current pairing')
    require(d['request']==request and d['settled'] is settled,'original request and settlement')
    require(d['coverage']=='explicit-paid-observation-grammar-only' and all(d[n] is False for n in
        ('comparison_paid','execution_authorized','td5_admitted','history_choice')),'no invented authority')
    roles=('stock','tool','repair_stock','procedure','peer','group') if setting=='canonical' else (
        'stock','relation','procedure','peer','group')
    expected={role:{None:set()} for role in roles} if settled else {}
    if settled:
        by_source={}
        for detail in snapshot.particulars: by_source.setdefault(detail.source,[]).append(detail)
        def emit(role,value,proof):
            if role=='peer' and value==snapshot.actor: return
            if setting=='canonical' and type(value) is ObjectRef:
                observed=[p.source for p in snapshot.particulars
                    if p.subject.identity==value.identity and p.source.identity==value.identity]
                if observed: value=sorted(observed,key=lambda r:r.revision)[-1]
            expected[role].setdefault(value,set()).update((p.source,p.address.delivery,p.address.key) for p in proof)
        for ref,details in by_source.items():
            visible={}
            for p in details: visible[p.address.key]=p.value
            if ('quantity' in visible and type(visible['quantity']) is int and
                isinstance(visible.get('owner'),ObjectId) and isinstance(visible.get('custodian'),ObjectId)):
                emit('stock',ref,details)
                if setting=='canonical':
                    emit('tool',ref,details);emit('repair_stock',ref,details)
            if [p for p in details if type(p.value) is Procedure]: emit('procedure',ref,details)
            if setting=='workflow': emit('relation',ref,details)
            observed=[(visible,details)]
            for p in details:
                if p.address.key=='payload' and type(p.value) is str:
                    try: value=decode(p.value)
                    except (TypeError,ValueError): continue
                    if type(value) is not dict: continue
                    observed.append((value,[p]))
                    if (isinstance(value.get('context'),ObjectRef) and type(value.get('members')) is tuple
                        and all(type(m) is ObjectId for m in value['members'])):emit('group',ref,[p])
            for attrs,proof in observed:
                candidates=[attrs.get(k) for k in ('owner','custodian','actor','partner','speaker','receiver')]
                for key in ('members','participants'):
                    if type(attrs.get(key)) is tuple: candidates.extend(attrs[key])
                for value in candidates:
                    if type(value) is ObjectId:emit('peer',value,proof)
    result={}
    for role,values in expected.items():
        result[role]=[{'value':None,'evidence':()}]
        for value in sorted((v for v in values if v is not None),key=dumps):
            result[role].append({'value':value,'evidence':tuple(sorted(values[value],key=dumps))})
    require(d['role_order']==tuple(result) and d['pools']==result,'complete exact paid role alternatives')
    count=prod(len(v) for v in result.values()) if settled else 0
    require(type(d['assignments']) is int and d['assignments']==count,'exact Cartesian size')
    return dict(passed=True,settled=settled,roles={k:len(v) for k,v in result.items()},assignments=count,
        execution_authorized=False,comparison_paid=False)


def audit_owned_role_domain(engine, comparison, original, source, binding, domain, operands, admission, prepared, text):
    audit_compared_preparation(engine,comparison,original,source,binding,domain,operands,admission,prepared)
    p=loads(prepared);view=engine.participant_view(p['actor'])
    return audit_role_payload(view.snapshot,p['request'],loads(source)['setting'],
        len(p['receipts'])==p['required'],text,sha256(engine.checkpoint().encode()).hexdigest(),
        sha256(prepared.encode()).hexdigest(),sha256(view.bytes().encode()).hexdigest())
