"""Independent current capacity reconstruction; no new builder or policy imports."""
from copy import deepcopy
from hashlib import sha256
from hle.model_a import fields as seat_fields
from hle_unified.selection_records import dumps, loads
from hle_unified.self_content import decode
from .content import FACETS
from .paid_window_comparison_audit import audit_paid_windows
from .route_means_audit import audit_route_means


def audit_current_window_capacity(engine, old, original, source, binding, intake, windows, text):
    def require(ok, reason):
        if not ok: raise ValueError('current window capacity audit: '+reason)
    digest = lambda x: sha256(x.encode()).hexdigest()
    native = engine.checkpoint()
    paid = audit_paid_windows(engine,old,original,source,binding,intake,windows)
    s,b,i,w,out = map(loads,(source,binding,intake,windows,text)); actor=s['actor']
    expected = dict(version='ft-current-window-capacity-v1',setting=s['setting'],actor=actor,
        native_sha256=digest(native),original_sha256=digest(original.checkpoint()),
        source_sha256=digest(source),binding_sha256=digest(binding),intake_sha256=digest(intake),
        windows_sha256=digest(windows),comparison_status=paid['status'],comparison_settled=paid['status']=='succeeded',
        controller_prefix_sha256=digest(s['demand_controller']),retention_prefix_sha256=digest(dumps(s['retention'])),
        reserve_prefix_sha256=digest(b['reserve']),history_prefix_sha256=digest(b['history']),
        required=None,inventory=None,means=(),retained=(),windows=(),preparation=None,selected=None,
        execution_authorized=False,td5_admitted=False,history_choice=False,full_operand_cost_domain=False,
        completion_claim=False,prefixes_mutated=False)
    if paid['status']=='succeeded':
        view=engine.participant_view(actor)
        require(actor not in engine._locks and view.bytes()==old.participant_view(actor).bytes()
            and engine._profiles==old._profiles and engine._cursors==old._cursors,'current input/profile/cursor pairing')
        task=view._bindings[i['task']]; previous=original.participant_view(actor)._bindings[s['request']['fields']['demand']]
        now_payload,old_payload=decode(task.content[0].object),decode(previous.content[0].object)
        changed='weights' if s['setting']=='canonical' else 'priorities'
        require(set(now_payload)==set(old_payload) and all(now_payload[k]==old_payload[k] for k in old_payload if k!=changed)
            and now_payload[changed]==tuple(10 if i['mask']//(2**j)%2 else 0 for j in range(4)),'priority-only input bridge')
        dem=deepcopy(s['required'])
        require((dem['family'],dem['context'],dem['cue'],dem['target'])==
            (s['setting'],task.context,task.cue,task.target),'exact conjunctive demand scope')
        first=w['requests'][0]; variable={'key','accessible'} if s['setting']=='workflow' else {'key'}
        for fields in w['requests']:
            require(set(fields)==set(first) and all(fields[k]==first[k] for k in first if k not in variable)
                and all(fields.get(k) is None for k in ('stock','tool','repair_stock','procedure','relation','peer','group')),
                'common capacity inputs and no support role')
        inv=deepcopy(out.get('inventory'))
        require(type(inv) is dict and set(inv)=={'policy','setting','at_tick','actor','demand','request',
            'tim','active_element','active_seat','wallet','options','selected','completion_claim','view_sha256'},
            'exact inventory schema')
        require(type(inv) is dict and inv.pop('view_sha256',None)==digest(view.bytes()),'current inventory view')
        inv['view']=view.bytes()
        require(inv['request']==first and inv['setting']==s['setting'],'representative inventory request')
        audit_route_means(tuple(engine.world.journal()),inv)
        origin=inv['active_seat']
        require(dict(loads(s['route_policy'])['relay']).get(actor,origin)==origin,'relay/native seam')
        ret=s['retention']; retained=[]
        recalled=view.traverse(dem['cue'],dem['context'])
        for key,c in sorted(ret['certificates'].items()):
            scope=c['scope']
            ordered=((scope['family'],scope['context'],scope['cue'])==(dem['family'],dem['context'],dem['cue'])
                and set(scope['requirements'])>=set(dem['requirements']) and set(scope['obligations'])>=set(dem['obligations'])
                and set(scope['alternatives'])<=set(dem['alternatives']) and scope['load']>=dem['load']
                and scope['deadline']<=dem['deadline'] and set(scope['support_allowed'])<=set(dem['support_allowed']))
            owned=(c['binding'] in view._bindings and view._bindings[c['binding']].endorsement.value not in ('retracted','disputed')) or bool(view.resolve(c['binding']))
            reason=('revoked_evidence' if key in ret['revoked'] else 'foreign_certificate' if c['actor']!=actor
                else 'outside_trained_demand_bounds' if not ordered else 'no_present_access' if not owned
                else 'not_recalled' if recalled.truncated or c['binding'] not in recalled.visited
                else 'support_withdrawn' if not set(c['required_support'])<=set(dem['support_allowed'])
                else 'owned_recalled_scoped_capacity')
            retained.append(dict(key=key,eligible=reason=='owned_recalled_scoped_capacity',reason=reason,certificate=deepcopy(c)))
        cert=next((c for c in retained if c['eligible']),None)
        covered=lambda seat:set(dem['requirements'])<=set(FACETS[:seat_fields(seat)['dimensionality']])
        ok=cert is not None and covered(origin)
        means=[dict(name='retained',eligible=ok,reason='owned_recalled_scoped_capacity' if ok else
            'no_applicable_capacity' if cert is None else 'current_dimensionality_insufficient',target_seat=origin,
            overhead=dict(energy=0,time=0),certificate=None if cert is None else cert['key'])]
        geometry={row['name']:row for row in inv['options']}
        for name in ('ordinary','n','cp'):
            row=geometry[name]; eligible=bool(row['eligible'] and covered(row['target_seat']))
            means.append(dict(name=name,eligible=eligible,reason='required_facets_available' if eligible else
                row['reason'] if not row['eligible'] else 'target_dimensionality_insufficient',
                target_seat=row['target_seat'],overhead=row['overhead']))
        means.extend((dict(name='support',eligible=False,reason='no_exact_allowed_consent',target_seat=origin,
            overhead=dict(energy=0,time=0),support=None),dict(name='defer',eligible=True,reason='no_feasible_prior_mean',
            target_seat=origin,overhead=dict(energy=0,time=0))))
        reserve=loads(b['reserve']); identity=dumps((actor,task.ref))
        require(reserve['actor']==actor and reserve['policy']=='load-v1' and identity not in reserve['demands'],
            'fresh reserve task, no borrowed old admission')
        balance=reserve['initial']
        for event in reserve['events']:
            require(event['balance_before']==balance and event['balance_after']==balance+event['delta'],'reserve prefix arithmetic')
            balance=event['balance_after']
        require(balance==reserve['balance'] and type(balance) is int and 0<=balance<=8,'current exact reserve')
        units=max(0,dem['load']-balance)
        expected.update(required=dem,inventory=deepcopy(out['inventory']),means=tuple(means),retained=tuple(retained),
            windows=tuple(dict(ordinal=n,request_sha256=digest(dumps(fields))) for n,fields in enumerate(w['requests'])),
            preparation=dict(demand_id=identity,task=task.ref,policy='load-v1',reserve=balance,load=dem['load'],
                units=units,energy=2*units,time=2*units,intake_credit=0,comparison_credit=0,receipt=None,admitted=False))
    require(dumps(out)==dumps(expected),'exact capacity, debt, prefix, wallet and authority projection')
    require(engine.checkpoint()==native,'native state unchanged')
    return dict(passed=True,paid_audit=paid,windows=len(out['windows']),means=len(out['means']),
        current_wallet=None if out['inventory'] is None else out['inventory']['wallet'],
        preparation_units=None if out['preparation'] is None else out['preparation']['units'],
        native_unchanged=True,execution_authorized=False,td5_admitted=False,history_choice=False)
