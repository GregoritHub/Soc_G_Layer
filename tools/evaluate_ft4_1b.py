"""Exact native-request IDs, admission regression and two saved request witnesses."""
from pathlib import Path
import hashlib
import json
import sys
import unittest
ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT),str(ROOT/'baseline/HLE_Rebuild_R21B')]
from tools.evaluate_ft4_1 import manifest,ids
from hle_unified.selection_records import dumps


def freeze():
    return manifest() | {str(p.relative_to(ROOT)):hashlib.sha256(p.read_bytes()).hexdigest()
        for p in (ROOT/'tools/evaluate_ft4_1.py',Path(__file__))}


def main(out):
    out.mkdir(parents=True,exist_ok=False);before=freeze()
    (out/'source_freeze.json').write_text(json.dumps(before,indent=2)+'\n')
    suite=unittest.defaultTestLoader.loadTestsFromNames(['tests_ft4.test_demands','tests_ft4.test_requests'])
    actual=sorted(ids(suite));expected=[]
    for p,cls in [('FT4_1a_Protocol_v1.json','tests_ft4.test_demands.DemandTests.'),
                  ('FT4_1b1_Protocol_v1.json','tests_ft4.test_requests.RequestTests.')]:
        expected += [cls+x for x in json.loads((ROOT/'contracts/ft'/p).read_text())['method_ids']]
    (out/'method_ids.json').write_text(json.dumps(actual,indent=2)+'\n')
    with (out/'controls.log').open('w') as log:
        result=unittest.TextTestRunner(stream=log,verbosity=2).run(suite)
    witnesses=[]
    if result.wasSuccessful() and actual==sorted(expected):
        from tests_ft4.test_requests import witness
        for setting in ('canonical','workflow'):
            e,l,v,row,report=witness(setting)
            (out/(setting+'-native.json')).write_text(e.checkpoint())
            (out/(setting+'-demands.json')).write_text(l.checkpoint())
            (out/(setting+'-view.json')).write_text(v.bytes())
            (out/(setting+'-request.json')).write_text(dumps(row))
            witnesses.append(dict(setting=setting,**report))
    summary=dict(passed=result.wasSuccessful() and actual==sorted(expected) and before==freeze() and len(witnesses)==2,
        exact_methods=actual==sorted(expected),methods=result.testsRun,failures=len(result.failures),errors=len(result.errors),
        source_unchanged=before==freeze(),witnesses=witnesses,scope='FT4.1b1 requests only; fulfillment and integration remain open')
    (out/'summary.json').write_text(json.dumps(summary,indent=2)+'\n');print(json.dumps(summary),flush=True)
    return summary


if __name__=='__main__':sys.exit(not main(Path(sys.argv[1]).resolve())['passed'])
