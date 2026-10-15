"""Finite role alternatives from paid particulars; never an execution grant."""
from hashlib import sha256
from itertools import product
from math import prod

from hle_unified.records import ObjectId, ObjectRef, Procedure
from hle_unified.selection_records import SelectionRequest, dumps, loads
from hle_unified.workflow_selection_records import WorkflowSelectionRequest, WorkflowCapacitySelectionRequest
from hle_unified.self_content import decode
from .compared_preparation_audit import audit_compared_preparation

VERSION = 'ft-owned-paid-role-domain-v1'


def paid_pools(view, setting):
    """Conservative vocabulary, including unusable/foreign/name-only alternatives."""
    names = ('stock','tool','repair_stock','procedure','peer','group') if setting == 'canonical' else (
        'stock','relation','procedure','peer','group')
    collected = {n:{} for n in names}
    refs = sorted({p.source for p in view.snapshot.particulars}, key=dumps)
    def add(role, value, details):
        if value == view.snapshot.actor and role == 'peer': return
        if type(value) is ObjectRef and setting == 'canonical':
            value = max((p.source for p in view.lookup(subject=value.identity)
                if p.source.identity == value.identity), key=lambda r:r.revision, default=value)
        proof = collected[role].setdefault(value,set())
        proof.update((p.source,p.address.delivery,p.address.key) for p in details)
    for ref in refs:
        details = view.resolve(ref); fields = {p.address.key:p.value for p in details}
        if (type(fields.get('quantity')) is int and type(fields.get('owner')) is ObjectId
            and type(fields.get('custodian')) is ObjectId):
            for role in ('stock','tool','repair_stock') if setting == 'canonical' else ('stock',):
                add(role,ref,details)
        if any(type(p.value) is Procedure for p in details): add('procedure',ref,details)
        if setting == 'workflow': add('relation',ref,details)
        values = [(fields,details)]
        for p in details:
            if p.address.key != 'payload' or type(p.value) is not str: continue
            try: decoded = decode(p.value)
            except (ValueError,TypeError): continue
            if type(decoded) is dict:
                values.append((decoded,(p,)))
                members = decoded.get('members')
                if (type(members) is tuple and all(type(x) is ObjectId for x in members)
                    and type(decoded.get('context')) is ObjectRef): add('group',ref,(p,))
        for value,proof in values:
            for field in ('owner','custodian','actor','partner','speaker','receiver'):
                if type(value.get(field)) is ObjectId: add('peer',value[field],proof)
            for field in ('members','participants'):
                if type(value.get(field)) is tuple:
                    for actor in value[field]:
                        if type(actor) is ObjectId: add('peer',actor,proof)
    return {name:[dict(value=None,evidence=())]+[
        dict(value=value,evidence=tuple(sorted(proof,key=dumps)))
        for value,proof in sorted(collected[name].items(),key=lambda x:dumps(x[0]))] for name in names}


def owned_role_domain(engine, comparison, original, source, binding, domain, operands, admission, prepared):
    audit_compared_preparation(engine,comparison,original,source,binding,domain,operands,admission,prepared)
    p = loads(prepared); setting = loads(source)['setting']
    view = engine.participant_view(p['actor'])
    settled = len(p['receipts']) == p['required']
    pools = paid_pools(view,setting) if settled else {}
    return dumps(dict(version=VERSION,setting=setting,native_sha256=sha256(engine.checkpoint().encode()).hexdigest(),
        preparation_sha256=sha256(prepared.encode()).hexdigest(),view_sha256=sha256(view.bytes().encode()).hexdigest(),
        request=p['request'],settled=settled,pools=pools,role_order=tuple(pools),
        assignments=prod(len(x) for x in pools.values()) if settled else 0,
        coverage='explicit-paid-observation-grammar-only',comparison_paid=False,
        execution_authorized=False,td5_admitted=False,history_choice=False))


def role_requests(text):
    """Lazy complete Cartesian product; no arbitrary cap or success filtering."""
    d = loads(text)
    if d['version'] != VERSION: raise ValueError('owned role schema')
    if not d['settled']: return
    names = d['role_order']
    for ordinal,values in enumerate(product(*(d['pools'][n] for n in names))):
        fields = dict(d['request']); fields.update((n,v['value']) for n,v in zip(names,values))
        fields['key'] = 'ft-owned-roles:' + d['preparation_sha256'] + ':' + str(ordinal)
        if d['setting'] == 'canonical': yield SelectionRequest(**fields)
        elif fields.get('procedure') is not None: yield WorkflowCapacitySelectionRequest(**fields)
        else:
            fields.pop('procedure',None)
            yield WorkflowSelectionRequest(**fields)
