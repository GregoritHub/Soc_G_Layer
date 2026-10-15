"""New paid role-domain comparison; never TD5 or movement authority."""
from dataclasses import dataclass
from hashlib import sha256
from functools import lru_cache
from hle.contracts import Record
from hle_unified import codec
from hle_unified.selection_records import dumps, loads, fields_of
from hle_unified.operation_records import OperationRequest
from hle_unified.operations import OperationEngine, record, address, job_address
from hle_unified.material import attrs, attributes
from hle_unified.store import next_version
from hle_unified.compact import seal, unseal
from .owned_paid_comparison import PaidCanonicalComparisonEngine, PaidWorkflowComparisonEngine
from .owned_role_domain import role_requests
from .owned_role_domain_audit import audit_role_payload


def digest(text): return sha256(text.encode()).hexdigest()


def snapshot_text(snapshot,setting):
    if setting=='canonical':return dumps(snapshot)
    def pack(value):
        if type(value) is dict:
            if any(type(k) is not str for k in value):raise ValueError('string snapshot keys required')
            return ('map',tuple((k,pack(value[k])) for k in sorted(value)))
        if type(value) is tuple:return ('tuple',tuple(pack(x) for x in value))
        if type(value) is list:return ('list',tuple(pack(x) for x in value))
        return ('leaf',value)
    return codec.dumps(pack(snapshot))


@dataclass(frozen=True)
class RoleComparisonRequest(Record):
    key: str
    roles: str
    prepared: str
    evidence: tuple


@lru_cache(maxsize=2)
def validate_source(native,roles,prepared,evidence,setting):
    from hle_unified.selection_execution import SelectionEngine
    from hle_unified.workflow_selection_execution import WorkflowFinalSelectionEngine
    from .owned_role_domain_audit import audit_owned_role_domain
    if type(evidence) is not tuple or len(evidence)!=7 or any(type(x) is not str for x in evidence):
        raise ValueError('exact immutable source chain required')
    cls=PaidCanonicalComparisonEngine if setting=='canonical' else PaidWorkflowComparisonEngine
    native_cls=SelectionEngine if setting=='canonical' else WorkflowFinalSelectionEngine
    old=cls.restore(native);comparison=cls.restore(evidence[4]);original=native_cls.restore(evidence[0])
    audit_owned_role_domain(old,comparison,original,evidence[1],evidence[2],evidence[3],
        evidence[5],evidence[6],prepared,roles)
    p=loads(prepared)
    if type(p['required']) is not int or p['required']<=0 or len(p['receipts'])!=p['required']:
        raise ValueError('fully paid preparation required')
    return True


def ballot(engine, text):
    d=loads(text); result=[]
    keys=(('cell','recipe','origin','destination','face','inputs','eligible','benefit',
          'grounding','effort','score','examined','deferred') if d['setting']=='canonical' else
          ('cell','recipe','inputs','eligible','priority','preference','effort','coverage','examined','deferred'))
    for ordinal,r in enumerate(role_requests(text)):
        try:
            s=engine.selection_view(r) if d['setting']=='canonical' else engine.workflow_selection_view(r)
        except ValueError as error:
            result.append(dict(ordinal=ordinal,request_sha256=digest(dumps(fields_of(r))),
                rejection=str(error),required=1,snapshot_sha256=None,candidates=(),nominee=None))
            continue
        if d['setting']=='canonical':
            rows,nominee=engine._select_policy(s)
            required=1+s['scanned']+s['foreign_total']+33+sum(x['examined'] for x in rows)
        else:
            rows,nominee=engine._workflow_policy(s)
            required=1+len(s['items'])+len(rows)+sum(x['examined'] for x in rows)
        projection=tuple({k:row[k] for k in keys} for row in rows)
        result.append(dict(ordinal=ordinal,request_sha256=digest(dumps(fields_of(r))),
            rejection=None,required=required,snapshot_sha256=digest(snapshot_text(s,d['setting'])),
            candidates=projection,nominee=None if nominee is None else nominee['cell']))
    return result


