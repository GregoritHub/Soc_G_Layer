"""A4 actor-visible material vocabulary; no native resolver or execution API."""
import json
from hashlib import sha256
from pathlib import Path
from hle_unified.records import ObjectId, ObjectRef
from hle_unified.selection_records import dumps, loads

VERSION = 'ft-observed-material-domain-a4-v1'
PROTOCOL = Path(__file__).resolve().parents[1]/'contracts/ft/FT7_Observed_Reference_A4_Protocol_v1.json'


def digest(text):
    return sha256(text.encode()).hexdigest()


def fields(details):
    result = {}
    for p in details:
        key = p.address.key
        if key in result and (type(result[key]) is not type(p.value) or result[key] != p.value):
            raise ValueError('conflicting explicit fields')
        result[key] = p.value
    return result


def material_vocabulary(view, refresh, setting):
    """Pure grammar over particulars, not material eligibility or current truth."""
    if setting not in ('canonical', 'workflow'):
        raise ValueError('registered setting required')
    if refresh['phase'] != 'complete':
        return (), {}
    actor = view.snapshot.actor
    grouped = {}
    for p in view.snapshot.particulars:
        grouped.setdefault(p.source, []).append(p)
    supports = []
    def proof(details):
        return tuple(sorted({(p.source,p.address.delivery,p.address.key) for p in details},key=dumps))
    for ref, details in grouped.items():
        f = fields(details)
        if type(f.get('quantity')) is int and type(f.get('owner')) is ObjectId and type(f.get('custodian')) is ObjectId:
            supports.append(dict(kind='direct',observed_ref=ref,evidence=proof(details)))
    observations = []
    for receipt in refresh['receipts']:
        delivery = 'ft-skill-refresh:'+refresh['source_native_sha256']+':'+str(receipt['index'])+':delivery'
        details = tuple(p for p in view.snapshot.particulars if p.address.delivery == delivery)
        sources = {p.source for p in details}
        if len(sources) != 1:
            raise ValueError('one paid observation source required')
        source = next(iter(sources)); f = fields(details)
        reads = tuple(r for r in view.snapshot.receipts if r.actor == actor and r.operation == 'read'
                      and r.work_key == delivery and r.inputs == (source,)
                      and r.required == r.completed == r.spent == 2)
        if len(reads) != 1 or f.get('actor') != actor or f.get('context') != refresh['context']:
            raise ValueError('exact completed owned observation receipt required')
        if f.get('primitive') != 'inspect' or f.get('outcome') != 'succeeded' or type(f.get('target')) is not ObjectRef:
            raise ValueError('explicit successful inspection target required')
        if type(f.get('owner')) is not ObjectId or type(f.get('custodian')) is not ObjectId:
            raise ValueError('explicit material ownership facts required')
        evidence = proof(details)
        observations.append(dict(source=source,target=f['target'],facts=f,evidence=evidence,receipt=reads[0].ref))
        supports.append(dict(kind='observation',observed_ref=f['target'],evidence=evidence))
    latest = {}
    for support in supports:
        ref = support['observed_ref']
        if ref.identity not in latest or ref.revision > latest[ref.identity].revision:
            latest[ref.identity] = ref
    candidates = {}
    for support in supports:
        ref = support['observed_ref']
        selected = latest[ref.identity] if setting == 'canonical' else ref
        candidates.setdefault(selected, {})[dumps(support)] = support
    rows = [dict(value=None,supports=())]+[
        dict(value=ref,supports=tuple(supports[k] for k in sorted(supports)))
        for ref,supports in sorted(candidates.items(),key=lambda item:dumps(item[0]))]
    roles = ('stock','tool','repair_stock') if setting == 'canonical' else ('stock',)
    return tuple(sorted(observations,key=dumps)), {role:rows for role in roles}


def observed_material_domain(view, refresh_text, setting):
    refresh = loads(refresh_text)
    identities = (refresh.get('expected_native_sha256'),digest(refresh_text),digest(view.bytes()))
    inputs = json.loads(PROTOCOL.read_text())['inputs']
    if not any(row['setting'] == setting and identities ==
               (row['native_sha256'],row['refresh_sha256'],row['view_sha256']) for row in inputs):
        raise ValueError('exact accepted native/refresh/view binding required')
    if refresh['actor'] != view.snapshot.actor:
        raise ValueError('owned actor required')
    observations,pools = material_vocabulary(view,refresh,setting)
    return dumps(dict(version=VERSION,setting=setting,native_sha256=identities[0],refresh_sha256=identities[1],
        view_sha256=identities[2],actor=refresh['actor'],context=refresh['context'],settled=refresh['phase']=='complete',
        observations=observations,pools=pools,role_order=tuple(pools),
        coverage='explicit-material-vocabulary-only',comparison_paid=False,execution_authorized=False,
        td5_admitted=False,history_choice=False,parent_accepted=False))
