"""A12A saved-source panel gate; does not restore an engine or pay intake."""
import argparse,gzip,hashlib,io,json,pathlib,sys,unittest,zipfile
from datetime import datetime,timezone
from hle_unified import codec
from full_theory.observed_cue_panel import build
from full_theory.observed_cue_panel_audit import audit
from tests_ft7 import test_observed_cue_panel as tests

def main():
    p=argparse.ArgumentParser();p.add_argument('archive');p.add_argument('output');p.add_argument('--public',required=True);p.add_argument('--owner',required=True);p.add_argument('--stop-at',required=True);a=p.parse_args()
    root=pathlib.Path(__file__).resolve().parents[1];out=pathlib.Path(a.output);out.mkdir(exist_ok=False);prefix='contracts/ft/FT7_Observed_Cue_Panel_A12A_'
    protocol=json.loads((root/(prefix+'Protocol_v1.json')).read_text());freeze=json.loads((root/(prefix+'Source_Freeze_v1.json')).read_text());prior=json.loads((root/protocol['prior_source_freeze']).read_text())
    def verify():
        state=json.loads((pathlib.Path(a.public)/'docs/FT_Run_State.json').read_text());now=datetime.now(timezone.utc)
        if state['run_id']!=a.owner or not state['active_worker'] or state['status']!='running' or now>=datetime.fromisoformat(state['lease_expires_at']) or now>=datetime.fromisoformat(a.stop_at):raise ValueError('ownership/deadline')
        for mapping in (prior,freeze):
            for n,h in mapping.items():
                if hashlib.sha256((root/n).read_bytes()).hexdigest()!=h:raise ValueError('source '+n)
    verify();archive=pathlib.Path(a.archive)
    if hashlib.sha256(archive.read_bytes()).hexdigest()!=protocol['archive']['sha256']:raise ValueError('archive')
    rows=[];audits=[]
    with zipfile.ZipFile(archive) as z:
        manifest=json.loads(z.read('SHA256.json'))
        if len(manifest)!=protocol['archive']['members']:raise ValueError('manifest count')
        for n,h in manifest.items():
            if hashlib.sha256(z.read(n)).hexdigest()!=h:raise ValueError('member '+n)
        for setting in ('canonical','workflow'):
            verify();row=codec.loads(gzip.decompress(z.read('ft71b2b3b2b1-attempt1/records/'+setting+'-live.json.gz')).decode())
            if row[0]!=setting+'/live':raise ValueError('original label')
            native,source,binding=row[1:4];report=build(native,source,binding,setting);path=out/(setting+'-panel.json');path.write_text(report)
            saved=path.read_text();audits.append(audit(native,source,binding,setting,saved));rows.append((native,source,binding,setting,saved))
    tests.CONTEXT.update(rows=rows,probes=0);suite=unittest.defaultTestLoader.loadTestsFromTestCase(tests.ObservedCuePanelTests);names=[t._testMethodName for t in suite]
    if sorted(names)!=sorted(protocol['methods']):raise ValueError('methods')
    log=io.StringIO();result=unittest.TextTestRunner(stream=log,verbosity=2).run(suite);(out/'tests.log').write_text(log.getvalue());verify()
    summary=dict(passed=result.wasSuccessful(),methods=names,failures=len(result.failures),errors=len(result.errors),audits=audits,forgery_probes=tests.CONTEXT['probes'],source_identities=len(freeze),prior_identities=len(prior),archive_members=len(manifest),native_work=0,engine_restores=0,accepted_replays=0,intake_paid=False,admission_claim=False)
    (out/'summary.json').write_text(json.dumps(summary,indent=2)+'\n');print(json.dumps(summary));sys.exit(0 if result.wasSuccessful() else 1)

if __name__=='__main__':main()
