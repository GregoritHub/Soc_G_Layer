"""Independent A6 owned-evidence reconstruction; no planner or selector imports."""
import json
from functools import lru_cache
from hashlib import sha256
from math import prod
from pathlib import Path
from hle_unified.records import ObjectId, ObjectRef, Procedure
from hle_unified.selection_records import dumps, loads, fields_of, SelectionRequest, demand_value
from hle_unified.workflow_selection_records import WorkflowSelectionRequest, demand_value as workflow_need
from hle_unified.self_content import decode


def digest(text): return sha256(text.encode()).hexdigest()


def require(ok, reason):
    if not ok: raise ValueError('changed input domain audit: '+reason)


@lru_cache(maxsize=2)
def reconstruct(view, native_hash, field_text, old_text, refresh_text, setting):
    entry = json.loads((Path(__file__).resolve().parents[1]/
        'contracts/ft/FT7_Changed_Input_Domain_A6_Protocol_v1.json').read_text())['inputs'].get(setting)
    require(entry is not None, 'registered setting')
    require((native_hash,digest(field_text),digest(old_text),digest(refresh_text),digest(view.bytes())) ==
        tuple(entry[k] for k in ('native_sha256','adapter_sha256','old_domain_sha256','refresh_sha256','view_sha256')),
        'accepted native / adapter / source / observation / view identities')
    f,o,r = map(loads,(field_text,old_text,refresh_text)); actor = o['actor']
    require(actor == view.snapshot.actor == f['actor'] == r['actor'] and f['phase'] == r['phase'] == 'complete', 'owned completion')
    require(f['expected_native_sha256'] == native_hash, 'changed native binding')
    c = loads(o['controller_prefix']); ledger = loads(c['ledger']); fresh = o['fresh_demand']
    b = view._bindings[fresh['binding']]; key = dumps((actor,b.ref))
    require(key not in ledger['demands'], 'fresh task not an older registered demand')
    heads = {}
    for x in view.snapshot.bindings:
        if x.actor == actor and (x.ref.identity not in heads or x.ref.revision > heads[x.ref.identity].ref.revision):
            heads[x.ref.identity] = x
    require(heads[b.ref.identity] == b and b.endorsement.value not in ('retracted','disputed'), 'current task')
    for x in heads.values():
        if x.ref != b.ref and x.endorsement.value not in ('retracted','disputed') and any(
                p.relation in ('c6.need','c7ws.need') for p in x.content):
            older = dumps((actor,x.ref))
            require(older in ledger['demands'] and older in c['outcomes'], 'no older unresolved owned need bypassed')
    for k,d in ledger['demands'].items():
        if d['actor'] == actor and d['status'] == 'pending' and k not in c['outcomes']:
            require((d['first_seen'],k) > (fresh['first_seen'],key), 'oldest priority preserved')
    receipt = view.receipt(b.receipt)
    require(receipt is not None and receipt.actor == actor and receipt.operation == 'bind' and receipt.complete
            and receipt.spent == receipt.required == 3, 'paid current task receipt')
    expected_fresh = dict(actor=actor,binding=b.ref,receipt=b.receipt,context=b.context,cue=b.cue,target=b.target,
        relation=b.content[0].relation,payload=(demand_value if setting=='canonical' else workflow_need)(decode(b.content[0].object)),
        raw_payload=b.content[0].object,first_seen=ledger['turn'],admitted_at=ledger['turn'],status='pending',reason=None)
    require(fresh == expected_fresh, 'unchanged complete demand')
    inventory = []
    if setting == 'workflow':
        for x in heads.values():
            paid = view.receipt(x.receipt)
            if (x.endorsement.value not in ('retracted','disputed') and len(x.content)==1
                    and x.content[0].relation=='c7w.data' and (x.context,x.cue,x.target)==(b.context,b.cue,b.target)
                    and paid is not None and paid.complete and paid.actor==actor and paid.spent>=paid.required):
                inventory.append(x.ref)
        inventory.sort(key=dumps);require(bool(inventory),'nonempty workflow inventory')
    common = dict(actor=actor,context=b.context,cue=b.cue,target=b.target,demand=b.ref)
    initial_key = 'ft-request:'+digest(key)
    if setting == 'canonical':
        initial = SelectionRequest(key=initial_key,**common); windows=[fields_of(initial)]
    else:
        initial = WorkflowSelectionRequest(key=initial_key,accessible=tuple(inventory),**common) if len(inventory)<=8 else None
        masks = []
        for mask in range(1,1<<len(inventory)):
            indices = tuple(i for i in range(len(inventory)) if mask & (1<<i))
            if len(indices)<=8: masks.append(indices)
        masks.sort(key=lambda x:(len(x),x)); windows=[]
        for indices in masks:
            subset=tuple(inventory[i] for i in indices)
            windows.append(fields_of(WorkflowSelectionRequest(key='ft-request-window:'+digest(key+dumps(subset)),accessible=subset,**common)))
    formation = dict(policy='owned-native-request-v1',actor=actor,selected=key,
        request=None if initial is None else fields_of(initial),
        reason='workflow_content_bound_exceeded' if initial is None else 'ready_for_native_comparison',
        rejected=[],content=tuple(inventory))
    require(formation==o['original_formation'] and windows==o['requests'], 'old request windows unchanged')
    names = ('stock','tool','repair_stock','procedure','peer','group') if setting=='canonical' else ('stock','relation','procedure','peer','group')
    values = {n:{} for n in names}; groups={}
    for p in view.snapshot.particulars: groups.setdefault(p.source,[]).append(p)
    def evidence(ps):return tuple(sorted({(p.source,p.address.delivery,p.address.key) for p in ps},key=dumps))
    def attrs(ps):
        out={}
        for p in ps:
            require(p.address.key not in out or (type(out[p.address.key]) is type(p.value) and out[p.address.key]==p.value),'consistent fields')
            out[p.address.key]=p.value
        return out
    def add(role,value,ps):
        if role=='peer' and value==actor:return
        if setting=='canonical' and type(value) is ObjectRef:
            value=max((p.source for p in view.lookup(subject=value.identity) if p.source.identity==value.identity),key=lambda x:x.revision,default=value)
        values[role].setdefault(value,set()).update(evidence(ps))
    supports=[]
    for ref in sorted(groups,key=dumps):
        ps=tuple(groups[ref]); fields=attrs(ps)
        if type(fields.get('quantity')) is int and type(fields.get('owner')) is ObjectId and type(fields.get('custodian')) is ObjectId:
            supports.append(dict(kind='direct',observed_ref=ref,evidence=evidence(ps)))
        if any(type(p.value) is Procedure for p in ps):add('procedure',ref,ps)
        if setting=='workflow':add('relation',ref,ps)
        records=[(fields,ps)]
        for p in ps:
            if p.address.key!='payload' or type(p.value) is not str:continue
            try:payload=decode(p.value)
            except (ValueError,TypeError):continue
            if type(payload) is dict:
                records.append((payload,(p,)))
                if type(payload.get('members')) is tuple and all(type(x) is ObjectId for x in payload['members']) and type(payload.get('context')) is ObjectRef:
                    add('group',ref,(p,))
        for fields,ps in records:
            for k in ('owner','custodian','actor','partner','speaker','receiver'):
                if type(fields.get(k)) is ObjectId:add('peer',fields[k],ps)
            for k in ('members','participants'):
                if type(fields.get(k)) is tuple:
                    for v in fields[k]:
                        if type(v) is ObjectId:add('peer',v,ps)
    observations=[]
    for receipt in r['receipts']:
        delivery='ft-skill-refresh:'+r['source_native_sha256']+':'+str(receipt['index'])+':delivery'
        ps=tuple(p for p in view.snapshot.particulars if p.address.delivery==delivery); refs={p.source for p in ps}
        require(len(refs)==1,'one observation source');ref=next(iter(refs));fields=attrs(ps)
        reads=[x for x in view.snapshot.receipts if x.actor==actor and x.operation=='read' and x.work_key==delivery
            and x.inputs==(ref,) and x.required==x.completed==x.spent==2]
        require(len(reads)==1 and fields.get('actor')==actor and fields.get('context')==r['context'] and
            fields.get('primitive')=='inspect' and fields.get('outcome')=='succeeded' and type(fields.get('target')) is ObjectRef and
            type(fields.get('owner')) is ObjectId and type(fields.get('custodian')) is ObjectId,'paid explicit material observation')
        observations.append(dict(source=ref,target=fields['target'],facts=fields,evidence=evidence(ps),receipt=reads[0].ref))
        supports.append(dict(kind='observation',observed_ref=fields['target'],evidence=evidence(ps)))
    latest={}
    for support in supports:
        ref=support['observed_ref']
        if ref.identity not in latest or ref.revision>latest[ref.identity].revision:latest[ref.identity]=ref
    material={}
    for support in supports:
        ref=support['observed_ref'];ref=latest[ref.identity] if setting=='canonical' else ref
        material.setdefault(ref,{})[dumps(support)]=support
    material_rows=[dict(value=None,supports=())]+[dict(value=ref,supports=tuple(proofs[k] for k in sorted(proofs)))
        for ref,proofs in sorted(material.items(),key=lambda x:dumps(x[0]))]
    pools={}
    for name in names:
        if name in (('stock','tool','repair_stock') if setting=='canonical' else ('stock',)):pools[name]=material_rows
        else:pools[name]=[dict(value=None,evidence=())]+[dict(value=v,evidence=tuple(sorted(proof,key=dumps)))
            for v,proof in sorted(values[name].items(),key=lambda x:dumps(x[0]))]
    radices=(len(windows),)+tuple(len(pools[n]) for n in names)
    return dict(version='ft-changed-input-domain-a6-v1',setting=setting,actor=actor,native_sha256=native_hash,
        view_sha256=digest(view.bytes()),fields_sha256=digest(field_text),old_domain_sha256=digest(old_text),refresh_sha256=digest(refresh_text),
        old_native_sha256=o['native_sha256'],source_sha256=o['source_sha256'],binding_sha256=o['binding_sha256'],intake_sha256=o['intake_sha256'],
        controller_prefix=o['controller_prefix'],fresh_demand=fresh,original_formation=formation,content_inventory=tuple(inventory),
        windows=windows,pools=pools,role_order=names,observations=tuple(sorted(observations,key=dumps)),radices=radices,assignments=prod(radices),
        namespace='ft-changed-a6:'+native_hash+':',coverage='complete-declared-paid-observation-cartesian-grammar',
        declared_domain_complete=True,native_view_probed=False,comparison_paid=False,execution_authorized=False,
        td5_admitted=False,history_choice=False,parent_accepted=False)


def audit_changed_input_domain(view, native_hash, field_text, old_text, refresh_text, setting, text):
    expected=reconstruct(view,native_hash,field_text,old_text,refresh_text,setting)
    require(loads(text)==expected and dumps(loads(text))==text,'exact complete typed domain')
    return dict(passed=True,setting=setting,windows=len(expected['windows']),
        role_sizes={n:len(expected['pools'][n]) for n in expected['role_order']},assignments=expected['assignments'],
        observations=len(expected['observations']),oldest_task_exact=True,controller_prefix_exact=True,
        comparison_paid=False,execution_authorized=False,td5_admitted=False,history_choice=False)