class _RoleComparison:
    ROLE_POLICY='ft-paid-owned-role-comparison-v1'

    def __init__(self,world,law):
        super().__init__(world,law);self._role_comparisons={}

    def _declare(self,cid,versions):
        if any(v.ref.identity.namespace.startswith('ftrc.') for v in versions):
            raise ValueError('role comparison evidence cannot be authored')
        return super()._declare(cid,versions)

    def _disclose(self,cid,actor,source,selectors,subject):
        if source.identity.namespace.startswith('ftrc.'):
            raise ValueError('role comparison evidence is audit-only')
        return super()._disclose(cid,actor,source,selectors,subject)

    def _start(self,cid,request):
        if type(request) is not RoleComparisonRequest:return super()._start(cid,request)
        d=loads(request.roles);p=loads(request.prepared);r=d['request'];actor=r['actor'];key=request.key
        native=seal(self.BASE_SCHEMA,unseal(self.checkpoint(),self.SCHEMA))
        validate_source(native,request.roles,request.prepared,request.evidence,self.SETTING)
        view=self.participant_view(actor)
        audit_role_payload(view.snapshot,p['request'],self.SETTING,len(p['receipts'])==p['required'],
            request.roles,digest(native),digest(request.prepared),digest(view.bytes()))
        if not d['settled'] or not d['assignments'] or key!='ft-role-comparison:'+digest(request.roles):
            raise ValueError('completed paired role domain and exact fresh key required')
        if actor in self._locks or (actor,key) in self._jobs:raise ValueError('free actor and fresh work required')
        rows=ballot(self,request.roles);required=sum(x['required'] for x in rows)
        snapshot=record(address('ftrc.snapshot',actor,key),'Declared role comparison input',
            dict(roles_sha256=digest(request.roles),view_sha256=digest(view.bytes()),
                 profile=self._profiles[actor],cursor=self._cursors[actor]))
        candidates=record(address('ftrc.candidates',actor,key),'Unsettled role comparison',dict(payload=dumps(rows)))
        op=fields_of(OperationRequest(key,actor,'bind',r['context']));op.pop('participants');op.pop('evidence')
        op.update(record_type='operation',ftrc=True,primitive='bind',policy=self.ROLE_POLICY,setting=self.SETTING,
            required=required,completed=0,spent=0,status='pending',failure=None,result=None,
            route_prepare=required,route_execute=0,started_tick=self._now().tick,
            snapshot=snapshot.ref,candidates=candidates.ref,assignments=len(rows),
            **{'participant.0':actor,'lock.0':actor,'input.0':r['demand'],'dependency.0':self.law})
        job=record(job_address(actor,key),'Paid complete role comparison',op)
        self._batch(cid,actor,(snapshot,candidates,job),evidence=(r['demand'],))
        self._jobs[actor,key]=job.ref;self._reserve(op,job.ref)
        self._role_comparisons[actor,key]=(request,rows,attrs(snapshot))
        return job.ref

    def _advance(self,cid,actor,key,work_limit):
        if (actor,key) in self._role_comparisons:return OperationEngine._advance(self,cid,actor,key,work_limit)
        return super()._advance(cid,actor,key,work_limit)

    def _commit(self,cid,actor,key):
        if (actor,key) not in self._role_comparisons:return super()._commit(cid,actor,key)
        old,d=self._active(actor,key)
        if d['status']!='ready':raise ValueError('full role comparison payment required')
        request,rows,snapshot=self._role_comparisons[actor,key]
        if (digest(self.participant_view(actor).bytes()),self._profiles[actor],self._cursors[actor])!=(
            snapshot['view_sha256'],snapshot['profile'],snapshot['cursor']):
            raise ValueError('role comparison inputs changed')
        event=self._event(cid,old,'succeeded')
        d.update(status='succeeded',failure=None,result=event.ref,finished_tick=self._now().tick)
        job=next_version(old,attributes=attributes(d));r=loads(request.roles)['request']
        receipt=record(address('u4.receipt',cid),'Completed paid role comparison',dict(
            actor=actor,operation='bind',work_key=key,required=d['required'],completed=d['completed'],
            spent=d['spent'],**{'input.0':r['demand']}))
        result=record(address('ftrc.result',actor,key),'Paid role comparison, not admission',dict(
            operation=job.ref,receipt=receipt.ref,policy=self.ROLE_POLICY,payload=dumps(dict(
                assignments=rows,required=d['required'],comparison_paid=True,
                execution_authorized=False,td5_admitted=False,history_choice=False))))
        self._batch(cid,actor,(job,receipt,result,event),evidence=(old.ref,))
        self._jobs[actor,key]=job.ref;self._release(d,old.ref)
        return event.ref

    def role_result(self,actor,key):
        if (actor,key) not in self._role_comparisons:raise ValueError('registered role comparison required')
        if self.job_status(actor,key)['status']!='succeeded':return None
        return loads(attrs(self.world.resolve(address('ftrc.result',actor,key)))['payload'])


class PaidCanonicalRoleEngine(_RoleComparison,PaidCanonicalComparisonEngine):
    SCHEMA='ft-canonical-paid-role-comparison-v1'
    BASE_SCHEMA=PaidCanonicalComparisonEngine.SCHEMA
    @staticmethod
    def _registry():return {**PaidCanonicalComparisonEngine._registry(),'RoleComparisonRequest':RoleComparisonRequest}


class PaidWorkflowRoleEngine(_RoleComparison,PaidWorkflowComparisonEngine):
    SCHEMA='ft-workflow-paid-role-comparison-v1'
    BASE_SCHEMA=PaidWorkflowComparisonEngine.SCHEMA
    @staticmethod
    def _registry():return {**PaidWorkflowComparisonEngine._registry(),'RoleComparisonRequest':RoleComparisonRequest}


def prepare_role_comparison(engine,roles,prepared,evidence):
    cls=PaidCanonicalRoleEngine if loads(roles)['setting']=='canonical' else PaidWorkflowRoleEngine
    return cls.from_native(engine.checkpoint()),RoleComparisonRequest('ft-role-comparison:'+digest(roles),roles,prepared,evidence)


def step_role_comparison(engine,request,*,work_limit=1,settle=True):
    if type(work_limit) is not int or work_limit<1 or type(settle) is not bool:raise ValueError('exact work bound required')
    actor=loads(request.roles)['request']['actor'];key=request.key
    if (actor,key) not in engine._jobs:engine.start(key+':start',request)
    d=engine.job_status(actor,key)
    if d['status'] in ('succeeded','failed','cancelled'):return d
    if d['status']!='ready':engine.advance(key+':work:'+str(d['completed'])+':'+str(work_limit),actor,key,work_limit)
    if settle and engine.job_status(actor,key)['status']=='ready':engine.commit(key+':commit',actor,key)
    return engine.job_status(actor,key)
