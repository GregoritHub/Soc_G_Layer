"""Independent exact A7 wallet and necessary-cost proof, without funding imports."""
import json
from hashlib import sha256
from pathlib import Path
from hle_unified import codec
from hle_unified.compact import unseal
from hle_unified.material import OperationStore
from hle_unified.records import ObjectId
from hle_unified.selection_records import dumps,loads


def audit_comparison_funding(native,domain,setting,text):
    sha=lambda s:sha256(s.encode()).hexdigest()
    def require(ok,reason):
        if not ok:raise ValueError('comparison funding audit: '+reason)
    protocol=json.loads((Path(__file__).resolve().parents[1]/'contracts/ft/FT7_Comparison_Funding_A7_Protocol_v1.json').read_text())
    entry=protocol['inputs'].get(setting)
    require(entry is not None and (sha(native),sha(domain))==(entry['native_sha256'],entry['domain_sha256']),'accepted input pair')
    d=loads(domain);actor=d['actor'];state=unseal(native,loads(native)['schema'])
    world=OperationStore.restore(state['world'])
    identity=ObjectId('u4.wallet',sha(codec.canonical([codec.encode(actor)])))
    wallet=world.head(identity);fields={a.name:a.value for a in wallet.attributes}
    require(fields.get('actor')==actor and fields.get('record_type')=='wallet','current owned wallet')
    sizes=(len(d['windows']),)+tuple(len(d['pools'][role]) for role in d['role_order'])
    total=1
    for size in sizes:require(size>=1,'nonempty factor');total*=size
    require(sizes==d['radices'] and total==d['assignments'],'complete product')
    energy,time=fields['energy'],fields['time']
    require(type(energy) is type(time) is int and energy>=0 and time>=0,'exact native resources')
    expected=dict(version='ft-comparison-funding-a7-v1',setting=setting,actor=actor,native_sha256=sha(native),
        domain_sha256=sha(domain),wallet=wallet.ref,energy=energy,time=time,radices=sizes,assignments=total,
        cost_floor='inherited-one-unit-per-assignment',parent_accepted=False,
        minimum_energy=total,minimum_time=total,energy_deficit=total-energy if total>energy else 0,
        time_deficit=total-time if total>time else 0,
        status='insufficient_lower_bound' if total>energy or total>time else 'exact_quote_required',
        may_launch=False,exact_quote=False,comparison_paid=False,execution_authorized=False,td5_admitted=False,history_choice=False)
    require(loads(text)==expected and dumps(loads(text))==text,'exact necessary-only funding report')
    return dict(passed=True,setting=setting,energy=energy,time=time,assignments=total,status=expected['status'],
        energy_deficit=expected['energy_deficit'],time_deficit=expected['time_deficit'],may_launch=False,exact_quote=False)
