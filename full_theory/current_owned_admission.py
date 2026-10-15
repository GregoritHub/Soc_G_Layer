"""Current TD5 admission over a settled, immutable paid operand inventory.

This is a priced diagnostic domain, not authority to launch native work.
"""
from copy import deepcopy
from hashlib import sha256
from hle_unified.selection_records import dumps, loads, fields_of
from .autonomous_reuse import _restore_ledger
from .demand_controller import IntegratedDemandController
from .demand_requests import form_request
from .retention import Demand
from .route_policy import IntegratedRoutePolicy, SOCIAL
from .owned_operand_domain_audit import audit_owned_operand_domain


def current_owned_admission(engine, original, source, binding, domain, operands):
    audit_owned_operand_domain(engine, original, source, binding, domain, operands)
    before=engine.checkpoint(); old=loads(source); paid=loads(domain); expanded=loads(operands)
    result=dict(version='ft-current-owned-admission-v1',actor=old['actor'],setting=old['setting'],
        native_sha256=sha256(before.encode()).hexdigest(),source_sha256=sha256(source.encode()).hexdigest(),
        binding_sha256=sha256(binding.encode()).hexdigest(),operand_sha256=sha256(operands.encode()).hexdigest(),
        comparison_settled=expanded['comparison_settled'],formation=None,current_snapshot=None,
        admission=None,preparation_due=None,candidates=[],nominee=None,
        execution_authorized=False,history_choice=False,completion_claim=False)
    if expanded['comparison_settled']:
        controller=IntegratedDemandController.restore(old['demand_controller'])
        request,formation=form_request(engine.participant_view(old['actor']),controller.effective_demands())
        if request is None or fields_of(request)!=paid['request']:
            raise ValueError('current oldest owned request differs from paid comparison')
        if request.actor in engine._locks:
            raise ValueError('current actor is locked')
        current=(engine.selection_view(request) if old['setting']=='canonical'
                 else engine.workflow_selection_view(request))
        if any(current[k]!=v for k,v in paid['snapshot'].items() if k!='wallet'):
            raise ValueError('paid comparison inputs became stale')
        policy=IntegratedRoutePolicy(); policy.relay=dict(loads(old['route_policy'])['relay'])
        ledger=_restore_ledger(deepcopy(old['retention']),engine)
        admission=policy._admit(engine,request,Demand(**old['required']),ledger,tuple(sorted(ledger.certificates)))
        debt=loads(binding)['reserve_bindings'][-1]
        if debt['demand_id']!=request.key or debt['completion'] is not None:
            raise ValueError('exact unpaid admission required')
        preparation=debt['admission']['preparation']
        if type(preparation) is not int or preparation<0:
            raise ValueError('exact preparation units required')
        candidates=[]
        for priority,mean in enumerate(admission['options'][:-1]):
            for cell in expanded['cells']:
                for option in cell['options']:
                    p=option['proposal']; effort=p['effort']
                    # Empty/unpriced native proposals remain visible and ineligible.
                    valid=type(effort) is int and effort>=0
                    total=None if not valid else dict(energy=effort+mean['overhead']['energy']+2*preparation,
                        time=effort+mean['overhead']['time']+2*preparation)
                    social=any(n in p['recipe'] for n in SOCIAL)
                    reason=(mean['reason'] if not mean['eligible'] else p['reason'] if not p['eligible']
                        else 'native_effort_unpriced' if not valid else 'support_requires_social_recipe'
                        if mean['name']=='support' and not social else 'insufficient_current_wallet'
                        if any(current['wallet'][i]<total[u] for i,u in enumerate(('energy','time')))
                        else 'current_td5_and_estimated_cost_admissible')
                    candidates.append(dict(identity=dumps((mean['name'],cell['cell'],option['ordinal'],option['bundle'])),
                        mean=mean['name'],priority=priority,cell=cell['cell'],ordinal=option['ordinal'],
                        bundle=option['bundle'],recipe=p['recipe'],native_effort_estimate=effort,
                        route_overhead=mean['overhead'],preparation_cost=dict(energy=2*preparation,time=2*preparation),
                        total_estimate=total,eligible=reason=='current_td5_and_estimated_cost_admissible',reason=reason))
        candidates.append(dict(identity='defer',mean='defer',priority=5,cell=None,ordinal=None,bundle=(),recipe=None,
            native_effort_estimate=0,route_overhead=dict(energy=0,time=0),preparation_cost=dict(energy=0,time=0),
            total_estimate=dict(energy=0,time=0),eligible=True,reason='fallback_no_work_no_credit'))
        nominee=min((x for x in candidates if x['eligible']),key=lambda x:(x['priority'],x['total_estimate']['time'],
            x['total_estimate']['energy'],x['identity']))
        result.update(formation=formation,current_snapshot=current,admission=admission,
            preparation_due=preparation,candidates=candidates,nominee=deepcopy(nominee))
    if engine.checkpoint()!=before:raise ValueError('current domain mutated native state')
    return dumps(result)
