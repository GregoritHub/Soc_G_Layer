"""Read-only root-removal relaxation; never an organization or admission policy."""
from hashlib import sha256
from itertools import combinations
from hle_unified.selection_records import dumps


def analyze(view, cue, context, task):
    before = view.bytes()
    roots = tuple(b.ref for b in view._heads.values()
                  if (b.cue, b.context) == (cue, context))
    eligible = tuple(r for r in roots if r.identity.namespace == 'workshop'
                     and r != task and not any(p.relation == 'u8.reorganize'
                     and type(p.object) is int and p.object > 0
                     for p in view._bindings[r].content))
    if len(eligible) > 2:
        raise ValueError('registered two-root bound exceeded')

    def walk(removed):
        queue = [r for r in roots if r not in removed]
        seen = set(); result = []; cursor = 0
        while cursor < len(queue):
            ref = queue[cursor]; cursor += 1
            b = view._bindings.get(ref)
            if ref in seen or b is None or b.context != context:
                continue
            seen.add(ref); result.append(ref); queue.extend(b.links)
        return tuple(result)

    rows = []
    for size in range(len(eligible) + 1):
        for removed in combinations(eligible, size):
            reached = walk(removed)
            rows.append(dict(removed_roots=removed, reachable=reached,
                             visited=reached[:32], truncated=len(reached) > 32))
    if view.bytes() != before:
        raise ValueError('view mutation')
    return dict(version='ft-recall-feasibility-a1-v1', actor=view.snapshot.actor,
                snapshot_sha256=sha256(before.encode()).hexdigest(), cue=cue,
                context=context, task=task, roots=roots, eligible_roots=eligible,
                rows=tuple(rows), visit_limit=32,
                best_reachable=min(len(r['reachable']) for r in rows),
                relaxation_only=True, execution_authorized=False,
                comparison_paid=False, td5_admitted=False, history_choice=False,
                source_unchanged=True)
