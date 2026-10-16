"""A8 immutable full canonical quotation; deliberately no native command API."""
import json
from hashlib import sha256
from math import prod
from pathlib import Path
from hle_unified.compact import unseal
from hle_unified.material import OperationStore, attrs
from hle_unified.operations import NativeAccess, wallet_address
from hle_unified.cognitive_routes import progress
from hle_unified.selection_records import dumps, loads, fields_of, SelectionRequest
from hle_unified.selection_execution import SelectionEngine

PROTOCOL = Path(__file__).resolve().parents[1]/'contracts/ft/FT7_Canonical_Quotation_A8_Protocol_v1.json'
KEYS = ('cell','recipe','origin','destination','face','inputs','eligible','benefit','grounding','effort','score','examined','deferred')


def digest(text): return sha256(text.encode()).hexdigest()


class Quotation:
    def __init__(self, native, domain):
        p = json.loads(PROTOCOL.read_text())['input']
        if (digest(native), digest(domain)) != (p['native_sha256'], p['domain_sha256']):
            raise ValueError('exact accepted A5/A6 canonical pair required')
        self.native, self.domain = native, domain
        self.d = loads(domain)
        if self.d['setting'] != 'canonical' or self.d['assignments'] != 5832:
            raise ValueError('complete canonical domain required')
        state = unseal(native, loads(native)['schema'])
        self.world = OperationStore.restore(state['world'])
        self.access = NativeAccess.restore(state['access'])
        self._profiles, self._cursors, self._views = {}, {}, {}
        for tx in self.world.journal():
            for v in tx.versions:
                a = attrs(v); actor = a.get('actor')
                if v.ref.identity.namespace == 'u5.profile':
                    self._profiles[actor] = v.ref
                    self._cursors.setdefault(actor, a['initial_active'])
                if 'route_count' in a and a.get('completed', 0) > 0:
                    self._cursors[actor] = progress(a)[0]
        actor = self.d['actor']
        self.current_wallet = self.world.head(wallet_address(actor).identity)
        self._wallet = attrs(self.current_wallet)
        self._views[actor] = self.access.view(actor)
        self.before = (self.world.checkpoint(), self.access.checkpoint(), dict(self._profiles), dict(self._cursors))
        self.radices = (len(self.d['windows']),) + tuple(len(self.d['pools'][n]) for n in self.d['role_order'])
        if self.radices != self.d['radices'] or prod(self.radices) != self.d['assignments']:
            raise ValueError('complete factor cardinality')

    def participant_view(self, actor): return self._views[actor]

    def wallet(self, actor):
        if actor != self.d['actor']: raise ValueError('quotation actor')
        return dict(self._wallet)

    def unchanged(self):
        return self.before == (self.world.checkpoint(), self.access.checkpoint(), self._profiles, self._cursors)

    def request(self, ordinal):
        if type(ordinal) is not int or not 0 <= ordinal < self.d['assignments']:
            raise ValueError('exact bounded ordinal')
        n = ordinal; digits = []
        for radix in reversed(self.radices):
            n, digit = divmod(n, radix); digits.append(digit)
        digits.reverse()
        r = dict(self.d['windows'][digits[0]])
        r.update((role, self.d['pools'][role][digit]['value']) for role, digit in zip(self.d['role_order'], digits[1:]))
        r['key'] = self.d['namespace'] + str(ordinal)
        return SelectionRequest(**r)

    def row(self, ordinal):
        r = self.request(ordinal)
        common = dict(ordinal=ordinal, request_sha256=digest(dumps(fields_of(r))))
        try: s = SelectionEngine.selection_view(self, r)
        except ValueError as error:
            return dict(**common, rejection=str(error), required=1, snapshot_sha256=None,
                candidates_sha256=None, nominee=None, scanned=None, foreign_total=None, examined=())
        rows, nominee = SelectionEngine._select_policy(self, s)
        projection = tuple({k: x[k] for k in KEYS} for x in rows)
        examined = tuple(x['examined'] for x in rows)
        if len(rows) != 33 or any(type(x) is not int or x < 0 for x in examined):
            raise ValueError('native cell domain and integer extent')
        return dict(**common, rejection=None,
            required=1+s['scanned']+s['foreign_total']+33+sum(examined),
            snapshot_sha256=digest(dumps(s)), candidates_sha256=digest(dumps(projection)),
            nominee=None if nominee is None else nominee['cell'],
            scanned=s['scanned'], foreign_total=s['foreign_total'], examined=examined)

    def report(self, rows):
        if len(rows) != self.d['assignments'] or [r['ordinal'] for r in rows] != list(range(len(rows))):
            raise ValueError('all exact ordered assignments required')
        total = sum(r['required'] for r in rows); w = self._wallet
        return dumps(dict(version='ft-canonical-quotation-a8-v1', setting='canonical',
            native_sha256=digest(self.native), domain_sha256=digest(self.domain),
            actor=self.d['actor'], wallet=self.current_wallet.ref, energy=w['energy'], time=w['time'],
            assignments=len(rows), rows=rows, required_energy=total, required_time=total,
            energy_deficit=max(0,total-w['energy']), time_deficit=max(0,total-w['time']),
            status='insufficient_exact_quote' if total>min(w['energy'],w['time']) else 'affordable_quote_only',
            exact_quote=True, may_launch=False, comparison_paid=False, execution_authorized=False,
            td5_admitted=False, history_choice=False, parent_accepted=False))
