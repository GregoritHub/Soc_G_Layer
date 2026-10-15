"""Reconstruct owned needs from raw access commands and native journal receipts.

No admission/controller, selector, scheduler or executor imports. Scope is
admission: pressure inputs are recorded observations, not autonomy evidence.
"""
from copy import deepcopy
from hle import model_a
from hle_unified import codec
from hle_unified.compact import ValuePool, unseal
from hle_unified.particulars import record_registry
from hle_unified.records import Account
from hle_unified.selection_records import dumps


def attributes(v):
    return {a.name:a.value for a in v.attributes}


def need_payload(text, relation):
    pairs = codec.loads(text)
    if type(pairs) is not tuple or any(type(p) is not tuple or len(p)!=2 for p in pairs):
        raise ValueError('invalid need encoding')
    d = dict(pairs)
    if len(d) != len(pairs):
        raise ValueError('duplicate need field')
    if relation == 'c6.need':
        if set(d) != {'kind','weights','commit','scope','amount','collective'} or d['kind'] != 'need':
            raise ValueError('invalid canonical need')
        priorities = d['weights']
        if (type(d['commit']) is not bool or type(d['collective']) is not bool
                or d['scope'] not in ('quantity','condition') or type(d['amount']) is not int
                or not 1 <= d['amount'] <= 1000):
            raise ValueError('invalid canonical requirement')
    else:
        if set(d) != {'kind','priorities','externalize'} or d['kind'] != 'workflow_need' or type(d['externalize']) is not bool:
            raise ValueError('invalid workflow need')
        priorities = d['priorities']
        if type(priorities) is not tuple:
            raise ValueError('invalid workflow priorities')
    if len(priorities)!=4 or not any(priorities) or any(type(p) is not int or not 0<=p<=10 for p in priorities):
        raise ValueError('invalid priorities')
    return d


def audit_demands(transactions, access_text, events):
    txs = tuple(transactions)
    raw = unseal(access_text, 'hle-unified-u4-access-v1')
    pool = ValuePool(record_registry()); pool.load_nodes(raw['nodes'])
    commands = [pool.get(pool.import_token(t)) for t in raw['events']]
    ledger, ages = {}, {}
    previous_counts = (0,0)
    for turn, event in enumerate(events):
        count, access_count = event['journal_count'], event['access_count']
        if (event['turn'] != turn or not previous_counts[0] <= count <= len(txs)
                or not previous_counts[1] <= access_count <= len(commands)):
            raise ValueError('invalid observation chronology')
        previous_counts = count, access_count
        versions = {v.ref:v for tx in txs[:count] for v in tx.versions}
        actor = event['actor']; heads = {}; used = set()
        for command, result in commands[:access_count]:
            if command[0] != 'bind':
                continue
            _, owner, ref, addresses, receipt_ref = command
            if receipt_ref in used:
                raise ValueError('duplicate bind receipt')
            used.add(receipt_ref)
            if ref not in versions or receipt_ref not in versions:
                raise ValueError('binding outside observation boundary')
            value = versions[ref]; account=value.facet(Account); bd=attributes(value)
            rd = attributes(versions[receipt_ref]); binding, receipt = result
            if (account is None or account.holder != owner or rd.get('actor') != owner
                    or rd.get('operation') != 'bind' or rd['completed'] != rd['required']
                    or rd['spent'] != rd['required'] or rd['required'] < 1
                    or rd['work_key'] != ref.identity.key or rd.get('input.0') != ref
                    or binding.ref != ref or binding.actor != owner or binding.receipt != receipt_ref
                    or binding.content != account.content or binding.target != account.referent
                    or binding.context != bd['context'] or binding.cue != bd['cue']
                    or binding.endorsement.value != bd['endorsement'] or binding.particulars != addresses
                    or receipt.ref != receipt_ref):
                raise ValueError('binding lacks exact paid ownership and scope')
            if owner == actor:
                old = heads.get(ref.identity)
                if old is None or ref.revision > old.ref.revision:
                    heads[ref.identity] = binding
        expected = {}
        for b in heads.values():
            if b.endorsement.value in ('retracted','disputed') or len(b.content)!=1:
                continue
            p=b.content[0]
            if p.relation not in ('c6.need','c7ws.need') or (p.subject,p.context)!=(b.target,b.context):
                continue
            try:
                payload=need_payload(p.object,p.relation)
            except (ValueError,TypeError,KeyError):
                continue
            key=dumps((actor,b.ref))
            expected[key]=dict(actor=actor,binding=b.ref,receipt=b.receipt,context=b.context,
                cue=b.cue,target=b.target,relation=p.relation,payload=payload,raw_payload=p.object)
        if expected != event['eligible']:
            raise ValueError('omitted, foreign, stale or fabricated owned need')
        for key in expected:
            ages.setdefault(key,turn)
        suspended=[]
        for key,value in ledger.items():
            if value['actor']==actor and key not in expected and value['status']!='suspended':
                value.update(status='suspended',reason='owned_need_missing_withdrawn_or_superseded')
                suspended.append(key)
        waiting=sorted(set(expected)-set(ledger),key=lambda k:(ages[k],k))
        limit=event['limit']
        if type(limit) is not int or not 1<=limit<=128:
            raise ValueError('invalid intake bound')
        chosen, omitted=waiting[:limit],waiting[limit:]
        for key in chosen:
            ledger[key]=dict(expected[key],first_seen=ages[key],admitted_at=turn,status='pending',reason=None)
        if (event['admitted']!=chosen or event['omitted']!=omitted
                or event['cursor']!=(omitted[0] if omitted else None)
                or event['suspended']!=sorted(suspended) or event['demands']!=ledger
                or event['first_seen']!=ages):
            raise ValueError('forged age, ordering, omission or demand state')
        pressure=event['pressure']
        seats=tuple(model_a.position_of(pressure['tim'],a) for a in pressure['pending_aspects'])
        if (seats!=pressure['pending_seats'] or len(seats)!=pressure['pending_count']
                or pressure['active']!=(bool(set(seats)&{3,4}) and not pressure['creative_charge'])):
            raise ValueError('false historical pressure predicate')
    return dict(passed=True,scans=len(events),demands=len(ledger),
                pending=sum(v['status']=='pending' for v in ledger.values()),
                suspended=sum(v['status']=='suspended' for v in ledger.values()))
