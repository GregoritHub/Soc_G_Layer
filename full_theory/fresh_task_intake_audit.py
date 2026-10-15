"""Independent fixed-panel, native payment and exact prefix reconstruction."""
from dataclasses import replace
from functools import lru_cache
from hashlib import sha256
from hle_unified import codec
from hle_unified.records import Account, ObjectId, ObjectRef
from hle_unified.particulars import Selector, DetailAddress
from hle_unified.operation_records import OperationRequest
from hle_unified.operations import address
from hle_unified.material import attrs
from hle_unified.selection_records import loads, dumps
from hle_unified.self_content import decode, encode
from hle_unified.development_audit import audit as audit_native
from hle_unified.workflow_selection_audit import extent
from .social_feedback_binding_audit import audit_social_feedback_binding


def digest(text): return sha256(text.encode()).hexdigest()


@lru_cache(maxsize=2)
def original_proof(native, source, binding, setting):
    from hle_unified.selection_execution import SelectionEngine
    from hle_unified.workflow_selection_execution import WorkflowFinalSelectionEngine
    typ = SelectionEngine if setting == 'canonical' else WorkflowFinalSelectionEngine
    engine = typ.restore(native)
    audit_social_feedback_binding(engine, source, binding)
    return True


def audit_fresh_task_intake(engine, original, source, binding, text):
    def require(ok, why):
        if not ok: raise ValueError('fresh intake audit: ' + why)
    d = loads(text); s = loads(source); b = loads(binding)
    fields = {'version','native_sha256','actor','setting','mask','source_sha256','binding_sha256',
        'source_native_sha256','expected_native_sha256','start_count','context','task','draft',
        'payload','original_particulars','jobs','reserve','history','controller_prefix','events',
        'receipt','comparison_paid','execution_authorized','td5_admitted','history_choice'}
    require(set(d) == fields and d['version'] == 'ft-fixed-fresh-task-intake-v1', 'schema')
    require(type(d['mask']) is int and 1 <= d['mask'] <= 15, 'fixed full panel member')
    require(d['native_sha256'] == d['expected_native_sha256'] == digest(engine.checkpoint()), 'native pairing')
    require(d['source_native_sha256'] == digest(original.checkpoint()) and
        d['source_sha256'] == digest(source) and d['binding_sha256'] == digest(binding), 'original pairing')
    original_proof(original.checkpoint(), source, binding, s['setting'])
    actor = s['actor']; view = original.participant_view(actor)
    require(d['actor'] == actor and d['setting'] == s['setting'] and s['phase'] == 'complete'
        and actor not in original._locks, 'completed unlocked source')
    controller = loads(s['demand_controller']); ledger = loads(controller['ledger'])
    for owned in view._heads.values():
        if owned.endorsement.value in ('retracted','disputed'): continue
        if any(p.relation in ('c6.need','c7ws.need') for p in owned.content):
            key = dumps((actor,owned.ref))
            require(key in ledger['demands'] and key in controller['outcomes'], 'all older current needs fulfilled')
    require(d['reserve'] == b['reserve'] and d['history'] == b['history'] and
        d['controller_prefix'] == s['demand_controller'], 'immutable accounting/controller prefixes')
    require(all(d[k] is False for k in ('comparison_paid','execution_authorized','td5_admitted','history_choice')),
        'no unauthorized acceptance flags')
    old = view._bindings[s['request']['fields']['demand']]
    raw = original.world.resolve(old.ref); account = raw.facet(Account)
    payload = decode(old.content[0].object)
    weights = tuple(10 * ((d['mask'] >> bit) & 1) for bit in range(4))
    payload['weights' if s['setting'] == 'canonical' else 'priorities'] = weights
    key = digest(source)[:20] + ':' + str(d['mask'])
    task = ObjectRef(ObjectId('ft.fresh.task', key), 1)
    expected = replace(raw, ref=task, label='Fixed route-free fresh task',
        facets=(replace(account, content=(replace(old.content[0],object=encode(payload)),), sources=account.sources+(task,)),))
    read = 'ft-fresh-read:' + key; bind = 'ft-fresh-bind:' + key; delivery = read + ':delivery'
    require(d['draft'] == codec.dumps(expected) and d['payload'] == encode(payload)
        and d['context'] == old.context and d['task'] == task and d['jobs'] == (read,bind)
        and d['original_particulars'] == old.particulars, 'independent route-free draft reconstruction')
    require(task.identity not in original.world._heads and not any((actor,k) in original._jobs for k in (read,bind)),
        'genuinely fresh task and work')
    prior = tuple(original.world.journal()); txs = tuple(engine.world.journal())
    require(d['start_count'] == len(prior) and txs[:len(prior)] == prior, 'native journal prefix')
    require(engine._initial == original._initial and engine.law == original.law
        and engine.resource_model == original.resource_model, 'unchanged configuration')
    commands = tuple(engine._pool.get(t) for t in engine._events)
    old_commands = tuple(original._pool.get(t) for t in original._events)
    require(commands[:len(old_commands)] == old_commands, 'exact command prefix')
    access = tuple(engine.access.pool.get(t) for t in engine.access._events)
    old_access = tuple(original.access.pool.get(t) for t in original.access._events)
    require(access[:len(old_access)] == old_access, 'exact access prefix')
    audit_native(txs, extent_check=extent, extended_flags=('c1','c2','c3','c4','c6','c7w','c7ws'))
    def heads(end): return {v.ref.identity:v for tx in txs[:end] for v in tx.versions}
    def wallet(h):
        values = [attrs(v) for v in h.values() if attrs(v).get('record_type') == 'wallet' and attrs(v).get('actor') == actor]
        require(len(values) == 1, 'unique wallet'); return values[0]
    expected_commands = []; end = len(prior); read_done = False; bound = False; total = 0
    for i,event in enumerate(d['events']):
        require(set(event) == {'index','kind','job','before','after','wallet_before','wallet_after','debit','work_limit','status'}, 'event schema')
        require(not bound and event['index'] == i and event['before'] == end and
            type(event['after']) is int and end < event['after'] <= len(txs), 'contiguous event boundaries')
        require(type(event['work_limit']) is int and event['work_limit'] > 0, 'work quantum')
        kind = 'bind' if read_done else 'read'; job = bind if read_done else read
        require((event['kind'],event['job']) == (kind,job), 'read then bind order')
        if i == 0: expected_commands.append(('declare', read + ':draft', (expected,)))
        cid = job + ':step:' + str(i); identity = address('u4.operation',actor,job).identity
        before = heads(end); after = heads(event['after'])
        require(identity in after, 'native operation')
        op_version = after[identity]; op = attrs(op_version)
        previous = attrs(before[identity]) if identity in before else {}
        if not previous:
            if kind == 'read':
                expected_commands.append(('disclose',delivery,actor,task,
                    (Selector('ft.fresh.payload','definition',('facets','0','content','0','object')),),task))
                request = OperationRequest(job,actor,kind,old.context,delivery=delivery)
            else:
                request = OperationRequest(job,actor,kind,old.context,binding=task,
                    evidence=old.particulars+(DetailAddress(delivery,'ft.fresh.payload'),))
            expected_commands.append(('start',cid+':start',request))
        bw = wallet(before); aw = wallet(after); delta = op['completed'] - previous.get('completed',0)
        require(event['wallet_before'] == bw and event['wallet_after'] == aw and
            event['debit'] == {u:bw[u]-aw[u] for u in ('energy','time')} == dict(energy=delta,time=delta)
            and 0 <= delta <= event['work_limit'], 'actual paid debit')
        if previous.get('status') != 'ready' and min(bw['energy'],bw['time']) > 0:
            expected_commands.append(('advance',cid+':work',actor,job,event['work_limit']))
        require(op['primitive'] == kind and op['actor'] == actor and op['context'] == old.context
            and op['required'] == (2 if kind == 'read' else 3) and op['spent'] == op['completed']
            and op['started_tick'] >= len(prior) and event['status'] == op['status'], 'native operation identity and extent')
        require(op['status'] in ('partial','waiting','succeeded'), 'registered lifecycle')
        if op['status'] == 'succeeded':
            expected_commands.append(('commit',cid+':commit',actor,job))
            require(op['completed'] == op['required'], 'complete paid extent')
            if kind == 'read': read_done = True
            else: bound = True
        total += delta; end = event['after']
    require(end == len(txs), 'no unaccounted journal suffix')
    require(tuple(x[0] for x in commands[len(old_commands):]) == tuple(expected_commands), 'exact intake-only commands')
    # Replay validates every access result and native command, not just declared labels.
    replay = type(engine).restore(engine.checkpoint())
    require(replay.access.checkpoint() == engine.access.checkpoint(), 'independent access replay')
    require(dict(engine.wallet(actor)) == wallet(heads(len(txs))), 'wallet readback')
    if d['events']:
        require(engine.world.resolve(task) == expected, 'exact declared task, no later rewrite')
    if read_done:
        detail = engine.participant_view(actor).detail(DetailAddress(delivery,'ft.fresh.payload'))
        require(detail is not None and (detail.source,detail.path,detail.value) ==
            (task,('facets','0','content','0','object'),encode(payload)), 'exact fresh paid disclosure')
    current = engine.participant_view(actor)._bindings.get(task)
    if bound:
        require(current is not None and current.content == expected.facet(Account).content and
            current.particulars == old.particulars+(DetailAddress(delivery,'ft.fresh.payload'),), 'owned task content/evidence')
        paid = engine.participant_view(actor).receipt(current.receipt)
        require(paid is not None and paid.complete and paid.spent == paid.required == 3 and paid.operation == 'bind', 'new paid bind receipt')
        receipt = dict(task=task,read_operation=engine._jobs[actor,read],bind_operation=engine._jobs[actor,bind],
            owned_receipt=current.receipt,energy=5,time=5)
        require(total == 5 and d['receipt'] == receipt, 'unique intake receipt')
    else:
        require(current is None and d['receipt'] is None, 'no partial owned task or receipt')
    return dict(passed=True,mask=d['mask'],bound=bound,native_cost=dict(energy=total,time=total),
        source_prefix_exact=True,controller_prefix_exact=True,reserve_history_unchanged=True,
        comparison_paid=False,execution_authorized=False,td5_admitted=False,history_choice=False)
