"""Read-only payment/receipt probes over exact original saved partials."""
import argparse,copy,gc,gzip,hashlib,json,pathlib,zipfile
from datetime import datetime,timezone
from hle_unified import codec
from hle_unified.selection_records import dumps,loads
from full_theory.paid_window_comparison import PaidCanonicalWindowEngine,PaidWorkflowWindowEngine
from full_theory.owned_material_inspection_audit import audit_owned_material_inspection,baseline


def sha(b): return hashlib.sha256(b).hexdigest()


def run():
    p=argparse.ArgumentParser();p.add_argument('archive');p.add_argument('paid');p.add_argument('capacity')
    p.add_argument('records');p.add_argument('output');p.add_argument('--owner',required=True)
    p.add_argument('--public',required=True);p.add_argument('--stop-at',required=True);a=p.parse_args()
    root=pathlib.Path(__file__).resolve().parents[1];out=pathlib.Path(a.output);out.mkdir(exist_ok=False)
    frozen=json.loads((root/'contracts/ft/FT7_Skill_Intake_A1_Saved_Source_Freeze_v1.json').read_text())
    def verify():
        for name,h in frozen.items():
            if sha((root/name).read_bytes())!=h:raise ValueError('saved probe source differs: '+name)
    def guard():
        st=json.loads((pathlib.Path(a.public)/'docs/FT_Run_State.json').read_text());now=datetime.now(timezone.utc)
        if st['run_id']!=a.owner or not st['active_worker'] or st['status']!='running' or now>=datetime.fromisoformat(st['lease_expires_at']) or now>=datetime.fromisoformat(a.stop_at):
            raise SystemExit('saved-probe launch guard; no native work performed')
    verify();guard()
    if sha(pathlib.Path(a.archive).read_bytes())!='4ece02f685fb7df900523bc64983e83e19f3d636994b90bf796f5a1282dca71b':raise ValueError('accepted archive identity')
    with zipfile.ZipFile(a.archive) as z:
        for name,h in json.loads(z.read('SHA256.json')).items():
            if sha(z.read(name))!=h:raise ValueError('accepted manifest identity')
        pi=json.loads(z.read('current-window-admission-final2/paid_index.json'))
        ci=json.loads(z.read('current-window-admission-final2/capacity_index.json'))
    progress=json.loads((pathlib.Path(a.records)/'progress.json').read_text());results=[]
    for setting,typ in (('canonical',PaidCanonicalWindowEngine),('workflow',PaidWorkflowWindowEngine)):
        guard();key=setting+'/mask-1';pe=next(x for x in pi if x['key']==key);ce=next(x for x in ci if x['key']==key)
        pr=(pathlib.Path(a.paid)/pe['file']).read_bytes();cr=(pathlib.Path(a.capacity)/ce['file']).read_bytes()
        if sha(pr)!=pe['sha256'] or sha(cr)!=ce['sha256'] or ce['input_sha256']!=pe['sha256']:raise ValueError('input pairing')
        prow=codec.loads(gzip.decompress(pr).decode());crow=codec.loads(gzip.decompress(cr).decode())
        if prow[0]!=key or crow[0]!=key or crow[1]!=pe['sha256']:raise ValueError('typed input pairing')
        original=prow[1];capacity=crow[2]
        row=next(x for x in progress if x['setting']==setting and x['record']=='inspect-partial')
        raw=(pathlib.Path(a.records)/row['file']).read_bytes()
        if sha(raw)!=row['sha256']:raise ValueError('saved partial identity')
        name,native,text=codec.loads(gzip.decompress(raw).decode())
        if name!='inspect-partial':raise ValueError('record label')
        print('restoring saved '+setting,flush=True);engine=typ.restore(native)
        audit=audit_owned_material_inspection(engine,original,capacity,text);rejections={}
        for kind in ('payment','receipt'):
            bad=copy.deepcopy(loads(text))
            if kind=='payment':
                event=next(e for e in bad['events'] if e['debit']['energy']>0);event['debit']['energy']+=1
            else:bad['receipts'].append(dict(index=0,inspect_job='forged-inspection',read_job='forged-read'))
            try:audit_owned_material_inspection(engine,original,capacity,dumps(bad))
            except ValueError as error:rejections[kind]=str(error)
            else:raise ValueError('forged '+kind+' accepted')
        if engine.checkpoint()!=native:raise ValueError('read-only probe changed native')
        verify();result=dict(setting=setting,passed=True,record_sha256=row['sha256'],original_audit=audit,rejections=rejections,native_unchanged=True,paid_work_calls=0)
        (out/(setting+'.json')).write_text(json.dumps(result,indent=2)+'\n');results.append(result);print(json.dumps(result),flush=True)
        del engine;baseline.cache_clear();gc.collect()
    verify();(out/'summary.json').write_text(json.dumps(dict(passed=True,settings=results,negative_probes=4,source_identities=len(frozen),prior_identities=419,paid_work_calls=0,parent_accepted=False),indent=2)+'\n')


if __name__=='__main__':run()
