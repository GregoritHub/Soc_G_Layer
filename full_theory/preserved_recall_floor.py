"""A11 finite preserved-root obstruction; not an organization executor."""
import json
from hashlib import sha256
from pathlib import Path
from hle_unified.compact import unseal
from hle_unified.operations import NativeAccess
from hle_unified.selection_records import loads, dumps

PROTOCOL = Path(__file__).resolve().parents[1] / 'contracts/ft/FT7_Preserved_Recall_Floor_A11_Protocol_v1.json'

def closure(graph, roots):
    queue = list(roots); seen = set(); reached = []
    for ref in queue:
        if ref not in graph or ref in seen:
            continue
        seen.add(ref); reached.append(ref); queue.extend(graph[ref])
    return tuple(reached)

def analyze(native, setting):
    protocol = json.loads(PROTOCOL.read_text())
    if type(native) is not str or setting not in protocol['inputs'] or sha256(native.encode()).hexdigest() != protocol['inputs'][setting]:
        raise ValueError('exact A10R complete native input required')
    access = NativeAccess.restore(unseal(native, loads(native)['schema'])['access'])
    before = access.checkpoint(); scopes = []
    for actor in access._states:
        view = access.view(actor)
        for binding in view._heads.values():
            if binding.ref.identity.namespace == 'ft.fresh.task' and binding.cue.identity.key == protocol['cue_key']:
                scopes.append((actor, binding, view))
    if len(scopes) != 1:
        raise ValueError('unique original owned fresh task required')
    actor, task, view = scopes[0]
    graph = {ref: b.links for ref, b in view._bindings.items() if b.context == task.context}
    roots = tuple(b.ref for b in view._heads.values() if (b.cue, b.context) == (task.cue, task.context))
    preserved = tuple(ref for ref in roots if ref.identity.namespace in protocol['preserved_namespaces'])
    reached = closure(graph, preserved); original = view.traverse(task.cue, task.context)
    if access.checkpoint() != before:
        raise ValueError('access mutation')
    return dumps(dict(version='ft-preserved-recall-floor-a11-v1', setting=setting,
        native_sha256=protocol['inputs'][setting], actor=actor, task=task.ref,
        cue=task.cue, context=task.context, graph=tuple(graph.items()), roots=roots,
        preserved_roots=preserved, reachable=reached, floor=len(reached),
        witness=reached[:33], limit=32, obstruction=len(reached)>32,
        original_visited=original.visited, original_truncated=original.truncated,
        scope=protocol['intervention'], source_unchanged=True,
        comparison_paid=False, execution_authorized=False, td5_admitted=False,
        history_choice=False, all_organization_impossible=False))
