"""One guarded A8 quotation and independent saved audit; never native paid work."""
import argparse, copy, gc, gzip, hashlib, json, pathlib, unittest
from datetime import datetime, timezone
from hle_unified import codec
from hle_unified.selection_records import dumps, loads, fields_of
from full_theory.canonical_quotation import Quotation
from full_theory.canonical_quotation_audit import QuotationAudit
from full_theory.changed_input_domain import request_at, ordinal_of


def run():
    p=argparse.ArgumentParser();p.add_argument('a5');p.add_argument('a6');p.add_argument('output')
    p.add_argument('--public',required=True);p.add_argument('--owner',required=True);p.add_argument('--stop-at',required=True);a=p.parse_args()
    root=pathlib.Path(__file__).resolve().parents[1];out=pathlib.Path(a.output);out.mkdir(exist_ok=False)
    protocol=json.loads((root/'contracts/ft/FT7_Canonical_Quotation_A8_Protocol_v1.json').read_text())
    freeze=json.loads((root/'contracts/ft/FT7_Canonical_Quotation_A8_Source_Freeze_v1.json').read_text())
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
        quote=Quotation(native,domain);d=loads(domain)
        for name in ('start','advance','commit','cancel','restore','_execute'):
            if hasattr(quote,name):raise ValueError('read-only facade unexpectedly exposes '+name)
        indices={0,d['assignments']-1}
        for j,radix in enumerate(d['radices']):
            for digit in range(radix):
                digits=[0]*len(d['radices']);digits[j]=digit;indices.add(ordinal_of(digits,d['radices']))
        for i in sorted(indices):
            if fields_of(quote.request(i))!=fields_of(request_at(domain,i)):raise ValueError('A6 exact request mapping')
        note('request_mapping',samples=len(indices))
        rows=[]
        with (out/'rows.jsonl').open('w') as f:
            for i in range(d['assignments']):
                if i%128==0:guard();note('quote_progress',completed=i)
                row=quote.row(i);rows.append(row);f.write(dumps(row)+'\n');f.flush()
        text=quote.report(rows)
        (out/'complete.json.gz').write_bytes(gzip.compress(text.encode(),mtime=0))
        note('quote_closed',assignments=len(rows),required=sum(r['required'] for r in rows))
        state_ok=quote.unchanged()
        if not state_ok:raise ValueError('quotation modified native data')
        native_view_calls=len(rows)
        del quote;gc.collect()
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
            request_mapping_samples=len(indices),forgery_rejections=probes,source_identities=len(freeze),prior_identities=493,
            native_unchanged=state_ok,audit_native_unchanged=audit_ok,cost_histogram=hist,
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
        (out/'summary.json').write_text(json.dumps(report,indent=2)+'\n');note('closed_pass')
    except BaseException as e:note('closed_nonpass',error_type=type(e).__name__,message=str(e));raise


if __name__=='__main__':run()
