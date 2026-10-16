"""A6 complete factorized grammar on exact changed owned inputs, never a choice."""
import json
from hashlib import sha256
from itertools import combinations
from math import prod
from pathlib import Path
from hle_unified.selection_records import dumps, loads, fields_of, SelectionRequest
from hle_unified.workflow_selection_records import WorkflowSelectionRequest, WorkflowCapacitySelectionRequest
from .demand_controller import IntegratedDemandController
from .demand_requests import form_request
from .owned_role_domain import paid_pools
from .observed_material_domain import material_vocabulary

VERSION = 'ft-changed-input-domain-a6-v1'
PROTOCOL = Path(__file__).resolve().parents[1]/'contracts/ft/FT7_Changed_Input_Domain_A6_Protocol_v1.json'


def digest(text): return sha256(text.encode()).hexdigest()


def coordinates(ordinal, radices):
    if type(ordinal) is not int or any(type(n) is not int or n < 1 for n in radices):
        raise ValueError('exact integer index and positive radices required')
    if not 0 <= ordinal < prod(radices): raise ValueError('ordinal outside complete product')
    result = []
    for radix in reversed(radices):
        ordinal, digit = divmod(ordinal, radix); result.append(digit)
    return tuple(reversed(result))


def ordinal_of(digits, radices):
    if len(digits) != len(radices): raise ValueError('factor arity')
    result = 0
    for digit, radix in zip(digits, radices):
        if type(radix) is not int or radix < 1 or type(digit) is not int or not 0 <= digit < radix:
            raise ValueError('factor coordinate')
        result = result * radix + digit
    return result


def changed_input_domain(view, native_sha256, field_text, old_text, refresh_text, setting):
    entry = json.loads(PROTOCOL.read_text())['inputs'].get(setting)
    actual = (native_sha256, digest(field_text), digest(old_text), digest(refresh_text), digest(view.bytes()))
    if entry is None or actual != tuple(entry[k] for k in
            ('native_sha256','adapter_sha256','old_domain_sha256','refresh_sha256','view_sha256')):
        raise ValueError('exact accepted changed-input pair required')
    field, old, refresh = map(loads, (field_text, old_text, refresh_text))
    actor = old['actor']
    if (view.snapshot.actor != actor or field['actor'] != actor or field['phase'] != 'complete'
            or field['expected_native_sha256'] != native_sha256):
        raise ValueError('complete exact owned field input required')
    controller = IntegratedDemandController.restore(old['controller_prefix'])
    demands = controller.effective_demands(); fresh = old['fresh_demand']
    key = dumps((actor, fresh['binding']))
    if key in demands: raise ValueError('fresh task already registered')
    demands[key] = fresh
    request, formation = form_request(view, demands)
    if formation != old['original_formation'] or formation['selected'] != key:
        raise ValueError('unchanged oldest current task and content required')
    inventory = tuple(formation['content'])
    if setting == 'canonical': windows = [fields_of(request)]
    else:
        windows = []
        for size in range(1, min(8, len(inventory)) + 1):
            for subset in combinations(inventory, size):
                windows.append(fields_of(WorkflowSelectionRequest(
                    key='ft-request-window:'+digest(key+dumps(subset)), actor=actor,
                    context=fresh['context'], cue=fresh['cue'], target=fresh['target'],
                    demand=fresh['binding'], accessible=subset)))
    if windows != old['requests']: raise ValueError('old non-role request semantics changed')
    pools = paid_pools(view, setting)
    observations, materials = material_vocabulary(view, refresh, setting)
    pools.update(materials)
    names = tuple(pools); radices = (len(windows),) + tuple(len(pools[n]) for n in names)
    return dumps(dict(version=VERSION, setting=setting, actor=actor, native_sha256=native_sha256,
        view_sha256=actual[-1], fields_sha256=actual[1], old_domain_sha256=actual[2], refresh_sha256=actual[3],
        old_native_sha256=old['native_sha256'], source_sha256=old['source_sha256'],
        binding_sha256=old['binding_sha256'], intake_sha256=old['intake_sha256'],
        controller_prefix=old['controller_prefix'], fresh_demand=fresh, original_formation=formation,
        content_inventory=inventory, windows=windows, pools=pools, role_order=names,
        observations=observations, radices=radices, assignments=prod(radices),
        namespace='ft-changed-a6:'+native_sha256+':',
        coverage='complete-declared-paid-observation-cartesian-grammar',
        declared_domain_complete=True, native_view_probed=False, comparison_paid=False,
        execution_authorized=False, td5_admitted=False, history_choice=False, parent_accepted=False))


def request_at(text, ordinal):
    d = loads(text)
    if d.get('version') != VERSION: raise ValueError('A6 schema required')
    names = d['role_order']
    radices = (len(d['windows']),) + tuple(len(d['pools'][n]) for n in names)
    if radices != d['radices'] or prod(radices) != d['assignments']: raise ValueError('factor sizes')
    digits = coordinates(ordinal, radices)
    fields = dict(d['windows'][digits[0]])
    fields.update((name, d['pools'][name][digit]['value']) for name, digit in zip(names, digits[1:]))
    fields['key'] = d['namespace'] + str(ordinal)
    if d['setting'] == 'canonical': return SelectionRequest(**fields)
    if fields.get('procedure') is not None: return WorkflowCapacitySelectionRequest(**fields)
    fields.pop('procedure', None)
    return WorkflowSelectionRequest(**fields)
