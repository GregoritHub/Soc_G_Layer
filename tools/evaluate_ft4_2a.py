"""Frozen FT4.2a structural means gate with independent reconstruction."""
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
    for path in (ROOT/'tools/evaluate_ft4_1.py',ROOT/'tools/evaluate_ft4_1b.py',
                 ROOT/'tools/evaluate_ft4_1c.py',Path(__file__)):
        result[str(path.relative_to(ROOT))]=hashlib.sha256(path.read_bytes()).hexdigest()
    return result


def main(out):
    out.mkdir(parents=True,exist_ok=False)
    before=freeze();(out/'source_freeze.json').write_text(json.dumps(before,indent=2)+'\n')
    names=['tests_ft4.test_demands','tests_ft4.test_requests','tests_ft4.test_controller','tests_ft4.test_route_means']
    suite=unittest.defaultTestLoader.loadTestsFromNames(names)
    actual=sorted(ids(suite));expected=[]
    rows=(("FT4_1a_Protocol_v1.json","tests_ft4.test_demands.DemandTests."),
          ("FT4_1b1_Protocol_v1.json","tests_ft4.test_requests.RequestTests."),
          ("FT4_1b2_Protocol_v1.json","tests_ft4.test_controller.ControllerTests."),
          ("FT4_2a_Protocol_v1.json","tests_ft4.test_route_means.RouteMeansTests."))
    for filename,prefix in rows:
        expected.extend(prefix+x for x in json.loads((ROOT/'contracts/ft'/filename).read_text())['method_ids'])
    (out/'method_ids.json').write_text(json.dumps(actual,indent=2)+'\n')
    with (out/'controls.log').open('w') as log:
        result=unittest.TextTestRunner(stream=log,verbosity=2).run(suite)
    witnesses=[]
    if result.wasSuccessful() and actual==sorted(expected):
        from tests_ft4.test_controller import prepared
        from full_theory.route_means import inventory_route_means
        from full_theory.route_means_audit import audit_route_means
        from hle_unified.selection_records import dumps
        for setting in ('canonical','workflow'):
            engine,_,request,_=prepared(setting);row=inventory_route_means(engine,request)
            report=audit_route_means(engine.world.journal(),row)
            (out/(setting+'-native.json')).write_text(engine.checkpoint())
            (out/(setting+'-means.json')).write_text(dumps(row)+'\n')
            witnesses.append(report)
        from hle.development_structure import lap,portage
        from hle.model_a import TYPES,element_at
        grid=[dict(tim=tim,seat=seat,active=element_at(tim,seat),ordinary=lap(seat),
                   n=portage(seat,'n'),cp=portage(seat,'cp'))
              for tim in TYPES for seat in range(1,9)]
        (out/'geometry_grid.json').write_text(json.dumps(grid,indent=2)+'\n')
    after=freeze()
    summary=dict(passed=result.wasSuccessful() and actual==sorted(expected) and before==after
        and len(witnesses)==2 and len(grid)==128,exact_methods=actual==sorted(expected),
        methods=result.testsRun,failures=len(result.failures),errors=len(result.errors),
        geometry_cells=len(grid) if 'grid' in locals() else 0,source_unchanged=before==after,
        witnesses=witnesses,scope='FT4.2a structural means only; paid choice and launch remain FT4.2b')
    (out/'summary.json').write_text(json.dumps(summary,indent=2)+'\n')
    print(json.dumps(summary),flush=True);return summary


if __name__=='__main__':sys.exit(not main(Path(sys.argv[1]).resolve())['passed'])
