"""Owned admission only; no selector, fulfillment, free work or goal invention."""
from copy import deepcopy
from hle import model_a
from hle_unified.selection_records import dumps, loads, demand_value
from hle_unified.workflow_selection_records import demand_value as workflow_need
from hle_unified.self_content import decode


class DemandLedger:
    VERSION = 'owned-demand-admission-v1'

    def __init__(self):
        self.turn = 0
        self.demands = {}
        self.first_seen = {}
        self.events = []
        self.cursor = None

    def scan(self, engine, actor, state, *, limit=128):
        if type(limit) is not int or not 1 <= limit <= 128:
            raise ValueError('bounded admission limit required')
        view = engine.participant_view(actor)
        # Latest *owned* revision, never a hidden material head.
        heads = {}
        for binding in view.snapshot.bindings:
            if binding.actor == actor:
                old = heads.get(binding.ref.identity)
                if old is None or binding.ref.revision > old.ref.revision:
                    heads[binding.ref.identity] = binding
        eligible = {}
        for b in heads.values():
            if b.endorsement.value in ('retracted', 'disputed') or len(b.content) != 1:
                continue
            p = b.content[0]
            if p.relation not in ('c6.need', 'c7ws.need'):
                continue
            receipt = view.receipt(b.receipt)
            if (receipt is None or not receipt.complete or receipt.actor != actor
                    or receipt.operation != 'bind' or receipt.spent < receipt.required):
                continue
            if (p.subject, p.context) != (b.target, b.context):
                continue
            try:
                payload = (demand_value if p.relation == 'c6.need' else workflow_need)(decode(p.object))
            except (ValueError, TypeError, KeyError):
                continue
            identity = dumps((actor, b.ref))
            eligible[identity] = dict(actor=actor, binding=b.ref, receipt=b.receipt,
                context=b.context, cue=b.cue, target=b.target, relation=p.relation,
                payload=payload, raw_payload=p.object)
        for key in eligible:
            self.first_seen.setdefault(key, self.turn)
        suspended = []
        for key, demand in self.demands.items():
            if demand['actor'] == actor and key not in eligible and demand['status'] != 'suspended':
                demand['status'] = 'suspended'
                demand['reason'] = 'owned_need_missing_withdrawn_or_superseded'
                suspended.append(key)
        waiting = sorted((k for k in eligible if k not in self.demands),
                         key=lambda k: (self.first_seen[k], k))
        admitted = waiting[:limit]
        for key in admitted:
            self.demands[key] = dict(eligible[key], first_seen=self.first_seen[key],
                                    admitted_at=self.turn, status='pending', reason=None)
        omitted = waiting[limit:]
        self.cursor = omitted[0] if omitted else None
        aspects = tuple(p.aspect for p in state.pending)
        seats = tuple(model_a.position_of(state.tim, aspect) for aspect in aspects)
        creative_charge = tuple(sorted(state.at(2).charge))
        pressure = dict(tim=state.tim, pending_aspects=aspects, pending_seats=seats,
            pending_count=len(aspects), creative_charge=creative_charge,
            retained=tuple(sorted(state.retained)),
            wallet={k:engine.wallet(actor)[k] for k in ('energy','time')},
            active=any(p in (3,4) for p in seats) and not creative_charge)
        row = dict(turn=self.turn, actor=actor, limit=limit,
            journal_count=len(engine.world.journal()), access_count=len(engine.access._events),
            eligible=eligible, admitted=admitted, omitted=omitted,
            suspended=sorted(suspended), cursor=self.cursor, pressure=pressure,
            demands=deepcopy(self.demands), first_seen=deepcopy(self.first_seen))
        self.events.append(row)
        self.turn += 1
        return deepcopy(row)

    def checkpoint(self):
        return dumps(dict(version=self.VERSION, turn=self.turn, demands=self.demands,
            first_seen=self.first_seen, cursor=self.cursor, events=self.events))

    @classmethod
    def restore(cls, text):
        data = loads(text)
        if data.pop('version') != cls.VERSION:
            raise ValueError('wrong demand checkpoint version')
        result = cls()
        if set(data) != {'turn','demands','first_seen','cursor','events'}:
            raise ValueError('invalid demand checkpoint fields')
        result.__dict__.update(data)
        if result.turn != len(result.events):
            raise ValueError('invalid demand turn')
        return result
