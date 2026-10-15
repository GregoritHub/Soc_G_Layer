"""Independent saved-record closure/certificate audit; no controller imports."""
import json
from hashlib import sha256
from hle import model_a
from hle_unified.selection_records import dumps, loads
from hle_unified.compact import unseal
from hle_unified.material import OperationStore, attrs
from hle_unified.records import Account
from hle_unified.development_values import attrs as devattrs
from hle_unified.development_audit import audit as audit_development
from hle_unified.workflow_selection_audit import extent as inherited_extent
from .content_audit import audit_content
from .retention_audit import audit_retention
from .fulfillment_audit import _snapshot
from .social_training_audit import _known


def audit_social_closure(engine, checkpoint):
    d = loads(checkpoint)
    expected = {'version','native_sha256','actor','setting','training_checkpoint','training_native',
        'prefix_count','start_count','demand','plan','phase','index','events','work','ledger','certificate_key','terminal'}
    def require(good, message):
        if not good:
            raise ValueError('social closure audit: ' + message)
    require(set(d) == expected and d['version'] == 'ft-owned-social-closure-v1', 'checkpoint schema')
    require(d['native_sha256'] == sha256(engine.checkpoint().encode()).hexdigest(), 'native pairing')
    txs = tuple(engine.world.journal())
    raw = json.loads(d['training_native'])
    prefix = tuple(OperationStore.restore(unseal(d['training_native'], raw['schema'])['world']).journal())
    training = loads(d['training_checkpoint'])
    require(len(prefix) == d['prefix_count'] and txs[:len(prefix)] == prefix, 'immutable training prefix')
    require(training['native_sha256'] == sha256(d['training_native'].encode()).hexdigest()
        and training['phase'] in ('complete','unqualified')
        and (training['actor'], training['setting']) == (d['actor'], d['setting']), 'finished owned training pairing')
    ep = training['plan']['episodes'][0]
    require(d['demand'] == dict(training['scope'], target=ep['target']), 'demand scope inflation')
    versions = {v.ref:v for tx in txs for v in tx.versions}
    def paid(ref):
        r = attrs(versions[ref])
        require(r.get('actor') == d['actor'] and r.get('status') == 'succeeded'
            and r.get('required',0) > 0 and r.get('spent',0) >= r['required']
            and r.get('completed') == r['required'], 'unpaid or foreign operation')
        return r
    def perspective(tim, seats):
        families = frozenset(model_a.element_at(tim,p)[0] for p in seats)
        return {frozenset('nf'):'I',frozenset('st'):'IT',frozenset('sf'):'WE',frozenset('nt'):'ITS'}[families]
    def scope(row):
        return row.get('content_target',row.get('target'))
    if d['events']:
        require(type(d['start_count']) is int and d['prefix_count'] <= d['start_count'] <= len(txs), 'start boundary')
        for tx in txs[d['prefix_count']:d['start_count']]:
            for v in tx.versions:
                require(not attrs(v).get('u8'), 'supplied post-training capacity')
        snapshot = _snapshot(d['events'][0]['view'])
        bindings = {b.ref:b for b in snapshot.bindings}
        uses = [x for x in training['events'] if x['phase_before'] == 'content'
                and x['request']['fields']['target'] == ep['target'] and x['work']['status'] == 'succeeded']
        plan = None
        if uses:
            source = paid(ep['source_operation']); final = paid(uses[0]['work']['operation'])
            kept = (ep['source'],final.get('binding') or final.get('result'))
            owned = all(ref in bindings and bindings[ref].endorsement.value not in ('retracted','disputed') for ref in kept)
            linked = (source.get('origin'),source.get('destination'),final.get('origin'),final.get('destination')) == (
                perspective(source['tim'],(5,6)),ep['destination'],ep['destination'],perspective(source['tim'],(1,2)))
            scoped = all((r.get('context'),scope(r)) == (d['demand']['context'],ep['target']) for r in (source,final))
            for ref in kept:
                account = versions[ref].facet(Account)
                require(account is not None and account.holder == d['actor'] and account.referent == ep['target'], 'return output owner/scope')
            if owned and linked and scoped and final.get('source.0') == ep['source']:
                plan = dict(source=ep['source'],destination=ep['destination'],kept=kept,
                    returns=(source['key'],final['key']),return_refs=(ep['source_operation'],uses[0]['work']['operation']))
        require(d['plan'] == plan, 'owned return discovery')
    else:
        require(d['start_count'] is None and d['plan'] is None, 'initial discovery')
        plan = None
    audit_development(txs, extent_check=inherited_extent, extended_flags=('c1','c2','c3','c4','c6','c7w','c7ws'))
    audit_content(txs,[w for w in d['work'] if attrs(versions[w['operation']]).get('c3') or attrs(versions[w['operation']]).get('c7w')])
    phase = 'discover'; index = 0; offset = d['start_count']; works = []; exposures = []; certificates = []
    for i, event in enumerate(d['events']):
        require(event['index'] == i and event['before'] == offset and event['phase_before'] == phase
            and offset <= event['after'] <= len(txs), 'phase or event order')
        s = _snapshot(event['view']); require(s.actor == d['actor'], 'foreign view')
        past = {v.ref:v for tx in txs[:offset] for v in tx.versions}
        require(all(p.source in past for p in s.particulars), 'future owned evidence')
        key = 'ft-social-closure:' + sha256(dumps((d['actor'],d['prefix_count'])).encode()).hexdigest()[:16] + ':' + str(index) + ':'
        work = event['work']; request = event['request']
        if phase == 'discover':
            require(work is None and request is None and offset == event['after'], 'discovery fabricated work')
            phase = 'use' if plan else 'deferred'
        elif phase in ('use','shell'):
            require(work is not None and request is not None, 'missing paid operation')
            q = request['fields']; r = attrs(versions[work['operation']]); works.append(work)
            require((q['key'],q['actor'],q['context'],q['cue'],q['target']) == (
                key+phase,d['actor'],d['demand']['context'],d['demand']['cue'],ep['target']), 'native request scope')
            require((r['key'],r['actor'],r['context']) == (q['key'],q['actor'],q['context'])
                and work['actor'] == d['actor'] and work['key'] == q['key'] and work['status'] == r['status'], 'native work identity')
            if phase == 'use':
                recipe = ('use-' if d['setting'] == 'canonical' else 'workflow-use-') + ('personal' if ep['destination'] == 'I' else 'system') + '-v1'
                require(q['recipe'] == r['recipe_key'] == recipe and q['inputs'] == work['consumed'] == (ep['source'],)
                    and r['source.0'] == ep['source'] and scope(r) == ep['target'], 'paid use operand')
            else:
                known,sources = _known(s,past,ep['target'],q['context'])
                evidence = tuple((p.address.delivery,p.address.key) for source in sources for p in s.particulars if p.source == source)
                require(request['type'] == 'EncounterRequest' and q['evidence'] == evidence
                    and q['carrier'] == (known.get('partner') or ep['target']) and q['demand'] is True
                    and q['route'] == 'engage' and r['purpose'] == 'encounter', 'full current Shell evidence')
            if work['status'] == 'succeeded':
                paid(work['operation']); phase = 'shell' if phase == 'use' else 'expose'
            elif work['status'] in ('failed','cancelled'):
                phase = 'failed'
        elif phase == 'expose':
            row = event['exposure']; require(work is None and request is None and offset == event['after'], 'exposure fabricated work')
            require(row is not None and row['actor'] == d['actor'] and row['demand'] == d['demand']
                and row['kept'] == plan['kept'] and row['returns'] == plan['return_refs']
                and row['interrupted'] == event['interrupted'] and row['at_tick'] == offset, 'exposure linkage')
            use = paid(row['consumer']); shell = paid(row['shell']['operation'])
            require(use['key'] == key+'use' and shell['key'] == key+'shell'
                and use['finished_tick'] <= shell['started_tick'], 'distinct ordered paid exposures')
            exposures.append(row); index += 1
            phase = 'use' if index < 2 else 'certify' if row['closed'] else 'open'
        elif phase == 'certify':
            require(work is None and request is None and offset == event['after'], 'certificate fabricated work')
            cert = event['certificate']
            if training['capacity'] is None:
                require(cert is None and d['certificate_key'] is None, 'supported/unqualified certification')
                phase = 'closed'
            else:
                cap = devattrs(versions[training['capacity']])
                key_expected = 'ft-social-certificate:' + sha256(dumps((d['actor'],d['demand'],d['prefix_count'])).encode()).hexdigest()[:20]
                require(cert is not None and cert['key'] == d['certificate_key'] == key_expected
                    and cert['actor'] == d['actor'] and cert['native_capacity'] == training['capacity']
                    and cert['scope'] == dict(d['demand'],load=cap['max_load'])
                    and cert['closure'] == exposures[-1] and cert['required_support'] == (), 'certificate scope/evidence')
                expected_uses = tuple(x['work']['operation'] for x in training['events']
                    if x['phase_before'] == 'content' and x['work']['status'] == 'succeeded')
                require(cert['content_uses'] == expected_uses, 'certificate training chronology')
                certificates.append(cert); phase = 'certified'
        else:
            require(False, 'events after terminal')
        require(event['phase'] == phase and event['episode_index'] == index, 'derived transition')
        if event['phase_before'] != 'expose':require(event['exposure'] is None, 'extra exposure')
        if event['phase_before'] != 'certify':require(event['certificate'] is None, 'extra certificate')
        offset = event['after']
    require(d['phase'] == phase and d['index'] == index and d['work'] == works, 'final state')
    if d['events']:require(offset == len(txs), 'unaccounted continuation')
    terminal = phase in ('certified','closed','open','deferred','failed')
    require(d['terminal'] == (d['events'][-1] if terminal else None), 'terminal')
    events = exposures + certificates
    require(d['ledger']['events'] == events, 'ledger events')
    result = audit_retention(txs,events)
    history = tuple(sorted(result['history'],key=dumps))
    require(d['ledger']['history'] == history, 'history inflation')
    windows = {}
    for row in exposures:
        dem = row['demand']; window_key = (row['actor'],dem['family'],dem['context'],dem['cue'])
        windows[window_key] = dict(signature=(row['kept'],dem),hold=row['hold'],last=row)
    require(d['ledger']['windows'] == tuple(sorted(windows.items(),key=dumps))
        and d['ledger']['exposures'] == tuple(sorted(((r['consumer'],r['shell']['operation']) for r in exposures),key=dumps))
        and d['ledger']['certificates'] == {c['key']:c for c in certificates} and d['ledger']['revoked'] == {}, 'ledger derived state')
    if not certificates:require(d['certificate_key'] is None, 'phantom certificate')
    return dict(passed=True,phase=phase,exposures=len(exposures),closed=bool(exposures and exposures[-1]['closed']),
        certificates=len(certificates),native_work=len(works),independent=True)
