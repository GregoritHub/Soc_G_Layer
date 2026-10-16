"""Fixed owned discovery panel; native paid inspection/read, no main-task choice."""
from copy import deepcopy
from hashlib import sha256
from hle_unified.operation_records import OperationRequest
from hle_unified.selection_records import dumps, loads


def digest(text): return sha256(text.encode()).hexdigest()

# Exact capacity payloads derived from the registered accepted archive indexes.
# This bounded adapter does not accept caller-authored capacity declarations.
ACCEPTED_CAPACITY=frozenset(('2d5315881624aa63d3420e922a1e5b20afe99f3550901047fac2d2f38201a476',
                           '0889c7bacec30519d432c7cdc71f80ea5d2b5089ca26b32cb2cc4d329185d8d0'))


def inventory(view):
    identities={p.source.identity for p in view.snapshot.particulars
                if p.category=='name' or (p.address.key=='quantity' and type(p.value) is int)}
    if len(identities)>128: raise ValueError('registered inventory bound exceeded')
    return tuple(sorted((max((p.source for p in view.snapshot.particulars if p.source.identity==i),
                             key=lambda r:r.revision) for i in identities),key=dumps))


class OwnedMaterialInspection:
    VERSION='ft-owned-material-inspection-a1-v1'

    def __init__(self,engine,capacity):
        if digest(capacity) not in ACCEPTED_CAPACITY: raise ValueError('registered exact capacity required')
        c=loads(capacity); native=engine.checkpoint()
        if c['native_sha256']!=digest(native) or not c['comparison_settled']:
            raise ValueError('exact settled accepted capacity pairing required')
        self.actor=c['actor']; self.context=c['required']['context']; self.task=c['preparation']['task']
        if self.actor in engine._locks: raise ValueError('unlocked actor required')
        self.source_native_sha256=digest(native); self.capacity_sha256=digest(capacity)
        self.expected_native_sha256=digest(native); self.start_count=len(engine.world.journal())
        self.plan=inventory(engine.participant_view(self.actor)); self.index=0
        self.phase='inspect' if self.plan else 'complete'; self.events=[]; self.receipts=[]
        self.main_execution_authorized=False; self.comparison_paid=False
        self.td5_admitted=False; self.history_choice=False; self.skill_acquired=False

    def key(self): return 'ft-skill-inspect:'+self.source_native_sha256+':'+str(self.index)

    def step(self,engine,*,work_limit=1,cancel=False):
        if type(work_limit) is not int or work_limit<1 or type(cancel) is not bool:
            raise ValueError('positive exact work bound required')
        if digest(engine.checkpoint())!=self.expected_native_sha256:
            raise ValueError('unrelated native extension')
        if self.phase in ('complete','cancelled'):
            return deepcopy(self.events[-1]) if self.events else None
        phase=self.phase; index=self.index; key=self.key()+(':'+phase)
        cid=key+':step:'+str(len(self.events)); actor=self.actor
        before=len(engine.world.journal()); wallet=dict(engine.wallet(actor)); rejection=None
        if cancel:
            if (actor,key) not in engine._jobs: raise ValueError('existing partial work required')
            engine.cancel(cid+':cancel',actor,key); self.phase='cancelled'
        else:
            if (actor,key) not in engine._jobs:
                if phase=='inspect':
                    target=self.plan[index]; v=engine.participant_view(actor)
                    request=OperationRequest(key,actor,'inspect',self.context,target=target,
                                             evidence=tuple(p.address for p in v.resolve(target)))
                    try: engine.start(cid+':start',request)
                    except ValueError as error:
                        if str(error)!='material input role required' or len(engine.world.journal())!=before:
                            raise
                        rejection=str(error); self.index+=1
                else:
                    event=engine.job_status(actor,self.key()+':inspect')['result']
                    delivery=self.key()+':delivery'
                    engine.deliver_event(delivery,event,actor)
                    engine.start(cid+':start',OperationRequest(key,actor,'read',self.context,delivery=delivery))
            if rejection is None:
                status=engine.job_status(actor,key)['status']
                if status not in ('succeeded','failed','cancelled','ready'):
                    engine.advance(cid+':work',actor,key,work_limit)
                if engine.job_status(actor,key)['status']=='ready': engine.commit(cid+':commit',actor,key)
                status=engine.job_status(actor,key)['status']
                if status in ('failed','cancelled'): raise ValueError('unexpected terminal native inspection failure')
                if status=='succeeded':
                    if phase=='inspect': self.phase='read'
                    else:
                        self.receipts.append(dict(index=index,inspect_job=self.key()+':inspect',read_job=key))
                        self.index+=1; self.phase='inspect'
        if self.index==len(self.plan): self.phase='complete'
        after_wallet=dict(engine.wallet(actor))
        row=dict(index=len(self.events),item=index,phase=phase,action='cancel' if cancel else 'step',
                 before=before,after=len(engine.world.journal()),job=key,work_limit=work_limit,
                 rejection=rejection,status='rejected' if rejection else engine.job_status(actor,key)['status'],
                 wallet_before=wallet,wallet_after=after_wallet,
                 debit={u:wallet[u]-after_wallet[u] for u in ('energy','time')})
        self.events.append(row); self.expected_native_sha256=digest(engine.checkpoint())
        return deepcopy(row)

    def checkpoint(self,engine):
        if digest(engine.checkpoint())!=self.expected_native_sha256: raise ValueError('native pairing')
        return dumps(dict(version=self.VERSION,**deepcopy(self.__dict__)))

    @classmethod
    def restore(cls,text,engine,original,capacity):
        from .owned_material_inspection_audit import audit_owned_material_inspection
        audit_owned_material_inspection(engine,original,capacity,text)
        data=loads(text); data.pop('version'); obj=cls.__new__(cls); obj.__dict__.update(data)
        if obj.checkpoint(engine)!=text: raise ValueError('adapter roundtrip')
        return obj
