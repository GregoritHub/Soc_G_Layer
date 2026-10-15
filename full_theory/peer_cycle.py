"""Owned incoming offer drives paid peer production; no supplied reply recipe."""
from copy import deepcopy
from hashlib import sha256
from hle_unified.selection_records import dumps,loads,fields_of
from hle_unified.crossing_records import CrossingRequest
from hle_unified.workflow_records import WorkflowRequest
from hle_unified.self_content import decode
from hle_unified.particulars import DetailAddress
from .packet_channel import PacketChannel
from .content import ContentBridge
from .social_cycle import SocialSupportCycle
from .retention import Demand


class AutonomousPeerCycle:
    VERSION='ft-autonomous-peer-cycle-v1'

    def __init__(self,engine,actor,peer,setting):
        if setting not in ('canonical','workflow') or actor==peer:
            raise ValueError('one exact named setting and distinct owners required')
        self.actor=actor;self.peer=peer;self.setting=setting
        self.channel=PacketChannel(engine,(actor,peer));self.production=ContentBridge(engine)
        self.phase='offer';self.turn=0;self.required=None;self.offer=None
        self.sender_view=None;self.peer_view=None;self.request=None;self.reply=None
        self.social=None;self.events=[];self.terminal=None

    def _discover(self,engine,demand):
        view=engine.participant_view(self.actor);self.sender_view=view.bytes();found=[]
        namespace='c3.message' if self.setting=='canonical' else 'c7w.message'
        for detail in view.lookup(key='payload'):
            if detail.source.identity.namespace!=namespace:continue
            body=decode(detail.value)
            if (body.get('kind'),body.get('speaker'),body.get('receiver'),body.get('context'),body.get('target'))!=('offer',self.actor,self.peer,demand.context,demand.target):continue
            if self.peer not in demand.support_allowed:continue
            for owner,key in sorted(engine._jobs,key=lambda x:dumps(x)):
                if owner!=self.actor:continue
                job=engine.job_status(owner,key)
                if job['status']=='succeeded' and detail.source in tuple(v for k,v in job.items() if k.startswith('public.')):
                    found.append(dict(output=detail.source,operation=engine._jobs[owner,key],key=key))
        if not found:return None
        return min(found,key=lambda row:dumps((row['output'],row['key'])))

    def _form(self,engine,demand):
        view=engine.participant_view(self.peer);self.peer_view=view.bytes()
        receipt=self.channel.bridge.receipts.get('peer-offer')
        if receipt is None or not view.resolve(self.offer['output']):return None
        body=decode(next(p.value for p in view.resolve(self.offer['output']) if p.address.key=='payload'))
        if (body.get('kind'),body.get('speaker'),body.get('receiver'),body.get('context'),body.get('target'))!=('offer',self.actor,self.peer,demand.context,demand.target):return None
        latest={}
        for b in view._bindings.values():
            old=latest.get(b.ref.identity)
            if old is None or b.ref.revision>old.ref.revision:latest[b.ref.identity]=b
        stances=[]
        for b in latest.values():
            if b.actor!=self.peer or b.endorsement.value in ('retracted','disputed') or len(b.content)!=1:continue
            if (b.context,b.cue,b.target)!=(demand.context,demand.cue,demand.target):continue
            if b.content[0].relation!=('c3.data' if self.setting=='canonical' else 'c7w.data'):continue
            r=view.receipt(b.receipt)
            if r is None or not r.complete or r.actor!=self.peer or r.spent<r.required:continue
            own=decode(b.content[0].object)
            if own.get('kind')!=('intention' if self.setting=='canonical' else 'stance'):continue
            stances.append(b.ref)
        if not stances:return None
        own=min(stances,key=dumps)
        evidence=tuple(p.address for p in view.resolve(demand.target))
        if not evidence:return None
        key='ft-peer-reply:'+sha256(dumps((self.peer,self.offer['output'],own)).encode()).hexdigest()
        typ=CrossingRequest if self.setting=='canonical' else WorkflowRequest
        recipe='reply-v1' if self.setting=='canonical' else 'workflow-reply-v1'
        return typ(key,self.peer,recipe,demand.context,demand.cue,(self.offer['output'],own),evidence,demand.target,peer=self.actor,group=body['group'])

    def step(self,engine,historical_state,demand,*,available,work_limit=1):
        if engine is not self.channel.bridge.engine or type(demand) is not Demand or demand.family!=self.setting:
            raise ValueError('exact paired owner and demand required')
        if type(work_limit) is not int or work_limit<1:raise ValueError('positive exact native work bound required')
        if len(set(available))!=len(available) or any(a not in self.channel.participants for a in available):
            raise ValueError('availability cannot introduce another owner')
        if self.required is not None and self.required!=demand.record():raise ValueError('cycle demand cannot change')
        if self.terminal is not None:return deepcopy(self.terminal)
        self.required=demand.record();self.turn+=1;before=len(engine.world.journal())
        intake=None;work=None;social_event=None;reason='waiting'
        if self.phase=='offer':
            if self.actor not in available:reason='sender_unavailable'
            else:
                self.offer=self._discover(engine,demand)
                if self.offer is None:self.phase='deferred';reason='no_owned_scoped_offer'
                else:
                    self.channel.emit('peer-offer',self.actor,self.offer['key'],self.peer,self.offer['output'])
                    self.phase='uptake';reason='offer_queued'
        elif self.phase=='uptake':
            intake=self.channel.step(available=available,work_limit=work_limit)
            reason='pending_paid_offer_uptake'
            if 'peer-offer' in self.channel.bridge.receipts:self.phase='peer';reason='offer_received'
        elif self.phase=='peer':
            if self.peer not in available:reason='peer_unavailable'
            else:
                if self.request is None:self.request=self._form(engine,demand)
                if self.request is None:self.phase='deferred';reason='no_owned_peer_stance_or_evidence'
                else:
                    work=self.production.execute(self.request,quantum=work_limit,consumed=self.request.inputs)
                    reason='paid_peer_partial'
                    if work['status'] in ('failed','cancelled'):
                        self.phase='failed';reason='paid_peer_failed'
                    elif work['status']=='succeeded':
                        self.reply=engine.job_status(self.peer,self.request.key)['public.0']
                        self.social=SocialSupportCycle(engine,self.actor,self.channel.participants)
                        self.social.queue_reply(self.peer,self.request.key,self.reply)
                        self.phase='recipient';reason='paid_peer_reply_queued'
        elif self.phase=='recipient':
            social_event=self.social.step(engine,historical_state,demand,available=available,work_limit=work_limit)
            reason=social_event['reason']
            if self.social.terminal is not None:self.phase=self.social.phase
        row=dict(index=len(self.events),turn=self.turn,phase=self.phase,reason=reason,before=before,after=len(engine.world.journal()),available=tuple(available),work_limit=work_limit,intake=intake,peer_work=work,social_event=social_event)
        self.events.append(row)
        if self.phase in ('complete','deferred','failed','cancelled'):self.terminal=deepcopy(row)
        return deepcopy(row)

    def checkpoint(self,engine):
        if engine is not self.channel.bridge.engine:raise ValueError('paired native owner required')
        return dumps(dict(version=self.VERSION,native_sha256=sha256(engine.checkpoint().encode()).hexdigest(),actor=self.actor,peer=self.peer,setting=self.setting,phase=self.phase,turn=self.turn,required=self.required,offer=self.offer,sender_view=self.sender_view,peer_view=self.peer_view,request=None if self.request is None else dict(fields_of(self.request),evidence=tuple((a.delivery,a.key) for a in self.request.evidence)),reply=self.reply,channel=self.channel.checkpoint(),production=deepcopy(self.production.events),social=None if self.social is None else self.social.checkpoint(engine),events=deepcopy(self.events),terminal=deepcopy(self.terminal)))

    @classmethod
    def restore(cls,text,engine):
        from .peer_cycle_audit import audit_peer_cycle
        audit_peer_cycle(engine,text);d=loads(text);obj=cls(engine,d['actor'],d['peer'],d['setting'])
        for name in ('phase','turn','required','offer','sender_view','peer_view','reply','events','terminal'):setattr(obj,name,deepcopy(d[name]))
        if d['request'] is not None:
            typ=CrossingRequest if d['setting']=='canonical' else WorkflowRequest
            fields=deepcopy(d['request']);fields['evidence']=tuple(DetailAddress(*a) for a in fields['evidence']);obj.request=typ(**fields)
        obj.channel=PacketChannel.restore(d['channel'],engine);obj.production.events=deepcopy(d['production'])
        if d['social'] is not None:obj.social=SocialSupportCycle.restore(d['social'],engine)
        if obj.checkpoint(engine)!=text:raise ValueError('peer restoration differs')
        return obj
