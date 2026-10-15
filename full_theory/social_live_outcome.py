"""Live continuation with immutable prior credit and pending outcome windows."""
from copy import deepcopy
from hashlib import sha256
from hle_unified import codec
from hle_unified.selection_records import dumps, loads
from .retention import Demand
from .reserve import ReserveLedger
from .use_history import UseHistoryLedger, classifications_for
from .social_reuse import SocialReuseController
from .social_feedback_binding import _segment_ends


def _hash(text):
    return sha256(text.encode()).hexdigest()


class SocialLiveOutcome:
    VERSION = 'ft-post-social-live-outcome-v1'

    def __init__(self, engine, source, binding):
        from .social_feedback_binding_audit import audit_social_feedback_binding
        audit_social_feedback_binding(engine, source, binding)
        r, b = loads(source), loads(binding)
        admission = b['reserve_bindings'][-1]
        if r['phase'] not in ('route', 'consumer', 'deferred') or admission['completion'] is not None:
            raise ValueError('uncompleted admitted source required')
        if r['phase'] != 'deferred' and admission['admission']['preparation']:
            raise ValueError('unpaid preparation debt cannot enter live work')
        self.actor = r['actor']
        self.source_sha256 = _hash(source)
        self.binding_sha256 = _hash(binding)
        self.start = len(engine.world.journal())
        self.prefix_sha256 = _hash(codec.dumps(tuple(engine.world.journal())))
        self.history_prefix = b['history']
        self.reserve_prefix = b['reserve']
        self.history = self.history_prefix
        self.reserve = self.reserve_prefix
        self.pending_start = self.start
        self.windows = []
        self.events = []
        self.completion = None
        self.cycle = SocialReuseController.restore(source, engine)
        self.status = 'deferred' if r['phase'] == 'deferred' else 'pending'
        if loads(self.history)['journal_count'] != self.start:
            raise ValueError('exact already-emitted history boundary required')

    def step(self, engine, *, work_limit=1):
        if type(work_limit) is not int or work_limit < 1:
            raise ValueError('positive exact work limit required')
        if engine is not self.cycle.ledger.engine:
            raise ValueError('paired native engine required')
        if _hash(codec.dumps(tuple(engine.world.journal())[:self.start])) != self.prefix_sha256:
            raise ValueError('immutable native prefix differs')
        if self.status != 'pending':
            return deepcopy(self.events[-1]) if self.events else None
        before = len(engine.world.journal())
        wallet = dict(engine.wallet(self.actor))
        phase = self.cycle.phase
        self.cycle.step(engine, None, Demand(**self.cycle.required), work_limit=work_limit)
        after = len(engine.world.journal())
        now = dict(engine.wallet(self.actor))
        terminal = self.cycle.terminal is not None
        if terminal:
            self.status = 'complete' if self.cycle.phase == 'complete' else 'failed'
            if self.status == 'complete':
                reserve = ReserveLedger.restore(self.reserve)
                self.completion = reserve.complete(self.cycle.request.key, 'independent')
                self.reserve = reserve.checkpoint()
            history = UseHistoryLedger.restore(self.history)
            txs = tuple(engine.world.journal())
            tag = 'independent' if self.status == 'complete' else 'failed'
            outcome = dict(status='succeeded' if self.status == 'complete' else 'failed',
                supported=False, rehearsal=False, demand_id=self.cycle.request.key,
                route_id=self.cycle.request.key)
            start = self.pending_start
            for end in _segment_ends(txs, self.actor, start, after):
                rows = classifications_for(txs[:start], txs[:end], self.actor,
                    history.turn + 1, tag, outcome)
                event = history.observe(txs[:end], history.turn + 1, rows)
                self.windows.append(dict(start=start, end=end, tag=tag, event=event))
                start = end
            self.history = history.checkpoint()
            self.pending_start = after
        event = dict(index=len(self.events), before=before, after=after,
            phase_before=phase, phase=self.cycle.phase, work_limit=work_limit,
            wallet_before=wallet, wallet_after=now,
            debit={k:wallet[k]-now[k] for k in ('energy','time')}, status=self.status)
        self.events.append(event)
        return deepcopy(event)

    def checkpoint(self, engine):
        if engine is not self.cycle.ledger.engine:
            raise ValueError('paired native engine required')
        values = {k:deepcopy(v) for k,v in self.__dict__.items() if k != 'cycle'}
        return dumps(dict(version=self.VERSION, native_sha256=_hash(engine.checkpoint()),
            cycle=self.cycle.checkpoint(engine), **values))

    @classmethod
    def restore(cls, text, engine, source_engine, source, binding):
        from .social_live_outcome_audit import audit_social_live_outcome
        audit_social_live_outcome(engine, source_engine, source, binding, text)
        d = loads(text); obj = cls.__new__(cls)
        for name,value in d.items():
            if name not in ('version','native_sha256','cycle'):
                setattr(obj,name,deepcopy(value))
        obj.cycle = SocialReuseController.restore(d['cycle'], engine)
        if obj.checkpoint(engine) != text:
            raise ValueError('live outcome restore differs')
        return obj
