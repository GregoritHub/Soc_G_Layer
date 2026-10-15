"""Owned paid closure after social training; certificates are not competence."""
from copy import deepcopy
from hashlib import sha256
from hle_unified.selection_records import dumps, loads
from hle_unified.material import attrs
from hle_unified.crossing_records import CrossingRequest
from hle_unified.workflow_records import WorkflowRequest
from hle_unified.shell_records import EncounterRequest
from hle_unified.development_policy import opportunity
from hle_unified.records import ObjectRef
from .content import ContentBridge, semantic_scope
from .historical import type_map
from .retention import Demand, RetentionLedger
from .autonomous_capability import discover_capability_candidates
from .autonomous_reuse import _ledger_record, _restore_ledger
from .social_training import request_record


class SocialClosureController:
    VERSION = 'ft-owned-social-closure-v1'

    def __init__(self, engine, training):
        from .social_training_audit import audit_social_training
        checkpoint = training.checkpoint(engine)
        audit_social_training(engine, checkpoint)
        if training.phase not in ('complete', 'unqualified'):
            raise ValueError('finished actual owned training required')
        self.actor = training.actor
        self.setting = training.setting
        self.training_checkpoint = checkpoint
        self.training_native = engine.checkpoint()
        self.prefix_count = len(engine.world.journal())
        self.start_count = None
        self.demand = Demand(**dict(training.scope, target=training.plan['episodes'][0]['target']))
        self.ledger = RetentionLedger(ContentBridge(engine))
        self.bridge = ContentBridge(engine)
        self.phase = 'discover'
        self.plan = None
        self.index = 0
        self.events = []
        self.certificate_key = None
        self.terminal = None

    def _discover(self, engine):
        training = loads(self.training_checkpoint)
        ep = training['plan']['episodes'][0]
        source = attrs(engine.world.resolve(ep['source_operation']))
        uses = [x for x in training['events'] if x['phase_before'] == 'content'
                and x['request']['fields']['target'] == self.demand.target
                and x['work']['status'] == 'succeeded']
        if not uses:
            return None
        use = uses[0]
        final = attrs(engine.world.resolve(use['work']['operation']))
        tm = type_map(self.bridge.tim(self.actor))
        kept = (ep['source'], final.get('binding') or final.get('result'))
        view = engine.participant_view(self.actor)
        if any(ref is None or ref not in view._bindings or
               view._bindings[ref].endorsement.value in ('retracted', 'disputed') for ref in kept):
            return None
        if (source.get('origin'), source.get('destination'), final.get('origin'), final.get('destination')) != (
                tm['complementary_perspective'], ep['destination'], ep['destination'], tm['native_perspective']):
            return None
        for row in (source, final):
            if (row.get('actor'), row.get('status'), row.get('context'), semantic_scope(engine, row)) != (
                    self.actor, 'succeeded', self.demand.context, self.demand.target):
                return None
        if final.get('source.0') != ep['source']:
            return None
        return dict(source=ep['source'], destination=ep['destination'], kept=kept,
                    returns=(source['key'], final['key']),
                    return_refs=(ep['source_operation'], use['work']['operation']))

    def _key(self, phase):
        return 'ft-social-closure:' + sha256(dumps((self.actor, self.prefix_count)).encode()).hexdigest()[:16] + ':' + str(self.index) + ':' + phase

    def step(self, engine, *, work_limit=1, interrupted=False):
        if engine is not self.bridge.engine or type(work_limit) is not int or work_limit < 1 or type(interrupted) is not bool:
            raise ValueError('paired engine, positive exact work bound and explicit interruption required')
        if self.terminal is not None:
            return deepcopy(self.terminal)
        if self.start_count is None:
            self.start_count = len(engine.world.journal())
        before = len(engine.world.journal())
        phase = self.phase
        snapshot = engine.participant_view(self.actor).bytes()
        request = work = exposure = certificate = None
        if phase == 'discover':
            self.plan = self._discover(engine)
            self.phase = 'use' if self.plan else 'deferred'
        elif phase in ('use', 'shell'):
            view = engine.participant_view(self.actor)
            if phase == 'use':
                typ = CrossingRequest if self.setting == 'canonical' else WorkflowRequest
                domain = 'personal' if self.plan['destination'] == 'I' else 'system'
                recipe = ('use-' if self.setting == 'canonical' else 'workflow-use-') + domain + '-v1'
                r = typ(self._key('use'), self.actor, recipe, self.demand.context, self.demand.cue,
                        (self.plan['source'],), tuple(p.address for p in view.resolve(self.demand.target)), self.demand.target)
            else:
                known, sources = opportunity(view, self.demand.target, self.demand.context)
                evidence = tuple(p.address for source in sources for p in view.resolve(source))
                r = EncounterRequest(self._key('shell'), self.actor, self.demand.target,
                    self.demand.context, self.demand.cue, known.get('partner') or self.demand.target,
                    ObjectRef(self.actor, 1), evidence)
            request = request_record(r)
            work = self.bridge.execute(r, quantum=work_limit,
                consumed=(self.plan['source'],) if phase == 'use' else ())
            if work['status'] in ('failed', 'cancelled'):
                self.phase = 'failed'
            elif work['status'] == 'succeeded':
                self.phase = 'shell' if phase == 'use' else 'expose'
        elif phase == 'expose':
            exposure = self.ledger.expose(self.actor, self.demand, self.plan['kept'],
                self.plan['returns'], self._key('shell'), self._key('use'), interrupted=interrupted)
            self.index += 1
            self.phase = 'use' if self.index < 2 else 'certify' if exposure['closed'] else 'open'
        elif phase == 'certify':
            candidates = discover_capability_candidates(engine, self.actor, self.demand)
            if not candidates:
                self.phase = 'closed'
            else:
                selected = candidates[0]
                self.certificate_key = 'ft-social-certificate:' + sha256(dumps((self.actor, self.demand.record(), self.prefix_count)).encode()).hexdigest()[:20]
                certificate = self.ledger.certify(self.certificate_key, self.actor, self.demand,
                    selected['capacity_ref'], selected['content_use_keys'])
                self.phase = 'certified'
        else:
            raise ValueError('unknown social closure phase')
        row = dict(index=len(self.events), before=before, after=len(engine.world.journal()),
            phase_before=phase, phase=self.phase, episode_index=self.index, view=snapshot,
            request=request, work=work, exposure=deepcopy(exposure), certificate=deepcopy(certificate),
            interrupted=interrupted)
        self.events.append(row)
        if self.phase in ('certified', 'closed', 'open', 'deferred', 'failed'):
            self.terminal = deepcopy(row)
        return deepcopy(row)

    def checkpoint(self, engine):
        if engine is not self.bridge.engine:
            raise ValueError('paired engine required')
        return dumps(dict(version=self.VERSION, native_sha256=sha256(engine.checkpoint().encode()).hexdigest(),
            actor=self.actor, setting=self.setting, training_checkpoint=self.training_checkpoint,
            training_native=self.training_native, prefix_count=self.prefix_count, start_count=self.start_count,
            demand=self.demand.record(), plan=self.plan, phase=self.phase, index=self.index,
            events=self.events, work=self.bridge.events, ledger=_ledger_record(self.ledger),
            certificate_key=self.certificate_key, terminal=self.terminal))

    @classmethod
    def restore(cls, text, engine):
        from .social_closure_audit import audit_social_closure
        audit_social_closure(engine, text)
        d = loads(text)
        obj = cls.__new__(cls)
        for key in ('actor', 'setting', 'training_checkpoint', 'training_native', 'prefix_count',
                    'start_count', 'plan', 'phase', 'index', 'events', 'certificate_key', 'terminal'):
            setattr(obj, key, deepcopy(d[key]))
        obj.demand = Demand(**d['demand'])
        obj.ledger = _restore_ledger(d['ledger'], engine)
        obj.bridge = ContentBridge(engine)
        obj.bridge.events = deepcopy(d['work'])
        if obj.checkpoint(engine) != text:
            raise ValueError('closure restart differs')
        return obj
