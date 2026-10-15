"""Current bounded TD5/cost domain over complete paid request windows."""
from copy import deepcopy
from hashlib import sha256
from hle_unified.selection_records import dumps, loads, SelectionRequest
from hle_unified.workflow_selection_records import WorkflowSelectionRequest
from .current_window_capacity_audit import audit_current_window_capacity
from .paid_window_comparison import snapshot_text
from .owned_operand_domain import expand_snapshot
from .route_policy import SOCIAL

def digest(text): return sha256(text.encode()).hexdigest()

def current_window_admission(engine,old,original,source,binding,intake,windows,capacity):
    before=engine.checkpoint()
    audit_current_window_capacity(engine,old,original,source,binding,intake,windows,capacity)
    cap=loads(capacity);w=loads(windows);setting=w['setting'];actor=w['actor']
    out=dict(version='ft-current-window-admission-v1',setting=setting,actor=actor,
        native_sha256=digest(before),capacity_sha256=digest(capacity),windows_sha256=digest(windows),
        comparison_status=cap['comparison_status'],comparison_settled=cap['comparison_settled'],
        current_wallet=None,preparation=None,windows=(),candidates=(),nominee=None,
        complete_within_paid_bound=False,unbounded_search_complete=False,
        execution_authorized=False,td5_admitted=False,history_choice=False,completion_claim=False)
    if cap['comparison_settled']:
        paid=engine.window_result(actor,'ft-window-comparison:'+digest(windows))
        cls=SelectionRequest if setting=='canonical' else WorkflowSelectionRequest
        records=[];candidates=[];complete=True
        for ordinal,(fields,ballot) in enumerate(zip(w['requests'],paid['windows'])):
            request=cls(**fields)
            try:
                snap=old.selection_view(request) if setting=='canonical' else old.workflow_selection_view(request)
            except ValueError as error:
                if ballot['rejection']!=str(error):raise ValueError('exact rejected window required')
                records.append(dict(ordinal=ordinal,request_sha256=digest(dumps(fields)),
                    snapshot_sha256=None,rejection=str(error),paid_required=1,old_nominee=None,cells=()))
                continue
            current=engine.selection_view(request) if setting=='canonical' else engine.workflow_selection_view(request)
            if (any(current[k]!=v for k,v in snap.items() if k!='wallet')
                or dict(zip(('energy','time'),current['wallet']))!=cap['inventory']['wallet']):
                raise ValueError('current exact post-payment snapshot required')
            rows,nominee=old._select_policy(snap) if setting=='canonical' else old._workflow_policy(snap)
            keys=tuple(ballot['candidates'][0])
            if (tuple({k:r[k] for k in keys} for r in rows)!=ballot['candidates']
                or digest(snapshot_text(snap,setting))!=ballot['snapshot_sha256']):
                raise ValueError('exact paid native ballot and snapshot required')
            cells=expand_snapshot(snap,setting,rows,ballot['required']);projected=[]
            proposal_keys=tuple(k for k in keys if k not in ('examined','deferred'))
            for cell,paid_cell in zip(cells,ballot['candidates']):
                options=[];complete=complete and not cell['deferred']
                for option in cell['options']:
                    p={k:option['proposal'][k] for k in proposal_keys}
                    options.append(dict(ordinal=option['ordinal'],bundle=option['bundle'],proposal=p))
                    effort=p['effort'];valid=type(effort) is int and effort>=0
                    for priority,mean in enumerate(cap['means'][:-1]):
                        prep={u:cap['preparation'][u] for u in ('energy','time')}
                        total={u:effort+mean['overhead'][u]+prep[u] for u in prep} if valid else None
                        reason=(mean['reason'] if not mean['eligible'] else 'native_proposal_ineligible' if not p['eligible']
                            else 'native_effort_unpriced' if not valid else 'support_requires_social_recipe'
                            if mean['name']=='support' and not any(n in p['recipe'] for n in SOCIAL)
                            else 'insufficient_current_wallet' if any(cap['inventory']['wallet'][u]<total[u] for u in prep)
                            else 'current_td5_and_estimated_cost_admissible')
                        candidates.append(dict(identity=dumps((ordinal,cell['cell'],option['ordinal'],option['bundle'],mean['name'])),
                            window=ordinal,cell=cell['cell'],ordinal=option['ordinal'],bundle=option['bundle'],mean=mean['name'],
                            priority=priority,recipe=p['recipe'],native_effort_estimate=effort,route_overhead=deepcopy(mean['overhead']),
                            preparation_cost=prep,total_estimate=total,eligible=reason=='current_td5_and_estimated_cost_admissible',reason=reason))
                projected.append(dict(cell=cell['cell'],examined=cell['examined'],deferred=cell['deferred'],
                    paid_nominee=deepcopy(paid_cell),options=tuple(options)))
            records.append(dict(ordinal=ordinal,request_sha256=digest(dumps(fields)),snapshot_sha256=ballot['snapshot_sha256'],
                rejection=None,paid_required=ballot['required'],old_nominee=ballot['nominee'],cells=tuple(projected)))
        if len(records)!=len(w['requests']):raise ValueError('all paid windows required')
        candidates.append(dict(identity='defer',window=None,cell=None,ordinal=None,bundle=(),mean='defer',priority=5,
            recipe=None,native_effort_estimate=0,route_overhead=dict(energy=0,time=0),preparation_cost=dict(energy=0,time=0),
            total_estimate=dict(energy=0,time=0),eligible=True,reason='fallback_no_work_no_credit'))
        nominee=min((c for c in candidates if c['eligible']),key=lambda c:(c['priority'],c['total_estimate']['time'],c['total_estimate']['energy'],c['identity']))
        out.update(current_wallet=deepcopy(cap['inventory']['wallet']),preparation=deepcopy(cap['preparation']),
            windows=tuple(records),candidates=tuple(candidates),nominee=deepcopy(nominee),
            complete_within_paid_bound=True,unbounded_search_complete=complete)
    if engine.checkpoint()!=before:raise ValueError('admission mutated native state')
    return dumps(out)
