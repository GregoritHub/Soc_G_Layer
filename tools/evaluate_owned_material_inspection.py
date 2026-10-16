"""Bounded serial paid inspection gate; accepted inputs restored, never regenerated."""
import argparse,gzip,hashlib,json,pathlib,unittest,zipfile,gc
from datetime import datetime,timezone
from hle_unified import codec
from hle_unified.selection_records import dumps,loads
from full_theory.paid_window_comparison import PaidCanonicalWindowEngine,PaidWorkflowWindowEngine
from full_theory.owned_material_inspection import OwnedMaterialInspection
from full_theory.owned_material_inspection_audit import audit_owned_material_inspection,baseline


def sha(b): return hashlib.sha256(b).hexdigest()


def run():
    p=argparse.ArgumentParser();p.add_argument('archive');p.add_argument('paid');p.add_argument('capacity');p.add_argument('output')
    p.add_argument('--owner',required=True);p.add_argument('--public',required=True);p.add_argument('--stop-at',required=True)
    a=p.parse_args();root=pathlib.Path(__file__).resolve().parents[1];out=pathlib.Path(a.output);out.mkdir(exist_ok=False)
    freeze=json.loads((root/'contracts/ft/FT7_Skill_Intake_A1_Source_Freeze_v1.json').read_text())
    def verify():
        for name,h in freeze.items():
            if sha((root/name).read_bytes())!=h:raise ValueError('frozen source differs: '+name)
    verify()
    def guard():
        state=json.loads((pathlib.Path(a.public)/'docs/FT_Run_State.json').read_text())
        now=datetime.now(timezone.utc)
        if (state['run_id']!=a.owner or not state['active_worker'] or state['status']!='running'
            or now>=datetime.fromisoformat(state['lease_expires_at'])
            or now>=datetime.fromisoformat(a.stop_at)):
            (out/'operational_stop.json').write_text(json.dumps(dict(reason='owner/lease/deadline launch guard',
                at=now.isoformat(),parent_accepted=False))+'\n')
            raise SystemExit('operational checkpoint guard; no further native work')
    guard()
    if sha(pathlib.Path(a.archive).read_bytes())!='4ece02f685fb7df900523bc64983e83e19f3d636994b90bf796f5a1282dca71b':
        raise ValueError('accepted archive differs')
    with zipfile.ZipFile(a.archive) as z:
        manifest=json.loads(z.read('SHA256.json'))
        for name,h in manifest.items():
            if sha(z.read(name))!=h:raise ValueError('accepted member differs')
        paid=json.loads(z.read('current-window-admission-final2/paid_index.json'))
        capacities=json.loads(z.read('current-window-admission-final2/capacity_index.json'))
    summaries=[]
    for setting,typ in (('canonical',PaidCanonicalWindowEngine),('workflow',PaidWorkflowWindowEngine)):
        guard()
        key=setting+'/mask-1';entry=next(x for x in paid if x['key']==key);ce=next(x for x in capacities if x['key']==key)
        raw=(pathlib.Path(a.paid)/entry['file']).read_bytes();cr=(pathlib.Path(a.capacity)/ce['file']).read_bytes()
        if sha(raw)!=entry['sha256'] or sha(cr)!=ce['sha256'] or ce['input_sha256']!=entry['sha256']:
            raise ValueError('accepted input differs')
        row=codec.loads(gzip.decompress(raw).decode());crow=codec.loads(gzip.decompress(cr).decode())
        original=row[1];capacity=crow[2]
        if row[0]!=key or crow[0]!=key or crow[1]!=entry['sha256']:raise ValueError('input key pairing')
        print('restoring '+setting,flush=True);engine=typ.restore(original)
        guard()
        adapter=OwnedMaterialInspection(engine,capacity);saved={}
        def save(name,e,b):
            native=e.checkpoint();text=b.checkpoint(e);audit=audit_owned_material_inspection(e,original,capacity,text)
            if dumps(loads(text))!=text:raise ValueError('typed roundtrip')
            filename=setting+'-'+name+'.json.gz';payload=codec.dumps((name,native,text))
            with gzip.open(out/filename,'wt') as f:f.write(payload)
            with gzip.open(out/filename,'rt') as f:
                if codec.loads(f.read())!=(name,native,text):raise ValueError('saved record differs')
            result=dict(setting=setting,record=name,file=filename,sha256=sha((out/filename).read_bytes()),**audit)
            summaries.append(result);saved[name]=(native,text);print(json.dumps(result),flush=True)
            (out/'progress.json').write_text(json.dumps(summaries,indent=2)+'\n')
        save('before',engine,adapter)
        for turn in range(768):
            guard()
            event=adapter.step(engine,work_limit=1)
            if event['status']=='partial' and event['phase']=='inspect' and 'inspect-partial' not in saved:
                save('inspect-partial',engine,adapter)
            if event['status']=='partial' and event['phase']=='read' and 'read-partial' not in saved:
                save('read-partial',engine,adapter)
            if adapter.phase=='complete':break
        else:raise ValueError('registered finite turn bound exceeded')
        save('complete',engine,adapter);final=(engine.checkpoint(),adapter.checkpoint(engine))
        adapter.step(engine);adapter.step(engine,cancel=True)
        if (engine.checkpoint(),adapter.checkpoint(engine))!=final:raise ValueError('terminal not idempotent')
        del engine,adapter;gc.collect()
        native,text=saved['read-partial'];engine=typ.restore(native)
        guard()
        adapter=OwnedMaterialInspection.restore(text,engine,original,capacity)
        for turn in range(768):
            guard()
            adapter.step(engine,work_limit=1)
            if adapter.phase=='complete':break
        else:raise ValueError('restart bound')
        if (engine.checkpoint(),adapter.checkpoint(engine))!=final:raise ValueError('restart differs')
        save('restarted',engine,adapter)
        # Adversarial saved-record audit: no new paid work in these checks.
        for field,value in (('main_execution_authorized',True),('source_native_sha256','0'*64),('plan',())):
            bad=loads(adapter.checkpoint(engine));bad[field]=value
            try:audit_owned_material_inspection(engine,original,capacity,dumps(bad))
            except ValueError:pass
            else:raise ValueError('forgery accepted: '+field)
        del engine,adapter;gc.collect()
        native,text=saved['inspect-partial'];engine=typ.restore(native)
        guard()
        adapter=OwnedMaterialInspection.restore(text,engine,original,capacity);adapter.step(engine,cancel=True)
        save('cancelled',engine,adapter)
        del engine,adapter,saved,final;baseline.cache_clear();gc.collect()
    import tests_ft7.test_owned_material_inspection as tests
    tests.RESULTS=summaries
    with (out/'tests.log').open('w') as f:
        result=unittest.TextTestRunner(stream=f,verbosity=2).run(unittest.defaultTestLoader.loadTestsFromModule(tests))
    if not result.wasSuccessful() or result.testsRun!=6:raise ValueError('six exact methods required')
    verify();summary=dict(passed=True,methods=result.testsRun,records=summaries,source_identities=len(freeze),
        prior_identities=412,skill_acquired=False,main_execution_authorized=False,history_choice=False,parent_accepted=False)
    (out/'summary.json').write_text(json.dumps(summary,indent=2)+'\n');print(json.dumps(summary),flush=True)

if __name__=='__main__':run()
