"""Complete route-free experimental descriptors; never native intake authority."""
import json
from hashlib import sha256
from pathlib import Path
from hle_unified.compact import unseal
from hle_unified.operations import NativeAccess
from hle_unified.selection_records import loads,dumps
from hle_unified.self_content import decode,encode
from .demand_controller import IntegratedDemandController

PROTOCOL=Path(__file__).resolve().parents[1]/'contracts/ft/FT7_Observed_Cue_Panel_A12A_Protocol_v1.json'

def build(native,source,binding,setting):
    p=json.loads(PROTOCOL.read_text());wanted=p['inputs'].get(setting)
    values=(native,source,binding)
    if wanted is None or any(type(v) is not str for v in values) or tuple(sha256(v.encode()).hexdigest() for v in values)!=tuple(wanted[k] for k in ('native','source','binding')):
        raise ValueError('exact fulfilled original triple required')
    s=loads(source);b=loads(binding)
    access=NativeAccess.restore(unseal(native,loads(native)['schema'])['access']);before=access.checkpoint();view=access.view(s['actor'])
    if s['phase']!='complete' or s['setting']!=setting:raise ValueError('fulfilled source')
    effective=IntegratedDemandController.restore(s['demand_controller']).effective_demands();needs=[]
    for owned in view._heads.values():
        if owned.endorsement.value not in ('retracted','disputed') and any(x.relation in ('c6.need','c7ws.need') for x in owned.content):
            key=dumps((s['actor'],owned.ref))
            if effective.get(key,{}).get('status')!='fulfilled':raise ValueError('older unresolved need')
            needs.append(owned.ref)
    old=view._bindings[s['request']['fields']['demand']];evidence={}
    for detail in view.snapshot.particulars:
        if detail.source.identity.namespace!='u5.reference' or detail.category!='name' or detail.path!=('label',):continue
        receipts=tuple(r.ref for r in view.work_receipts('read',detail.address.delivery) if r.actor==s['actor'] and r.complete and r.spent>=r.required)
        if receipts:evidence.setdefault(detail.source,[]).append((detail.address,receipts))
    cues=tuple(sorted(evidence,key=dumps));rows=[]
    if old.cue not in cues:raise ValueError('original cue must be paid and visible')
    for cue in cues:
        for mask in range(1,16):
            payload=decode(old.content[0].object)
            payload['weights' if setting=='canonical' else 'priorities']=tuple(10 if mask&(1<<i) else 0 for i in range(4))
            rows.append(dict(cue=cue,mask=mask,payload=encode(payload),historical_only=cue==old.cue,intake_paid=False))
    if access.checkpoint()!=before:raise ValueError('source mutation')
    return dumps(dict(version='ft-observed-cue-panel-a12a-v1',setting=setting,inputs=wanted,actor=s['actor'],
        original_task=old.ref,context=old.context,target=old.target,original_cue=old.cue,
        fulfilled_needs=tuple(needs),cue_evidence=tuple((c,tuple(evidence[c])) for c in cues),cues=cues,
        masks=tuple(range(1,16)),rows=tuple(rows),reserve=b['reserve'],history=b['history'],controller_prefix=s['demand_controller'],
        intake_paid=False,comparison_paid=False,execution_authorized=False,td5_admitted=False,history_choice=False,source_unchanged=True))
