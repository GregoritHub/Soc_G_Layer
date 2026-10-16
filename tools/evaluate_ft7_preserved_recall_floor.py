"""A11 bounded saved-state evaluator: no engine restore or native commands."""
import argparse,gzip,hashlib,io,json,pathlib,sys,unittest
from datetime import datetime,timezone
from hle_unified import codec
from hle_unified.selection_records import loads
from full_theory.preserved_recall_floor import analyze
from full_theory.preserved_recall_floor_audit import audit
from tests_ft7 import test_preserved_recall_floor as tests

def main():
    p=argparse.ArgumentParser();p.add_argument('inputs');p.add_argument('output');p.add_argument('--public',required=True);p.add_argument('--owner',required=True);p.add_argument('--stop-at',required=True);a=p.parse_args()
    root=pathlib.Path(__file__).resolve().parents[1];out=pathlib.Path(a.output);out.mkdir(exist_ok=False)
    prefix='contracts/ft/FT7_Preserved_Recall_Floor_A11_'
    protocol=json.loads((root/(prefix+'Protocol_v1.json')).read_text());freeze=json.loads((root/(prefix+'Source_Freeze_v1.json')).read_text());prior=json.loads((root/protocol['prior_source_freeze']).read_text())
    def verify():
        s=json.loads((pathlib.Path(a.public)/'docs/FT_Run_State.json').read_text());now=datetime.now(timezone.utc)
        if s['run_id']!=a.owner or not s['active_worker'] or s['status']!='running' or now>=datetime.fromisoformat(s['lease_expires_at']) or now>=datetime.fromisoformat(a.stop_at):raise ValueError('ownership/deadline')
        for files in (prior,freeze):
            for name,h in files.items():
                if hashlib.sha256((root/name).read_bytes()).hexdigest()!=h:raise ValueError('source identity '+name)
    verify();rows=[];audits=[]
    for setting in ('canonical','workflow'):
        verify();raw=pathlib.Path(a.inputs)/(setting+'-complete.json.gz')
        label,native,_=codec.loads(gzip.decompress(raw.read_bytes()).decode())
        if label!='complete':raise ValueError('original label')
        report=analyze(native,setting);path=out/(setting+'-report.json');path.write_text(report)
        saved=path.read_text();audits.append(audit(native,saved,setting));rows.append((setting,native,saved))
    tests.CONTEXT.update(rows=rows,probes=0);suite=unittest.defaultTestLoader.loadTestsFromTestCase(tests.PreservedRecallFloorTests);names=[x._testMethodName for x in suite]
    if sorted(names)!=sorted(protocol['methods']):raise ValueError('exact method identities')
    log=io.StringIO();result=unittest.TextTestRunner(stream=log,verbosity=2).run(suite);(out/'tests.log').write_text(log.getvalue());verify()
    summary=dict(passed=result.wasSuccessful(),methods=names,failures=len(result.failures),errors=len(result.errors),audits=audits,forgery_probes=tests.CONTEXT['probes'],source_identities=len(freeze),prior_identities=len(prior),native_commands=0,engine_restores=0,paid_work=0,accepted_stage_replays=0,admission_claim=False)
    (out/'summary.json').write_text(json.dumps(summary,indent=2)+'\n');print(json.dumps(summary));sys.exit(0 if result.wasSuccessful() else 1)

if __name__=='__main__':main()
