"""Frozen bounded diagnostic. Reads accepted evidence; never executes native jobs."""
import argparse, gzip, hashlib, json, pathlib, unittest, zipfile
from hle_unified import codec
from hle_unified.compact import unseal
from hle_unified.operations import NativeAccess
from hle_unified.selection_records import loads, dumps
from full_theory.recall_feasibility import analyze
from full_theory.recall_feasibility_audit import audit


def digest(data): return hashlib.sha256(data).hexdigest()


def main():
    p=argparse.ArgumentParser(); p.add_argument('archive'); p.add_argument('paid'); p.add_argument('capacity'); p.add_argument('output')
    a=p.parse_args(); root=pathlib.Path(__file__).resolve().parents[1]
    out=pathlib.Path(a.output); out.mkdir(exist_ok=False)
    freeze=json.loads((root/'contracts/ft/FT7_Recall_Feasibility_A1_Source_Freeze_v1.json').read_text())
    def verify():
        for name,h in freeze.items():
            if digest((root/name).read_bytes())!=h: raise ValueError('source differs: '+name)
    verify()
    tests=unittest.defaultTestLoader.loadTestsFromName('tests_ft7.test_recall_feasibility')
    with (out/'tests.log').open('w') as f:
        result=unittest.TextTestRunner(stream=f,verbosity=2).run(tests)
    if not result.wasSuccessful(): raise ValueError('diagnostic tests failed')
    archive=pathlib.Path(a.archive)
    if digest(archive.read_bytes())!='4ece02f685fb7df900523bc64983e83e19f3d636994b90bf796f5a1282dca71b':
        raise ValueError('accepted archive differs')
    with zipfile.ZipFile(archive) as z:
        manifest=json.loads(z.read('SHA256.json'))
        for name,h in manifest.items():
            if digest(z.read(name))!=h: raise ValueError('archive member differs: '+name)
        index=json.loads(z.read('current-window-admission-final2/paid_index.json'))
        capacities=json.loads(z.read('current-window-admission-final2/capacity_index.json'))
    summaries=[]
    for setting in ('canonical','workflow'):
        key=setting+'/mask-1'; ent=next(x for x in index if x['key']==key)
        raw=(pathlib.Path(a.paid)/ent['file']).read_bytes()
        if digest(raw)!=ent['sha256']: raise ValueError('paid raw differs')
        row=codec.loads(gzip.decompress(raw).decode())
        capraw=(pathlib.Path(a.capacity)/'records'/(setting+'-mask-1.json.gz')).read_bytes()
        capentry=next(x for x in capacities if x['key']==key)
        if digest(capraw)!=capentry['sha256'] or capentry['input_sha256']!=ent['sha256']:
            raise ValueError('accepted capacity differs')
        caprow=codec.loads(gzip.decompress(capraw).decode()); cap=loads(caprow[2])
        if row[0]!=key or caprow[0]!=key or caprow[1]!=ent['sha256']:
            raise ValueError('saved key/pair differs')
        if digest(row[1].encode())!=cap['native_sha256']: raise ValueError('native pairing differs')
        schema='ft-'+setting+'-paid-window-comparison-v1'
        data=unseal(row[1],schema)
        access=NativeAccess.restore(data['access']); before=access.checkpoint()
        v=access.view(cap['actor']); d=cap['required']
        report=analyze(v,d['cue'],d['context'],cap['preparation']['task'])
        if not audit(v.snapshot,report): raise ValueError('audit failed')
        if access.checkpoint()!=before: raise ValueError('access changed')
        text=dumps(report)
        if dumps(loads(text))!=text or not audit(v.snapshot,loads(text)): raise ValueError('roundtrip')
        (out/(setting+'.json')).write_text(text)
        (out/(setting+'-snapshot.txt')).write_text(v.bytes())
        summaries.append(dict(key=key,paid_raw_sha256=ent['sha256'],capacity_raw_sha256=digest(capraw),
            native_sha256=cap['native_sha256'],report_sha256=digest(text.encode()),
            roots=len(report['roots']),eligible_roots=len(report['eligible_roots']),
            reachable=[len(r['reachable']) for r in report['rows']],
            all_truncated=all(r['truncated'] for r in report['rows']),best_reachable=report['best_reachable']))
        print(json.dumps(summaries[-1]),flush=True)
    verify()
    summary=dict(status='diagnostic_pass',tests=result.testsRun,records=summaries,
        frozen_identities=len(freeze),native_operation_bodies_executed=0,
        parent_acceptance=False,scope='two mask-1 saved states; optimistic workshop-root removal only')
    (out/'summary.json').write_text(json.dumps(summary,indent=2)+'\n')
    print(json.dumps(summary),flush=True)

if __name__=='__main__': main()
