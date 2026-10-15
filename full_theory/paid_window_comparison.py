"""Complete paid owned request windows; no admission or live choice authority."""
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
from hle_unified.selection_records import SelectionRequest
from hle_unified.workflow_selection_records import WorkflowSelectionRequest
from hle_unified.selection_execution import SelectionEngine
from hle_unified.workflow_selection_execution import WorkflowFinalSelectionEngine
from .owned_request_windows_audit import audit_owned_request_windows


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
class WindowComparisonRequest(Record):
    key: str
    windows: str
    evidence: tuple


@lru_cache(maxsize=2)
def validate_source(native,windows,evidence,setting):
    if type(evidence) is not tuple or len(evidence)!=4 or any(type(x) is not str for x in evidence):
        raise ValueError('exact original/source/binding/intake chain required')
    cls=SelectionEngine if setting=='canonical' else WorkflowFinalSelectionEngine
    old=cls.restore(native);original=cls.restore(evidence[0])
    audit_owned_request_windows(old,original,evidence[1],evidence[2],evidence[3],windows)
    if loads(windows)['setting']!=setting:raise ValueError('exact native setting required')
    return True


def ballot(engine, text):
    d=loads(text); result=[]
    keys=(('cell','recipe','origin','destination','face','inputs','eligible','benefit',
          'grounding','effort','score','examined','deferred') if d['setting']=='canonical' else
          ('cell','recipe','inputs','eligible','priority','preference','effort','coverage','examined','deferred'))
    cls=SelectionRequest if d['setting']=='canonical' else WorkflowSelectionRequest
    for ordinal,fields in enumerate(d['requests']):
        r=cls(**fields)
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


class _WindowComparison:
    WINDOW_POLICY='ft-paid-owned-window-comparison-v1'

    def __init__(self,world,law):
        super().__init__(world,law);self._window_comparisons={}

    def _declare(self,cid,versions):
        if any(v.ref.identity.namespace.startswith('ftwc.') for v in versions):
            raise ValueError('window comparison evidence cannot be authored')
        return super()._declare(cid,versions)

    def _disclose(self,cid,actor,source,selectors,subject):
        if source.identity.namespace.startswith('ftwc.'):
            raise ValueError('window comparison evidence is audit-only')
        return super()._disclose(cid,actor,source,selectors,subject)

    def _start(self,cid,request):
        if type(request) is not WindowComparisonRequest:return super()._start(cid,request)
        d=loads(request.windows);r=d['fresh_demand'];actor=d['actor'];key=request.key
        native=seal(self.BASE_SCHEMA,unseal(self.checkpoint(),self.SCHEMA))
        validate_source(native,request.windows,request.evidence,self.SETTING)
        view=self.participant_view(actor)
        if not d['requests'] or key!='ft-window-comparison:'+digest(request.windows):
            raise ValueError('complete paired window domain and exact fresh key required')
        if actor in self._locks or (actor,key) in self._jobs:raise ValueError('free actor and fresh work required')
        r=dict(context=r['context'],demand=r['binding'])
        rows=ballot(self,request.windows);required=sum(x['required'] for x in rows)
        snapshot=record(address('ftwc.snapshot',actor,key),'Declared window comparison input',
            dict(windows_sha256=digest(request.windows),view_sha256=digest(view.bytes()),
                 profile=self._profiles[actor],cursor=self._cursors[actor]))
        candidates=record(address('ftwc.candidates',actor,key),'Unsettled window comparison',dict(payload=dumps(rows)))
        op=fields_of(OperationRequest(key,actor,'bind',r['context']));op.pop('participants');op.pop('evidence')
        op.update(record_type='operation',ftwc=True,primitive='bind',policy=self.WINDOW_POLICY,setting=self.SETTING,
            required=required,completed=0,spent=0,status='pending',failure=None,result=None,
            route_prepare=required,route_execute=0,started_tick=self._now().tick,
            snapshot=snapshot.ref,candidates=candidates.ref,windows=len(rows),
            **{'participant.0':actor,'lock.0':actor,'input.0':r['demand'],'dependency.0':self.law})
        job=record(job_address(actor,key),'Paid complete window comparison',op)
        self._batch(cid,actor,(snapshot,candidates,job),evidence=(r['demand'],))
        self._jobs[actor,key]=job.ref;self._reserve(op,job.ref)
        self._window_comparisons[actor,key]=(request,rows,attrs(snapshot))
        return job.ref

    def _advance(self,cid,actor,key,work_limit):
        if (actor,key) in self._window_comparisons:return OperationEngine._advance(self,cid,actor,key,work_limit)
        return super()._advance(cid,actor,key,work_limit)

    def _commit(self,cid,actor,key):
        if (actor,key) not in self._window_comparisons:return super()._commit(cid,actor,key)
        old,d=self._active(actor,key)
        if d['status']!='ready':raise ValueError('full window comparison payment required')
        request,rows,snapshot=self._window_comparisons[actor,key]
        if (digest(self.participant_view(actor).bytes()),self._profiles[actor],self._cursors[actor])!=(
            snapshot['view_sha256'],snapshot['profile'],snapshot['cursor']):
            raise ValueError('window comparison inputs changed')
        event=self._event(cid,old,'succeeded')
        d.update(status='succeeded',failure=None,result=event.ref,finished_tick=self._now().tick)
        job=next_version(old,attributes=attributes(d));f=loads(request.windows)['fresh_demand'];r=dict(context=f['context'],demand=f['binding'])
        receipt=record(address('u4.receipt',cid),'Completed paid window comparison',dict(
            actor=actor,operation='bind',work_key=key,required=d['required'],completed=d['completed'],
            spent=d['spent'],**{'input.0':r['demand']}))
        result=record(address('ftwc.result',actor,key),'Paid window comparison, not admission',dict(
            operation=job.ref,receipt=receipt.ref,policy=self.WINDOW_POLICY,payload=dumps(dict(
                windows=rows,required=d['required'],comparison_paid=True,
                execution_authorized=False,td5_admitted=False,history_choice=False))))
        self._batch(cid,actor,(job,receipt,result,event),evidence=(old.ref,))
        self._jobs[actor,key]=job.ref;self._release(d,old.ref)
        return event.ref

    def window_result(self,actor,key):
        if (actor,key) not in self._window_comparisons:raise ValueError('registered window comparison required')
        if self.job_status(actor,key)['status']!='succeeded':return None
        return loads(attrs(self.world.resolve(address('ftwc.result',actor,key)))['payload'])


