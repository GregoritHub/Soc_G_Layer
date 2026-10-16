"""A7 necessary funding condition only; a lower bound never permits work."""
import json
from hashlib import sha256
from math import prod
from pathlib import Path
from hle_unified.compact import unseal
from hle_unified.material import OperationStore,attrs
from hle_unified.operations import wallet_address
from hle_unified.selection_records import dumps,loads

PROTOCOL=Path(__file__).resolve().parents[1]/'contracts/ft/FT7_Comparison_Funding_A7_Protocol_v1.json'


def digest(text):return sha256(text.encode()).hexdigest()


def floor_status(assignments,energy,time):
    if any(type(x) is not int for x in (assignments,energy,time)) or assignments<1 or min(energy,time)<0:
        raise ValueError('positive exact assignment count and nonnegative exact wallets required')
    return dict(minimum_energy=assignments,minimum_time=assignments,
        energy_deficit=max(0,assignments-energy),time_deficit=max(0,assignments-time),
        status='insufficient_lower_bound' if min(energy,time)<assignments else 'exact_quote_required',
        may_launch=False,exact_quote=False,comparison_paid=False,execution_authorized=False,
        td5_admitted=False,history_choice=False)


def comparison_funding(native,domain,setting):
    entry=json.loads(PROTOCOL.read_text())['inputs'].get(setting)
    if entry is None or (digest(native),digest(domain))!=(entry['native_sha256'],entry['domain_sha256']):
        raise ValueError('exact accepted native/domain pair required')
    d=loads(domain);state=unseal(native,loads(native)['schema']);world=OperationStore.restore(state['world'])
    wallet=world.head(wallet_address(d['actor']).identity);w=attrs(wallet)
    if w.get('actor')!=d['actor'] or w.get('record_type')!='wallet':raise ValueError('own current wallet required')
    radices=(len(d['windows']),)+tuple(len(d['pools'][n]) for n in d['role_order'])
    total=prod(radices)
    if radices!=d['radices'] or total!=d['assignments']:raise ValueError('complete domain factors')
    return dumps(dict(version='ft-comparison-funding-a7-v1',setting=setting,actor=d['actor'],
        native_sha256=digest(native),domain_sha256=digest(domain),wallet=wallet.ref,
        energy=w['energy'],time=w['time'],radices=radices,assignments=total,
        cost_floor='inherited-one-unit-per-assignment',parent_accepted=False,
        **floor_status(total,w['energy'],w['time'])))
