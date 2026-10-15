"""Separately versioned native paid comparison; never route authorization."""
from dataclasses import dataclass
from hashlib import sha256
from hle.contracts import Record
from hle_unified.selection_records import SelectionRequest, fields_of, dumps, loads, registry as canonical_registry
from hle_unified.workflow_selection_records import WorkflowSelectionRequest, registry as workflow_registry
from hle_unified.selection_execution import SelectionEngine
from hle_unified.workflow_selection_execution import WorkflowFinalSelectionEngine
from hle_unified.operation_records import OperationRequest
from hle_unified.operations import OperationEngine, record, address, job_address
from hle_unified.material import attrs, attributes
from hle_unified.store import next_version
from hle_unified.compact import seal, unseal
from .owned_proposal_domain import owned_proposal_domain


@dataclass(frozen=True)
class PaidComparisonRequest(Record):
    key: str
    request: SelectionRequest | WorkflowSelectionRequest

    def __post_init__(self):
        super().__post_init__()
        if not self.key.startswith('ft-owned-comparison:'):
            raise ValueError('versioned comparison key required')


class _PaidComparison:
    POLICY = 'ft-owned-paid-comparison-v1'

    def __init__(self, world, law):
        super().__init__(world, law)
        self._ft_comparisons = {}

    @classmethod
    def from_native(cls, text):
        return cls.restore(seal(cls.SCHEMA, unseal(text, cls.BASE_SCHEMA)))

    def _declare(self, cid, versions):
        if any(v.ref.identity.namespace.startswith('ftpc.') for v in versions):
            raise ValueError('comparison evidence cannot be authored')
        return super()._declare(cid, versions)

    def _disclose(self, cid, actor, source, selectors, subject):
        if source.identity.namespace.startswith('ftpc.'):
            raise ValueError('comparison evidence is audit-only')
        return super()._disclose(cid, actor, source, selectors, subject)

    def _comparison_view(self, request):
        if self.SETTING == 'canonical':
            if type(request) is not SelectionRequest:raise ValueError('canonical request required')
            s = self.selection_view(request); rows, nominee = self._select_policy(s)
            extent = 1+s['scanned']+s['foreign_total']+33+sum(x['examined'] for x in rows)
        else:
            if type(request) is not WorkflowSelectionRequest:raise ValueError('workflow request required')
            s = self.workflow_selection_view(request); rows, nominee = self._workflow_policy(s)
            if s.get('policy') != 'c7-workflow-selection-v4':raise ValueError('explicit v4 required')
            extent = 1+len(s['items'])+len(rows)+sum(x['examined'] for x in rows)
        return s, rows, nominee, extent

    def _start(self, cid, request):
        if type(request) is not PaidComparisonRequest:return super()._start(cid, request)
        r = request.request; actor = r.actor; key = request.key
        if actor not in self._profiles or actor in self._locks or (actor,key) in self._jobs:
            raise ValueError('free typed actor and fresh comparison required')
        s, rows, nominee, extent = self._comparison_view(r)
        snapshot = record(address('ftpc.snapshot',actor,key),'Current owned comparison inputs',
            dict(payload=dumps(s)))
        ballot = record(address('ftpc.candidates',actor,key),'Unsettled native comparison',
            dict(payload=dumps(rows)))
        d = fields_of(OperationRequest(key,actor,'bind',r.context))
        d.pop('participants');d.pop('evidence')
        d.update(record_type='operation',ftpc=True,primitive='bind',policy=self.POLICY,
            setting=self.SETTING,required=extent,completed=0,spent=0,status='pending',
            failure=None,result=None,route_prepare=extent,route_execute=0,
            started_tick=self._now().tick,snapshot=snapshot.ref,candidates=ballot.ref,
            scanned=s.get('scanned',len(s['items'])),foreign_count=s.get('foreign_total',0),
            candidate_count=len(rows),evaluated=sum(x['examined'] for x in rows),
            **{'participant.0':actor,'lock.0':actor,'input.0':r.demand,'dependency.0':self.law})
        job = record(job_address(actor,key),'Paid owned comparison',d)
        self._batch(cid,actor,(snapshot,ballot,job),evidence=(r.demand,))
        self._jobs[actor,key]=job.ref;self._reserve(d,job.ref)
        self._ft_comparisons[actor,key]=(r,s,rows,nominee)
        return job.ref

    def _advance(self,cid,actor,key,work_limit):
        if (actor,key) in self._ft_comparisons:
            return OperationEngine._advance(self,cid,actor,key,work_limit)
        return super()._advance(cid,actor,key,work_limit)

    def _commit(self,cid,actor,key):
        if (actor,key) not in self._ft_comparisons:return super()._commit(cid,actor,key)
        old,d=self._active(actor,key)
        if d['status']!='ready':raise ValueError('comparison must be fully paid')
        r,s,rows,nominee=self._ft_comparisons[actor,key]
        now,_,_,_=self._comparison_view(r)
        failure='changed_participant_inputs' if any(now[k]!=s[k] for k in s if k!='wallet') else None
        event=self._event(cid,old,'failed' if failure else 'succeeded')
        d.update(status='failed' if failure else 'succeeded',failure=failure,
            result=event.ref,finished_tick=self._now().tick)
        current=next_version(old,attributes=attributes(d))
        outputs=()
        if failure is None:
            receipt=record(address('u4.receipt',cid),'Completed paid comparison',dict(
                actor=actor,operation='bind',work_key=key,required=d['required'],
                completed=d['completed'],spent=d['spent'],**{'input.0':r.demand}))
            result=record(address('ftpc.result',actor,key),'Comparison result, not admission',dict(
                operation=current.ref,receipt=receipt.ref,policy=self.POLICY,
                payload=dumps(dict(candidates=rows,native_nominee=nominee,
                    comparison_paid=True,comparison_required=d['required'],execution_authorized=False))))
            outputs=(receipt,result)
        self._batch(cid,actor,(current,*outputs,event),evidence=(old.ref,))
        self._jobs[actor,key]=current.ref;self._release(d,old.ref)
        return event.ref

    def comparison_result(self,actor,key):
        if (actor,key) not in self._ft_comparisons:raise ValueError('owned comparison required')
        if self.job_status(actor,key)['status']!='succeeded':return None
        return loads(attrs(self.world.resolve(address('ftpc.result',actor,key)))['payload'])


