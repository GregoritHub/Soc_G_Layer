"""Saved-only A8 audit continuation. Original closed5832 quotes are never replayed."""
import argparse, copy, gc, gzip, hashlib, json, pathlib, unittest
from datetime import datetime, timezone
from hle_unified import codec
from hle_unified.selection_records import dumps, loads, fields_of
from full_theory.canonical_quotation import Quotation
from full_theory.canonical_quotation_audit import QuotationAudit
from full_theory.changed_input_domain import request_at, ordinal_of


def run():
    p=argparse.ArgumentParser();p.add_argument('a5');p.add_argument('a6');p.add_argument('prior');p.add_argument('output')
    p.add_argument('--public',required=True);p.add_argument('--owner',required=True);p.add_argument('--stop-at',required=True);a=p.parse_args()
    root=pathlib.Path(__file__).resolve().parents[1];out=pathlib.Path(a.output);out.mkdir(exist_ok=False)
    protocol=json.loads((root/'contracts/ft/FT7_Canonical_Quotation_A8_Protocol_v1.json').read_text())
    freeze=json.loads((root/'contracts/ft/FT7_Canonical_Quotation_A8_Saved_Audit_Source_Freeze_v1.json').read_text())
    sha=lambda b:hashlib.sha256(b.encode() if isinstance(b,str) else b).hexdigest()
    def note(kind,**kw):
        with (out/'events.jsonl').open('a') as f:f.write(json.dumps(dict(at=datetime.now(timezone.utc).isoformat(),kind=kind,**kw))+'\n');f.flush()
        print(kind,kw,flush=True)
    def guard():
        s=json.loads((pathlib.Path(a.public)/'docs/FT_Run_State.json').read_text());now=datetime.now(timezone.utc)
        if s['run_id']!=a.owner or not s['active_worker'] or s['status']!='running' or now>=datetime.fromisoformat(s['lease_expires_at']) or now>=datetime.fromisoformat(a.stop_at):raise SystemExit('ownership/lease/deadline')
    def verify():
        for n,h in freeze.items():
            if sha((root/n).read_bytes())!=h:raise ValueError('source changed: '+n)
        original_freeze=json.loads((root/'contracts/ft/FT7_Canonical_Quotation_A8_Source_Freeze_v1.json').read_text())
        if len(original_freeze)!=499 or any(freeze.get(n)!=h for n,h in original_freeze.items()):raise ValueError('all original499 unchanged')
        old=json.loads((root/protocol['prior_freeze']).read_text())
        if len(old)!=493 or any(freeze.get(n)!=h for n,h in old.items()):raise ValueError('prior493 identities')
    probes=[]
    def reject(name,call):
        try:call()
        except ValueError:probes.append(name)
        else:raise ValueError('forgery accepted: '+name)
    try:
        guard();verify();note('start',owner=a.owner)
        raw=(pathlib.Path(a.a5)/'canonical-complete.json.gz').read_bytes()
        _,native,_=codec.loads(gzip.decompress(raw).decode())
        domain=gzip.decompress((pathlib.Path(a.a6)/'canonical-complete.json.gz').read_bytes()).decode()
        prior=pathlib.Path(a.prior);d=loads(domain)
        binding=json.loads((root/'contracts/ft/FT7_Canonical_Quotation_A8_Closed_Input_Binding_v1.json').read_text())
        actual={p.name:sha(p.read_bytes()) for p in prior.iterdir() if p.is_file()}
        if actual!=binding['files'] or binding['original_exit']['exit_code']!=1:raise ValueError('exact original closed output')
        events=[json.loads(x) for x in (prior/'events.jsonl').read_text().splitlines()]
        if (events[-1]['kind'],events[-1]['error_type'],events[-1]['message'])!=('closed_nonpass','SystemExit','ownership/lease/deadline'):
            raise ValueError('registered original deadline closure required')
        if any(e['kind'] in ('audit_closed','methods_start','closed_pass') for e in events):raise ValueError('closed passing stage must not replay')
        closed=[e for e in events if e['kind']=='quote_closed']
        if len(closed)!=1 or closed[0]['assignments']!=5832 or closed[0]['required']!=432864:raise ValueError('exact original closed quote')
        # Original frozen control flow checks world/access/profile/cursor unchanged before audit_progress.
        if not any(e['kind']=='audit_progress' for e in events):raise ValueError('original immutability check not evidenced')
        state_ok=True
        mapping=[e for e in events if e['kind']=='request_mapping']
        if len(mapping)!=1 or mapping[0]['samples']!=29:raise ValueError('original exact mapping check')
        mapping_samples=mapping[0]['samples']
        rows=[loads(s) for s in (prior/'rows.jsonl').read_text().splitlines()]
        text=gzip.decompress((prior/'complete.json.gz').read_bytes()).decode()
        if len(rows)!=5832 or [r['ordinal'] for r in rows]!=list(range(5832)) or loads(text)['rows']!=rows:
            raise ValueError('original complete ordered quote and report')
        for name in ('complete.json.gz','rows.jsonl'):(out/name).write_bytes((prior/name).read_bytes())
        native_view_calls=len(rows) # Preserved original calls; no valid Quotation or row call occurs here.
        note('original_quote_preserved',rows=5832,new_native_view_calls=0,original_exit_code=1)
        guard();auditor=QuotationAudit(native,domain)
        reference=auditor.reconstruct(guard,lambda n:note('audit_progress',completed=n))
        if rows!=reference:raise ValueError('full independent row reconstruction differs')
        records=[]
        for label in ('complete','restored'):
            if label=='restored':
                restored=dumps(loads(text))
                if restored!=text:raise ValueError('typed report roundtrip')
                (out/'restored.json.gz').write_bytes(gzip.compress(restored.encode(),mtime=0))
            saved=gzip.decompress((out/(label+'.json.gz')).read_bytes()).decode()
            result=auditor.audit(saved)
            records.append(dict(record=label,file=label+'.json.gz',sha256=sha((out/(label+'.json.gz')).read_bytes()),
                payload_sha256=sha(saved),**result))
        note('audit_closed',rows=len(reference))
        z=loads(text)
        for name,value in (('required_energy',z['required_energy']+1),('required_time',z['required_time']-1),
                ('energy',z['energy']+1),('wallet',None),('assignments',5831),('status','affordable'),
                ('may_launch',True),('comparison_paid',True),('td5_admitted',True),('extra',True)):
            bad=dict(z);bad[name]=value;reject(name,lambda bad=bad:auditor.audit(dumps(bad)))
        for field,value in (('required',rows[0]['required']+1),('snapshot_sha256','forged'),('candidates_sha256','forged'),
                ('request_sha256','forged'),('examined',()),('nominee',999)):
            bad=copy.deepcopy(z);bad['rows'][0][field]=value
            reject('row_'+field,lambda bad=bad:auditor.audit(dumps(bad)))
        bad=dict(z);bad['rows']=list(reversed(rows));reject('permuted',lambda:auditor.audit(dumps(bad)))
        for name,bn,bd in (('native_pair','forged',domain),('domain_pair',native,'forged')):
            reject(name+'_builder',lambda bn=bn,bd=bd:Quotation(bn,bd))
            reject(name+'_auditor',lambda bn=bn,bd=bd:QuotationAudit(bn,bd))
        audit_ok=auditor.unchanged()
        if not audit_ok:raise ValueError('independent audit modified saved native state')
        guard();verify()
        hist={}
        for row in rows:hist[str(row['required'])]=hist.get(str(row['required']),0)+1
        report=dict(passed=True,records=records,independent_rows=len(reference),native_view_calls=native_view_calls,
            request_mapping_samples=mapping_samples,forgery_rejections=probes,source_identities=len(freeze),prior_identities=493,
            native_unchanged=state_ok,audit_native_unchanged=audit_ok,cost_histogram=hist,
            original_source_identities=499,new_native_view_calls=0,original_quote_invocations_preserved=1,
            native_work_calls=0,engine_restore_calls=0,accepted_stage_replays=0,parent_accepted=False)
        import tests_ft7.test_canonical_quotation as tests
        tests.REPORT=report;tests.ROWS=rows;tests.RAW=z
        suite=unittest.defaultTestLoader.loadTestsFromModule(tests)
        actual=[t._testMethodName for group in suite for t in group]
        if sorted(actual)!=sorted(protocol['methods']):raise ValueError('exact method identities')
        note('methods_start')
        with (out/'tests.log').open('w') as f:result=unittest.TextTestRunner(stream=f,verbosity=2).run(suite)
        if result.testsRun!=6 or not result.wasSuccessful():raise ValueError('six exact methods required')
        report['methods']=actual;verify()
        if {p.name:sha(p.read_bytes()) for p in prior.iterdir() if p.is_file()}!=binding['files']:raise ValueError('original closed files changed')
        (out/'summary.json').write_text(json.dumps(report,indent=2)+'\n');note('closed_pass')
    except BaseException as e:note('closed_nonpass',error_type=type(e).__name__,message=str(e));raise


if __name__=='__main__':run()
