"""Bounded auxiliary owned-content rehearsal; no main-demand settlement."""
import json
from copy import deepcopy
from hashlib import sha256
from pathlib import Path
from hle_unified.crossing_records import CrossingRequest
from hle_unified.workflow_records import WorkflowRequest
from hle_unified.selection_records import loads,dumps
from hle_unified.self_content import decode

PROTOCOL=Path(__file__).resolve().parents[1]/'contracts/ft/FT7_Owned_Rehearsal_A10_Protocol_v1.json'
def digest(text): return sha256(text.encode()).hexdigest()

def owned_plan(view,actor,context,setting):
    kinds=({'intention':'personal','personal_policy':'personal','model':'system','rule':'system'}
           if setting=='canonical' else {'intention':'personal','personal':'personal','system':'system','rule':'system'})
    rows=[]
    for b in view._heads.values():
        receipt=view.receipt(b.receipt)
        if (b.actor!=actor or b.context!=context or b.endorsement.value in ('retracted','disputed')
            or len(b.content)!=1 or b.content[0].relation!=('c3.data' if setting=='canonical' else 'c7w.data')
            or receipt is None or receipt.actor!=actor or receipt.operation!='bind' or not receipt.complete
            or receipt.spent<receipt.required or not view.resolve(b.target)):continue
        try:kind=decode(b.content[0].object).get('kind')
        except (ValueError,TypeError):continue
        if kind not in kinds:continue
        rows.append(dict(source=b.ref,target=b.target,context=b.context,cue=b.cue,kind=kind,
                         recipe=('use-' if setting=='canonical' else 'workflow-use-')+kinds[kind]+'-v1',
                         evidence=tuple((p.address.delivery,p.address.key) for p in view.resolve(b.target))))
    if len(rows)>32:raise ValueError('registered candidate bound')
    return tuple(sorted(rows,key=lambda r:dumps(r['source'])))

class OwnedContentRehearsal:
    VERSION='ft-owned-content-rehearsal-a10-v1'
    def __init__(self,engine,adapter,setting):
        native=engine.checkpoint();entry=json.loads(PROTOCOL.read_text())['inputs'].get(setting)
        if entry is None or digest(native)!=entry['native_sha256'] or digest(adapter)!=entry['adapter_sha256']:
            raise ValueError('exact accepted A5 pairing')
        a=loads(adapter)
        if a['phase']!='complete' or a['expected_native_sha256']!=digest(native) or a['actor'] in engine._locks:
            raise ValueError('completed unlocked A5 input')
        self.actor=a['actor'];self.context=a['context'];self.setting=setting
        self.source_native_sha256=digest(native);self.adapter_sha256=digest(adapter)
        self.expected_native_sha256=digest(native);self.start_count=len(engine.world.journal())
        self.plan=owned_plan(engine.participant_view(self.actor),self.actor,self.context,setting)
        self.index=0;self.phase='rehearse' if self.plan else 'complete';self.events=[];self.results=[]
        self.main_execution_authorized=False;self.comparison_paid=False;self.td5_admitted=False
        self.history_choice=False;self.skill_acquired=False;self.independent_credit=False

    def step(self,engine,*,work_limit=1,cancel=False):
        from hle_unified.particulars import DetailAddress
        if type(work_limit) is not int or work_limit<1 or type(cancel) is not bool:raise ValueError('exact work bound')
        if digest(engine.checkpoint())!=self.expected_native_sha256:raise ValueError('native pairing')
        if self.phase in ('complete','cancelled'):return None
        item=self.index;row=self.plan[item];key='ft-rehearsal-a10:'+self.source_native_sha256+':'+str(item)
        cid=key+':step:'+str(len(self.events));before=len(engine.world.journal());wallet=dict(engine.wallet(self.actor))
        if cancel:
            if (self.actor,key) not in engine._jobs:raise ValueError('existing partial work required')
            engine.cancel(cid+':cancel',self.actor,key);self.phase='cancelled'
        else:
            if (self.actor,key) not in engine._jobs:
                typ=CrossingRequest if self.setting=='canonical' else WorkflowRequest
                request=typ(key,self.actor,row['recipe'],row['context'],row['cue'],(row['source'],),
                            tuple(DetailAddress(*x) for x in row['evidence']),row['target'])
                engine.start(cid+':start',request)
            status=engine.job_status(self.actor,key)['status']
            if status not in ('ready','succeeded','failed','cancelled'):
                engine.advance(cid+':work',self.actor,key,work_limit)
            if engine.job_status(self.actor,key)['status']=='ready':engine.commit(cid+':commit',self.actor,key)
            status=engine.job_status(self.actor,key)['status']
            if status in ('succeeded','failed','cancelled'):
                self.results.append(dict(item=item,job=key,status=status));self.index+=1
                if self.index==len(self.plan):self.phase='complete'
        after=dict(engine.wallet(self.actor))
        self.events.append(dict(index=len(self.events),item=item,action='cancel' if cancel else 'step',
            before=before,after=len(engine.world.journal()),job=key,work_limit=work_limit,
            status=engine.job_status(self.actor,key)['status'],wallet_before=wallet,wallet_after=after,
            debit={u:wallet[u]-after[u] for u in ('energy','time')}))
        self.expected_native_sha256=digest(engine.checkpoint())
        return deepcopy(self.events[-1])

    def checkpoint(self,engine):
        if digest(engine.checkpoint())!=self.expected_native_sha256:raise ValueError('native pairing')
        return dumps(dict(version=self.VERSION,**deepcopy(self.__dict__)))

    @classmethod
    def restore(cls,text,engine,original,adapter,setting):
        from .owned_content_rehearsal_audit import audit
        audit(engine,original,adapter,setting,text)
        d=loads(text);d.pop('version');o=cls.__new__(cls);o.__dict__.update(d)
        if o.checkpoint(engine)!=text:raise ValueError('exact restart state')
        return o
