"""Independent paid comparison ledger audit; no comparison executor imports."""
from hashlib import sha256
from hle_unified.selection_records import loads, dumps, fields_of
from hle_unified.operation_records import OperationRequest
from hle_unified.material import attrs
from hle_unified.operations import address
from hle_unified.compact import unseal
from hle_unified.development_audit import audit as audit_native
from hle_unified.workflow_selection_audit import extent as previous_extent
from .owned_proposal_domain_audit import audit_owned_proposal_domain


def audit_owned_paid_comparison(engine, source_engine, source, binding, domain):
    def require(ok, why):
        if not ok:raise ValueError('paid comparison audit: '+why)
    audit_owned_proposal_domain(source_engine,source,binding,domain)
    d=loads(domain);r=d['request'];actor=d['actor'];required=d['comparison_required']
    require(r is not None and required>0,'pending owned request')
    key='ft-owned-comparison:'+sha256(source.encode()).hexdigest()[:24]
    old=tuple(source_engine.world.journal());txs=tuple(engine.world.journal())
    require(txs[:len(old)]==old,'exact original journal prefix')
    access=unseal(engine.access.checkpoint(),engine.access.SCHEMA)
    source_access=unseal(source_engine.access.checkpoint(),source_engine.access.SCHEMA)
    require(set(access)==set(source_access)=={'world','nodes','events'} and
        access['nodes']==source_access['nodes'] and access['events']==source_access['events'],
        'participant access nodes and events unchanged')
    require(access['world']==engine.world.checkpoint() and source_access['world']==source_engine.world.checkpoint(),
        'access paired with exact respective native world')
    def extent(op):
        if not op.get('ftpc'):return previous_extent(op)
        require(op['required']==required and op['route_prepare']==required and
            op['route_execute']==0 and op['primitive']=='bind','exact paid extent')
    audit_native(txs,extent_check=extent,extended_flags=('c1','c2','c3','c4','c6','c7w','c7ws','ftpc'))
    heads={v.ref.identity:v for tx in old for v in tx.versions}
    wallets=[v for v in heads.values() if attrs(v).get('record_type')=='wallet' and attrs(v).get('actor')==actor]
    require(len(wallets)==1,'one original wallet');wallet=wallets[0];initial_wallet=attrs(wallet)
    opid=address('u4.operation',actor,key).identity
    snapref=address('ftpc.snapshot',actor,key);rowsref=address('ftpc.candidates',actor,key)
    resultref=address('ftpc.result',actor,key)
    require(all(i not in heads for i in (opid,snapref.identity,rowsref.identity,resultref.identity)),'fresh identities')
    base=fields_of(OperationRequest(key,actor,'bind',r['context']))
    base.pop('participants');base.pop('evidence')
    base.update(record_type='operation',ftpc=True,primitive='bind',policy='ft-owned-paid-comparison-v1',
        setting=d['setting'],required=required,route_prepare=required,route_execute=0,
        snapshot=snapref,candidates=rowsref,scanned=d['snapshot'].get('scanned',len(d['snapshot']['items'])),
        foreign_count=d['snapshot'].get('foreign_total',0),candidate_count=len(d['candidates']),
        evaluated=sum(x['examined'] for x in d['candidates']),
        **{'participant.0':actor,'lock.0':actor,'input.0':r['demand'],'dependency.0':source_engine.law})
    previous=None;receipts=0;result=None
    for index,tx in enumerate(txs[len(old):],len(old)):
        versions={v.ref.identity:v for v in tx.versions}
        require(len(versions)==len(tx.versions) and opid in versions,'one registered comparison per suffix transaction')
        job=versions[opid];op=attrs(job)
        dynamic={'completed','spent','status','failure','result','started_tick'}
        if op['status'] in ('succeeded','failed','cancelled'):dynamic.add('finished_tick')
        require(set(op)==set(base)|dynamic and all(op[k]==v for k,v in base.items()),'exact operation fields')
        require(op['started_tick']==len(old),'fresh start tick')
        pd={} if previous is None else attrs(previous)
        delta=op['completed']-pd.get('completed',0)
        allowed={opid}
        if previous is None:
            require(index==len(old) and op['status']=='pending' and op['completed']==op['spent']==0 and
                op['failure'] is None and op['result'] is None,'unpaid initial state')
            allowed|={snapref.identity,rowsref.identity}
            require(attrs(versions[snapref.identity])=={'payload':dumps(d['snapshot'])} and
                loads(attrs(versions[rowsref.identity])['payload'])==d['candidates'] and
                set(attrs(versions[rowsref.identity]))=={'payload'},'exact scoped snapshot and full ballot')
        elif op['status'] in ('partial','waiting','ready'):
            require(pd['status'] in ('pending','partial','waiting') and op['failure'] is None and op['result'] is None,
                'valid paid work transition')
            if delta:allowed.add(wallet.ref.identity)
        else:
            require(delta==0 and op['finished_tick']==index and op['status'] in ('succeeded','cancelled'),
                'registered terminal transition')
            event=versions.get(op['result'].identity)
            require(event is not None and attrs(event)==dict(actor=actor,primitive='bind',context=r['context'],
                outcome=op['status'],operation=previous.ref,event=event.ref,**{'participant.0':actor}),
                'exact terminal event')
            allowed.add(event.ref.identity)
            if op['status']=='succeeded':
                require(pd['status']=='ready' and op['completed']==op['spent']==required,'fully paid settlement')
                receipt_rows=[v for v in tx.versions if v.ref.identity.namespace=='u4.receipt']
                require(len(receipt_rows)==1,'one completion receipt');receipt=receipt_rows[0];receipts+=1
                require(attrs(receipt)==dict(actor=actor,operation='bind',work_key=key,required=required,
                    completed=required,spent=required,**{'input.0':r['demand']}),'exact receipt fields')
                result=versions.get(resultref.identity);require(result is not None,'settled comparison result')
                rd=attrs(result)
                require(set(rd)=={'operation','receipt','policy','payload'} and rd['operation']==job.ref and
                    rd['receipt']==receipt.ref and rd['policy']==base['policy'],'result native pairing')
                require(loads(rd['payload'])==dict(candidates=d['candidates'],native_nominee=d['native_nominee'],
                    comparison_paid=True,comparison_required=required,execution_authorized=False),'result is comparison only')
                allowed|={receipt.ref.identity,result.ref.identity}
            else:require(pd['status'] in ('pending','partial','waiting','ready'),'cancel active only')
        require(set(versions)==allowed,'no hidden operation, movement, content or history writes')
        require(job.ref.revision==(1 if previous is None else previous.ref.revision+1),'exact job revisions')
        for v in tx.versions:heads[v.ref.identity]=v
        previous=job
    final={} if previous is None else attrs(previous);spent=final.get('spent',0)
    after=attrs(heads[wallet.ref.identity]);expected_wallet=dict(initial_wallet)
    expected_wallet.update(energy=initial_wallet['energy']-spent,time=initial_wallet['time']-spent)
    require(after==expected_wallet,'exact native debit without refund or default change')
    require(receipts==int(final.get('status')=='succeeded') and (result is not None)==bool(receipts),'no early result or duplicate credit')
    return dict(passed=True,status=final.get('status','before'),required=required,spent=spent,
        native_cost=dict(energy=spent,time=spent),receipts=receipts,new_transactions=len(txs)-len(old),
        source_prefix_exact=True,access_unchanged=True,reserve_history_unchanged=True,execution_authorized=False)
