"""A5 paid exact-revision reads, restricted to already owned field paths."""
import json
from copy import deepcopy
from hashlib import sha256
from pathlib import Path
from hle_unified.operation_records import OperationRequest
from hle_unified.particulars import Selector
from hle_unified.selection_records import dumps, loads

PROTOCOL=Path(__file__).resolve().parents[1]/'contracts/ft/FT7_Observed_Fields_A5_Protocol_v1.json'


def digest(text): return sha256(text.encode()).hexdigest()


def field_plan(view, projection):
    targets=sorted({o['target'] for o in projection['observations']},key=dumps)
    if len(targets)>128: raise ValueError('target bound')
    plan=[]
    for target in targets:
        prior=tuple(p for p in view.snapshot.particulars
                    if p.source.identity==target.identity and p.source.revision<=target.revision)
        if not prior: continue
        revision=max(p.source.revision for p in prior)
        details=tuple(p for p in prior if p.source.revision==revision)
        descriptors={}
        for p in details:
            descriptor=(p.address.key,p.category,p.path)
            if p.address.key in descriptors and descriptors[p.address.key]!=descriptor:
                raise ValueError('ambiguous known field path')
            descriptors[p.address.key]=descriptor
        known={(p.address.key,p.category,p.path) for p in view.resolve(target)}
        missing=tuple(sorted(set(descriptors.values())-known,key=dumps))
        if len(missing)>128: raise ValueError('selector bound')
        if missing:
            evidence=tuple(sorted({(p.source,p.address.delivery,p.address.key) for p in details
                                   if (p.address.key,p.category,p.path) in missing},key=dumps))
            plan.append(dict(target=target,selectors=missing,evidence=evidence))
    return tuple(plan)


class ObservedFieldReads:
    VERSION='ft-observed-field-reads-a5-v1'

    def __init__(self,engine,refresh,projection,setting):
        inputs=json.loads(PROTOCOL.read_text())['inputs']; entry=inputs.get(setting)
        native=engine.checkpoint()
        if entry is None or any(digest(text)!=entry[key] for text,key in
                ((native,'native_sha256'),(refresh,'refresh_sha256'),(projection,'projection_sha256'))):
            raise ValueError('exact accepted A3/A4 identity')
        c=loads(refresh); p=loads(projection); self.actor=c['actor']; self.context=c['context']
        view=engine.participant_view(self.actor)
        if digest(view.bytes())!=entry['view_sha256'] or self.actor in engine._locks:
            raise ValueError('exact unlocked input view')
        self.setting=setting; self.source_native_sha256=digest(native)
        self.refresh_sha256=digest(refresh); self.projection_sha256=digest(projection)
        self.expected_native_sha256=digest(native); self.start_count=len(engine.world.journal())
        self.plan=field_plan(view,p); self.index=0; self.phase='read' if self.plan else 'complete'
        self.events=[]; self.receipts=[]
        self.main_execution_authorized=False; self.comparison_paid=False
        self.td5_admitted=False; self.history_choice=False; self.skill_acquired=False

    def key(self): return 'ft-observed-fields-a5:'+self.source_native_sha256+':'+str(self.index)

    def step(self,engine,*,work_limit=1,cancel=False):
        if type(work_limit) is not int or work_limit<1 or type(cancel) is not bool:
            raise ValueError('positive exact work bound required')
        if digest(engine.checkpoint())!=self.expected_native_sha256: raise ValueError('native pairing')
        if self.phase in ('complete','cancelled'): return None
        item=self.index; base=self.key(); key=base+':read'; delivery=base+':delivery'
        cid=key+':step:'+str(len(self.events)); actor=self.actor
        before=len(engine.world.journal()); wallet=dict(engine.wallet(actor))
        if cancel:
            if (actor,key) not in engine._jobs: raise ValueError('existing partial read required')
            engine.cancel(cid+':cancel',actor,key); self.phase='cancelled'
        else:
            if (actor,key) not in engine._jobs:
                row=self.plan[item]
                engine.disclose(delivery,actor,row['target'],tuple(Selector(*x) for x in row['selectors']),row['target'])
                engine.start(cid+':start',OperationRequest(key,actor,'read',self.context,delivery=delivery))
            status=engine.job_status(actor,key)['status']
            if status not in ('succeeded','failed','cancelled','ready'):
                engine.advance(cid+':work',actor,key,work_limit)
            if engine.job_status(actor,key)['status']=='ready': engine.commit(cid+':commit',actor,key)
            status=engine.job_status(actor,key)['status']
            if status in ('failed','cancelled'): raise ValueError('unexpected native read failure')
            if status=='succeeded':
                self.receipts.append(dict(index=item,delivery=delivery,read_job=key))
                self.index+=1
                if self.index==len(self.plan): self.phase='complete'
        after_wallet=dict(engine.wallet(actor))
        self.events.append(dict(index=len(self.events),item=item,action='cancel' if cancel else 'step',
            before=before,after=len(engine.world.journal()),job=key,work_limit=work_limit,
            status=engine.job_status(actor,key)['status'],wallet_before=wallet,wallet_after=after_wallet,
            debit={u:wallet[u]-after_wallet[u] for u in ('energy','time')}))
        self.expected_native_sha256=digest(engine.checkpoint())
        return deepcopy(self.events[-1])

    def checkpoint(self,engine):
        if digest(engine.checkpoint())!=self.expected_native_sha256: raise ValueError('native pairing')
        return dumps(dict(version=self.VERSION,**deepcopy(self.__dict__)))

    @classmethod
    def restore(cls,text,engine,original,refresh,projection,setting):
        from .observed_field_reads_audit import audit_observed_field_reads
        audit_observed_field_reads(engine,original,refresh,projection,setting,text)
        data=loads(text); data.pop('version'); obj=cls.__new__(cls); obj.__dict__.update(data)
        if obj.checkpoint(engine)!=text: raise ValueError('adapter roundtrip')
        return obj
