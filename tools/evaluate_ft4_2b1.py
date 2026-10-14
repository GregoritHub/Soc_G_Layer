"""Frozen FT4.2b1 bounded native execution gate."""
from pathlib import Path
import hashlib
import json
import sys
import unittest
ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT),str(ROOT/'baseline/HLE_Rebuild_R21B')]
from tools.evaluate_ft4_1 import manifest,ids


def freeze():
    result=manifest()
    # Freeze manifests record this result, so omit only the self-referential file.
    result.pop('contracts/ft/FT4_2b1_Source_Freeze_v1.json',None)
    for path in sorted((ROOT/'tools').glob('evaluate_ft4*.py')):
        result[str(path.relative_to(ROOT))]=hashlib.sha256(path.read_bytes()).hexdigest()
    return result


def main(out):
    out.mkdir(parents=True,exist_ok=False);before=freeze()
    (out/'source_freeze.json').write_text(json.dumps(before,indent=2)+'\n')
    registered=json.loads((ROOT/'contracts/ft/FT4_2b1_Source_Freeze_v1.json').read_text())
    rows=[('FT4_1a','test_demands','DemandTests'),('FT4_1b1','test_requests','RequestTests'),
          ('FT4_1b2','test_controller','ControllerTests'),('FT4_2a','test_route_means','RouteMeansTests'),
          ('FT4_2b1','test_route_execution','NativeTurnTests')]
    expected=[]
    for batch,module,cls in rows:
        p=json.loads((ROOT/'contracts/ft'/(batch+'_Protocol_v1.json')).read_text())
        expected.extend('tests_ft4.'+module+'.'+cls+'.'+m for m in p['method_ids'])
    suite=unittest.defaultTestLoader.loadTestsFromNames(['tests_ft4.'+m for _,m,_ in rows])
    actual=sorted(ids(suite));(out/'method_ids.json').write_text(json.dumps(actual,indent=2)+'\n')
    with (out/'controls.log').open('w') as log:result=unittest.TextTestRunner(stream=log,verbosity=2).run(suite)
    witnesses=[]
    if result.wasSuccessful() and actual==sorted(expected) and before==registered:
        from tests_ft4.test_route_execution import run
        for setting in ('canonical','workflow'):
            engine,controller,_,report=run(setting)
            (out/(setting+'-native.json')).write_text(engine.checkpoint())
            (out/(setting+'-turns.json')).write_text(controller.checkpoint(engine))
            witnesses.append(dict(setting=setting,**report))
    after=freeze()
    summary=dict(passed=result.wasSuccessful() and actual==sorted(expected) and before==after==registered and len(witnesses)==2,
        methods=result.testsRun,failures=len(result.failures),errors=len(result.errors),exact_methods=actual==sorted(expected),
        source_unchanged=before==after,registered_freeze=before==registered,witnesses=witnesses,
        scope='FT4.2b1 native execution bridge; full TD5 and FT4 acceptance remain pending')
    (out/'summary.json').write_text(json.dumps(summary,indent=2)+'\n');print(json.dumps(summary),flush=True)
    return summary


if __name__=='__main__':sys.exit(not main(Path(sys.argv[1]).resolve())['passed'])
