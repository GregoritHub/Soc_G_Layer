"""Fresh paid task reads for an exact preserved post-social preparation debt.

This adapter does not choose or complete a route, replenish reserve, or award
independent-use credit. Partial reads leave the original history untouched.
"""
from copy import deepcopy
from hashlib import sha256

from hle_unified import codec
from hle_unified.operation_records import OperationRequest
from hle_unified.particulars import Selector, DetailAddress
from hle_unified.records import Account
from hle_unified.selection_records import dumps, loads
from .social_feedback_binding import _segment_ends
from .use_history import UseHistoryLedger, classifications_for, native_snapshot


def _hash(text):
    return sha256(text.encode()).hexdigest()


class SocialPaidPreparation:
    VERSION = 'ft-post-social-paid-preparation-v1'

    def __init__(self, engine, source, binding):
        from .social_feedback_binding_audit import audit_social_feedback_binding
        audit_social_feedback_binding(engine, source, binding)
        b = loads(binding); r = loads(source)
        admission = b['reserve_bindings'][-1]
        debt = admission['admission']['preparation']
        if type(debt) is not int or debt <= 0 or admission['completion'] is not None:
            raise ValueError('positive unpaid preparation debt required')
        request = r['request']['fields']
        if admission['demand_id'] != request['key']:
            raise ValueError('original demand admission required')
        actor = r['actor']; view = engine.participant_view(actor)
        owned = view._bindings[request['demand']]
        heads = [x.ref.revision for x in view.snapshot.bindings
                 if x.ref.identity == owned.ref.identity]
        receipt = view.receipt(owned.receipt)
        if (max(heads) != owned.ref.revision or owned.endorsement.value in ('retracted', 'disputed')
                or (owned.actor, owned.context, owned.cue, owned.target) !=
                   (actor, request['context'], request['cue'], request['target'])
                or len(owned.content) != 1 or receipt is None or not receipt.complete
                or receipt.actor != actor or receipt.spent < receipt.required):
            raise ValueError('current fully paid owned task required')
        obj = engine.world.resolve(request['demand'])
        accounts = [(i, f) for i, f in enumerate(obj.facets) if type(f) is Account]
        if len(accounts) != 1 or accounts[0][1].holder != actor or accounts[0][1].content != owned.content:
            raise ValueError('exact owned task account required')
        self.actor = actor
        self.source_sha256 = _hash(source)
        self.binding_sha256 = _hash(binding)
        self.source_native_sha256 = _hash(engine.checkpoint())
        self.start_count = len(engine.world.journal())
        self.prefix_sha256 = _hash(codec.dumps(tuple(engine.world.journal())))
        self.request = deepcopy(request)
        self.admission = deepcopy(admission)
        self.required = debt
        self.path = ('facets', str(accounts[0][0]), 'content', '0', 'object')
        self.payload = owned.content[0].object
        self.reserve = b['reserve']
        self.history_prefix = b['history']
        self.history = b['history']
        self.events = []
        self.receipts = []
        self.windows = []
        self.jobs = tuple('ft-social-preparation:' + self.binding_sha256[:20] + ':' + str(i)
                          for i in range(debt))
        if any((actor, key) in engine._jobs for key in self.jobs):
            raise ValueError('cannot adopt existing preparation work')
        if loads(self.history)['journal_count'] != self.start_count:
            raise ValueError('exact complete history boundary required')

    def step(self, engine, *, work_limit=1):
        if type(work_limit) is not int or work_limit < 1:
            raise ValueError('positive exact work bound required')
        txs = tuple(engine.world.journal())
        if _hash(codec.dumps(txs[:self.start_count])) != self.prefix_sha256:
            raise ValueError('immutable native source prefix differs')
        if len(self.receipts) == self.required:
            return deepcopy(self.events[-1])
        index = len(self.receipts); key = self.jobs[index]
        delivery = key + ':delivery'
        before = len(txs); wallet = dict(engine.wallet(self.actor))
        command = key + ':step:' + str(len(self.events))
        if (self.actor, key) not in engine._jobs:
            if self.actor in engine._locks:
                raise ValueError('free actor required for fresh preparation read')
            engine.disclose(delivery, self.actor, self.request['demand'],
                (Selector('ft.reserve.task', 'definition', self.path),), self.request['demand'])
            engine.start(command + ':start', OperationRequest(key, self.actor, 'read',
                self.request['context'], delivery=delivery))
        status = engine.job_status(self.actor, key)
        if status['status'] not in ('succeeded', 'failed', 'cancelled'):
            if status['status'] != 'ready' and not engine.resource_exhausted(self.actor, key):
                engine.advance(command + ':work', self.actor, key, work_limit)
            if engine.job_status(self.actor, key)['status'] == 'ready':
                engine.commit(command + ':commit', self.actor, key)
        status = engine.job_status(self.actor, key)
        if status['status'] == 'succeeded':
            if (status['required'], status['completed'], status['spent']) != (2, 2, 2):
                raise ValueError('exact two-unit read required')
            detail = engine.participant_view(self.actor).detail(DetailAddress(delivery, 'ft.reserve.task'))
            if detail is None or detail.source != self.request['demand'] or detail.value != self.payload or detail.path != self.path:
                raise ValueError('exact processed task definition required')
            self.receipts.append(dict(job=key, operation=engine._jobs[self.actor, key],
                delivery=delivery, demand=self.request['demand'], energy=2, time=2))
            history = UseHistoryLedger.restore(self.history)
            txs = tuple(engine.world.journal()); left = history.journal_count
            for end in _segment_ends(txs, self.actor, left, len(txs)):
                outcome = dict(status='succeeded', supported=False, rehearsal=True,
                    demand_id=self.admission['demand_id'], route_id=key)
                a = native_snapshot(txs[:left], self.actor); b = native_snapshot(txs[:end], self.actor)
                rows = classifications_for(txs[:left], txs[:end], self.actor,
                    history.turn + 1, 'rehearsal', outcome) if a['counts'] != b['counts'] else ()
                event = history.observe(txs[:end], history.turn + 1, rows)
                self.windows.append(dict(start=left, end=end, job=key, event=event)); left = end
            self.history = history.checkpoint()
        after_wallet = dict(engine.wallet(self.actor))
        event = dict(index=len(self.events), job=key, before=before,
            after=len(engine.world.journal()), wallet_before=wallet, wallet_after=after_wallet,
            debit={u: wallet[u] - after_wallet[u] for u in ('energy', 'time')},
            work_limit=work_limit, status=status['status'], bound=len(self.receipts),
            remaining=self.required-len(self.receipts))
        self.events.append(event)
        return deepcopy(event)

    def checkpoint(self, engine):
        return dumps(dict(version=self.VERSION, native_sha256=_hash(engine.checkpoint()),
            **deepcopy(self.__dict__)))

    @classmethod
    def restore(cls, text, engine, source_engine, source, binding):
        from .social_preparation_audit import audit_social_preparation
        audit_social_preparation(engine, source_engine, source, binding, text)
        data = loads(text); data.pop('version'); data.pop('native_sha256')
        obj = cls.__new__(cls); obj.__dict__.update(deepcopy(data))
        if obj.checkpoint(engine) != text:
            raise ValueError('preparation checkpoint differs after restore')
        return obj
