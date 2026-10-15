"""Bounded owned training after social completion; no competence by transmission.

This checkpoint forms native guarded response capacity only. FT closure,
scoped certificates, later reuse and feedback remain separate parent gates.
"""
from copy import deepcopy
from hashlib import sha256
from hle_unified import codec
from hle_unified.material import attrs
from hle_unified.self_content import decode
from hle_unified.development_policy import opportunity
from hle_unified.development_records import DevelopmentRequest
from hle_unified.operation_records import OperationRequest
from hle_unified.crossing_records import CrossingRequest
from hle_unified.workflow_records import WorkflowRequest
from hle_unified.selection_records import dumps, loads, fields_of
from .content import ContentBridge, semantic_scope


def request_record(r):
    d=fields_of(r)
    if 'evidence' in d:d['evidence']=tuple((a.delivery,a.key) for a in d['evidence'])
    return dict(type=type(r).__name__,fields=d)


class SocialTrainingController:
    VERSION='ft-owned-social-training-v1'

    def __init__(self, engine, peer_cycle):
        from .peer_cycle_audit import audit_peer_cycle
        if peer_cycle.phase!='complete':raise ValueError('completed autonomous social prefix required')
        check=peer_cycle.checkpoint(engine);audit_peer_cycle(engine,check)
        self.actor=peer_cycle.actor;self.setting=peer_cycle.setting
        self.scope=deepcopy(peer_cycle.required)
        self.prefix_native=engine.checkpoint();self.prefix_peer=check
        self.prefix_count=len(engine.world.journal());self.start_count=None
        self.phase='discover';self.index=0;self.plan=None;self.events=[]
        self.bridge=ContentBridge(engine);self.response=None;self.observation=None
        self.delivery=None;self.capacity=None;self.terminal=None

    def _discover(self,e):
        view=e.participant_view(self.actor);options=[]
        patterns=sorted((p for p in e.pattern_view(self.actor)
            if (p.context,p.cue)==(self.scope['context'],self.scope['cue'])),key=lambda p:dumps(p.ref))
        if not patterns:return None
        p=patterns[0]
        for (actor,key),ref in e._jobs.items():
            if actor!=self.actor:continue
            r=e.job_status(actor,key)
            if (r.get('status')!='succeeded' or not r.get('route_count')
                or r.get('u8') or r.get('context')!=self.scope['context']
                or r.get('destination') not in ('I','ITS')):continue
            output=r.get('binding') or r.get('result')
            if output is None or output not in view._bindings:continue
            binding=view._bindings[output]
            if len(binding.content)!=1 or binding.content[0].relation!=('c3.data' if self.setting=='canonical' else 'c7w.data'):continue
            try:body=decode(binding.content[0].object)
            except ValueError:continue
            kinds=({'I':('intention','personal_policy'),'ITS':('model','rule')} if self.setting=='canonical' else {'I':('intention','personal'),'ITS':('system','rule')})
            if body.get('kind') not in kinds[r['destination']]:continue
            try:target=semantic_scope(e,r)
            except ValueError:continue
            known,sources=opportunity(view,target,self.scope['context'])
            if not sources or known.get('trigger')!=p.trigger or known.get('partner') is None:continue
            if not view.resolve(target):continue
            options.append(dict(target=target,source=output,source_operation=ref,
                destination=r['destination'],partner=known['partner']))
        chosen={}
        for row in sorted(options,key=lambda row:dumps((row['target'],row['source']))):
            chosen.setdefault(row['target'].identity,row)
        if len(chosen)<2:return None
        return dict(pattern=p.ref,episodes=tuple(list(chosen.values())[:2]))

    def _key(self,kind):return 'ft-social-training:'+sha256(dumps((self.actor,self.prefix_count)).encode()).hexdigest()[:16]+':'+str(self.index)+':'+kind

    def _request(self,e):
        v=e.participant_view(self.actor);episode=self.plan['episodes'][min(self.index,1)]
        target=episode['target'];context=self.scope['context'];cue=self.scope['cue']
        if self.phase=='respond':
            _,sources=opportunity(v,target,context)
            evidence=tuple(p.address for source in sources for p in v.resolve(source))
            return DevelopmentRequest(self._key('respond'),self.actor,'respond',self.plan['pattern'],context,cue,(target,),evidence,episode['partner'])
        if self.phase=='content':
            domain='personal' if episode['destination']=='I' else 'system'
            typ=CrossingRequest if self.setting=='canonical' else WorkflowRequest
            return typ(key=self._key('content'),actor=self.actor,recipe=('use-' if self.setting=='canonical' else 'workflow-use-')+domain+'-v1',context=context,cue=cue,inputs=(episode['source'],),evidence=tuple(p.address for p in v.resolve(target)),target=target)
        if self.phase=='observe':
            if self.observation is None:
                self.delivery=self._key('delivery')
                self.observation=e.deliver_event(self.delivery,self.response,self.actor)
            return OperationRequest(self._key('observe'),self.actor,'read',context,delivery=self.delivery)
        if self.phase=='practice':
            return DevelopmentRequest(self._key('practice'),self.actor,'practice',self.plan['pattern'],context,cue,(target,),tuple(p.address for p in v.resolve(self.observation)),episode['partner'],observation=self.observation)
        if self.phase=='organize':
            rows=[r for r in e.development_view(self.actor)['practices'] if r['pattern']==self.plan['pattern']]
            evidence=tuple(dict.fromkeys(p.address for r in rows for p in v.resolve(r['observation'])))
            return DevelopmentRequest(self._key('organize'),self.actor,'reorganize',self.plan['pattern'],context,cue,(self.plan['episodes'][0]['target'],),evidence)
        raise ValueError('invalid training phase')

    def step(self,e,*,work_limit=1):
        if e is not self.bridge.engine or type(work_limit) is not int or work_limit<1:raise ValueError('paired native engine and positive exact bound required')
        if self.terminal is not None:return deepcopy(self.terminal)
        if self.start_count is None:self.start_count=len(e.world.journal())
        before=len(e.world.journal());phase=self.phase;view=e.participant_view(self.actor).bytes();request=None;work=None
        if self.phase=='discover':
            self.plan=self._discover(e);self.phase='respond' if self.plan else 'deferred'
        elif self.phase=='organize' and len([r for r in e.development_view(self.actor)['practices'] if r['pattern']==self.plan['pattern'] and r['independent']])<2:
            self.phase='unqualified'
        else:
            r=self._request(e);request=request_record(r)
            work=self.bridge.execute(r,quantum=work_limit,consumed=r.inputs if self.phase=='content' else ())
            if work['status'] in ('failed','cancelled'):self.phase='failed'
            elif work['status']=='succeeded':
                if self.phase=='respond':self.response=e.job_status(self.actor,r.key)['result'];self.phase='content'
                elif self.phase=='content':self.phase='observe'
                elif self.phase=='observe':self.phase='practice'
                elif self.phase=='practice':
                    self.index+=1;self.response=None;self.observation=None;self.delivery=None
                    self.phase='respond' if self.index<2 else 'organize'
                else:
                    self.capacity=e.job_status(self.actor,r.key)['development'];self.phase='complete'
        row=dict(index=len(self.events),before=before,after=len(e.world.journal()),phase_before=phase,phase=self.phase,episode_index=self.index,view=view,request=request,work=work)
        self.events.append(row)
        if self.phase in ('complete','unqualified','deferred','failed'):self.terminal=deepcopy(row)
        return deepcopy(row)

    def checkpoint(self,e):
        if e is not self.bridge.engine:raise ValueError('paired native engine required')
        return dumps(dict(version=self.VERSION,native_sha256=sha256(e.checkpoint().encode()).hexdigest(),actor=self.actor,setting=self.setting,scope=self.scope,prefix_native=self.prefix_native,prefix_peer=self.prefix_peer,prefix_count=self.prefix_count,start_count=self.start_count,phase=self.phase,index=self.index,plan=self.plan,events=self.events,work=self.bridge.events,response=self.response,observation=self.observation,delivery=self.delivery,capacity=self.capacity,terminal=self.terminal))

    @classmethod
    def restore(cls,text,e):
        from .social_training_audit import audit_social_training
        audit_social_training(e,text)
        d=loads(text);o=cls.__new__(cls)
        for name in ('actor','setting','scope','prefix_native','prefix_peer','prefix_count','start_count','phase','index','plan','events','response','observation','delivery','capacity','terminal'):setattr(o,name,deepcopy(d[name]))
        o.bridge=ContentBridge(e);o.bridge.events=deepcopy(d['work'])
        if o.checkpoint(e)!=text:raise ValueError('training restoration differs')
        return o
