"""Independent comparison/preparation composition audit; no runtime imports."""
from hashlib import sha256

from hle_unified import codec
from hle_unified.material import attrs
from hle_unified.operations import address
from hle_unified.particulars import DetailAddress, Selector
from hle_unified.operation_records import OperationRequest
from hle_unified.records import Account
from hle_unified.selection_records import loads
from hle_unified.development_audit import audit as audit_native
from hle_unified.workflow_selection_audit import extent as previous_extent
from .current_owned_admission_audit import audit_current_owned_admission
from .social_feedback_binding_audit import audit_social_feedback_binding
from .use_history_audit import audit_use_history


def audit_compared_preparation(engine, comparison, source_engine, source, binding, domain, operands, admission_text, checkpoint):
    def require(ok, reason):
        if not ok:
            raise ValueError('paid preparation audit: ' + reason)
    def digest(text):
        return sha256(text.encode()).hexdigest()
    audit_current_owned_admission(comparison, source_engine, source, binding, domain, operands, admission_text)
    current = loads(admission_text)
    require(current['comparison_settled'] and current['admission'] is not None, 'settled current comparison')
    d = loads(checkpoint); b = loads(binding); r = loads(source)
    fields = {'version', 'native_sha256', 'actor', 'source_sha256', 'binding_sha256',
        'source_native_sha256', 'start_count', 'prefix_sha256', 'request', 'admission',
        'required', 'path', 'payload', 'reserve', 'history_prefix', 'history',
        'events', 'receipts', 'windows', 'jobs', 'comparison_native_sha256', 'comparison_count',
        'comparison_prefix_sha256', 'domain_sha256', 'operands_sha256', 'admission_sha256',
        'expected_native_sha256', 'execution_authorized', 'history_choice'}
    require(set(d) == fields and d['version'] == 'ft-compared-social-preparation-v1', 'schema')
    require(d['native_sha256'] == digest(engine.checkpoint()), 'exact current native pairing')
    require(d['source_native_sha256'] == digest(source_engine.checkpoint()) and
        d['source_sha256'] == digest(source) and d['binding_sha256'] == digest(binding), 'source pairing')
    audit_social_feedback_binding(source_engine, source, binding)
    oldtx = tuple(source_engine.world.journal()); txs = tuple(engine.world.journal())
    require(d['start_count'] == len(oldtx) and txs[:len(oldtx)] == oldtx and
        d['prefix_sha256'] == digest(codec.dumps(oldtx)), 'immutable native prefix')
    compared = tuple(comparison.world.journal())
    require(txs[:len(compared)] == compared and d['comparison_count'] == len(compared) and
        d['comparison_prefix_sha256'] == digest(codec.dumps(compared)) and
        d['comparison_native_sha256'] == digest(comparison.checkpoint()), 'exact comparison prefix')
    require(d['domain_sha256'] == digest(domain) and d['operands_sha256'] == digest(operands) and
        d['admission_sha256'] == digest(admission_text) and
        d['expected_native_sha256'] == d['native_sha256'], 'exact composition pairing')
    require(d['execution_authorized'] is False and d['history_choice'] is False, 'no execution or choice authority')
    extent_required = loads(domain)['comparison_required']
    def extent(op):
        if not op.get('ftpc'): return previous_extent(op)
        require(op['required'] == extent_required and op['route_prepare'] == extent_required and
            op['route_execute'] == 0 and op['primitive'] == 'bind', 'comparison extent')
    audit_native(txs, extent_check=extent, extended_flags=('c1','c2','c3','c4','c6','c7w','c7ws','ftpc'))
    command_rows = tuple(engine._pool.get(t) for t in engine._events)
    prefix_commands = tuple(comparison._pool.get(t) for t in comparison._events)
    require(command_rows[:len(prefix_commands)] == prefix_commands, 'exact command prefix')
    expected_commands = []
    require(engine._initial == comparison._initial and engine.law == comparison.law and
        engine.resource_model == comparison.resource_model, 'native configuration unchanged')
    require(d['actor'] == r['actor'] and d['request'] == r['request']['fields'] and
        d['admission'] == b['reserve_bindings'][-1] and d['reserve'] == b['reserve'] and
        d['history_prefix'] == b['history'], 'original request and ledgers')
    admission = d['admission']; debt = admission['admission']['preparation']
    require(type(debt) is int and debt > 0 and d['required'] == debt and
        admission['completion'] is None and admission['demand_id'] == d['request']['key'], 'unpaid debt')
    actor = d['actor']; request = d['request']; view = source_engine.participant_view(actor)
    owned = view._bindings[request['demand']]; paid = view.receipt(owned.receipt)
    require(max(x.ref.revision for x in view.snapshot.bindings if x.ref.identity == owned.ref.identity) ==
        owned.ref.revision and owned.endorsement.value not in ('retracted','disputed') and
        (owned.actor,owned.context,owned.cue,owned.target) ==
        (actor,request['context'],request['cue'],request['target']) and len(owned.content) == 1 and
        paid is not None and paid.complete and paid.actor == actor and paid.spent >= paid.required, 'paid current owned task')
    obj = source_engine.world.resolve(request['demand']); account = obj.facet(Account)
    require(account.holder == actor and account.content == owned.content and d['payload'] == owned.content[0].object and
        d['path'] == ('facets',str(obj.facets.index(account)),'content','0','object'), 'task payload/selector')
    jobs = tuple('ft-social-preparation:' + digest(binding)[:20] + ':' + str(i) for i in range(debt))
    require(d['jobs'] == jobs and not any((actor,k) in comparison._jobs for k in jobs), 'fresh job identities')
    require(len(d['receipts']) <= debt, 'receipt bound')
    def heads(n):
        return {v.ref.identity: v for tx in txs[:n] for v in tx.versions}
    def wallet(h):
        rows = [attrs(v) for v in h.values() if attrs(v).get('record_type') == 'wallet' and attrs(v).get('actor') == actor]
        require(len(rows) == 1, 'unique native wallet')
        return rows[0]
    end = len(compared); receipts = []; completion_ends = []
    for i, e in enumerate(d['events']):
        require(set(e) == {'index','job','before','after','wallet_before','wallet_after','debit',
            'work_limit','status','bound','remaining'}, 'event fields')
        require(e['index'] == i and e['before'] == end and type(e['after']) is int and
            end <= e['after'] <= len(txs) and len(receipts) < debt, 'contiguous event domain')
        require(type(e['work_limit']) is int and e['work_limit'] >= 1, 'work quantum')
        job = jobs[len(receipts)]; delivery = job + ':delivery'
        require(e['job'] == job, 'debt read order')
        before = heads(end); after = heads(e['after']); identity = address('u4.operation',actor,job).identity
        require(identity in after, 'native read exists')
        v = after[identity]; op = attrs(v); previous = attrs(before[identity]) if identity in before else {}
        delta = op['completed'] - previous.get('completed',0)
        bw = wallet(before); aw = wallet(after)
        require(e['wallet_before'] == bw and e['wallet_after'] == aw and
            e['debit'] == {u:bw[u]-aw[u] for u in ('energy','time')} == dict(energy=delta,time=delta) and
            0 <= delta <= e['work_limit'], 'exact native payment')
        require(op['primitive'] == 'read' and op['actor'] == actor and op['required'] == 2 and
            op['spent'] == op['completed'] and op['input.0'] == request['demand'] and
            op['delivery'] == delivery and op['context'] == request['context'] and
            op['started_tick'] >= len(compared) and e['status'] == op['status'], 'fresh scoped task read')
        command = job + ':step:' + str(i)
        if not previous:
            expected_commands.extend((
                ('disclose', delivery, actor, request['demand'],
                    (Selector('ft.reserve.task','definition',d['path']),), request['demand']),
                ('start', command + ':start', OperationRequest(job,actor,'read',request['context'],delivery=delivery))))
        require(previous.get('status') not in ('succeeded','failed','cancelled'), 'no terminal replay event')
        if previous.get('status') != 'ready' and min(bw['energy'],bw['time']) > 0:
            expected_commands.append(('advance',command + ':work',actor,job,e['work_limit']))
        if op['status'] == 'succeeded':
            expected_commands.append(('commit',command + ':commit',actor,job))
        require(op['status'] in ('partial','waiting','succeeded'), 'registered preparation states')
        for tx in txs[end:e['after']]:
            vs = {v.ref.identity:v for v in tx.versions}
            require(identity in vs and len(vs) == len(tx.versions), 'only current read transaction')
            stage = attrs(vs[identity])['status']
            allowed = {identity}
            if stage in ('partial','waiting','ready'):
                allowed |= {v.ref.identity for v in tx.versions
                    if attrs(v).get('record_type') == 'wallet' and attrs(v).get('actor') == actor}
            elif stage == 'succeeded':
                allowed |= {address('u4.receipt',command + ':commit').identity,
                            address('u4.event',command + ':commit').identity}
            require(set(vs) == allowed, 'no unrelated suffix version')
        if op['status'] == 'succeeded':
            require(op['spent'] == op['completed'] == 2, 'read fully paid')
            detail = engine.participant_view(actor).detail(DetailAddress(delivery,'ft.reserve.task'))
            require(detail is not None and (detail.source,detail.path,detail.value) ==
                (request['demand'],d['path'],d['payload']), 'read exact realized payload')
            receipts.append(dict(job=job, operation=v.ref, delivery=delivery,
                demand=request['demand'],energy=2,time=2))
            completion_ends.append((job,e['after']))
        require(e['bound'] == len(receipts) and e['remaining'] == debt-len(receipts), 'no partial receipt')
        end = e['after']
    require(end == len(txs) and receipts == d['receipts'], 'complete extension and receipt domain')
    require(tuple(x[0] for x in command_rows[len(prefix_commands):]) == tuple(expected_commands),
        'exact preparation-only command suffix')
    old = loads(b['history']); now = loads(d['history'])
    observed_end = completion_ends[-1][1] if completion_ends else len(oldtx)
    audit_use_history(d['history'],txs[:observed_end])
    require(old['journal_count'] == len(oldtx) and now['journal_count'] == observed_end and
        now['scores'] == old['scores'] and now['native_counts'] == old['native_counts'] and
        now['tag_totals'] == old['tag_totals'], 'read grants no independent processing credit')
    require(now['base'] == old['base'] and now['events'][:len(old['events'])] == old['events'] and
        now['event_count'] == old['event_count']+len(completion_ends) and
        len(now['events']) == now['event_count'], 'immutable history events')
    require(len(d['windows']) == len(completion_ends), 'exact read history window domain')
    left = len(oldtx)
    for row,(job,right),event in zip(d['windows'],completion_ends,now['events'][len(old['events']):]):
        require(row == dict(start=left,end=right,job=job,event=event) and
            event['journal_before']['count'] == left and event['journal_after']['count'] == right and
            event['classifications'] == () and not any(event['credit_delta'].values()), 'read-only outcome window')
        left = right
    if not receipts:
        require(d['history'] == b['history'], 'pending history must stay byte-exact')
    return dict(passed=True, source_prefix_exact=True, required=debt, bound=len(receipts),
        remaining=debt-len(receipts), native_cost={u:sum(e['debit'][u] for e in d['events']) for u in ('energy','time')},
        comparison_cost={u:loads(domain)['comparison_required'] for u in ('energy','time')},
        comparison_prefix_exact=True, command_prefix_exact=True,
        reserve_unchanged=True, independent_credit=False, live_choice_causality=False)
