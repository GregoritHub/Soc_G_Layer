"""A12E1 current paid-observation grammar after accepted cue processing."""
import json
from hashlib import sha256
from itertools import combinations
from math import prod
from pathlib import Path
from hle_unified.records import ObjectId,ObjectRef
from hle_unified.selection_records import SelectionRequest,dumps,loads,fields_of
from hle_unified.workflow_selection_records import WorkflowSelectionRequest,WorkflowCapacitySelectionRequest
from .demand_controller import IntegratedDemandController
from .demand_requests import form_request
from .owned_role_domain import paid_pools

VERSION='ft-post-processing-domain-a12e1-v1'
ROOT=Path(__file__).resolve().parents[1]
PROTOCOL=ROOT/'contracts/ft/FT7_Post_Processing_Domain_A12E1_Protocol_v1.json'
SOURCE=ROOT/'contracts/ft/FT7_Cue_Processing_Panel_A12D2_Protocol_v1.json'
def digest(value):return sha256(value.encode() if isinstance(value,str) else value).hexdigest()
def coordinates(ordinal,radices):
    if type(ordinal) is not int or any(type(n) is not int or n<1 for n in radices):raise ValueError('exact integer index and positive radices')
    if not 0<=ordinal<prod(radices):raise ValueError('ordinal outside complete product')
    out=[]
    for n in reversed(radices):ordinal,d=divmod(ordinal,n);out.append(d)
    return tuple(reversed(out))
def ordinal_of(digits,radices):
    if len(digits)!=len(radices):raise ValueError('factor arity')
    out=0
    for d,n in zip(digits,radices):
        if type(d) is not int or type(n) is not int or n<1 or not 0<=d<n:raise ValueError('factor coordinate')
        out=out*n+d
    return out
def _fields(rows):
    result={}
    for p in rows:
        if p.address.key in result and (type(result[p.address.key]) is not type(p.value) or result[p.address.key]!=p.value):raise ValueError('conflicting explicit fields')
        result[p.address.key]=p.value
    return result
def _materials(view,setting,actor,context):
    grouped={}
    for p in view.snapshot.particulars:grouped.setdefault(p.source,[]).append(p)
    def proof(rows):return tuple(sorted({(p.source,p.address.delivery,p.address.key) for p in rows},key=dumps))
    supports=[];observations=[]
    for ref,rows in grouped.items():
        f=_fields(rows)
        if type(f.get('quantity')) is int and type(f.get('owner')) is ObjectId and type(f.get('custodian')) is ObjectId:
            supports.append(dict(kind='direct',observed_ref=ref,evidence=proof(rows)))
        deliveries={p.address.delivery for p in rows}
        reads=[r for r in view.snapshot.receipts if r.actor==actor and r.operation=='read' and r.inputs==(ref,)
            and r.required==r.completed==r.spent==2 and r.work_key in deliveries]
        if (f.get('actor')==actor and f.get('context')==context and f.get('primitive')=='inspect' and f.get('outcome')=='succeeded'
                and type(f.get('target')) is ObjectRef and type(f.get('owner')) is ObjectId and type(f.get('custodian')) is ObjectId and len(reads)==1):
            row=dict(source=ref,target=f['target'],facts=f,evidence=proof(rows),receipt=reads[0].ref)
            observations.append(row);supports.append(dict(kind='observation',observed_ref=f['target'],evidence=row['evidence']))
    latest={}
    for s in supports:
        r=s['observed_ref']
        if r.identity not in latest or r.revision>latest[r.identity].revision:latest[r.identity]=r
    found={}
    for s in supports:
        r=s['observed_ref'];r=latest[r.identity] if setting=='canonical' else r
        found.setdefault(r,{})[dumps(s)]=s
    rows=[dict(value=None,supports=())]+[dict(value=r,supports=tuple(v[k] for k in sorted(v))) for r,v in sorted(found.items(),key=lambda x:dumps(x[0]))]
    return tuple(sorted(observations,key=dumps)),rows
