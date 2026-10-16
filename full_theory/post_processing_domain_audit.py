"""Independent A12E1 reconstruction; no planner, selector or executor imports."""
import json
from hashlib import sha256
from itertools import combinations
from math import prod
from pathlib import Path
from hle_unified.records import ObjectId,ObjectRef,Procedure
from hle_unified.selection_records import SelectionRequest,dumps,loads,fields_of,demand_value
from hle_unified.workflow_selection_records import WorkflowSelectionRequest,demand_value as workflow_need
from hle_unified.self_content import decode
ROOT=Path(__file__).resolve().parents[1]
def digest(v):return sha256(v.encode() if isinstance(v,str) else v).hexdigest()
def require(ok,why):
    if not ok:raise ValueError('post-processing domain audit: '+why)
def _attrs(rows):
    out={}
    for p in rows:
        require(p.address.key not in out or (type(out[p.address.key]) is type(p.value) and out[p.address.key]==p.value),'consistent explicit fields')
        out[p.address.key]=p.value
    return out
def reconstruct(view,native,adapter,windows,setting,mask):
    protocol=json.loads((ROOT/'contracts/ft/FT7_Post_Processing_Domain_A12E1_Protocol_v1.json').read_text())
    source=json.loads((ROOT/'contracts/ft/FT7_Cue_Processing_Panel_A12D2_Protocol_v1.json').read_text())
    e=protocol['inputs'].get(f'{setting}-{mask:02d}');s=source['inputs'].get(f'{setting}-{mask:02d}')
    require(e is not None and s is not None,'registered branch')
    require((digest(native),digest(adapter),digest(windows))==(e['native_sha256'],e['adapter_sha256'],s['windows_sha256']),'exact current/source identities')
    a=loads(adapter);w=loads(windows);actor=w['actor'];fresh=w['fresh_demand']
    require((a['actor'],a['setting'],a['phase'],a['index'],a['task'])==(actor,setting,'complete',3,fresh['binding']),'complete processing')
    require((a['controller_prefix'],a['reserve'],a['history'])==(w['controller_prefix'],w['reserve'],w['history']),'immutable prefixes')
    require((mask==1 and a['version']=='ft-owned-cue-processing-a12d-v1') or (mask>1 and a.get('version')=='ft-owned-cue-processing-panel-a12d2-v2' and a.get('source_mask')==mask),'version provenance')
    require(view.snapshot.actor==actor,'owned actor');heads={}
    for b in view.snapshot.bindings:
        if b.actor==actor and (b.ref.identity not in heads or b.ref.revision>heads[b.ref.identity].ref.revision):heads[b.ref.identity]=b
    b=heads.get(fresh['binding'].identity);require(b is not None and b.ref==fresh['binding'] and b.endorsement.value not in ('retracted','disputed'),'current task binding')
    paid=view.receipt(b.receipt);require(paid is not None and paid.actor==actor and paid.operation=='bind' and paid.complete and paid.spent==paid.required==3,'paid current task')
    c=loads(w['controller_prefix']);ledger=loads(c['ledger']);key=dumps((actor,b.ref));require(key not in ledger['demands'],'fresh demand')
    for x in heads.values():
        if x.ref!=b.ref and x.endorsement.value not in ('retracted','disputed') and any(p.relation in ('c6.need','c7ws.need') for p in x.content):
            old=dumps((actor,x.ref));require(old in ledger['demands'] and old in c['outcomes'],'no older unresolved need bypass')
    expected_fresh=dict(actor=actor,binding=b.ref,receipt=b.receipt,context=b.context,cue=b.cue,target=b.target,relation=b.content[0].relation,
        payload=(demand_value if setting=='canonical' else workflow_need)(decode(b.content[0].object)),raw_payload=b.content[0].object,
        first_seen=ledger['turn'],admitted_at=ledger['turn'],status='pending',reason=None)
    require(fresh==expected_fresh,'unchanged demand')
    inventory=[]
    if setting=='workflow':
        for x in heads.values():
            r=view.receipt(x.receipt)
            if x.endorsement.value not in ('retracted','disputed') and len(x.content)==1 and x.content[0].relation=='c7w.data' and (x.context,x.cue,x.target)==(b.context,b.cue,b.target) and r is not None and r.complete and r.actor==actor and r.spent>=r.required:inventory.append(x.ref)
        inventory.sort(key=dumps);require(1<=len(inventory)<=16,'bounded paid workflow inventory')
    common=dict(actor=actor,context=b.context,cue=b.cue,target=b.target,demand=b.ref);initial_key='ft-request:'+digest(key)
    if setting=='canonical':
        initial=SelectionRequest(key=initial_key,**common);request_rows=[fields_of(initial)]
    else:
        initial=WorkflowSelectionRequest(key=initial_key,accessible=tuple(inventory),**common) if len(inventory)<=8 else None
        request_rows=[fields_of(WorkflowSelectionRequest(key='ft-cue-window:'+digest(key+dumps(sub)),accessible=sub,**common))
            for size in range(1,min(8,len(inventory))+1) for sub in combinations(inventory,size)]
    formation=dict(policy='owned-native-request-v1',actor=actor,selected=key,request=None if initial is None else fields_of(initial),
        reason='workflow_content_bound_exceeded' if initial is None else 'ready_for_native_comparison',rejected=[],content=tuple(inventory))
    require(formation==w['original_formation'] and request_rows==w['requests'],'current windows and oldest formation')
    names=('stock','tool','repair_stock','procedure','peer','group') if setting=='canonical' else ('stock','relation','procedure','peer','group')
    values={n:{} for n in names};groups={}
    for p in view.snapshot.particulars:groups.setdefault(p.source,[]).append(p)
    def evidence(rows):return tuple(sorted({(p.source,p.address.delivery,p.address.key) for p in rows},key=dumps))
    def add(role,value,rows):
        if role=='peer' and value==actor:return
        if setting=='canonical' and type(value) is ObjectRef:
            value=max((p.source for p in view.lookup(subject=value.identity) if p.source.identity==value.identity),key=lambda x:x.revision,default=value)
        values[role].setdefault(value,set()).update(evidence(rows))
    supports=[];observations=[]
    for ref,rows in sorted(groups.items(),key=lambda x:dumps(x[0])):
        f=_attrs(rows)
        if type(f.get('quantity')) is int and type(f.get('owner')) is ObjectId and type(f.get('custodian')) is ObjectId:supports.append(dict(kind='direct',observed_ref=ref,evidence=evidence(rows)))
        if any(type(p.value) is Procedure for p in rows):add('procedure',ref,rows)
        if setting=='workflow':add('relation',ref,rows)
        records=[(f,rows)]
        for p in rows:
            if p.address.key!='payload' or type(p.value) is not str:continue
            try:d=decode(p.value)
            except (TypeError,ValueError):continue
            if type(d) is dict:
                records.append((d,(p,)))
                if type(d.get('members')) is tuple and all(type(x) is ObjectId for x in d['members']) and type(d.get('context')) is ObjectRef:add('group',ref,(p,))
        for d,proof in records:
            for field in ('owner','custodian','actor','partner','speaker','receiver'):
                if type(d.get(field)) is ObjectId:add('peer',d[field],proof)
            for field in ('members','participants'):
                if type(d.get(field)) is tuple:
                    for person in d[field]:
                        if type(person) is ObjectId:add('peer',person,proof)
        deliveries={p.address.delivery for p in rows};reads=[r for r in view.snapshot.receipts if r.actor==actor and r.operation=='read' and r.inputs==(ref,) and r.required==r.completed==r.spent==2 and r.work_key in deliveries]
        if (f.get('actor')==actor and f.get('context')==b.context and f.get('primitive')=='inspect' and f.get('outcome')=='succeeded' and type(f.get('target')) is ObjectRef
                and type(f.get('owner')) is ObjectId and type(f.get('custodian')) is ObjectId and len(reads)==1):
            row=dict(source=ref,target=f['target'],facts=f,evidence=evidence(rows),receipt=reads[0].ref);observations.append(row);supports.append(dict(kind='observation',observed_ref=f['target'],evidence=row['evidence']))
    latest={}
    for srow in supports:
        r=srow['observed_ref']
        if r.identity not in latest or r.revision>latest[r.identity].revision:latest[r.identity]=r
    material={}
    for srow in supports:
        r=srow['observed_ref'];r=latest[r.identity] if setting=='canonical' else r
        material.setdefault(r,{})[dumps(srow)]=srow
    material_rows=[dict(value=None,supports=())]+[dict(value=r,supports=tuple(v[k] for k in sorted(v))) for r,v in sorted(material.items(),key=lambda x:dumps(x[0]))]
    pools={}
    for name in names:
        if name in (('stock','tool','repair_stock') if setting=='canonical' else ('stock',)):pools[name]=material_rows
        else:pools[name]=[dict(value=None,evidence=())]+[dict(value=v,evidence=tuple(sorted(proof,key=dumps))) for v,proof in sorted(values[name].items(),key=lambda x:dumps(x[0]))]
    radices=(len(request_rows),)+tuple(len(pools[n]) for n in names)
    return dict(version='ft-post-processing-domain-a12e1-v1',setting=setting,mask=mask,actor=actor,current_native_sha256=digest(native),adapter_sha256=digest(adapter),
        source_windows_sha256=digest(windows),view_sha256=digest(view.bytes()),controller_prefix=w['controller_prefix'],reserve=w['reserve'],history=w['history'],
        fresh_demand=fresh,original_formation=formation,content_inventory=tuple(inventory),windows=request_rows,pools=pools,role_order=names,
        observations=tuple(sorted(observations,key=dumps)),radices=radices,assignments=prod(radices),
        namespace=f'ft-post-processing-a12e1:{setting}:{mask:02d}:'+digest(native)+':',coverage='complete-current-explicit-paid-observation-cartesian-grammar',
        declared_domain_complete=True,native_work=False,engine_restored=False,comparison_paid=False,execution_authorized=False,td5_admitted=False,history_choice=False,parent_accepted=False)
def audit_post_processing_domain(view,native,adapter,windows,setting,mask,text):
    expected=reconstruct(view,native,adapter,windows,setting,mask)
    require(loads(text)==expected and dumps(loads(text))==text,'exact complete typed report')
    return dict(passed=True,setting=setting,mask=mask,windows=len(expected['windows']),role_sizes={n:len(expected['pools'][n]) for n in expected['role_order']},
        assignments=expected['assignments'],observations=len(expected['observations']),oldest_task_exact=True,prefixes_exact=True,native_work=False,engine_restored=False,
        comparison_paid=False,execution_authorized=False,td5_admitted=False,history_choice=False)
