"""Bounded continuation of the interrupted frozen paid-window gate.

Original paid records, runtime, auditor and actual test bodies stay exact.
"""
from pathlib import Path
import argparse, gc, gzip, hashlib, json, os, shutil, sys, unittest
ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT), str(ROOT/'baseline/HLE_Rebuild_R21B')]
from tools.evaluate_ft7_1b2b3b2b2b2b2b2b1b import (
    PREFIX, input_row, original_row, domain_row, paid_type, predecessors,
    freeze as original_freeze)
AMEND = PREFIX+'_Bounded_Continuation_v1'
FREEZE = PREFIX+'_Continuation_Source_Freeze_v1.json'
METHOD_PREFIX = 'tests_ft7.test_paid_window_comparison.PaidWindowComparisonTests.'

def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()

def read(path):
    return json.loads(path.read_text())

def write_new(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open('x') as stream:
        stream.write(json.dumps(data, indent=2, sort_keys=True)+'\n')

def freeze():
    prior = ROOT/'contracts/ft'/(PREFIX+'_Source_Freeze_v1.json')
    names = set(read(prior)) | {str(prior.relative_to(ROOT)),
        'contracts/ft/'+AMEND+'.json', 'contracts/ft/'+AMEND+'.sha256',
        'tools/continue_ft7_1b2b3b2b2b2b2b2b1b.py'}
    return {name: sha(ROOT/name) for name in sorted(names)}

def check(args):
    protocol = read(ROOT/'contracts/ft'/(PREFIX+'_Protocol_v1.json'))
    amendment = read(ROOT/'contracts/ft'/(AMEND+'.json'))
    if sha(args.archive) != protocol['input']['sha256']:
        raise ValueError('exact accepted input archive required')
    if sha(ROOT/'contracts/ft'/(AMEND+'.json')) != (
            ROOT/'contracts/ft'/(AMEND+'.sha256')).read_text().split()[0]:
        raise ValueError('amendment hash differs')
    old = read(ROOT/'contracts/ft'/(PREFIX+'_Source_Freeze_v1.json'))
    current = freeze()
    if original_freeze() != old or current != read(ROOT/'contracts/ft'/FREEZE):
        raise ValueError('complete unchanged original/continuation freeze required')
    for name, expected in amendment['preserve']['files'].items():
        if sha(args.prior/name) != expected:
            raise ValueError('interrupted evidence changed: '+name)
    if sha(args.prior.parent/amendment['preserve']['log_file']) != amendment['preserve']['log_sha256']:
        raise ValueError('interrupted log changed')
    if len(predecessors()) != 468:
        raise ValueError('exact predecessor method identities required')
    os.environ.update(FT7_WINDOW_INPUT=str(args.archive), FT7_WINDOW_OUTPUT=str(args.output))
    return protocol, amendment, current

def copied_prefix(args, amendment):
    if read(args.output/'bridge.json')['preserved'] != amendment['preserve']:
        raise ValueError('exact registered original evidence bridge required')
    for entry in amendment['preserve']['records']:
        if sha(args.output/entry['file']) != entry['sha256']:
            raise ValueError('original raw record changed')
    original_audits = read(args.prior/'decoded_audits.json')
    if len(original_audits) != 32 or not all(v['passed'] for v in original_audits.values()):
        raise ValueError('original 32 exact passing independent audits required')
    return original_audits

def initialize(args, amendment, before):
    args.output.mkdir(parents=True, exist_ok=False)
    (args.output/'records').mkdir()
    for entry in amendment['preserve']['records']:
        shutil.copy2(args.prior/entry['file'], args.output/entry['file'])
    for name in ('record_index.json', 'decoded_audits.json', 'cost_readback.json'):
        shutil.copy2(args.prior/name, args.output/name)
    write_new(args.output/'bridge.json', dict(preserved=amendment['preserve'],
        original_frozen_identities=388, continuation_freeze=before,
        original_records=32, original_actual_methods=0, accepted=False))
    copied_prefix(args, amendment)

def record_stage(args, mask, before):
    from hle_unified import codec
    from hle_unified.selection_records import loads
    from full_theory.paid_window_comparison import prepare_window_comparison, step_window_comparison
    from full_theory.paid_window_comparison_audit import audit_paid_windows, reconstruct
    from tests_ft7.test_social_live_outcome import engine_type
    if mask not in range(8,16):
        raise ValueError('only eight missing workflow records may be generated')
    report = args.output/'stages'/('record-'+str(mask)+'.json')
    if report.exists():
        raise ValueError('completed saved-record stage must not be rerun')
    setting = 'workflow'; key = setting+'/mask-'+str(mask)
    path = args.output/'records'/(setting+'-mask-'+str(mask)+'.json.gz')
    original = original_row(setting)
    old = engine_type(setting).restore(original[1])
    intake = input_row(setting, 'mask-'+str(mask))
    native = engine_type(setting).restore(intake[1])
    dr = domain_row(setting, mask)
    if dr[1] != intake[1]:
        raise ValueError('exact original intake/domain native bridge required')
    domain = dr[2]; actor = loads(domain)['actor']
    resumed_saved_readback = path.exists()
    if not resumed_saved_readback:
        e, request = prepare_window_comparison(native, domain,
            (original[1], original[2], original[3], intake[2]))
        required = sum(x['required'] for x in reconstruct(
            native, old, original[2], original[3], intake[2], domain))
        step_window_comparison(e, request, work_limit=required)
        row = (key, e.checkpoint(), domain)
        terminal = e.checkpoint()
        step_window_comparison(e, request); step_window_comparison(e, request)
        if e.checkpoint() != terminal:
            raise ValueError('terminal idempotence differs')
        with gzip.open(path, 'xt', encoding='ascii') as stream:
            stream.write(codec.dumps(row)+'\n')
        with gzip.open(path, 'rt') as stream:
            if codec.loads(stream.read()) != row:
                raise ValueError('new record typed roundtrip differs')
        del e, request, terminal, row; gc.collect()
    with gzip.open(path, 'rt') as stream:
        decoded = codec.loads(stream.read())
    if decoded[0] != key or decoded[2] != domain:
        raise ValueError('saved continuation record domain differs')
    if codec.loads(codec.dumps(decoded)) != decoded:
        raise ValueError('exact typed saved roundtrip differs')
    e = paid_type(setting).restore(decoded[1])
    audit = audit_paid_windows(e, native, old, original[2], original[3], intake[2], domain)
    if not audit['passed'] or audit['status'] != 'succeeded':
        raise ValueError('full exact settled native independent audit required')
    request = next(command[2] for command, _ in (e._pool.get(t) for t in e._events)
        if command[0]=='start' and type(command[2]).__name__=='WindowComparisonRequest')
    terminal = e.checkpoint()
    step_window_comparison(e, request); step_window_comparison(e, request)
    if e.checkpoint() != terminal or terminal != decoded[1]:
        raise ValueError('saved terminal idempotence differs')
    if native.checkpoint() != intake[1] or old.checkpoint() != original[1]:
        raise ValueError('immutable original/intake changed')
    if freeze() != before:
        raise ValueError('source changed during bounded record stage')
    required = audit['required']
    write_new(report, dict(key=key, file=str(path.relative_to(args.output)), sha256=sha(path),
        passed=True, typed_roundtrip_exact=True, independent_audit=audit,
        terminal_idempotent=True, source_freeze=before, resumed_saved_readback=resumed_saved_readback,
        cost=dict(required=required, energy=required, time=required,
            wallet_before={u:native.wallet(actor)[u] for u in ('energy','time')},
            wallet_after={u:e.wallet(actor)[u] for u in ('energy','time')})))
    print(key+': saved, roundtrip exact, independently audited', flush=True)

def assemble(args, protocol, amendment, before):
    from hle_unified import codec
    audits = copied_prefix(args, amendment)
    index = list(amendment['preserve']['records'])
    costs = read(args.prior/'cost_readback.json')
    for mask in range(8,16):
        stage = read(args.output/'stages'/('record-'+str(mask)+'.json'))
        if (not stage['passed'] or stage['source_freeze'] != before or
                not stage['typed_roundtrip_exact'] or not stage['terminal_idempotent']):
            raise ValueError('complete bounded record stage required')
        if stage['key'] != 'workflow/mask-'+str(mask):
            raise ValueError('exact missing mask required')
        index.append({k:stage[k] for k in ('key','file','sha256')})
        audits[stage['key']] = stage['independent_audit']
        costs['workflow/'+str(mask)] = stage['cost']
    if len(index) != 40 or sorted(x['key'] for x in index) != sorted(protocol['saved_records']):
        raise ValueError('all forty exact original registered records required')
    for entry in index:
        path=args.output/entry['file']
        if sha(path) != entry['sha256']:
            raise ValueError('saved raw identity differs')
        with gzip.open(path,'rt') as stream:
            row=codec.loads(stream.read())
        if row[0] != entry['key'] or codec.loads(codec.dumps(row)) != row:
            raise ValueError('full typed roundtrip/key differs')
    if set(audits) != set(protocol['saved_records']) or not all(v['passed'] for v in audits.values()):
        raise ValueError('full forty independent audits required')
    # Rebuild descriptive aggregate files only; immutable raw/stage evidence is never overwritten.
    for name, data in (('record_index.json',index),('decoded_audits.json',audits),('cost_readback.json',costs)):
        (args.output/name).write_text(json.dumps(data,indent=2)+'\n')
    return index

def method_stage(args, protocol, before, index):
    from tools.evaluate_ft6_3b import ids
    name=args.target
    if name not in protocol['registered_tests']:
        raise ValueError('exact original registered method required')
    directory=args.output/'methods'/name
    existing=list(directory.glob('attempt-*/result.json'))
    if any(read(p)['passed'] for p in existing):
        raise ValueError('passing actual method must not be rerun')
    if existing:
        raise ValueError('failed actual method needs prospective repair before retry')
    if args.attempt > 1:
        previous=directory/('attempt-'+str(args.attempt-1))
        note=read(previous/'interruption.json')
        if note.get('log_sha256') != sha(previous/'controls.log') or not note.get('reason'):
            raise ValueError('recorded exact prior interruption required')
    attempt=directory/('attempt-'+str(args.attempt))
    attempt.mkdir(parents=True,exist_ok=False)
    suite=unittest.defaultTestLoader.loadTestsFromName(METHOD_PREFIX+name)
    actual=ids(suite)
    if list(actual) != [METHOD_PREFIX+name]:
        raise ValueError('one exact original actual method body required')
    with (attempt/'controls.log').open('x') as stream:
        result=unittest.TextTestRunner(stream=stream,verbosity=2).run(suite)
    unchanged=freeze()==before and all(sha(args.output/x['file'])==x['sha256'] for x in index)
    report=dict(method=METHOD_PREFIX+name, methods=result.testsRun, failures=len(result.failures),
        errors=len(result.errors), passed=result.wasSuccessful() and result.testsRun==1 and unchanged,
        source_unchanged=unchanged, source_freeze=before)
    write_new(attempt/'result.json', report)
    print(json.dumps(report,default=str),flush=True)
    if not report['passed']:
        raise SystemExit(1)

def finish(args, protocol, before, index):
    reports=[]
    for name in protocol['registered_tests']:
        files=list((args.output/'methods'/name).glob('attempt-*/result.json'))
        if len(files)!=1:
            raise ValueError('one complete passing actual result per registered method required')
        report=read(files[0])
        if (not report['passed'] or report['method']!=METHOD_PREFIX+name or
                report['source_freeze']!=before or report['methods']!=1):
            raise ValueError('exact passed actual method and unchanged source required')
        reports.append(report)
    summary=dict(batch=protocol['batch'],passed=True,methods=8,failures=0,errors=0,
        predecessor_identities=468,saved_records=40,original_records_preserved=32,new_records=8,
        typed_roundtrip_exact=True,independent_audits=True,source_unchanged=freeze()==before,
        frozen_identities=len(before),original_frozen_identities=388,
        original_interrupted_attempt_preserved=True,claim=protocol['claim_boundary'])
    if not summary['source_unchanged']:
        raise ValueError('final source changed')
    write_new(args.output/'method_ids.json',[x['method'] for x in reports])
    write_new(args.output/'summary.json',summary)
    print(json.dumps(summary,indent=2),flush=True)

def main():
    parser=argparse.ArgumentParser()
    for name in ('archive','prior','output'):
        parser.add_argument(name,type=lambda x:Path(x).resolve())
    parser.add_argument('action',choices=('init','record','assemble','method','finish'))
    parser.add_argument('target',nargs='?')
    parser.add_argument('--attempt',type=int,default=1)
    args=parser.parse_args()
    protocol,amendment,before=check(args)
    if args.action=='init':
        initialize(args,amendment,before)
    else:
        copied_prefix(args,amendment)
        if args.action=='record':
            record_stage(args,int(args.target),before)
        else:
            index=assemble(args,protocol,amendment,before)
            if args.action=='method':
                method_stage(args,protocol,before,index)
            elif args.action=='finish':
                finish(args,protocol,before,index)
    if freeze()!=before:
        raise ValueError('source changed across continuation action')

if __name__=='__main__':
    main()