def post_processing_domain(view,native,adapter,windows,setting,mask):
    p=json.loads(PROTOCOL.read_text());entry=p['inputs'].get(f'{setting}-{mask:02d}');source=json.loads(SOURCE.read_text())['inputs'].get(f'{setting}-{mask:02d}')
    if entry is None or source is None or (digest(native),digest(adapter))!=(entry['native_sha256'],entry['adapter_sha256']) or digest(windows)!=source['windows_sha256']:
        raise ValueError('exact registered current/source binding required')
    a=loads(adapter);w=loads(windows);actor=w['actor']
    if (a['actor'],a['setting'],a['phase'],a['index'])!=(actor,setting,'complete',3) or a['task']!=w['fresh_demand']['binding'] or a['controller_prefix']!=w['controller_prefix'] or a['reserve']!=w['reserve'] or a['history']!=w['history']:
        raise ValueError('complete processing and immutable task prefixes required')
    if mask==1:
        if a['version']!='ft-owned-cue-processing-a12d-v1':raise ValueError('legacy v1 provenance')
    elif a.get('version')!='ft-owned-cue-processing-panel-a12d2-v2' or a.get('source_mask')!=mask:raise ValueError('v2 mask provenance')
    if view.snapshot.actor!=actor:raise ValueError('owned actor')
    fresh=w['fresh_demand'];controller=IntegratedDemandController.restore(w['controller_prefix']);demands=controller.effective_demands();key=dumps((actor,fresh['binding']))
    if key in demands:raise ValueError('fresh task already registered')
    demands[key]=fresh;request,formation=form_request(view,demands)
    if formation!=w['original_formation'] or formation['selected']!=key:raise ValueError('unchanged oldest current task')
    inventory=tuple(formation['content'])
    if setting=='canonical':current=[fields_of(request)]
    else:
        current=[fields_of(WorkflowSelectionRequest(key='ft-cue-window:'+digest(key+dumps(subset)),actor=actor,context=fresh['context'],cue=fresh['cue'],target=fresh['target'],demand=fresh['binding'],accessible=subset))
            for size in range(1,min(8,len(inventory))+1) for subset in combinations(inventory,size)]
    if current!=w['requests']:raise ValueError('current request windows changed')
    pools=paid_pools(view,setting);observations,materials=_materials(view,setting,actor,fresh['context'])
    for name in (('stock','tool','repair_stock') if setting=='canonical' else ('stock',)):pools[name]=materials
    names=tuple(pools);radices=(len(current),)+tuple(len(pools[n]) for n in names)
    return dumps(dict(version=VERSION,setting=setting,mask=mask,actor=actor,current_native_sha256=digest(native),adapter_sha256=digest(adapter),
        source_windows_sha256=digest(windows),view_sha256=digest(view.bytes()),controller_prefix=w['controller_prefix'],reserve=w['reserve'],history=w['history'],
        fresh_demand=fresh,original_formation=formation,content_inventory=inventory,windows=current,pools=pools,role_order=names,observations=observations,
        radices=radices,assignments=prod(radices),namespace=f'ft-post-processing-a12e1:{setting}:{mask:02d}:'+digest(native)+':',
        coverage='complete-current-explicit-paid-observation-cartesian-grammar',declared_domain_complete=True,native_work=False,engine_restored=False,
        comparison_paid=False,execution_authorized=False,td5_admitted=False,history_choice=False,parent_accepted=False))
def request_at(text,ordinal):
    d=loads(text)
    if d.get('version')!=VERSION:raise ValueError('A12E1 schema required')
    names=d['role_order'];radices=(len(d['windows']),)+tuple(len(d['pools'][n]) for n in names)
    if radices!=d['radices'] or prod(radices)!=d['assignments']:raise ValueError('factor sizes')
    ds=coordinates(ordinal,radices);fields=dict(d['windows'][ds[0]]);fields.update((n,d['pools'][n][x]['value']) for n,x in zip(names,ds[1:]));fields['key']=d['namespace']+str(ordinal)
    if d['setting']=='canonical':return SelectionRequest(**fields)
    if fields.get('procedure') is not None:return WorkflowCapacitySelectionRequest(**fields)
    fields.pop('procedure',None);return WorkflowSelectionRequest(**fields)
