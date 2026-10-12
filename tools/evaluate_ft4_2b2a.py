"""Frozen cp orientation payment instrument, not full FT4.2 acceptance."""
from pathlib import Path
import hashlib
import json
import sys
import unittest
ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT),str(ROOT/'baseline/HLE_Rebuild_R21B')]
from tools.evaluate_ft4_1 import manifest,ids


def freeze():
    result=manifest();result.pop('contracts/ft/FT4_2b2a_Source_Freeze_v1.json',None)
    for path in sorted((ROOT/'tools').glob('evaluate_ft4*.py')):
        result[str(path.relative_to(ROOT))]=hashlib.sha256(path.read_bytes()).hexdigest()
    return result


def main(out):
    out.mkdir(parents=True,exist_ok=False);before=freeze()
    (out/'source_freeze.json').write_text(json.dumps(before,indent=2)+'\n')
    registered=json.loads((ROOT/'contracts/ft/FT4_2b2a_Source_Freeze_v1.json').read_text())
    expected=[]
    for batch,module,cls in [('FT4_2b1','test_route_execution','NativeTurnTests'),('FT4_2b2a','test_orientation','OrientationTests')]:
        p=json.loads((ROOT/'contracts/ft'/(batch+'_Protocol_v1.json')).read_text())
        expected.extend('tests_ft4.'+module+'.'+cls+'.'+m for m in p['method_ids'])
    suite=unittest.defaultTestLoader.loadTestsFromNames(['tests_ft4.test_route_execution','tests_ft4.test_orientation'])
    actual=sorted(ids(suite));(out/'method_ids.json').write_text(json.dumps(actual,indent=2)+'\n')
    with (out/'controls.log').open('w') as log:result=unittest.TextTestRunner(stream=log,verbosity=2).run(suite)
    witnesses=[]
    if result.wasSuccessful() and actual==sorted(expected) and before==registered:
        from tests_ft4.test_orientation import run
        for setting in ('canonical','workflow'):
            engine,controller,_,report=run(setting)
            (out/(setting+'-native.json')).write_text(engine.checkpoint())
            (out/(setting+'-orientation.json')).write_text(controller.checkpoint(engine))
            witnesses.append(dict(setting=setting,**report))
    after=freeze();summary=dict(passed=result.wasSuccessful() and actual==sorted(expected) and before==after==registered and len(witnesses)==2,
        methods=result.testsRun,failures=len(result.failures),errors=len(result.errors),exact_methods=actual==sorted(expected),
        source_unchanged=before==after,registered_freeze=before==registered,witnesses=witnesses,
        scope='FT4.2b2a orientation fee only; traversal and full TD5 remain pending')
    (out/'summary.json').write_text(json.dumps(summary,indent=2)+'\n');print(json.dumps(summary),flush=True);return summary


if __name__=='__main__':sys.exit(not main(Path(sys.argv[1]).resolve())['passed'])
