"""Exact post-social accounting over committed work; no choice effect yet."""
from copy import deepcopy
from hashlib import sha256
from hle_unified.selection_records import dumps, loads
from hle_unified.conditioning_audit import completed_use
from .reserve import ReserveLedger
from .use_history import UseHistoryLedger, classifications_for, native_snapshot


def _hash(text):
    return sha256(text.encode()).hexdigest()


def _segment_ends(transactions, actor, start, end):
    counts = completed_use(transactions[:start])[1][actor]
    ends = []; current = start
    for boundary in range(start + 1, end + 1):
        observed = completed_use(transactions[:boundary])[1][actor]
        if any(observed[e] - counts[e] > 9 for e in counts):
            if boundary - 1 == current:
                raise ValueError('one transaction exceeds registered observer delta bound')
            ends.append(boundary - 1); current = boundary - 1
            counts = completed_use(transactions[:current])[1][actor]
            if any(observed[e] - counts[e] > 9 for e in counts):
                raise ValueError('one transaction exceeds registered observer delta bound')
    if current < end:ends.append(end)
    return ends


def _prefixes(source):
    reuse = loads(source)
    closure = loads(reuse['prefix_checkpoint'])
    training = loads(closure['training_checkpoint'])
    peer = loads(training['prefix_peer'])
    social = loads(peer['social'])
    reserve = loads(loads(loads(social['cycle'])['candidates'])['binding'])['reserve']
    return reuse, training, social, reserve


class SocialPostUseBinding:
    VERSION = 'ft-post-social-reserve-history-binding-v1'

    def __init__(self, engine, source):
        from .social_reuse_audit import audit_social_reuse
        audit_social_reuse(engine, source)
        reuse, training, social, reserve_prefix = _prefixes(source)
        txs = tuple(engine.world.journal())
        self.actor = reuse['actor']
        self.native_sha256 = _hash(engine.checkpoint())
        self.reuse_sha256 = _hash(source)
        self.social_prefix_sha256 = _hash(training['prefix_peer'])
        self.reserve_prefix = reserve_prefix
        self.history_prefix = social['history']
        reserve = ReserveLedger.restore(reserve_prefix)
        history = UseHistoryLedger.restore(self.history_prefix)
        if (reserve.actor, history.actor, reserve.policy, history.policy) != (self.actor, self.actor, 'load-v1', 'success-v1'):
            raise ValueError('original owned engineering policy prefix required')
        self.windows = []
        self.reserve_bindings = []
        start = history.journal_count
        episodes = []
        active = None
        for event in training['events']:
            if event['phase_before'] == 'respond' and active is None:
                active = event['before']
            if event['phase_before'] == 'practice' and event['work']['status'] == 'succeeded':
                episodes.append((active, event['after'], event['work']['operation']))
                active = None
        if len(episodes) != 2 or training['phase'] != 'complete':
            raise ValueError('two real independently completed training episodes required')
        attempts = loads(reuse['route_policy'])['attempts']
        if len(attempts) != 1:
            raise ValueError('one exact owned later admission required')
        admission = attempts[0]['inventory']['at_tick']
        identity = 'ft-post-social:' + self.reuse_sha256[:20]

        def observe_one(end, kind, tag, demand_id):
            nonlocal start
            if not start <= end <= len(txs):
                raise ValueError('accounting windows overlap or escape native journal')
            if end == start:
                return
            outcome = dict(status='failed' if tag == 'failed' else 'succeeded',
                supported=False, rehearsal=tag == 'rehearsal', demand_id=demand_id, route_id=demand_id)
            before = native_snapshot(txs[:start], self.actor)
            after = native_snapshot(txs[:end], self.actor)
            delta = sum(after['counts'][e] - before['counts'][e] for e in before['counts'])
            rows = classifications_for(txs[:start], txs[:end], self.actor, history.turn + 1, tag, outcome) if delta else ()
            event = history.observe(txs[:end], history.turn + 1, rows)
            self.windows.append(dict(kind=kind, start=start, end=end, tag=tag,
                demand_id=demand_id, event=event))
            start = end

        def observe(end, kind, tag, demand_id):
            if not start <= end <= len(txs):
                raise ValueError('accounting interval escapes native journal')
            for boundary in _segment_ends(txs, self.actor, start, end):
                observe_one(boundary, kind, tag, demand_id)
            if len(history.events) != history.event_count:
                raise ValueError('observer cannot evict immutable original history events')

        observe(episodes[0][0], 'preparation', 'rehearsal', identity + ':preparation')
        for index, (begin, end, operation) in enumerate(episodes):
            demand_id = identity + ':practice:' + str(index)
            if begin != start:
                raise ValueError('independent episode leaves an unclassified gap')
            admission_event = reserve.admit(demand_id, training['scope']['load'])
            if admission_event['preparation']:
                raise ValueError('retrospective receipt cannot supply unpaid preparation')
            completion = reserve.complete(demand_id, 'independent')
            observe(end, 'independent-practice', 'independent', demand_id)
            self.reserve_bindings.append(dict(demand_id=demand_id, start=begin, end=end,
                operation=operation, admission=admission_event, completion=completion))
        observe(admission, 'preparation', 'rehearsal', identity + ':later-preparation')
        demand_id = reuse['request']['fields']['key']
        event = reserve.admit(demand_id, reuse['required']['load'])
        completed = reuse['phase'] == 'complete'
        completion = reserve.complete(demand_id, 'independent') if completed else None
        self.reserve_bindings.append(dict(demand_id=demand_id, start=admission, end=len(txs),
            operation=None if not completed else engine._jobs[self.actor, reuse['consumer_key']],
            admission=event, completion=completion))
        tag = 'independent' if completed else 'failed' if reuse['phase'] in ('deferred','failed','cancelled') else 'rehearsal'
        observe(len(txs), 'later-use', tag, demand_id)
        self.reserve = reserve.checkpoint()
        self.history = history.checkpoint()

    def checkpoint(self):
        return dumps(dict(version=self.VERSION, actor=self.actor, native_sha256=self.native_sha256,
            reuse_sha256=self.reuse_sha256, social_prefix_sha256=self.social_prefix_sha256,
            reserve_prefix=self.reserve_prefix, history_prefix=self.history_prefix,
            reserve=self.reserve, history=self.history, windows=deepcopy(self.windows),
            reserve_bindings=deepcopy(self.reserve_bindings)))

    @classmethod
    def restore(cls, text, engine, source):
        from .social_feedback_binding_audit import audit_social_feedback_binding
        audit_social_feedback_binding(engine, source, text)
        data = loads(text)
        obj = cls.__new__(cls)
        for name, value in data.items():
            if name != 'version':setattr(obj, name, deepcopy(value))
        if obj.checkpoint() != text:
            raise ValueError('post-social binding restoration differs')
        return obj
