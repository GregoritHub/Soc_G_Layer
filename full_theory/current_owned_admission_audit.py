"""Independent current admission reconstruction; no new controller imports."""
from copy import deepcopy
from hashlib import sha256
from hle.model_a import fields as seat_fields
from hle_unified.selection_records import dumps,loads,fields_of
from .content import FACETS
from .owned_operand_domain_audit import audit_owned_operand_domain
from .owned_proposal_domain_audit import _request,_snapshot
from .route_means_audit import audit_route_means


def audit_current_owned_admission(engine,original,source,binding,domain,operands,text):
    previous=audit_owned_operand_domain(engine,original,source,binding,domain,operands)
    out=loads(text);old=loads(source);paid=loads(domain);op=loads(operands)
    expected=dict(version='ft-current-owned-admission-v1',actor=old['actor'],setting=old['setting'],
        native_sha256=sha256(engine.checkpoint().encode()).hexdigest(),source_sha256=sha256(source.encode()).hexdigest(),
        binding_sha256=sha256(binding.encode()).hexdigest(),operand_sha256=sha256(operands.encode()).hexdigest(),
        comparison_settled=op['comparison_settled'],formation=None,current_snapshot=None,
        admission=None,preparation_due=None,candidates=[],nominee=None,
        execution_authorized=False,history_choice=False,completion_claim=False)
    if op['comparison_settled']:
        view=engine.participant_view(old['actor']);request,formation=_request(view,old)
        if request is None or fields_of(request)!=paid['request'] or old['actor'] in engine._locks:
            raise ValueError('current owned request or lock differs')
        current=_snapshot(engine,view,request,old['setting'])
        if any(current[k]!=v for k,v in paid['snapshot'].items() if k!='wallet'):
            raise ValueError('stale paid operand snapshot')
        a=out.get('admission')
        if type(a) is not dict:raise ValueError('missing admission')
        inv=a['inventory'];audit_route_means(tuple(engine.world.journal()),inv)
        if inv['request']!=fields_of(request) or inv['view']!=view.bytes():raise ValueError('current inventory pairing')
        dem=old['required'];origin=inv['active_seat']
        if dict(loads(old['route_policy'])['relay']).get(request.actor,origin)!=origin:
            raise ValueError('relay seam differs')
        if (dem['context'],dem['cue'],dem['target'])!=(request.context,request.cue,request.target):
            raise ValueError('demand scope differs')
        ret=old['retention'];retained=[]
        for key,c in sorted(ret['certificates'].items()):
            bound=c['scope']
            ordered=((bound['family'],bound['context'],bound['cue'])==(dem['family'],dem['context'],dem['cue'])
                and set(bound['requirements'])>=set(dem['requirements']) and set(bound['obligations'])>=set(dem['obligations'])
                and set(bound['alternatives'])<=set(dem['alternatives']) and bound['load']>=dem['load']
                and bound['deadline']<=dem['deadline'] and set(bound['support_allowed'])<=set(dem['support_allowed']))
            owned=(c['binding'] in view._bindings and view._bindings[c['binding']].endorsement.value not in ('retracted','disputed')) or bool(view.resolve(c['binding']))
            recalled=view.traverse(dem['cue'],dem['context'])
            reason=('revoked_evidence' if key in ret['revoked'] else 'foreign_certificate' if c['actor']!=request.actor
                else 'outside_trained_demand_bounds' if not ordered else 'no_present_access' if not owned
                else 'not_recalled' if recalled.truncated or c['binding'] not in recalled.visited
                else 'support_withdrawn' if not set(c['required_support'])<=set(dem['support_allowed'])
                else 'owned_recalled_scoped_capacity')
            retained.append(dict(key=key,eligible=reason=='owned_recalled_scoped_capacity',reason=reason,certificate=deepcopy(c)))
        cert=next((x for x in retained if x['eligible']),None)
        consent=[]
        if request.peer is not None and request.group is not None and request.peer in dem['support_allowed']:
            for x in current['items']:
                d=x['data']
                if (d.get('kind')=='reply' and d.get('speaker')==request.peer and d.get('receiver')==request.actor
                    and d.get('group')==request.group and d.get('context')==request.context
                    and d.get('target')==request.target and d.get('consent') is True):consent.append(dict(ref=x['ref'],data=d))
        support=min(consent,key=lambda x:dumps(x['ref'])) if consent else None
        covered=lambda seat:set(dem['requirements'])<=set(FACETS[:seat_fields(seat)['dimensionality']])
        ok=cert is not None and covered(origin)
        means=[dict(name='retained',eligible=ok,reason='owned_recalled_scoped_capacity' if ok else
            'no_applicable_capacity' if cert is None else 'current_dimensionality_insufficient',target_seat=origin,
            overhead=dict(energy=0,time=0),certificate=None if cert is None else cert['key'])]
        native={x['name']:x for x in inv['options']}
        for name in ('ordinary','n','cp'):
            n=native[name];good=bool(n['eligible'] and covered(n['target_seat']))
            means.append(dict(name=name,eligible=good,reason='required_facets_available' if good else
                n['reason'] if not n['eligible'] else 'target_dimensionality_insufficient',target_seat=n['target_seat'],overhead=n['overhead']))
        means.extend((dict(name='support',eligible=support is not None,reason='exact_paid_peer_consent' if support else 'no_exact_allowed_consent',
            target_seat=origin,overhead=dict(energy=0,time=0),support=None if support is None else support['ref']),
            dict(name='defer',eligible=True,reason='no_feasible_prior_mean',target_seat=origin,overhead=dict(energy=0,time=0))))
        selected=next(x for x in means if x['eligible'])
        admission=dict(actor=request.actor,key=request.key,request=fields_of(request),setting=old['setting'],demand=dem,
            inventory=inv,options=tuple(means),selected=deepcopy(selected),retained=tuple(retained),
            retention_events=tuple(deepcopy(ret['events'])),support=deepcopy(support),origin_seat=origin,
            origin_dimension=seat_fields(origin)['dimensionality'],status='deferred' if selected['name']=='defer' else 'admitted',
            orientation_ticket=None,traversal=None)
        debt=loads(binding)['reserve_bindings'][-1]
        if debt['demand_id']!=request.key or debt['completion'] is not None:raise ValueError('debt scope differs')
        prep=debt['admission']['preparation'];candidates=[]
        for priority,m in enumerate(means[:-1]):
            for cell in op['cells']:
                for option in cell['options']:
                    p=option['proposal'];effort=p['effort'];valid=type(effort) is int and effort>=0
                    total={u:effort+m['overhead'][u]+2*prep for u in ('energy','time')} if valid else None
                    reason='current_td5_and_estimated_cost_admissible'
                    if not m['eligible']:reason=m['reason']
                    elif not p['eligible']:reason=p['reason']
                    elif not valid:reason='native_effort_unpriced'
                    elif m['name']=='support' and not any(n in p['recipe'] for n in ('share','coordinate','educate','identify','mobilize','institutionalize','commune')):reason='support_requires_social_recipe'
                    elif current['wallet'][0]<total['energy'] or current['wallet'][1]<total['time']:reason='insufficient_current_wallet'
                    candidates.append(dict(identity=dumps((m['name'],cell['cell'],option['ordinal'],option['bundle'])),mean=m['name'],priority=priority,
                        cell=cell['cell'],ordinal=option['ordinal'],bundle=option['bundle'],recipe=p['recipe'],native_effort_estimate=effort,
                        route_overhead=m['overhead'],preparation_cost=dict(energy=2*prep,time=2*prep),total_estimate=total,
                        eligible=reason=='current_td5_and_estimated_cost_admissible',reason=reason))
        candidates.append(dict(identity='defer',mean='defer',priority=5,cell=None,ordinal=None,bundle=(),recipe=None,
            native_effort_estimate=0,route_overhead=dict(energy=0,time=0),preparation_cost=dict(energy=0,time=0),
            total_estimate=dict(energy=0,time=0),eligible=True,reason='fallback_no_work_no_credit'))
        nominee=sorted((x for x in candidates if x['eligible']),key=lambda x:(x['priority'],x['total_estimate']['time'],x['total_estimate']['energy'],x['identity']))[0]
        expected.update(formation=formation,current_snapshot=current,admission=admission,preparation_due=prep,candidates=candidates,nominee=nominee)
    if dumps(out)!=dumps(expected):raise ValueError('current admission domain, estimate, priority or authority differs')
    return dict(passed=True,operand_audit=previous,candidates=len(out['candidates']),
        nominee=None if out['nominee'] is None else out['nominee']['mean'],execution_authorized=False)
