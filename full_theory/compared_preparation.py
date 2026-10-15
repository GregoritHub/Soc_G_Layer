"""Exact composition of settled comparison and fresh original task preparation.

The original social wrapper is immutable. This adapter grants no route authority.
"""
from copy import deepcopy
from hashlib import sha256
from hle_unified import codec
from hle_unified.selection_records import dumps, loads
from .social_preparation import SocialPaidPreparation
from .current_owned_admission_audit import audit_current_owned_admission


def digest(text):
    return sha256(text.encode()).hexdigest()


class ComparedSocialPreparation(SocialPaidPreparation):
    VERSION = 'ft-compared-social-preparation-v1'

    def __init__(self, engine, original, source, binding, domain, operands, admission):
        audit_current_owned_admission(engine, original, source, binding, domain, operands, admission)
        current = loads(admission)
        if not current['comparison_settled'] or current['admission'] is None:
            raise ValueError('settled current owned comparison required')
        # Never regenerate the original social wrapper against extended native state.
        super().__init__(original, source, binding)
        if any((self.actor, key) in engine._jobs for key in self.jobs) or self.actor in engine._locks:
            raise ValueError('fresh free preparation continuation required')
        self.comparison_native_sha256 = digest(engine.checkpoint())
        txs = tuple(engine.world.journal())
        self.comparison_count = len(txs)
        self.comparison_prefix_sha256 = digest(codec.dumps(txs))
        self.domain_sha256 = digest(domain)
        self.operands_sha256 = digest(operands)
        self.admission_sha256 = digest(admission)
        self.expected_native_sha256 = self.comparison_native_sha256
        self.execution_authorized = False
        self.history_choice = False

    def step(self, engine, *, work_limit=1):
        if digest(engine.checkpoint()) != self.expected_native_sha256:
            raise ValueError('unbound native extension')
        txs = tuple(engine.world.journal())
        if digest(codec.dumps(txs[:self.comparison_count])) != self.comparison_prefix_sha256:
            raise ValueError('immutable comparison prefix differs')
        event = super().step(engine, work_limit=work_limit)
        self.expected_native_sha256 = digest(engine.checkpoint())
        return event

    @classmethod
    def restore(cls, text, engine, comparison, original, source, binding, domain, operands, admission):
        from .compared_preparation_audit import audit_compared_preparation
        audit_compared_preparation(engine, comparison, original, source, binding, domain, operands, admission, text)
        data = loads(text); data.pop('version'); data.pop('native_sha256')
        obj = cls.__new__(cls); obj.__dict__.update(deepcopy(data))
        if obj.checkpoint(engine) != text:
            raise ValueError('composed checkpoint differs after restore')
        return obj
