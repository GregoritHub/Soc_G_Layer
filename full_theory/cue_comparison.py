"""New-cue paid current-request comparisons; original policies remain exact."""
from dataclasses import dataclass
from hashlib import sha256
from itertools import combinations
import json
from pathlib import Path
from hle.contracts import Record
from hle_unified.selection_records import dumps, loads, fields_of, SelectionRequest, demand_value
from hle_unified.workflow_selection_records import WorkflowSelectionRequest, demand_value as workflow_need
from hle_unified.self_content import decode
from hle_unified.compact import seal, unseal
from hle_unified.operations import record, address, job_address
from hle_unified.operation_records import OperationRequest
from hle_unified.material import attrs
from .paid_window_comparison import _WindowComparison, ballot, step_window_comparison
from .owned_paid_comparison import PaidCanonicalComparisonEngine, PaidWorkflowComparisonEngine
from .demand_controller import IntegratedDemandController
from .demand_requests import form_request

PROTOCOL = Path(__file__).resolve().parents[1]/'contracts/ft/FT7_Cue_Comparison_A12C_Protocol_v1.json'
def digest(text): return sha256(text.encode()).hexdigest()

def cue_windows(engine, intake):
    i = loads(intake); setting = i['setting']; actor = i['actor']
    if setting not in ('canonical','workflow') or type(i['mask']) is not int:
        raise ValueError('exact accepted setting and mask')
    entry = json.loads(PROTOCOL.read_text())['inputs'].get(f"{setting}-{i['mask']:02d}-complete")
    # Wrapper schemas do not change native evidence, only the explicitly new command interpreter.
    # The exact inherited BASE_SCHEMA is read from the native class, never guessed.
    from hle_unified.selection_execution import SelectionEngine
    from hle_unified.workflow_selection_execution import WorkflowFinalSelectionEngine
    schema = (SelectionEngine if setting == 'canonical' else WorkflowFinalSelectionEngine).SCHEMA
    native = seal(schema, unseal(engine.checkpoint(), engine.SCHEMA))
    if entry is None or digest(native) != entry['native_sha256'] or digest(intake) != entry['intake_sha256']:
        raise ValueError('exact accepted complete A12B input required')
    if i['receipt'] is None or i['cancelled'] or actor in engine._locks:
        raise ValueError('settled unlocked task')
    view = engine.participant_view(actor); owned = view._bindings[i['task']]
    controller = IntegratedDemandController.restore(i['controller_prefix'])
    demands = controller.effective_demands(); key = dumps((actor,owned.ref))
    if key in demands: raise ValueError('fresh task')
    for b in view._heads.values():
        if b.ref == owned.ref or b.endorsement.value in ('retracted','disputed'): continue
        if any(p.relation in ('c6.need','c7ws.need') for p in b.content):
            if demands.get(dumps((actor,b.ref)),{}).get('status') != 'fulfilled':
                raise ValueError('older unresolved need')
    payload = (demand_value if setting == 'canonical' else workflow_need)(decode(owned.content[0].object))
    fresh = dict(actor=actor,binding=owned.ref,receipt=owned.receipt,context=owned.context,
        cue=owned.cue,target=owned.target,relation=owned.content[0].relation,payload=payload,
        raw_payload=owned.content[0].object,first_seen=controller.ledger.turn,
        admitted_at=controller.ledger.turn,status='pending',reason=None)
    demands[key] = fresh; request, formation = form_request(view, demands)
    if formation['selected'] != key: raise ValueError('oldest current task required')
    inventory = tuple(formation['content'])
    if setting == 'canonical':
        if request is None: raise ValueError('current canonical request')
        requests = [fields_of(request)]
    else:
        if not inventory or len(inventory)>16: raise ValueError('registered owned workflow bound')
        requests = []
        for size in range(1,min(8,len(inventory))+1):
            for subset in combinations(inventory,size):
                requests.append(fields_of(WorkflowSelectionRequest(key='ft-cue-window:'+digest(key+dumps(subset)),
                    actor=actor,context=owned.context,cue=owned.cue,target=owned.target,
                    demand=owned.ref,accessible=subset)))
    walk = view.traverse(owned.cue,owned.context)
    return dumps(dict(version='ft-cue-request-windows-a12c-v1',policy='owned-cue-role-absent-domain-v1',
        setting=setting,actor=actor,native_sha256=digest(native),intake_sha256=digest(intake),
        controller_prefix=i['controller_prefix'],reserve=i['reserve'],history=i['history'],
        fresh_demand=fresh,original_formation=formation,content_inventory=inventory,requests=requests,
        recall=dict(visited=walk.visited,truncated=walk.truncated,task_visited=owned.ref in walk.visited,limit=32),
        comparison_paid=False,execution_authorized=False,td5_admitted=False,history_choice=False,
        full_future_role_domain=False))

