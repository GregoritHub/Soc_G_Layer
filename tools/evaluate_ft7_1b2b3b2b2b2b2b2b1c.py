"""Bounded read-only capacity bridge evaluation over exact accepted paid records."""
from pathlib import Path
from zipfile import ZipFile
import argparse, gc, gzip, hashlib, json, os, sys, unittest
ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT),str(ROOT/'baseline/HLE_Rebuild_R21B')]
PREFIX='FT7_1b2b3b2b2b2b2b2b1c'
PRIOR='FT7_1b2b3b2b2b2b2b2b1b_Continuation_Source_Freeze_v1.json'
METHOD='tests_ft7.test_current_window_capacity.CurrentWindowCapacityTests.'

def sha(path): return hashlib.sha256(path.read_bytes()).hexdigest()
def read(path): return json.loads(path.read_text())
def write_new(path,data):
    path.parent.mkdir(parents=True,exist_ok=True)
    with path.open('x') as f: f.write(json.dumps(data,indent=2,sort_keys=True)+'\n')

def protocol(): return read(ROOT/'contracts/ft'/(PREFIX+'_Protocol_v1.json'))
def freeze():
    prior=ROOT/'contracts/ft'/PRIOR
    names=set(read(prior))|{str(prior.relative_to(ROOT)),
        'contracts/ft/'+PREFIX+'_Protocol_v1.json','contracts/ft/'+PREFIX+'_Protocol_v1.sha256',
        *protocol()['modules'],protocol()['tests']}
    return {n:sha(ROOT/n) for n in sorted(names)}

def predecessors():
    from tools.evaluate_ft7_1b2b3b2b2b2b2b2b1b import predecessors as previous
    from tools.evaluate_ft6_3b import ids
    actual=sorted(ids(unittest.defaultTestLoader.loadTestsFromName('tests_ft7.test_paid_window_comparison')))
    p=read(ROOT/'contracts/ft/FT7_1b2b3b2b2b2b2b2b1b_Protocol_v1.json')
    expected=sorted('tests_ft7.test_paid_window_comparison.PaidWindowComparisonTests.'+n for n in p['registered_tests'])
    if actual!=expected: raise ValueError('exact eight predecessor bodies required')
    result=previous()+actual
    if len(result)!=476: raise ValueError('exact 476 predecessor identities required')
    return result

def entries(): return read(Path(os.environ['FT7_CAPACITY_OUTPUT'])/'input_index.json')
def input_entry(key):
    rows=[e for e in entries() if e['key']==key]
    if len(rows)!=1: raise ValueError('exact accepted input key required')
    return rows[0]

def context(key):
    from hle_unified import codec
    from tools.evaluate_ft7_1b2b3b2b2b2b2b2b1b import original_row,input_row,paid_type
    from tests_ft7.test_social_live_outcome import engine_type
    setting,stage=key.split('/'); mask=int(stage[5:]) if stage.startswith('mask-') else 1
    entry=input_entry(key); path=Path(os.environ['FT7_CAPACITY_PAID'])/entry['file']
    if sha(path)!=entry['sha256']: raise ValueError('accepted paid raw changed')
    with gzip.open(path,'rt') as f: row=codec.loads(f.read())
    if row[0]!=key or codec.loads(codec.dumps(row))!=row: raise ValueError('paid typed roundtrip')
    original=original_row(setting); intake=input_row(setting,'mask-'+str(mask))
    return (paid_type(setting).restore(row[1]),engine_type(setting).restore(intake[1]),
        engine_type(setting).restore(original[1]),original[2],original[3],intake[2],row[2])

def saved(key):
    from hle_unified import codec
    path=Path(os.environ['FT7_CAPACITY_OUTPUT'])/'records'/(key.replace('/','-')+'.json.gz')
    with gzip.open(path,'rt') as f: row=codec.loads(f.read())
    if row[0]!=key or row[1]!=input_entry(key)['sha256']: raise ValueError('bridge input identity')
    return row