class PaidCanonicalComparisonEngine(_PaidComparison,SelectionEngine):
    SCHEMA='ft-canonical-paid-comparison-engine-v1'
    BASE_SCHEMA=SelectionEngine.SCHEMA
    SETTING='canonical'
    @staticmethod
    def _registry():return {**canonical_registry(),'PaidComparisonRequest':PaidComparisonRequest}


class PaidWorkflowComparisonEngine(_PaidComparison,WorkflowFinalSelectionEngine):
    SCHEMA='ft-workflow-paid-comparison-engine-v1'
    BASE_SCHEMA=WorkflowFinalSelectionEngine.SCHEMA
    SETTING='workflow'
    @staticmethod
    def _registry():return {**workflow_registry(),'PaidComparisonRequest':PaidComparisonRequest}


def prepare_owned_comparison(source_engine,source,binding):
    domain=owned_proposal_domain(source_engine,source,binding);d=loads(domain)
    if d['request'] is None:raise ValueError('current pending owned request required')
    cls=PaidCanonicalComparisonEngine if d['setting']=='canonical' else PaidWorkflowComparisonEngine
    request_cls=SelectionRequest if d['setting']=='canonical' else WorkflowSelectionRequest
    key='ft-owned-comparison:'+sha256(source.encode()).hexdigest()[:24]
    request=PaidComparisonRequest(key,request_cls(**d['request']))
    engine=cls.from_native(source_engine.checkpoint())
    return engine,request,domain


def step_owned_comparison(engine,request,*,work_limit=1,settle=True):
    if type(work_limit) is not int or work_limit<1 or type(settle) is not bool:
        raise ValueError('positive exact work bound and settlement flag required')
    actor=request.request.actor;key=request.key
    if (actor,key) not in engine._jobs:engine.start(key+':start',request)
    d=engine.job_status(actor,key)
    if d['status'] in ('succeeded','failed','cancelled'):return d
    if d['status']!='ready':
        engine.advance(key+':work:'+str(d['completed'])+':'+str(work_limit),actor,key,work_limit)
    if settle and engine.job_status(actor,key)['status']=='ready':engine.commit(key+':commit',actor,key)
    return engine.job_status(actor,key)