@dataclass(frozen=True)
class CueComparisonRequest(Record):
    key: str
    windows: str
    evidence: tuple

class _CueComparison(_WindowComparison):
    WINDOW_POLICY = 'ft-paid-cue-window-comparison-a12c-v1'
    def _start(self,cid,request):
        if type(request) is not CueComparisonRequest: return super()._start(cid,request)
        if type(request.evidence) is not tuple or len(request.evidence)!=1:
            raise ValueError('exact accepted intake evidence')
        if cue_windows(self,request.evidence[0]) != request.windows:
            raise ValueError('complete current owned cue windows required')
        d=loads(request.windows);r=d['fresh_demand'];actor=d['actor'];key=request.key
        view=self.participant_view(actor)
        if not d['requests'] or key!='ft-cue-comparison:'+digest(request.windows):
            raise ValueError('complete paired window domain and exact fresh key required')
        if actor in self._locks or (actor,key) in self._jobs:raise ValueError('free actor and fresh work required')
        rows=ballot(self,request.windows);required=sum(x['required'] for x in rows)
        snapshot=record(address('ftwc.snapshot',actor,key),'Declared new-cue comparison input',
            dict(windows_sha256=digest(request.windows),view_sha256=digest(view.bytes()),profile=self._profiles[actor],cursor=self._cursors[actor]))
        candidates=record(address('ftwc.candidates',actor,key),'Unsettled new-cue comparison',dict(payload=dumps(rows)))
        op=fields_of(OperationRequest(key,actor,'bind',r['context']));op.pop('participants');op.pop('evidence')
        op.update(record_type='operation',ftwc=True,primitive='bind',policy=self.WINDOW_POLICY,setting=self.SETTING,
            required=required,completed=0,spent=0,status='pending',failure=None,result=None,
            route_prepare=required,route_execute=0,started_tick=self._now().tick,
            snapshot=snapshot.ref,candidates=candidates.ref,windows=len(rows),
            **{'participant.0':actor,'lock.0':actor,'input.0':r['binding'],'dependency.0':self.law})
        job=record(job_address(actor,key),'Paid complete new-cue comparison',op)
        self._batch(cid,actor,(snapshot,candidates,job),evidence=(r['binding'],))
        self._jobs[actor,key]=job.ref;self._reserve(op,job.ref)
        self._window_comparisons[actor,key]=(request,rows,attrs(snapshot))
        return job.ref

class CueCanonicalEngine(_CueComparison,PaidCanonicalComparisonEngine):
    SCHEMA='ft-canonical-cue-comparison-a12c-v1'
    @staticmethod
    def _registry():return {**PaidCanonicalComparisonEngine._registry(),'CueComparisonRequest':CueComparisonRequest}

class CueWorkflowEngine(_CueComparison,PaidWorkflowComparisonEngine):
    SCHEMA='ft-workflow-cue-comparison-a12c-v1'
    @staticmethod
    def _registry():return {**PaidWorkflowComparisonEngine._registry(),'CueComparisonRequest':CueComparisonRequest}

def prepare(engine,intake):
    text=cue_windows(engine,intake);typ=CueCanonicalEngine if loads(intake)['setting']=='canonical' else CueWorkflowEngine
    return typ.from_native(engine.checkpoint()),CueComparisonRequest('ft-cue-comparison:'+digest(text),text,(intake,))
