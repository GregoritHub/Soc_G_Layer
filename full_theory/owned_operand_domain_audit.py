"""Independent bounded operand audit; imports no participant selector/generator."""
from hashlib import sha256
from itertools import product, islice
from hle_unified.selection_records import NAMES, dumps, loads
from hle_unified.selection_audit import reference as canonical_reference
from hle_unified.workflow_selection_audit import reference as workflow_reference
from hle_unified.material import attrs
from hle_unified.operations import address
from .owned_paid_comparison_audit import audit_owned_paid_comparison


def reference_bundles(s, cell, setting):
    """Separate positional product/filter reconstruction of the bundle grammar."""
    n = NAMES[cell // 2] if cell < 32 else 'Transfer'; acc = cell % 2 == 0
    r = s['request']; a = r['actor']; workflow = setting == 'workflow'
    items = s['items']; idx = {x['ref']: i for i, x in enumerate(items)}
    def take(kinds):
        if workflow: return [x for x in items if x['data']['kind'] in kinds]
        return sorted((x for x in items if x['data'].get('kind') in kinds),
            key=lambda x: (kinds.index(x['data']['kind']), idx[x['ref']]))
    if n == 'Act' and not workflow: yield (); return
    if workflow and n in ('Organize', 'Institutionalize') and (n == 'Organize' or acc):
        obs = tuple(take(('activity',)))
        if obs:
            if n == 'Organize': yield obs
            else:
                for x in take(('shared',)): yield (x, *obs)
        return
    if n == 'Transfer':
        pools = [s['foreign'], take(('intention',)), [x for x in take(('observation',))
            if x['data'].get('outcome') == 'succeeded' and 'available' in x['data']]]
    else:
        grammar = {
            'Contemplate': (('intention','stance'),)*2 if workflow else (('personal',),)*2,
            'Integrate': (('system',),)*2,
            'Act': (('activity',),),
            'Express': (('intention',),),
            'Theorize': (('intention','personal'),) if workflow else (('intention',),),
            'Embody': (('activity',),) if workflow else (('observation',),),
            'Organize': (('observation',),),
            'Apply': (('system','rule'),) if workflow else (('model','rule'),),
            'Mobilize': (('shared',),),
            'Understand': (('system','rule'),('intention','stance')) if workflow else (('model','rule'),('intention',)),
            'Identify': (('shared',), ('intention','stance') if workflow else ('intention',)),
            'Share': (('intention','personal') if workflow else ('intention',),('offer',),('reply',)),
            'Coordinate': (('activity',) if workflow else ('observation',),('offer',),('reply',)),
            'Educate': (('system','rule') if workflow else ('model','rule'),('offer',),('reply',)),
            'Commune': (('shared',),('offer',),('reply',)) if workflow else (('offer',),('reply',)),
            'Institutionalize': (('rule',),('vote',),('vote',)) if not acc else (('shared',),('observation',))}
        pools = [take(k) for k in grammar[n]]
    for b in product(*pools):
        if n in ('Contemplate','Integrate') and idx[b[0]['ref']] >= idx[b[1]['ref']]: continue
        if n in ('Share','Coordinate','Educate') or (n == 'Commune' and workflow):
            x,o,q = b; ov=o['data'];qv=q['data']
            if ov.get('source') != x['ref'] or qv.get('offer') != o['ref']: continue
            if not workflow and ((ov.get('speaker'),ov.get('receiver'),ov.get('group')) != (a,r['peer'],r['group'])
                or (qv.get('speaker'),qv.get('receiver'),qv.get('group')) != (r['peer'],a,r['group'])): continue
        if n == 'Commune' and not workflow:
            o,q=b
            if not (o['ref'].identity.namespace == 'c2.message' and o['data'].get('speaker') == a
                and o['data'].get('group') == r['group'] and q['data'].get('offer') == o['ref']
                and q['data'].get('speaker') == r['peer'] and q['data'].get('group') == r['group']): continue
        if n == 'Institutionalize':
            if acc:
                if b[1]['data'].get('primitive') != 'consume' or b[1]['data'].get('outcome') != 'succeeded': continue
            else:
                x,y,z=b
                if idx[y['ref']] >= idx[z['ref']] or y['data'].get('draft') != x['ref'] or z['data'].get('draft') != x['ref']: continue
                if not workflow and (x['data'].get('status') != 'draft'
                    or y['data'].get('group') != r['group'] or z['data'].get('group') != r['group']
                    or {y['data'].get('speaker'),z['data'].get('speaker')} != {a,r['peer']}): continue
        yield b


def audit_owned_operand_domain(engine, original, source, binding, domain, text):
    paid = audit_owned_paid_comparison(engine, original, source, binding, domain)
    d=loads(domain); out=loads(text); s=d['snapshot']; actor=d['actor']
    key='ft-owned-comparison:'+sha256(source.encode()).hexdigest()[:24]
    heads={v.ref.identity:v for tx in engine.world.journal() for v in tx.versions}
    op=heads.get(address('u4.operation',actor,key).identity)
    status='before' if op is None else attrs(op)['status']; settled=status=='succeeded'
    expected=dict(version='ft-owned-operand-domain-v1',setting=d['setting'],actor=actor,key=key,status=status,
        paid_native_sha256=sha256(engine.checkpoint().encode()).hexdigest(),
        original_native_sha256=sha256(original.checkpoint().encode()).hexdigest(),
        source_sha256=sha256(source.encode()).hexdigest(),binding_sha256=sha256(binding.encode()).hexdigest(),
        domain_sha256=sha256(domain.encode()).hexdigest(),comparison_settled=settled,
        comparison_required=d['comparison_required'],complete_within_paid_bound=settled,
        unbounded_search_complete=d['bounded_search_complete'] if settled else False,
        execution_authorized=False,td5_admitted=False,history_choice=False)
    if set(out)!=set(expected)|{'cells'} or any(out[k]!=v or type(out[k]) is not type(v) for k,v in expected.items()):
        raise ValueError('operand schema, status or exact pairing differs')
    cells=out['cells']; originals=d['candidates'] if settled else []
    if [c['cell'] for c in cells] != [c['cell'] for c in originals]: raise ValueError('cell domain differs')
    count=0
    for c,old in zip(cells, originals):
        bounded=list(islice(reference_bundles(s,c['cell'],d['setting']),s['request']['alternatives']+1))
        used=bounded[:s['request']['alternatives']]
        if set(c)!={'cell','examined','deferred','options','empty_reason'}:raise ValueError('cell fields')
        if (c['examined'],c['deferred'],len(c['options']))!=(len(used),len(bounded)>len(used),len(used)):
            raise ValueError('omitted or false bounded alternatives')
        if (c['examined'],c['deferred'])!=(old['examined'],old['deferred']):raise ValueError('paid extent changed')
        if c['empty_reason']!=(old['reason'] if not used else None):raise ValueError('empty reason differs')
        for i,(option,bundle) in enumerate(zip(c['options'],used)):
            if set(option)!={'ordinal','bundle','proposal'} or option['ordinal']!=i or option['bundle']!=tuple(x['ref'] for x in bundle):
                raise ValueError('operand identity or order differs')
            refs={x['ref'] for x in bundle}; projection=dict(s,items=[x for x in s['items'] if x['ref'] in refs])
            if d['setting']=='canonical':
                projection['foreign']=[x for x in s['foreign'] if x['ref'] in refs]
                row=dict(canonical_reference(projection,c['cell']),cell=c['cell'])
            else:
                row=workflow_reference(projection)[0][c['cell']]
                row['eligible']=bool(row['eligible'] and min(s['wallet'])>=d['comparison_required']+row['effort'])
            if row.pop('examined')!=1 or row.pop('deferred'):raise ValueError('ambiguous projection')
            proposal=option['proposal']
            if any(proposal.get(k)!=v for k,v in row.items()):raise ValueError('native operand effect or effort differs')
            if not isinstance(proposal.get('reason'),str) or not proposal['reason']:raise ValueError('reason missing')
            count+=1
        if used:
            if d['setting']=='canonical': rank=lambda p:(not p['eligible'],-p['score'],dumps(p['inputs']))
            else: rank=lambda p:(not p['eligible'],-p['priority'],-p['preference'],-p.get('coverage',0),p['effort'],p['cell'],dumps(p['inputs']))
            best=min((o['proposal'] for o in c['options']),key=rank)
            if best!={k:v for k,v in old.items() if k not in ('examined','deferred')}:raise ValueError('old cell nominee changed')
    return dict(passed=True,paid_audit=paid,cells=len(cells),alternatives=count,
        comparison_settled=settled,complete_within_paid_bound=settled,
        unbounded_search_complete=expected['unbounded_search_complete'],execution_authorized=False)
