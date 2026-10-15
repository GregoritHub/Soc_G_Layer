"""Independent window/operand/TD5-cost reconstruction; no builder or selector."""
from copy import deepcopy
from hashlib import sha256
from itertools import islice
from hle_unified.selection_records import dumps,loads,SelectionRequest
from hle_unified.workflow_selection_records import WorkflowSelectionRequest
from hle_unified.selection_audit import reference as canonical_reference
from hle_unified.workflow_selection_audit import reference as workflow_reference
from .current_window_capacity_audit import audit_current_window_capacity
from .owned_operand_domain_audit import reference_bundles
from .owned_proposal_domain_audit import _snapshot
from .paid_role_comparison_audit import snapshot_digest

def audit_current_window_admission(engine,old,original,source,binding,intake,windows,capacity,text):
    def require(ok,reason):
        if not ok:raise ValueError('current window admission audit: '+reason)
    digest=lambda t:sha256(t.encode()).hexdigest()
    native=engine.checkpoint()
    proof=audit_current_window_capacity(engine,old,original,source,binding,intake,windows,capacity)
    cap=loads(capacity);w=loads(windows);actual=loads(text);setting=w['setting'];actor=w['actor']
    expected=dict(version='ft-current-window-admission-v1',setting=setting,actor=actor,native_sha256=digest(native),
        capacity_sha256=digest(capacity),windows_sha256=digest(windows),comparison_status=cap['comparison_status'],
        comparison_settled=cap['comparison_settled'],current_wallet=None,preparation=None,windows=(),candidates=(),nominee=None,
        complete_within_paid_bound=False,unbounded_search_complete=False,execution_authorized=False,
        td5_admitted=False,history_choice=False,completion_claim=False)
    operands=0;records=[];joined=[];unbounded=True
    if cap['comparison_settled']:
        cls=SelectionRequest if setting=='canonical' else WorkflowSelectionRequest
        oldview=old.participant_view(actor);view=engine.participant_view(actor)
        names=('retained','ordinary','n','cp','support');require(tuple(m['name'] for m in cap['means'][:-1])==names,'mean order')
        keys=(('cell','recipe','origin','destination','face','inputs','eligible','benefit','grounding','effort','score','examined','deferred')
            if setting=='canonical' else ('cell','recipe','inputs','eligible','priority','preference','effort','coverage','examined','deferred'))
        for number,fields in enumerate(w['requests']):
            req=cls(**fields)
            try:s=_snapshot(old,oldview,req,setting)
            except ValueError as error:
                records.append(dict(ordinal=number,request_sha256=digest(dumps(fields)),snapshot_sha256=None,rejection=str(error),
                    paid_required=1,old_nominee=None,cells=()));continue
            now=_snapshot(engine,view,req,setting)
            require(all(now[k]==v for k,v in s.items() if k!='wallet'),'current snapshot inputs')
            require(now['wallet']==tuple(cap['inventory']['wallet'][u] for u in ('energy','time')),'current wallet')
            if setting=='canonical':
                rows=[dict(canonical_reference(s,k),cell=k) for k in range(33)]
                best=min((r for r in rows if r['eligible'] and r['score']>0),key=lambda r:(-r['score'],r['cell'],dumps(r['inputs'])),default=None)
                required=1+s['scanned']+s['foreign_total']+33+sum(r['examined'] for r in rows)
            else:
                rows,best=workflow_reference(s);required=1+len(s['items'])+32+sum(r['examined'] for r in rows)
            cells=[]
            for row in rows:
                bound=list(islice(reference_bundles(s,row['cell'],setting),fields['alternatives']+1))
                used=bound[:fields['alternatives']];deferred=len(bound)>len(used);unbounded=unbounded and not deferred
                require((len(used),deferred)==(row['examined'],row['deferred']),'exact paid extent')
                options=[]
                for ordinal,bundle in enumerate(used):
                    refs={x['ref'] for x in bundle};snapshot=dict(s,items=[x for x in s['items'] if x['ref'] in refs])
                    if setting=='canonical':
                        snapshot['foreign']=[x for x in s['foreign'] if x['ref'] in refs]
                        r=dict(canonical_reference(snapshot,row['cell']),cell=row['cell'])
                    else:
                        r=workflow_reference(snapshot)[0][row['cell']]
                        r['eligible']=bool(r['eligible'] and min(s['wallet'])>=required+r['effort'])
                    require(r['examined']==1 and not r['deferred'],'single exact operand')
                    proposal={k:r[k] for k in keys if k not in ('examined','deferred')}
                    bundle_refs=tuple(x['ref'] for x in bundle);options.append(dict(ordinal=ordinal,bundle=bundle_refs,proposal=proposal));operands+=1
                    for priority,name in enumerate(names):
                        mean=cap['means'][priority];effort=proposal['effort'];valid=type(effort) is int and effort>=0
                        prep=dict(energy=cap['preparation']['energy'],time=cap['preparation']['time'])
                        total=dict(energy=effort+mean['overhead']['energy']+prep['energy'],time=effort+mean['overhead']['time']+prep['time']) if valid else None
                        reason='current_td5_and_estimated_cost_admissible'
                        if not mean['eligible']:reason=mean['reason']
                        elif not proposal['eligible']:reason='native_proposal_ineligible'
                        elif not valid:reason='native_effort_unpriced'
                        elif name=='support' and not any(n in proposal['recipe'] for n in ('share','coordinate','educate','identify','mobilize','institutionalize','commune')):reason='support_requires_social_recipe'
                        elif any(total[u]>cap['inventory']['wallet'][u] for u in ('energy','time')):reason='insufficient_current_wallet'
                        joined.append(dict(identity=dumps((number,row['cell'],ordinal,bundle_refs,name)),window=number,cell=row['cell'],
                            ordinal=ordinal,bundle=bundle_refs,mean=name,priority=priority,recipe=proposal['recipe'],native_effort_estimate=effort,
                            route_overhead=deepcopy(mean['overhead']),preparation_cost=prep,total_estimate=total,
                            eligible=reason=='current_td5_and_estimated_cost_admissible',reason=reason))
                cells.append(dict(cell=row['cell'],examined=len(used),deferred=deferred,paid_nominee={k:row[k] for k in keys},options=tuple(options)))
            records.append(dict(ordinal=number,request_sha256=digest(dumps(fields)),snapshot_sha256=snapshot_digest(s,setting),
                rejection=None,paid_required=required,old_nominee=None if best is None else best['cell'],cells=tuple(cells)))
        joined.append(dict(identity='defer',window=None,cell=None,ordinal=None,bundle=(),mean='defer',priority=5,recipe=None,
            native_effort_estimate=0,route_overhead=dict(energy=0,time=0),preparation_cost=dict(energy=0,time=0),
            total_estimate=dict(energy=0,time=0),eligible=True,reason='fallback_no_work_no_credit'))
        ranked=sorted((r for r in joined if r['eligible']),key=lambda r:(r['priority'],r['total_estimate']['time'],r['total_estimate']['energy'],r['identity']))
        expected.update(current_wallet=deepcopy(cap['inventory']['wallet']),preparation=deepcopy(cap['preparation']),windows=tuple(records),
            candidates=tuple(joined),nominee=deepcopy(ranked[0]),complete_within_paid_bound=True,unbounded_search_complete=unbounded)
    require(dumps(actual)==dumps(expected),'exact window/operand/cost/priority/nominee/authority domain')
    require(engine.checkpoint()==native,'native unchanged')
    return dict(passed=True,capacity_audit=proof,windows=len(records),operands=operands,candidates=len(joined),
        nominee=None if actual['nominee'] is None else actual['nominee']['mean'],native_unchanged=True,execution_authorized=False)
