"""Frozen, exact-ID FT4.1a admission panel; never FT4-wide acceptance."""
from pathlib import Path
import hashlib
import json
import sys
import unittest
ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT),str(ROOT/'baseline/HLE_Rebuild_R21B')]
from hle_unified.selection_records import dumps


def manifest():
    return {str(p.relative_to(ROOT)):hashlib.sha256(p.read_bytes()).hexdigest()
        for area in ('full_theory','hle_unified','baseline','tests_ft4','contracts/ft','evidence/FT0.1/reference')
        for p in sorted((ROOT/area).rglob('*')) if p.is_file() and p.suffix in ('.py','.json','.sha256')}


def ids(suite):
    for item in suite:
        if isinstance(item,unittest.TestSuite):yield from ids(item)
        else:yield item.id()


def main(out):
    out.mkdir(parents=True,exist_ok=False)
    freeze=manifest();freeze['tools/evaluate_ft4_1.py']=hashlib.sha256(Path(__file__).read_bytes()).hexdigest()
    (out/'source_freeze.json').write_text(json.dumps(freeze,indent=2)+'\n')
    protocol=json.loads((ROOT/'contracts/ft/FT4_1a_Protocol_v1.json').read_text())
    suite=unittest.defaultTestLoader.loadTestsFromName('tests_ft4.test_demands')
    actual=sorted(ids(suite));expected=sorted('tests_ft4.test_demands.DemandTests.'+x for x in protocol['method_ids'])
    (out/'method_ids.json').write_text(json.dumps(actual,indent=2)+'\n')
    with (out/'controls.log').open('w') as log:
        result=unittest.TextTestRunner(stream=log,verbosity=2).run(suite)
    witnesses=[]
    if result.wasSuccessful() and actual==expected:
        from tests_ft4.test_demands import witness
        for setting in ('canonical','workflow'):
            e,l,report=witness(setting)
            (out/(setting+'-native.json')).write_text(e.checkpoint())
            (out/(setting+'-demands.json')).write_text(l.checkpoint())
            witnesses.append(dict(setting=setting,**report))
    after=manifest();after['tools/evaluate_ft4_1.py']=hashlib.sha256(Path(__file__).read_bytes()).hexdigest()
    summary=dict(passed=result.wasSuccessful() and actual==expected and len(witnesses)==2 and after==freeze,
        exact_methods=actual==expected,methods=result.testsRun,failures=len(result.failures),errors=len(result.errors),
        pressure_cells=64 if result.wasSuccessful() else None,source_unchanged=after==freeze,witnesses=witnesses,
        scope='FT4.1a admission only; parent FT4.1 remains open')
    (out/'summary.json').write_text(json.dumps(summary,indent=2)+'\n')
    print(json.dumps(summary),flush=True)
    return summary


if __name__=='__main__':sys.exit(not main(Path(sys.argv[1]).resolve())['passed'])
