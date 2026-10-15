"""Stricter unsupported requalification, then owned paid retained reuse."""
from copy import deepcopy
from dataclasses import replace
from hashlib import sha256
from hle_unified.selection_records import dumps, loads, fields_of, SelectionRequest
from hle_unified.workflow_selection_records import WorkflowSelectionRequest
from hle_unified.crossing_records import CrossingRequest
from hle_unified.workflow_records import WorkflowRequest
from hle_unified.shell_records import EncounterRequest
from hle_unified.development_policy import opportunity
from hle_unified.records import ObjectRef
from hle_unified.material import attrs, attributes
from hle_unified.store import next_version
from hle_unified.cognitive_records import reference
from hle_unified.operation_records import OperationRequest
from hle_unified.particulars import Selector
from .content import ContentBridge
from .retention import Demand
from .demand_controller import IntegratedDemandController
from .route_policy import IntegratedRoutePolicy
from .social_training import request_record
from .autonomous_reuse import (AutonomousReuseController, _copy_ledger, _ledger_record,
    _restore_ledger, _owned_need_refs)


class SocialReuseController(AutonomousReuseController):
    VERSION = 'ft-unsupported-social-reuse-v1'

    def __init__(self, closure, engine):
        from .social_closure_audit import audit_social_closure
        audit_social_closure(engine, closure.checkpoint(engine))
        if closure.phase != 'certified':
            raise ValueError('actual independent training and closed certificate required')
        self.actor = closure.actor
        self.setting = closure.setting
        self.prefix_checkpoint = closure.checkpoint(engine)
        self.prefix_native = engine.checkpoint()
        self.prefix_count = len(engine.world.journal())
        self.source_certificate_key = closure.certificate_key
        self.certificate_key = None
        self.ledger = _copy_ledger(closure.ledger, engine)
        self.requalification_demand = replace(closure.demand, support_allowed=())
        self.plan = deepcopy(closure.plan)
        self.qualification_events = []
        self.bridge = ContentBridge(engine)
        self.qualification_index = 0
        self.qualified_native = None
        self.qualified_access = None
        self.ready_boundary = None
        self.prior_need_refs = None
        self.demand_controller = IntegratedDemandController()
        self.route_policy = IntegratedRoutePolicy()
        self.required = None
        self.request = None
        self.phase = 'qualify-use'
        self.consumer_key = None
        self.events = []
        self.terminal = None
        self.organization = None

    def _qualification_key(self,kind):
        return 'ft-no-support:' + sha256(dumps((self.actor,self.prefix_count)).encode()).hexdigest()[:16] + ':' + str(self.qualification_index) + ':' + kind

    def _qualify(self,engine,work_limit):
        phase = self.phase; before = len(engine.world.journal()); view = engine.participant_view(self.actor)
        snapshot = view.bytes(); request = work = exposure = certificate = None
        dem = self.requalification_demand
        if phase in ('qualify-use','qualify-shell'):
            if phase == 'qualify-use':
                typ = CrossingRequest if self.setting == 'canonical' else WorkflowRequest
                domain = 'personal' if self.plan['destination'] == 'I' else 'system'
                recipe = ('use-' if self.setting == 'canonical' else 'workflow-use-') + domain + '-v1'
                r = typ(self._qualification_key('use'),self.actor,recipe,dem.context,dem.cue,
                    (self.plan['source'],),tuple(p.address for p in view.resolve(dem.target)),dem.target)
            else:
                known,sources = opportunity(view,dem.target,dem.context)
                r = EncounterRequest(self._qualification_key('shell'),self.actor,dem.target,dem.context,dem.cue,
                    known.get('partner') or dem.target,ObjectRef(self.actor,1),
                    tuple(p.address for source in sources for p in view.resolve(source)))
            request = request_record(r)
            work = self.bridge.execute(r,quantum=work_limit,
                consumed=(self.plan['source'],) if phase == 'qualify-use' else ())
            if work['status'] in ('failed','cancelled'):self.phase = 'qualification-failed'
            elif work['status'] == 'succeeded':self.phase = 'qualify-shell' if phase == 'qualify-use' else 'qualify-expose'
        elif phase == 'qualify-expose':
            exposure = self.ledger.expose(self.actor,dem,self.plan['kept'],self.plan['returns'],
                self._qualification_key('shell'),self._qualification_key('use'))
            self.qualification_index += 1
            self.phase = 'qualify-use' if self.qualification_index < 2 else 'qualify-certify' if exposure['closed'] else 'qualification-open'
        elif phase == 'qualify-certify':
            original = self.ledger.certificates[self.source_certificate_key]
            uses = tuple(attrs(engine.world.resolve(ref))['key'] for ref in original['content_uses'])
            self.certificate_key = 'ft-no-support-certificate:' + sha256(dumps((self.actor,dem.record(),self.prefix_count)).encode()).hexdigest()[:20]
            certificate = self.ledger.certify(self.certificate_key,self.actor,dem,original['native_capacity'],uses)
            self.qualified_native = engine.checkpoint(); self.qualified_access = engine.access.checkpoint()
            self.ready_boundary = len(engine.world.journal()); self.prior_need_refs = _owned_need_refs(engine,self.actor)
            self.phase = 'organize'
        else:
            raise ValueError('invalid unsupported qualification phase')
        row = dict(index=len(self.qualification_events),phase_before=phase,phase=self.phase,
            before=before,after=len(engine.world.journal()),view=snapshot,request=request,work=work,
            exposure=deepcopy(exposure),certificate=deepcopy(certificate),episode_index=self.qualification_index)
        self.qualification_events.append(row)
        return deepcopy(row)

    def _organize(self,engine,work_limit):
        dem = self.requalification_demand
        archive = reference('suit:Wand')
        if self.organization is None:
            view = engine.participant_view(self.actor)
            refs = tuple(sorted((b.ref for b in view._heads.values()
                if (b.cue,b.context)==(dem.cue,dem.context) and b.ref.identity.namespace=='workshop'
                and not any(p.relation=='u8.reorganize' and type(p.object) is int and p.object>0
                            for p in b.content)),key=dumps))
            self.organization = dict(cue=archive,view=view.bytes(),refs=refs,index=0,events=[],complete=False)
        org = self.organization
        bridge = ContentBridge(engine)
        key = self._qualification_key('archive-read')
        delivery = key + ':delivery'
        if (self.actor,key) not in engine._jobs:
            engine.disclose(delivery,self.actor,archive,(Selector('archive-cue','name',('label',)),))
        work = bridge.execute(OperationRequest(key,self.actor,'read',dem.context,delivery=delivery),quantum=work_limit)
        org['events'].append(dict(kind='read',work=work))
        if work['status']!='succeeded':return deepcopy(org)
        while org['index'] < len(org['refs']):
            ref = org['refs'][org['index']]
            prior = engine.participant_view(self.actor)._bindings[ref]
            key = self._qualification_key('archive-' + str(org['index']))
            original = engine.world.resolve(ref)
            revised = next_version(original,attributes=attributes(dict(attrs(original),cue=archive)))
            if (self.actor,key) not in engine._jobs:
                engine.declare(key+':draft',(revised,))
            work = bridge.execute(OperationRequest(key,self.actor,'bind',dem.context,
                binding=revised.ref,evidence=prior.particulars),quantum=work_limit)
            org['events'].append(dict(kind='bind',original=ref,revised=revised.ref,work=work))
            if work['status']!='succeeded':return deepcopy(org)
            org['index'] += 1
        org['complete'] = True
        self.phase = 'scan'
        return deepcopy(org)

    def step(self,engine,historical_state,demand=None,*,work_limit=1):
        if engine is not self.ledger.engine or type(work_limit) is not int or work_limit < 1:
            raise ValueError('paired engine and positive exact bound required')
        if self.phase=='organize':
            if demand is not None:raise ValueError('later demand must follow paid organization')
            return self._organize(engine,work_limit)
        if self.phase.startswith('qualify-'):
            if demand is not None:raise ValueError('later demand must follow unsupported certification')
            return self._qualify(engine,work_limit)
        if self.phase.startswith('qualification-'):
            return deepcopy(self.qualification_events[-1])
        return super().step(engine,historical_state,demand,work_limit=work_limit)

    def checkpoint(self,engine):
        if engine is not self.ledger.engine:raise ValueError('paired engine required')
        request = None if self.request is None else dict(setting=self.setting,fields=fields_of(self.request))
        return dumps(dict(version=self.VERSION,native_sha256=sha256(engine.checkpoint().encode()).hexdigest(),
            actor=self.actor,setting=self.setting,prefix_checkpoint=self.prefix_checkpoint,prefix_native=self.prefix_native,
            prefix_count=self.prefix_count,source_certificate_key=self.source_certificate_key,certificate_key=self.certificate_key,
            requalification_demand=self.requalification_demand.record(),plan=self.plan,qualification_events=self.qualification_events,
            qualification_work=self.bridge.events,qualification_index=self.qualification_index,organization=self.organization,qualified_native=self.qualified_native,
            qualified_access=self.qualified_access,ready_boundary=self.ready_boundary,prior_need_refs=self.prior_need_refs,
            retention=_ledger_record(self.ledger),demand_controller=self.demand_controller.checkpoint(),
            route_policy=self.route_policy.checkpoint(engine),required=self.required,request=request,phase=self.phase,
            consumer_key=self.consumer_key,events=self.events,terminal=self.terminal))

    @classmethod
    def restore(cls,text,engine):
        from .social_reuse_audit import audit_social_reuse
        audit_social_reuse(engine,text)
        d = loads(text);obj = cls.__new__(cls)
        for name in ('actor','setting','prefix_checkpoint','prefix_native','prefix_count','source_certificate_key',
            'certificate_key','plan','qualification_events','qualification_index','qualified_native','qualified_access',
            'ready_boundary','prior_need_refs','required','phase','consumer_key','events','terminal','organization'):
            setattr(obj,name,deepcopy(d[name]))
        obj.requalification_demand = Demand(**d['requalification_demand'])
        obj.ledger = _restore_ledger(d['retention'],engine)
        obj.bridge = ContentBridge(engine);obj.bridge.events = deepcopy(d['qualification_work'])
        obj.demand_controller = IntegratedDemandController.restore(d['demand_controller'])
        obj.route_policy = IntegratedRoutePolicy.restore(d['route_policy'],engine)
        obj.request = None if d['request'] is None else (SelectionRequest if d['setting']=='canonical' else WorkflowSelectionRequest)(**d['request']['fields'])
        if obj.checkpoint(engine) != text:raise ValueError('reuse restoration differs')
        return obj
