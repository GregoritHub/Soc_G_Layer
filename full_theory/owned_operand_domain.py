"""Expand the exact bounded operand work behind a settled native comparison.

This is a typed inventory, not TD5 admission or a live-choice authority.
The old comparison snapshot and policy labels remain immutable.
"""
from hashlib import sha256
from itertools import combinations, product, islice

from hle_unified.selection_records import NAMES, dumps, loads
from hle_unified.selection_policy import proposals as canonical_proposals
from hle_unified.workflow_selection_policy import proposals as workflow_proposals
from .owned_paid_comparison_audit import audit_owned_paid_comparison


def bundles(snapshot, cell, setting):
    """Native-order grammar; includes the one beyond-bound sentinel."""
    s = snapshot; r = s['request']; a = r['actor']
    n = NAMES[cell // 2] if cell < 32 else 'Transfer'
    accumulation = cell % 2 == 0
    def kinds(*names):
        if setting == 'canonical':
            return [x for k in names for x in s['items'] if x['data'].get('kind') == k]
        return [x for x in s['items'] if x['data']['kind'] in names]
    def single(*names): return ((x,) for x in kinds(*names))
    if setting == 'canonical':
        if n in ('Contemplate', 'Integrate'):
            return combinations(kinds('personal' if n == 'Contemplate' else 'system'), 2)
        if n == 'Act': return iter(((),))
        if n in ('Express', 'Theorize'): return single('intention')
        if n in ('Embody', 'Organize'): return single('observation')
        if n in ('Apply', 'Mobilize'): return single(*(('model', 'rule') if n == 'Apply' else ('shared',)))
        if n in ('Identify', 'Understand'):
            return product(kinds(*(('shared',) if n == 'Identify' else ('model', 'rule'))), kinds('intention'))
        if n == 'Commune':
            return ((o, q) for o, q in product(kinds('offer'), kinds('reply'))
                if o['ref'].identity.namespace == 'c2.message' and o['data'].get('speaker') == a
                and o['data'].get('group') == r['group'] and q['data'].get('offer') == o['ref']
                and q['data'].get('speaker') == r['peer'] and q['data'].get('group') == r['group'])
        if n in ('Share', 'Coordinate', 'Educate'):
            names = {'Share': ('intention',), 'Coordinate': ('observation',), 'Educate': ('model', 'rule')}[n]
            return ((x, o, q) for x, o, q in product(kinds(*names), kinds('offer'), kinds('reply'))
                if (o['data'].get('source'), o['data'].get('speaker'), o['data'].get('receiver'), o['data'].get('group')) == (x['ref'], a, r['peer'], r['group'])
                and (q['data'].get('offer'), q['data'].get('speaker'), q['data'].get('receiver'), q['data'].get('group')) == (o['ref'], r['peer'], a, r['group']))
        if n == 'Institutionalize':
            if accumulation:
                return ((x, y) for x, y in product(kinds('shared'), kinds('observation'))
                    if y['data'].get('primitive') == 'consume' and y['data'].get('outcome') == 'succeeded')
            return ((x, y, z) for x in kinds('rule') for y, z in combinations(kinds('vote'), 2)
                if x['data'].get('status') == 'draft' and y['data'].get('draft') == z['data'].get('draft') == x['ref']
                and y['data'].get('group') == z['data'].get('group') == r['group']
                and {y['data'].get('speaker'), z['data'].get('speaker')} == {a, r['peer']})
        return product(s['foreign'], kinds('intention'),
            [x for x in kinds('observation') if x['data'].get('outcome') == 'succeeded' and 'available' in x['data']])
    if n in ('Contemplate', 'Integrate'):
        return combinations(kinds(*(('intention', 'stance') if n == 'Contemplate' else ('system',))), 2)
    if n in ('Act', 'Embody'): return single('activity')
    if n == 'Express': return single('intention')
    if n == 'Theorize': return single('intention', 'personal')
    if n == 'Apply': return single('system', 'rule')
    if n == 'Understand': return product(kinds('system', 'rule'), kinds('intention', 'stance'))
    if n == 'Identify': return product(kinds('shared'), kinds('intention', 'stance'))
    if n == 'Mobilize': return single('shared')
    if n == 'Organize':
        observations = tuple(kinds('activity'))
        return iter((observations,) if observations else ())
    if n == 'Institutionalize':
        if accumulation:
            observations = tuple(kinds('activity'))
            return ((x, *observations) for x in kinds('shared')) if observations else iter(())
        return ((x, y, z) for x in kinds('rule') for y, z in combinations(kinds('vote'), 2)
            if y['data'].get('draft') == z['data'].get('draft') == x['ref'])
    names = {'Share': ('intention', 'personal'), 'Coordinate': ('activity',), 'Educate': ('system', 'rule'), 'Commune': ('shared',)}[n]
    return ((x, o, q) for x, o, q in product(kinds(*names), kinds('offer'), kinds('reply'))
        if o['data'].get('source') == x['ref'] and q['data'].get('offer') == o['ref'])


def expand_snapshot(snapshot, setting, original_rows, comparison_required):
    result = []
    for original in original_rows:
        cell = original['cell']
        bounded = list(islice(bundles(snapshot, cell, setting), snapshot['request']['alternatives'] + 1))
        options = []
        for bundle in bounded[:snapshot['request']['alternatives']]:
            refs = {x['ref'] for x in bundle}
            projection = dict(snapshot, items=[x for x in snapshot['items'] if x['ref'] in refs])
            if setting == 'canonical':
                projection['foreign'] = [x for x in snapshot['foreign'] if x['ref'] in refs]
                row = canonical_proposals(projection)[cell]
            else:
                row = workflow_proposals(projection, tuple(range(32)))[cell]
                if row['eligible'] and min(snapshot['wallet']) < comparison_required + row['effort']:
                    row.update(eligible=False, reason='insufficient paid comparison and estimated child budget')
            if row['examined'] != 1 or row['deferred']:
                raise ValueError('single exact operand projection required')
            row = {k: v for k, v in row.items() if k not in ('examined', 'deferred')}
            options.append(dict(ordinal=len(options), bundle=tuple(x['ref'] for x in bundle), proposal=row))
        examined = min(len(bounded), snapshot['request']['alternatives'])
        deferred = len(bounded) > snapshot['request']['alternatives']
        if (examined, deferred) != (original['examined'], original['deferred']):
            raise ValueError('bounded enumeration differs from paid comparison')
        result.append(dict(cell=cell, examined=examined, deferred=deferred, options=options,
            empty_reason=original['reason'] if not options else None))
    return result


def owned_operand_domain(engine, original, source, binding, domain):
    audit_owned_paid_comparison(engine, original, source, binding, domain)
    before = engine.checkpoint(); d = loads(domain)
    actor = d['actor']
    key = 'ft-owned-comparison:' + sha256(source.encode()).hexdigest()[:24]
    if set(engine._ft_comparisons) not in (set(), {(actor, key)}):
        raise ValueError('one exact paired paid comparison required')
    status = engine.job_status(actor, key)['status'] if (actor, key) in engine._jobs else 'before'
    receipt = engine.comparison_result(actor, key) if engine._ft_comparisons else None
    cells = []
    if receipt is not None:
        if status != 'succeeded': raise ValueError('only settled comparison can expose operands')
        cells = expand_snapshot(d['snapshot'], d['setting'], d['candidates'], d['comparison_required'])
    if engine.checkpoint() != before:
        raise ValueError('operand inventory mutated native state')
    return dumps(dict(version='ft-owned-operand-domain-v1', setting=d['setting'], actor=actor,
        key=key, status=status, paid_native_sha256=sha256(before.encode()).hexdigest(),
        original_native_sha256=sha256(original.checkpoint().encode()).hexdigest(),
        source_sha256=sha256(source.encode()).hexdigest(), binding_sha256=sha256(binding.encode()).hexdigest(),
        domain_sha256=sha256(domain.encode()).hexdigest(), cells=cells,
        comparison_settled=receipt is not None, comparison_required=d['comparison_required'],
        complete_within_paid_bound=receipt is not None,
        unbounded_search_complete=d['bounded_search_complete'] if receipt is not None else False,
        execution_authorized=False, td5_admitted=False, history_choice=False))
