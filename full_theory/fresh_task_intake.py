"""Fixed supplied task intake, paid natively; no goal, route or choice policy."""
from copy import deepcopy
from dataclasses import replace
from functools import lru_cache
from hashlib import sha256
from hle_unified import codec
from hle_unified.records import Account, ObjectRef, ObjectId
from hle_unified.particulars import Selector, DetailAddress
from hle_unified.operation_records import OperationRequest
from hle_unified.selection_records import dumps, loads
from hle_unified.self_content import decode, encode
from .demand_controller import IntegratedDemandController


def digest(text): return sha256(text.encode()).hexdigest()


@lru_cache(maxsize=2)
def validate_original(native, source, binding, setting):
    from hle_unified.selection_execution import SelectionEngine
    from hle_unified.workflow_selection_execution import WorkflowFinalSelectionEngine
    from .social_feedback_binding_audit import audit_social_feedback_binding
    typ = SelectionEngine if setting == 'canonical' else WorkflowFinalSelectionEngine
    old = typ.restore(native)
    audit_social_feedback_binding(old, source, binding)
    return True


class FreshTaskIntake:
    VERSION = 'ft-fixed-fresh-task-intake-v1'

    def __init__(self, engine, source, binding, mask):
        if type(mask) is not int or not 1 <= mask <= 15:
            raise ValueError('fixed nonempty four-priority mask required')
        s = loads(source); b = loads(binding); native = engine.checkpoint()
        validate_original(native, source, binding, s['setting'])
        actor = s['actor']; view = engine.participant_view(actor)
        demands = IntegratedDemandController.restore(s['demand_controller']).effective_demands()
        if s['phase'] != 'complete' or actor in engine._locks:
            raise ValueError('completed unlocked original source required')
        for owned in view._heads.values():
            if owned.endorsement.value in ('retracted', 'disputed'):
                continue
            if any(p.relation in ('c6.need', 'c7ws.need') for p in owned.content):
                if demands.get(dumps((actor, owned.ref)), {}).get('status') != 'fulfilled':
                    raise ValueError('older unresolved owned need cannot be bypassed')
        old = view._bindings[s['request']['fields']['demand']]
        draft = engine.world.resolve(old.ref); account = draft.facet(Account)
        payload = decode(old.content[0].object)
        payload['weights' if s['setting'] == 'canonical' else 'priorities'] = tuple(
            10 if mask & (1 << i) else 0 for i in range(4))
        key = digest(source)[:20] + ':' + str(mask)
        task = ObjectRef(ObjectId('ft.fresh.task', key), 1)
        if task.identity in engine.world._heads:
            raise ValueError('fresh task identity required')
        proposition = replace(old.content[0], object=encode(payload))
        fresh = replace(draft, ref=task, label='Fixed route-free fresh task',
            facets=(replace(account, content=(proposition,), sources=account.sources+(task,)),))
        self.actor = actor; self.setting = s['setting']; self.mask = mask
        self.source_sha256 = digest(source); self.binding_sha256 = digest(binding)
        self.source_native_sha256 = digest(native); self.expected_native_sha256 = digest(native)
        self.start_count = len(engine.world.journal()); self.context = old.context
        self.task = task; self.draft = codec.dumps(fresh); self.payload = proposition.object
        self.original_particulars = tuple((a.delivery,a.key) for a in old.particulars)
        self.jobs = ('ft-fresh-read:' + key, 'ft-fresh-bind:' + key)
        if any((actor, k) in engine._jobs for k in self.jobs):
            raise ValueError('cannot adopt existing task work')
        self.reserve = b['reserve']; self.history = b['history']
        self.controller_prefix = s['demand_controller']
        self.events = []; self.receipt = None
        self.comparison_paid = False; self.execution_authorized = False
        self.td5_admitted = False; self.history_choice = False

    def step(self, engine, *, work_limit=1):
        if type(work_limit) is not int or work_limit < 1:
            raise ValueError('positive exact work quantum required')
        if digest(engine.checkpoint()) != self.expected_native_sha256:
            raise ValueError('exact intake native pairing required')
        if self.receipt is not None:
            return deepcopy(self.events[-1])
        actor = self.actor; read, bind = self.jobs; delivery = read + ':delivery'
        kind = 'read' if (actor, read) not in engine._jobs or engine.job_status(actor, read)['status'] != 'succeeded' else 'bind'
        key = read if kind == 'read' else bind
        cid = key + ':step:' + str(len(self.events))
        before = len(engine.world.journal()); wallet = dict(engine.wallet(actor))
        if not self.events:
            engine.declare(read + ':draft', (codec.loads(self.draft),))
        if (actor, key) not in engine._jobs:
            if kind == 'read':
                engine.disclose(delivery, actor, self.task,
                    (Selector('ft.fresh.payload', 'definition', ('facets','0','content','0','object')),), self.task)
                request = OperationRequest(key, actor, 'read', self.context, delivery=delivery)
            else:
                request = OperationRequest(key, actor, 'bind', self.context, binding=self.task,
                    evidence=tuple(DetailAddress(*a) for a in self.original_particulars) + (DetailAddress(delivery, 'ft.fresh.payload'),))
            engine.start(cid + ':start', request)
        status = engine.job_status(actor, key)
        if status['status'] not in ('succeeded','failed','cancelled'):
            if status['status'] != 'ready' and not engine.resource_exhausted(actor, key):
                engine.advance(cid + ':work', actor, key, work_limit)
            if engine.job_status(actor, key)['status'] == 'ready':
                engine.commit(cid + ':commit', actor, key)
        status = engine.job_status(actor, key)
        if kind == 'bind' and status['status'] == 'succeeded':
            owned = engine.participant_view(actor)._bindings[self.task]
            self.receipt = dict(task=self.task, read_operation=engine._jobs[actor,read],
                bind_operation=engine._jobs[actor,bind], owned_receipt=owned.receipt, energy=5, time=5)
        after_wallet = dict(engine.wallet(actor))
        event = dict(index=len(self.events), kind=kind, job=key, before=before,
            after=len(engine.world.journal()), wallet_before=wallet, wallet_after=after_wallet,
            debit={u:wallet[u]-after_wallet[u] for u in ('energy','time')},
            work_limit=work_limit, status=status['status'])
        self.events.append(event); self.expected_native_sha256 = digest(engine.checkpoint())
        return deepcopy(event)

    def checkpoint(self, engine):
        if digest(engine.checkpoint()) != self.expected_native_sha256:
            raise ValueError('unrelated native extension')
        return dumps(dict(version=self.VERSION, native_sha256=self.expected_native_sha256, **deepcopy(self.__dict__)))

    @classmethod
    def restore(cls, text, engine, original, source, binding):
        from .fresh_task_intake_audit import audit_fresh_task_intake
        audit_fresh_task_intake(engine, original, source, binding, text)
        d = loads(text); d.pop('version'); d.pop('native_sha256')
        obj = cls.__new__(cls); obj.__dict__.update(d)
        if obj.checkpoint(engine) != text: raise ValueError('intake roundtrip differs')
        return obj