class PaidCanonicalWindowEngine(_WindowComparison,PaidCanonicalComparisonEngine):
    SCHEMA='ft-canonical-paid-window-comparison-v1'
    BASE_SCHEMA=SelectionEngine.SCHEMA
    @staticmethod
    def _registry():return {**PaidCanonicalComparisonEngine._registry(),'WindowComparisonRequest':WindowComparisonRequest}


class PaidWorkflowWindowEngine(_WindowComparison,PaidWorkflowComparisonEngine):
    SCHEMA='ft-workflow-paid-window-comparison-v1'
    BASE_SCHEMA=WorkflowFinalSelectionEngine.SCHEMA
    @staticmethod
    def _registry():return {**PaidWorkflowComparisonEngine._registry(),'WindowComparisonRequest':WindowComparisonRequest}


def prepare_window_comparison(engine,windows,evidence):
    cls=PaidCanonicalWindowEngine if loads(windows)['setting']=='canonical' else PaidWorkflowWindowEngine
    validate_source(engine.checkpoint(),windows,evidence,loads(windows)['setting'])
    return cls.from_native(engine.checkpoint()),WindowComparisonRequest('ft-window-comparison:'+digest(windows),windows,evidence)


def step_window_comparison(engine,request,*,work_limit=1,settle=True):
    if type(work_limit) is not int or work_limit<1 or type(settle) is not bool:raise ValueError('exact work bound required')
    actor=loads(request.windows)['actor'];key=request.key
    if (actor,key) not in engine._jobs:engine.start(key+':start',request)
    d=engine.job_status(actor,key)
    if d['status'] in ('succeeded','failed','cancelled'):return d
    if d['status']!='ready':engine.advance(key+':work:'+str(d['completed'])+':'+str(work_limit),actor,key,work_limit)
    if settle and engine.job_status(actor,key)['status']=='ready':engine.commit(key+':commit',actor,key)
    return engine.job_status(actor,key)
