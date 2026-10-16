"""Independent saved-panel reconstruction without importing the generator."""
import json
from functools import lru_cache
from hashlib import sha256
from pathlib import Path
from hle_unified.compact import unseal
from hle_unified.operations import NativeAccess
from hle_unified.selection_records import loads,dumps
from hle_unified.self_content import decode,encode

@lru_cache(maxsize=2)
def expected(native,source,binding,setting):
    p=json.loads((Path(__file__).resolve().parents[1]/'contracts/ft/FT7_Observed_Cue_Panel_A12A_Protocol_v1.json').read_text())
    wanted=p['inputs'].get(setting)
    if wanted is None or [sha256(v.encode()).hexdigest() for v in (native,source,binding)]!=[wanted[k] for k in ('native','source','binding')]:raise ValueError('input binding')
    s,b=loads(source),loads(binding);a=NativeAccess.restore(unseal(native,loads(native)['schema'])['access']);before=a.checkpoint();v=a.view(s['actor'])
    if s['phase']!='complete' or s['setting']!=setting:raise ValueError('completed setting')
    controller=loads(s['demand_controller']);ledger=loads(controller['ledger']);needs=[]
    for owned in v._heads.values():
        if owned.endorsement.value in ('retracted','disputed') or not any(x.relation in ('c6.need','c7ws.need') for x in owned.content):continue
        key=dumps((s['actor'],owned.ref))
        if key not in ledger['demands'] or key not in controller['outcomes']:raise ValueError('missing fulfilled original need')
        needs.append(owned.ref)
    task=v._bindings[s['request']['fields']['demand']];pool={}
    for item in v.snapshot.particulars:
        if item.source.identity.namespace=='u5.reference' and item.category=='name' and item.path==('label',):
            refs=tuple(r.ref for r in v.snapshot.receipts if r.operation=='read' and r.work_key==item.address.delivery and r.actor==s['actor'] and r.completed==r.required and r.spent>=r.required)
            if refs:pool.setdefault(item.source,[]).append(((item.address.delivery,item.address.key),refs))
    cues=tuple(sorted(pool,key=dumps))
    if task.cue not in cues:raise ValueError('original paid cue')
    rows=[]
    for cue in cues:
        for mask in range(1,16):
            data=decode(task.content[0].object);data['weights' if setting=='canonical' else 'priorities']=tuple(10*((mask>>i)&1) for i in range(4))
            rows.append(dict(cue=cue,mask=mask,payload=encode(data),historical_only=cue==task.cue,intake_paid=False))
    if a.checkpoint()!=before:raise ValueError('mutation')
    return dumps(dict(version='ft-observed-cue-panel-a12a-v1',setting=setting,inputs=wanted,actor=s['actor'],original_task=task.ref,context=task.context,target=task.target,original_cue=task.cue,fulfilled_needs=tuple(needs),cue_evidence=tuple((c,tuple(pool[c])) for c in cues),cues=cues,masks=tuple(range(1,16)),rows=tuple(rows),reserve=b['reserve'],history=b['history'],controller_prefix=s['demand_controller'],intake_paid=False,comparison_paid=False,execution_authorized=False,td5_admitted=False,history_choice=False,source_unchanged=True))

def audit(native,source,binding,setting,report):
    if report!=expected(native,source,binding,setting):raise ValueError('independent complete panel mismatch')
    d=loads(report)
    return dict(passed=True,setting=setting,cues=len(d['cues']),descriptors=len(d['rows']),historical=sum(r['historical_only'] for r in d['rows']),new_unpaid=sum(not r['historical_only'] for r in d['rows']),fulfilled_needs=len(d['fulfilled_needs']))
