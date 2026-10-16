"""Independent A12B cue/provenance, native payment and exact prefix reconstruction."""
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
from .observed_cue_panel_audit import audit as audit_panel


def digest(text): return sha256(text.encode()).hexdigest()


@lru_cache(maxsize=2)
def original_proof(native, source, binding, setting):
    from hle_unified.selection_execution import SelectionEngine
    from hle_unified.workflow_selection_execution import WorkflowFinalSelectionEngine
    typ = SelectionEngine if setting == 'canonical' else WorkflowFinalSelectionEngine
    engine = typ.restore(native)
    audit_social_feedback_binding(engine, source, binding)
    return True


def audit_cue_task_intake(engine, original, source, binding, panel, text):
    def require(ok, why):
        if not ok: raise ValueError('cue intake audit: ' + why)
    d = loads(text); s = loads(source); b = loads(binding)
    fields = {'version','native_sha256','actor','setting','mask','source_sha256','binding_sha256',
        'source_native_sha256','expected_native_sha256','start_count','context','task','draft',
        'payload','original_particulars','jobs','reserve','history','controller_prefix','events',
        'receipt','panel_sha256','cue','cancelled','comparison_paid','execution_authorized','td5_admitted','history_choice'}
    require(set(d) == fields and d['version'] == 'ft-observed-cue-task-intake-a12b-v1', 'schema')
    require(type(d['mask']) is int and 1 <= d['mask'] <= 15, 'fixed full panel member')
    require(d['native_sha256'] == d['expected_native_sha256'] == digest(engine.checkpoint()), 'native pairing')
    require(d['source_native_sha256'] == digest(original.checkpoint()) and
        d['source_sha256'] == digest(source) and d['binding_sha256'] == digest(binding), 'original pairing')
    audit_panel(original.checkpoint(), source, binding, s['setting'], panel)
    panel_data = loads(panel)
    rows = [r for r in panel_data['rows'] if r['mask'] == d['mask'] and not r['historical_only']]
    require(len(rows) == 1 and d['cue'] == rows[0]['cue'] and d['panel_sha256'] == digest(panel), 'exact new panel member')
    require(type(d['cancelled']) is bool, 'cancellation flag type')
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
    cue = rows[0]['cue']
    cue_addresses = tuple(DetailAddress(*a) for c, entries in panel_data['cue_evidence'] if c == cue for a, receipts in entries)
    evidence = tuple(dict.fromkeys(old.particulars + cue_addresses))
    sources = tuple(dict.fromkeys(view.detail(a).source for a in evidence))
    key = digest(source)[:20] + ':' + digest(dumps((cue,d['mask'])))[:20]
    task = ObjectRef(ObjectId('ft.cue.task', key), 1)
    expected = replace(raw, ref=task, label='Paid observed-cue route-free task',
        attributes=tuple(replace(a,value=cue) if a.name == 'cue' else a for a in raw.attributes),
        facets=(replace(account, content=(replace(old.content[0],object=encode(payload)),), sources=sources+(task,)),))
    read = 'ft-cue-read:' + key; bind = 'ft-cue-bind:' + key; delivery = read + ':delivery'
    require(d['draft'] == codec.dumps(expected) and d['payload'] == encode(payload)
        and d['context'] == old.context and d['task'] == task and d['jobs'] == (read,bind)
        and d['original_particulars'] == tuple((a.delivery,a.key) for a in evidence), 'independent route-free draft reconstruction')
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
    expected_commands = []; end = len(prior); read_done = False; bound = False; total = 0; cancelled = False
    for i,event in enumerate(d['events']):
        require(set(event) == {'index','kind','job','before','after','wallet_before','wallet_after','debit','work_limit','commit_ready','cancel','status'}, 'event schema')
        require(not bound and not cancelled and event['index'] == i and event['before'] == end and
            type(event['after']) is int and end < event['after'] <= len(txs), 'contiguous event boundaries')
        require(type(event['work_limit']) is int and event['work_limit'] > 0, 'work quantum')
        require(type(event['commit_ready']) is bool and type(event['cancel']) is bool, 'lifecycle controls')
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
                    (Selector('ft.cue.payload','definition',('facets','0','content','0','object')),),task))
                request = OperationRequest(job,actor,kind,old.context,delivery=delivery)
            else:
                request = OperationRequest(job,actor,kind,old.context,binding=task,
                    evidence=evidence+(DetailAddress(delivery,'ft.cue.payload'),))
            expected_commands.append(('start',cid+':start',request))
        bw = wallet(before); aw = wallet(after); delta = op['completed'] - previous.get('completed',0)
        require(event['wallet_before'] == bw and event['wallet_after'] == aw and
            event['debit'] == {u:bw[u]-aw[u] for u in ('energy','time')} == dict(energy=delta,time=delta)
            and 0 <= delta <= event['work_limit'], 'actual paid debit')
        if event['cancel']:
            require(bool(previous) and i > 0 and op['status'] == 'cancelled' and delta == 0, 'cancel active partial work without refund')
            expected_commands.append(('cancel',cid+':cancel',actor,job)); cancelled = True
        elif previous.get('status') != 'ready' and min(bw['energy'],bw['time']) > 0:
            expected_commands.append(('advance',cid+':work',actor,job,event['work_limit']))
        require(op['primitive'] == kind and op['actor'] == actor and op['context'] == old.context
            and op['required'] == (2 if kind == 'read' else 3) and op['spent'] == op['completed']
            and op['started_tick'] >= len(prior) and event['status'] == op['status'], 'native operation identity and extent')
        require(op['status'] in ('partial','waiting','ready','succeeded','cancelled'), 'registered lifecycle')
        if op['status'] == 'ready': require(not event['commit_ready'] and not event['cancel'] and op['completed'] == op['required'], 'ready uncommitted')
        if op['status'] == 'succeeded':
            require(event['commit_ready'] and not event['cancel'], 'explicit settlement')
            expected_commands.append(('commit',cid+':commit',actor,job))
            require(op['completed'] == op['required'], 'complete paid extent')
            if kind == 'read': read_done = True
            else: bound = True
        total += delta; end = event['after']
    require(d['cancelled'] == cancelled, 'exact cancellation state')
    require(end == len(txs), 'no unaccounted journal suffix')
    require(tuple(x[0] for x in commands[len(old_commands):]) == tuple(expected_commands), 'exact intake-only commands')
    # Replay validates every access result and native command, not just declared labels.
    replay = type(engine).restore(engine.checkpoint())
    require(replay.access.checkpoint() == engine.access.checkpoint(), 'independent access replay')
    require(dict(engine.wallet(actor)) == wallet(heads(len(txs))), 'wallet readback')
    if d['events']:
        require(engine.world.resolve(task) == expected, 'exact declared task, no later rewrite')
    if read_done:
        detail = engine.participant_view(actor).detail(DetailAddress(delivery,'ft.cue.payload'))
        require(detail is not None and (detail.source,detail.path,detail.value) ==
            (task,('facets','0','content','0','object'),encode(payload)), 'exact fresh paid disclosure')
    current = engine.participant_view(actor)._bindings.get(task)
    if bound:
        require(current is not None and current.content == expected.facet(Account).content and
            current.cue == cue and current.context == old.context and current.target == old.target and
            current.particulars == evidence+(DetailAddress(delivery,'ft.cue.payload'),), 'owned task content/evidence')
        paid = engine.participant_view(actor).receipt(current.receipt)
        require(paid is not None and paid.complete and paid.spent == paid.required == 3 and paid.operation == 'bind', 'new paid bind receipt')
        receipt = dict(task=task,read_operation=engine._jobs[actor,read],bind_operation=engine._jobs[actor,bind],
            owned_receipt=current.receipt,energy=5,time=5)
        require(total == 5 and d['receipt'] == receipt, 'unique intake receipt')
    else:
        require(current is None and d['receipt'] is None, 'no partial owned task or receipt')
    return dict(passed=True,mask=d['mask'],cue=codec.dumps(cue),bound=bound,cancelled=cancelled,native_cost=dict(energy=total,time=total),
        source_prefix_exact=True,controller_prefix_exact=True,reserve_history_unchanged=True,
        comparison_paid=False,execution_authorized=False,td5_admitted=False,history_choice=False)
