"""Owned-observation practice panel, separate from the main-task selector."""
from copy import deepcopy
from hashlib import sha256
from itertools import product
from hle_unified.records import Procedure
from hle_unified.operation_records import OperationRequest
from hle_unified.selection_records import dumps, loads


def digest(text): return sha256(text.encode()).hexdigest()


SOURCES = frozenset(('0eb6ec03ff64f4da8c297527fedb95d71398b7bb066a33f0c080f4881ac7b1d0',
                     '50ed4da94e7a03066d5b1099f1fc78f6e0d5ffa60d8af9a0e68b67735294080e'))


def owned_plan(view, actor, context):
    groups = {}
    for p in view.snapshot.particulars:
        groups.setdefault(p.source, {})[p.address.key] = p.value
    procedures = sorted((r for r, d in groups.items() if any(type(p) is Procedure and
        p.executor == 'u4.repair.v1' and p.inputs == ('target','tool','stock') and
        not p.steps and not p.preconditions and not p.effects for p in d.values())
        and not view.can_use(r, context)), key=dumps)
    observations = {}
    for r, d in groups.items():
        if (r.identity.namespace == 'u4.observation' and d.get('primitive') == 'inspect'
            and d.get('outcome') == 'succeeded' and d.get('actor') == actor
            and d.get('context') == context and d.get('target') is not None):
            observations[d['target'].identity] = (r, d)
    pools = {'target': [], 'tool': [], 'stock': []}
    for observation, d in observations.values():
        if d.get('owner') != actor or d.get('custodian') != actor: continue
        target = d['target']; condition = d.get('condition')
        if condition == 'damaged': pools['target'].append(target)
        if condition == 'serviceable': pools['tool'].append(target)
        direct = groups.get(target, {})
        if (condition == 'stock' and type(d.get('available')) is int and d['available'] >= 1
            and ('purpose' not in direct or direct['purpose'] == 'repair')):
            pools['stock'].append(target)
    candidates = tuple(sorted((tuple(row) for row in product(*(pools[k] for k in ('target','tool','stock')))
        if len({r.identity for r in row}) == 3), key=dumps)) if procedures else ()
    if len(candidates) > 512: raise ValueError('registered practice bound exceeded')
    return (procedures[0] if procedures else None), candidates


class OwnedRepairPractice:
    VERSION = 'ft-owned-repair-practice-a2-v1'

    def __init__(self, engine, intake):
        native = engine.checkpoint(); i = loads(intake)
        if digest(native) not in SOURCES or i['expected_native_sha256'] != digest(native) or i['phase'] != 'complete':
            raise ValueError('exact accepted completed intake required')
        self.actor = i['actor']; self.context = i['context']
        if self.actor in engine._locks: raise ValueError('unlocked actor required')
        self.source_native_sha256 = digest(native); self.intake_sha256 = digest(intake)
        self.expected_native_sha256 = digest(native)
        self.procedure, self.plan = owned_plan(engine.participant_view(self.actor), self.actor, self.context)
        self.index = 0; self.phase = 'practice' if self.plan else 'exhausted'
        self.events = []; self.practice = None; self.skill_acquired = False
        self.main_execution_authorized = False; self.comparison_paid = False
        self.td5_admitted = False; self.history_choice = False

    def key(self): return 'ft-skill-practice:' + self.source_native_sha256 + ':' + str(self.index)

    def step(self, engine, *, work_limit=1, cancel=False):
        if type(work_limit) is not int or work_limit < 1 or type(cancel) is not bool:
            raise ValueError('positive exact work bound required')
        if digest(engine.checkpoint()) != self.expected_native_sha256: raise ValueError('native pairing')
        if self.phase in ('complete','exhausted','cancelled'): return None
        phase = self.phase; key = self.key() + ':' + phase; cid = key + ':step:' + str(len(self.events))
        before = len(engine.world.journal()); wallet = dict(engine.wallet(self.actor))
        if cancel:
            if (self.actor,key) not in engine._jobs: raise ValueError('existing partial work required')
            engine.cancel(cid+':cancel', self.actor, key); self.phase = 'cancelled'
        else:
            if (self.actor,key) not in engine._jobs:
                view = engine.participant_view(self.actor)
                if phase == 'practice':
                    target,tool,stock = self.plan[self.index]
                    evidence = tuple(p.address for p in view.snapshot.particulars if p.source in
                        (target,tool,stock,self.procedure) or p.value in (target,tool,stock))
                    r = OperationRequest(key,self.actor,'repair',self.context,target=target,tool=tool,stock=stock,evidence=evidence)
                elif phase == 'read':
                    event = engine.job_status(self.actor,self.key()+':practice')['result']
                    delivery = self.key()+':delivery'; engine.deliver_event(delivery,event,self.actor)
                    r = OperationRequest(key,self.actor,'read',self.context,delivery=delivery)
                else:
                    r = OperationRequest(key,self.actor,'acquire',self.context,procedure=self.procedure,practice=self.practice)
                engine.start(cid+':start',r)
            status = engine.job_status(self.actor,key)['status']
            if status not in ('ready','succeeded','failed','cancelled'): engine.advance(cid+':work',self.actor,key,work_limit)
            if engine.job_status(self.actor,key)['status'] == 'ready': engine.commit(cid+':commit',self.actor,key)
            status = engine.job_status(self.actor,key)['status']
            if phase == 'practice' and status in ('succeeded','failed'): self.phase = 'read'
            elif status == 'failed': raise ValueError('unexpected read/acquisition failure')
            elif phase == 'read' and status == 'succeeded':
                facts = {p.address.key:p.value for p in engine.participant_view(self.actor).snapshot.particulars
                         if p.address.delivery == self.key()+':delivery'}
                if facts.get('outcome') == 'succeeded': self.practice = facts['event']; self.phase = 'acquire'
                else:
                    self.index += 1; self.phase = 'practice' if self.index < len(self.plan) else 'exhausted'
            elif phase == 'acquire' and status == 'succeeded':
                self.skill_acquired = engine.participant_view(self.actor).can_use(self.procedure,self.context)
                if not self.skill_acquired: raise ValueError('native acquisition receipt missing')
                self.phase = 'complete'
        after_wallet = dict(engine.wallet(self.actor))
        self.events.append(dict(index=len(self.events),phase=phase,job=key,action='cancel' if cancel else 'step',
            before=before,after=len(engine.world.journal()),work_limit=work_limit,
            status=engine.job_status(self.actor,key)['status'],wallet_before=wallet,wallet_after=after_wallet,
            debit={u:wallet[u]-after_wallet[u] for u in ('energy','time')}))
        self.expected_native_sha256 = digest(engine.checkpoint())
        return deepcopy(self.events[-1])

    def checkpoint(self, engine):
        if digest(engine.checkpoint()) != self.expected_native_sha256: raise ValueError('native pairing')
        return dumps(dict(version=self.VERSION,**deepcopy(self.__dict__)))

    @classmethod
    def restore(cls,text,engine,original,intake):
        from .owned_repair_practice_audit import audit_owned_repair_practice
        audit_owned_repair_practice(engine,original,intake,text)
        data=loads(text);data.pop('version');obj=cls.__new__(cls);obj.__dict__.update(data)
        if obj.checkpoint(engine)!=text:raise ValueError('adapter roundtrip')
        return obj
