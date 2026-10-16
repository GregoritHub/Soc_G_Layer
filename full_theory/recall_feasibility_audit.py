"""Independent fixed-point closure audit over the original owned snapshot."""
from hashlib import sha256
from hle_unified.particulars import ParticipantView
from hle_unified.selection_records import dumps


def audit(snapshot, report):
    v = ParticipantView(snapshot)
    roots = tuple(b.ref for b in v._heads.values()
                  if b.cue == report['cue'] and b.context == report['context'])
    eligible = tuple(r for r in roots if r.identity.namespace == 'workshop'
                     and r != report['task'] and not any(p.relation == 'u8.reorganize'
                     and type(p.object) is int and p.object > 0
                     for p in v._bindings[r].content))
    if len(eligible) > 2:
        raise ValueError('root bound')
    expected_subsets = {frozenset(eligible[i] for i in range(len(eligible)) if mask & (1 << i))
                        for mask in range(1 << len(eligible))}
    rows = report['rows']
    if len(rows) != len(expected_subsets) or {frozenset(r['removed_roots']) for r in rows} != expected_subsets:
        raise ValueError('incomplete subset panel')
    for row in rows:
        if len(set(row['removed_roots'])) != len(row['removed_roots']):
            raise ValueError('duplicate removed root')
        reached = set(roots) - set(row['removed_roots'])
        while True:
            grown = reached | {link for ref in reached for link in v._bindings[ref].links
                              if link in v._bindings and v._bindings[link].context == report['context']}
            if grown == reached:
                break
            reached = grown
        if set(row['reachable']) != reached or len(row['reachable']) != len(reached):
            raise ValueError('closure differs')
        # Independent ordered oracle: immutable clone changes only root membership.
        # Archived roots retain bindings and links; no simulated revision or payment.
        from types import MappingProxyType
        clone = ParticipantView(snapshot)
        object.__setattr__(clone, '_heads', MappingProxyType({k:b for k,b in clone._heads.items()
                          if b.ref not in row['removed_roots']}))
        native = clone.traverse(report['cue'], report['context'])
        if row['visited'] != native.visited or row['truncated'] != native.truncated:
            raise ValueError('native ordered traversal differs')
        if row['truncated'] != (len(reached) > 32):
            raise ValueError('truncation differs')
    expected = dict(version='ft-recall-feasibility-a1-v1', actor=snapshot.actor,
                    snapshot_sha256=sha256(v.bytes().encode()).hexdigest(),
                    cue=report['cue'], context=report['context'], task=report['task'],
                    roots=roots, eligible_roots=eligible, rows=rows, visit_limit=32,
                    best_reachable=min(len(r['reachable']) for r in rows),
                    relaxation_only=True, execution_authorized=False,
                    comparison_paid=False, td5_admitted=False, history_choice=False,
                    source_unchanged=True)
    if dumps(expected) != dumps(report):
        raise ValueError('report fields or authority differ')
    return True
