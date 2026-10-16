"""Independent fixed-point readback auditor; does not import the generator."""
import json
from hashlib import sha256
from pathlib import Path
from hle_unified.compact import unseal
from hle_unified.operations import NativeAccess
from hle_unified.selection_records import loads

def audit(native, serialized, setting):
    p=json.loads((Path(__file__).resolve().parents[1]/'contracts/ft/FT7_Preserved_Recall_Floor_A11_Protocol_v1.json').read_text())
    if setting not in p['inputs'] or sha256(native.encode()).hexdigest()!=p['inputs'][setting]:
        raise ValueError('input binding')
    r=loads(serialized)
    access=NativeAccess.restore(unseal(native,loads(native)['schema'])['access']);before=access.checkpoint()
    candidates=[]
    for actor in access._states:
        view=access.view(actor)
        candidates.extend((actor,b,view) for b in view._heads.values() if b.ref.identity.namespace=='ft.fresh.task' and b.cue.identity.key==p['cue_key'])
    if len(candidates)!=1:raise ValueError('unique task')
    actor,task,view=candidates[0]
    graph={ref:b.links for ref,b in view._bindings.items() if b.context==task.context}
    roots=tuple(b.ref for b in view._heads.values() if b.context==task.context and b.cue==task.cue)
    kept=tuple(ref for ref in roots if ref.identity.namespace in p['preserved_namespaces'])
    fixed=set(kept)
    while True:
        extended=fixed|{target for ref in fixed for target in graph[ref] if target in graph}
        if extended==fixed:break
        fixed=extended
    # Separately reconstruct ordered queue semantics, not the generator helper.
    levels=list(kept);ordered=[];seen=set();i=0
    while i<len(levels):
        ref=levels[i];i+=1
        if ref in graph and ref not in seen:
            seen.add(ref);ordered.append(ref);levels.extend(graph[ref])
    if seen!=fixed:raise ValueError('fixed point/order disagreement')
    traversal=view.traverse(task.cue,task.context)
    expected=dict(version='ft-preserved-recall-floor-a11-v1',setting=setting,native_sha256=p['inputs'][setting],
        actor=actor,task=task.ref,cue=task.cue,context=task.context,graph=tuple(graph.items()),roots=roots,
        preserved_roots=kept,reachable=tuple(ordered),floor=len(fixed),witness=tuple(ordered[:33]),limit=32,
        obstruction=len(fixed)>32,original_visited=traversal.visited,original_truncated=traversal.truncated,
        scope=p['intervention'],source_unchanged=True,comparison_paid=False,execution_authorized=False,
        td5_admitted=False,history_choice=False,all_organization_impossible=False)
    if r!=expected or access.checkpoint()!=before:raise ValueError('independent report mismatch')
    return dict(passed=True,setting=setting,floor=len(fixed),preserved_roots=len(kept),
                graph_nodes=len(graph),obstruction=len(fixed)>32,source_unchanged=True)
