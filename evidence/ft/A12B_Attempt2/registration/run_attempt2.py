"""User-authorized single-case new attempt; original evidence is read-only."""
import gzip, hashlib, io, json, os, pathlib, sys, traceback, unittest, zipfile
from datetime import datetime, timezone
ROOT = pathlib.Path(__file__).resolve().parents[1]
REG = pathlib.Path(__file__).resolve().parent
RT = ROOT/'runtime-b1d-recovered'
OLD = ROOT/'cue-intake-a12b-attempt1'
OUT = ROOT/'cue-intake-a12b-attempt2'
sys.path[:0] = [str(RT), str(RT/'tools')]
from hle_unified import codec
from full_theory.cue_task_intake import CueTaskIntake
from full_theory.cue_task_intake_audit import audit_cue_task_intake
from evaluate_ft7_cue_task_intake import expected_names, engine_type

def sha(b): return hashlib.sha256(b).hexdigest()
def now(): return datetime.now(timezone.utc).isoformat()
def write(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_name(path.name+'.pending')
    with tmp.open('xb') as f:
        f.write(data); f.flush(); os.fsync(f.fileno())
    os.link(tmp, path); tmp.unlink()
    fd = os.open(path.parent, os.O_RDONLY)
    try: os.fsync(fd)
    finally: os.close(fd)
    assert path.read_bytes() == data
def js(path, data): write(path, (json.dumps(data,indent=2)+'\n').encode())
def verify():
    freeze=json.loads((REG/'Freeze.json').read_text())
    for n,h in freeze.items(): assert sha((ROOT/n).read_bytes())==h,n
    for n,h in json.loads((REG/'Original_Attempt_Manifest.json').read_text()).items():
        assert sha((OLD/n).read_bytes())==h,n
def inputs(setting):
    archive=ROOT/'a12-original-input/FT7_1b2b3b2b1_Owned_Proposal_Domain_Evidence_20261015.zip'
    assert sha(archive.read_bytes())=='3973f24b472e90ff047f5d61c16e3b987860c2d5478a62234dde213fc3212945'
    with zipfile.ZipFile(archive) as z:
        r=codec.loads(gzip.decompress(z.read('ft71b2b3b2b1-attempt1/records/'+setting+'-live.json.gz')).decode())
    assert r[0]==setting+'/live'
    panel=(ROOT/'observed-cue-panel-a12a-attempt2'/(setting+'-panel.json')).read_text()
    init=json.loads((OLD/'jobs/init.outcome.json').read_text())
    assert sha(panel.encode())==init['result']['panels'][setting]
    return (*r[1:4],panel)
def row(path): return codec.loads(gzip.decompress(path.read_bytes()).decode())
def pack(name):
    target=ROOT/name
    files={p.relative_to(OUT).as_posix():p.read_bytes() for p in OUT.rglob('*') if p.is_file()}
    for p in REG.iterdir():
        if p.is_file(): files['registration/'+p.name]=p.read_bytes()
    files['SHA256.json']=(json.dumps({n:sha(b) for n,b in sorted(files.items())},indent=2)+'\n').encode()
    stream=io.BytesIO()
    with zipfile.ZipFile(stream,'w',zipfile.ZIP_DEFLATED) as z:
        for n,b in sorted(files.items()): z.writestr(n,b)
    write(target,stream.getvalue())
    with zipfile.ZipFile(target) as z:
        for n,h in json.loads(z.read('SHA256.json')).items(): assert sha(z.read(n))==h,n
    return dict(path=str(target),sha256=sha(target.read_bytes()),bytes=target.stat().st_size)

def generate():
    OUT.mkdir(exist_ok=False)
    js(OUT/'jobs/generate-workflow-12.start.json',dict(attempt=2,started=now(),authorized_rerun=True))
    native,source,binding,panel=inputs('workflow')
    engine=engine_type('workflow').restore(native)
    adapter=CueTaskIntake(engine,source,binding,panel,12)
    adapter.step(engine,work_limit=2);adapter.step(engine,work_limit=3)
    assert adapter.receipt is not None
    data=codec.dumps(('workflow',12,'complete',engine.checkpoint(),adapter.checkpoint(engine)))
    compressed=gzip.compress(data.encode(),mtime=0)
    path=OUT/'records/workflow-12-complete.json.gz'
    write(path,compressed)
    assert codec.dumps(row(path))==data
    write(OUT/'backup/workflow-12-complete.json.gz',compressed)
    js(OUT/'NEW_RECORD.json',dict(attempt=2,record=path.name,sha256=sha(compressed),bytes=len(compressed),typed_roundtrip=True,exact_backup=True,recovered_original=False))
    js(OUT/'jobs/generate-workflow-12.outcome.json',dict(passed=True,attempt=2,ended=now(),record_sha256=sha(compressed),native_cost=adapter.receipt['energy']))
    verify()
    print(json.dumps(pack('FT7_A12B_Attempt2_Immediate_Evidence.zip')),flush=True)

def validate():
    js(OUT/'jobs/validation.start.json',dict(started=now(),attempt=2))
    provenance={};audits={}
    for name in expected_names():
        p=OUT/'records'/(name+'.json.gz')
        if name=='workflow-12-complete':
            saved=row(p);native,source,binding,panel=inputs('workflow');typ=engine_type('workflow')
            result=audit_cue_task_intake(typ.restore(saved[3]),typ.restore(native),source,binding,panel,saved[4])
            assert result['passed']
            result.update(record=name,record_sha256=sha(p.read_bytes()))
            js(OUT/'audits'/(name+'.json'),result)
            js(OUT/'jobs/audit-workflow-12-complete.outcome.json',dict(passed=True,attempt=2,ended=now(),result=result))
            provenance[name]=dict(attempt=2,sha256=sha(p.read_bytes()))
        else:
            raw=(OLD/'records'/(name+'.json.gz')).read_bytes()
            a=(OLD/'audits'/(name+'.json')).read_bytes();result=json.loads(a)
            closed=json.loads((OLD/'jobs'/('audit-'+name+'.outcome.json')).read_text())
            assert closed['passed'] and result['passed'] and result['record']==name and result['record_sha256']==sha(raw)
            write(p,raw);write(OUT/'audits'/(name+'.json'),a)
            provenance[name]=dict(attempt=1,sha256=sha(raw),audit_outcome_sha256=sha((OLD/'jobs'/('audit-'+name+'.outcome.json')).read_bytes()))
        saved=row(p)
        assert f'{saved[0]}-{saved[1]:02d}-{saved[2]}'==name
        assert codec.dumps(saved)==gzip.decompress(p.read_bytes()).decode()
        audits[name]=result
    js(OUT/'PROVENANCE.json',provenance)
    print('All 50 record identities and passing independent audits bound; 49 original plus one new.',flush=True)
    from tests_ft7 import test_cue_task_intake as tests
    rows={n:row(OUT/'records'/(n+'.json.gz')) for n in expected_names()}
    tests.CONTEXT.update(rows=rows,audits=audits,inputs={s:inputs(s) for s in ('canonical','workflow')})
    suite=unittest.defaultTestLoader.loadTestsFromTestCase(tests.CueTaskIntakeTests)
    names=[t._testMethodName for t in suite]
    protocol=json.loads((RT/'contracts/ft/FT7_Cue_Intake_A12B_Protocol_v1.json').read_text())
    assert sorted(names)==sorted(protocol['methods'])
    with (OUT/'tests.log').open('x') as log:
        result=unittest.TextTestRunner(stream=log,verbosity=2).run(suite)
    js(OUT/'jobs/tests.outcome.json',dict(passed=result.wasSuccessful(),methods=names,failures=len(result.failures),errors=len(result.errors)))
    assert result.wasSuccessful()
    verify()
    for n,a in audits.items(): assert a['record_sha256']==sha((OUT/'records'/(n+'.json.gz')).read_bytes())
    # The original finish aggregate's complete gate, with explicit new-attempt provenance.
    summary=dict(passed=True,records=len(rows),methods=names,source_identities=576,prior_identities=568,new_primary_reruns=1,original_records_reused=49,original_attempt_preserved=True,original_gate_denominators_unchanged=True,publication_pending=True,comparison_paid=False,execution_authorized=False,td5_admitted=False,history_choice=False)
    js(OUT/'summary.json',summary)
    js(OUT/'jobs/validation.outcome.json',dict(passed=True,ended=now(),result=summary))
    print(json.dumps(pack('FT7_A12B_Attempt2_Validated_Evidence.zip')),flush=True)

if __name__=='__main__':
    verify()
    try:
        {'generate':generate,'validate':validate}[sys.argv[1]]()
    except BaseException:
        if OUT.exists():
            failure=OUT/('failure-'+sys.argv[1]+'.txt')
            if not failure.exists():write(failure,traceback.format_exc().encode())
        raise