def check(args):
    p=protocol(); current=freeze()
    if current!=read(ROOT/'contracts/ft'/(PREFIX+'_Source_Freeze_v1.json')): raise ValueError('frozen source changed')
    prior=read(ROOT/'contracts/ft'/PRIOR)
    if len(prior)!=392 or any(current[n]!=h for n,h in prior.items()): raise ValueError('392 prior identities changed')
    pp=ROOT/'contracts/ft'/(PREFIX+'_Protocol_v1.json')
    if sha(pp)!=pp.with_suffix('.sha256').read_text().split()[0]: raise ValueError('protocol hash')
    os.environ.update(FT7_CAPACITY_OUTPUT=str(args.output),FT7_CAPACITY_PAID=str(args.paid),
        FT7_WINDOW_INPUT=str(args.archives/p['input']['request_input']['filename']))
    if args.action!='init':
        verified=read(args.output/'input_verification.json')
        if not verified['passed'] or verified['input']!=p['input']: raise ValueError('verified input contract')
        for entry in entries():
            if sha(args.paid/entry['file'])!=entry['sha256']: raise ValueError('accepted input changed')
    return p,current

def initialize(args,p,before):
    args.output.mkdir(parents=True,exist_ok=False)
    members={}
    for key,item in p['input'].items():
        path=args.archives/item['filename']
        if sha(path)!=item['sha256']: raise ValueError('exact durable input archive required')
        with ZipFile(path) as z:
            manifest=json.loads(z.read('SHA256.json'))
            if set(z.namelist())!=set(manifest)|{'SHA256.json'}: raise ValueError('archive member domain')
            for name,digest in manifest.items():
                if hashlib.sha256(z.read(name)).hexdigest()!=digest: raise ValueError('archive member identity')
            members[key]=len(manifest)
            if key=='closure':
                summary=json.loads(z.read('paid-window-continuation1/summary.json'))
                if not summary['passed'] or (summary['methods'],summary['saved_records'],summary['predecessor_identities'])!=(8,40,468):
                    raise ValueError('complete prior acceptance required')
                index=json.loads(z.read('paid-window-continuation1/record_index.json'))
    if sorted(x['key'] for x in index)!=sorted(p['saved_records']): raise ValueError('exact forty input records')
    with ZipFile(args.archives/p['input']['continuation']['filename']) as z:
        for entry in index:
            raw=z.read('paid-window-continuation1/'+entry['file'])
            if hashlib.sha256(raw).hexdigest()!=entry['sha256'] or raw!=(args.paid/entry['file']).read_bytes():
                raise ValueError('durable/local exact paid input bridge')
    write_new(args.output/'input_index.json',index)
    write_new(args.output/'input_verification.json',dict(passed=True,input=p['input'],members=members,raw_exact=40))
    write_new(args.output/'source_freeze.json',before)
    write_new(args.output/'predecessor_ids.json',predecessors())
    print('verified exact input pair, request archive, forty paid records and 476 identities',flush=True)

def record_stage(args,p,before):
    from hle_unified import codec
    from full_theory.current_window_capacity import current_window_capacity
    from full_theory.current_window_capacity_audit import audit_current_window_capacity
    key=args.target
    if key not in p['saved_records']: raise ValueError('registered record key required')
    report=args.output/'stages'/(key.replace('/','-')+'.json')
    if report.exists(): raise ValueError('completed record stage must not be rerun')
    path=args.output/'records'/(key.replace('/','-')+'.json.gz'); path.parent.mkdir(parents=True,exist_ok=True)
    print(key+': restoring exact accepted input (no payment)',flush=True)
    ctx=context(key); native=ctx[0].checkpoint()
    if not path.exists():
        text=current_window_capacity(*ctx)
        with gzip.open(path,'xt',encoding='ascii') as f: f.write(codec.dumps((key,input_entry(key)['sha256'],text))+'\n')
    row=saved(key)
    if codec.loads(codec.dumps(row))!=row: raise ValueError('new typed roundtrip')
    result=audit_current_window_capacity(*ctx,row[2])
    if ctx[0].checkpoint()!=native or freeze()!=before: raise ValueError('native/source mutation')
    write_new(report,dict(key=key,passed=True,sha256=sha(path),file=str(path.relative_to(args.output)),
        input_sha256=input_entry(key)['sha256'],typed_roundtrip_exact=True,independent_audit=result,source_freeze=before))
    print(key+': saved exact typed bridge and full independent native/source/payment/capacity audit',flush=True)
    del ctx;gc.collect()

