"""Independent A8 complete cost reconstruction; imports no quotation or selector."""
import json
from hashlib import sha256
from itertools import product
from pathlib import Path
from types import SimpleNamespace
from hle_unified.compact import unseal
from hle_unified.material import OperationStore, attrs
from hle_unified.operations import NativeAccess
from hle_unified.selection_records import dumps, loads, SelectionRequest
from hle_unified.selection_audit import reference
from .owned_proposal_domain_audit import _snapshot


def digest(text): return sha256(text.encode()).hexdigest()


class QuotationAudit:
    def __init__(self, native, domain):
        p = json.loads((Path(__file__).resolve().parents[1]/'contracts/ft/FT7_Canonical_Quotation_A8_Protocol_v1.json').read_text())['input']
        if (digest(native), digest(domain)) != (p['native_sha256'], p['domain_sha256']):
            raise ValueError('audit exact accepted input pair')
        self.native, self.domain, self.d = native, domain, loads(domain)
        self.actor = self.d['actor']
        data = unseal(native, loads(native)['schema'])
        self.world = OperationStore.restore(data['world'])
        self.access = NativeAccess.restore(data['access'])
        profiles = {}; cursors = {}; wallets = {}
        for tx in self.world.journal():
            for version in tx.versions:
                a = {f.name:f.value for f in version.attributes}
                actor = a.get('actor')
                if version.ref.identity.namespace == 'u5.profile':
                    profiles[actor] = version.ref
                    if actor not in cursors: cursors[actor] = a['initial_active']
                if a.get('record_type') == 'wallet': wallets[actor] = version
                if 'route_count' in a and a.get('completed',0)>0:
                    left=max(0,a['completed']-a['recall_units']); cursor=a['active_start']; stop=False
                    for i in range(a['route_count']):
                        prefix='route.'+str(i)+'.'; j=0
                        while prefix+'charges.'+str(j) in a:
                            cost=a[prefix+'charges.'+str(j)]
                            if left<cost: stop=True; break
                            left-=cost;cursor=a[prefix+'path.'+str(j+1)];j+=1
                        if stop or left<a[prefix+'content_units']: break
                        left-=a[prefix+'content_units'];cursor=a[prefix+'element']
                    cursors[actor]=cursor
        self.wallet = wallets[self.actor]; self.w = attrs(self.wallet)
        self.facade = SimpleNamespace(world=self.world, _profiles=profiles, _cursors=cursors,
            wallet=lambda actor: attrs(wallets[actor]))
        self.view = self.access.view(self.actor)
        self.before = (self.world.checkpoint(), self.access.checkpoint(), dict(profiles), dict(cursors))
        self.expected_rows = None

    def reconstruct(self, guard=lambda:None, note=lambda n:None):
        rows=[]; d=self.d
        factors=[d['windows']]+[d['pools'][n] for n in d['role_order']]
        for ordinal, values in enumerate(product(*factors)):
            if ordinal % 128 == 0: guard(); note(ordinal)
            fields=dict(values[0])
            fields.update((name, row['value']) for name,row in zip(d['role_order'],values[1:]))
            fields['key']=d['namespace']+str(ordinal); r=SelectionRequest(**fields)
            binding=self.view._bindings.get(r.demand)
            if binding is None or (binding.actor,binding.context,binding.cue,binding.target.identity)!=(r.actor,r.context,r.cue,r.target.identity) or len(binding.content)!=1 or binding.content[0].relation!='c6.need':
                rows.append(dict(ordinal=ordinal,request_sha256=digest(dumps(fields)),
                    rejection='owned paid demand in this context required',required=1,snapshot_sha256=None,
                    candidates_sha256=None,nominee=None,scanned=None,foreign_total=None,examined=()))
                continue
            s=_snapshot(self.facade,self.view,r,'canonical')
            candidates=[dict(reference(s,i),cell=i) for i in range(33)]
            nominee=min((c for c in candidates if c['eligible'] and c['score']>0),
                key=lambda c:(-c['score'],c['cell'],dumps(c['inputs'])),default=None)
            keys=('cell','recipe','origin','destination','face','inputs','eligible','benefit','grounding','effort','score','examined','deferred')
            projection=tuple({k:c[k] for k in keys} for c in candidates)
            counts=tuple(c['examined'] for c in candidates)
            rows.append(dict(ordinal=ordinal,request_sha256=digest(dumps(fields)),rejection=None,
                required=34+s['scanned']+s['foreign_total']+sum(counts),
                snapshot_sha256=digest(dumps(s)),candidates_sha256=digest(dumps(projection)),
                nominee=None if nominee is None else nominee['cell'],scanned=s['scanned'],
                foreign_total=s['foreign_total'],examined=counts))
        if len(rows)!=5832 or len(rows)!=d['assignments']:raise ValueError('complete independent product')
        self.expected_rows=rows
        return rows

    def unchanged(self):
        return self.before==(self.world.checkpoint(),self.access.checkpoint(),self.facade._profiles,self.facade._cursors)

    def audit(self,text):
        if self.expected_rows is None:raise ValueError('independent full reconstruction required')
        rows=self.expected_rows; total=sum(r['required'] for r in rows); energy=self.w['energy']; time=self.w['time']
        expected=dict(version='ft-canonical-quotation-a8-v1',setting='canonical',
            native_sha256=digest(self.native),domain_sha256=digest(self.domain),actor=self.actor,wallet=self.wallet.ref,
            energy=energy,time=time,assignments=len(rows),rows=rows,required_energy=total,required_time=total,
            energy_deficit=total-energy if total>energy else 0,time_deficit=total-time if total>time else 0,
            status='insufficient_exact_quote' if total>energy or total>time else 'affordable_quote_only',
            exact_quote=True,may_launch=False,comparison_paid=False,execution_authorized=False,td5_admitted=False,
            history_choice=False,parent_accepted=False)
        if loads(text)!=expected or dumps(loads(text))!=text:raise ValueError('exact independent quotation differs')
        return dict(passed=True,assignments=len(rows),required=total,energy=energy,time=time,
            energy_deficit=expected['energy_deficit'],time_deficit=expected['time_deficit'],status=expected['status'],
            exact_quote=True,may_launch=False,comparison_paid=False)