def complete_records(args,p,before):
    reports=[]
    for key in p['saved_records']:
        r=read(args.output/'stages'/(key.replace('/','-')+'.json'))
        if not r['passed'] or not r['typed_roundtrip_exact'] or r['key']!=key or r['source_freeze']!=before:
            raise ValueError('complete exact saved stage required')
        if sha(args.output/r['file'])!=r['sha256']: raise ValueError('saved bridge changed')
        reports.append(r)
    return reports

def method_stage(args,p,before):
    from tools.evaluate_ft6_3b import ids
    complete_records(args,p,before)
    if args.target not in p['registered_tests']: raise ValueError('registered actual method required')
    directory=args.output/'methods'/args.target
    directory.mkdir(parents=True,exist_ok=False)
    suite=unittest.defaultTestLoader.loadTestsFromName(METHOD+args.target)
    if list(ids(suite))!=[METHOD+args.target]: raise ValueError('exact one actual method')
    with (directory/'controls.log').open('x') as f: result=unittest.TextTestRunner(stream=f,verbosity=2).run(suite)
    complete_records(args,p,before)
    passed=result.wasSuccessful() and result.testsRun==1 and freeze()==before
    write_new(directory/'result.json',dict(method=METHOD+args.target,methods=result.testsRun,failures=len(result.failures),
        errors=len(result.errors),passed=passed,source_freeze=before))
    print(args.target+': '+str(passed),flush=True)
    if not passed: raise SystemExit(1)

def finish(args,p,before):
    records=complete_records(args,p,before); methods=[]
    for name in p['registered_tests']:
        r=read(args.output/'methods'/name/'result.json')
        if not r['passed'] or r['method']!=METHOD+name or (r['methods'],r['failures'],r['errors'])!=(1,0,0) or r['source_freeze']!=before:
            raise ValueError('all eight exact actual methods required')
        methods.append(r['method'])
    if read(args.output/'predecessor_ids.json')!=predecessors() or freeze()!=before: raise ValueError('identities changed')
    write_new(args.output/'record_index.json',[{k:r[k] for k in ('key','file','sha256','input_sha256')} for r in records])
    write_new(args.output/'method_ids.json',methods)
    write_new(args.output/'summary.json',dict(batch=p['batch'],passed=True,methods=8,failures=0,errors=0,
        saved_records=40,predecessor_identities=476,frozen_identities=len(before),prior_identities=392,
        native_unchanged=True,new_native_work=False,claim=p['claim_boundary']))
    print('PASS: 8 exact methods / 40 exact audited bridges / 476 predecessors / unchanged source',flush=True)

def main():
    parser=argparse.ArgumentParser()
    for name in ('archives','paid','output'): parser.add_argument(name,type=lambda s:Path(s).resolve())
    parser.add_argument('action',choices=('init','record','method','finish'));parser.add_argument('target',nargs='?')
    args=parser.parse_args();p,before=check(args)
    if args.action=='init': initialize(args,p,before)
    elif args.action=='record': record_stage(args,p,before)
    elif args.action=='method': method_stage(args,p,before)
    else: finish(args,p,before)

if __name__=='__main__': main()
