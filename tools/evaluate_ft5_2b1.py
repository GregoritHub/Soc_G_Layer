"""Frozen FT5.2b1 reserve candidate-readiness gate."""
from pathlib import Path
import hashlib
import json
import sys
import unittest

ROOT = Path(__file__).resolve().parents[1]
sys.path[:0] = [str(ROOT), str(ROOT / "baseline/HLE_Rebuild_R21B")]

FT4_ROWS = (("FT4_1a","test_demands","DemandTests"),("FT4_1b1","test_requests","RequestTests"),
 ("FT4_1b2","test_controller","ControllerTests"),("FT4_2a","test_route_means","RouteMeansTests"),
 ("FT4_2b1","test_route_execution","NativeTurnTests"),("FT4_2b2a","test_orientation","OrientationTests"),
 ("FT4_2b2b1","test_route_policy","RoutePolicyTests"),("FT4_2b2b2","test_opposition","OppositionTests"),
 ("FT4_3a","test_autonomous_cycle","AutonomousCycleTests"),("FT4_3b1","test_autonomous_closure","AutonomousClosureTests"),
 ("FT4_3b2a","test_autonomous_capability","AutonomousCapabilityTests"),("FT4_3b2b","test_autonomous_reuse","AutonomousReuseTests"))


def digest(path): return hashlib.sha256(path.read_bytes()).hexdigest()


def freeze():
    result={}
    for area in ("full_theory","tests_ft4","tests_ft5","contracts/ft"):
        for path in sorted((ROOT/area).rglob("*")):
            if path.is_file() and path.suffix in (".py",".json",".sha256"):
                relative=str(path.relative_to(ROOT))
                if relative!="contracts/ft/FT5_2b1_Source_Freeze_v1.json":result[relative]=digest(path)
    for relative in ("hle_unified/operations.py","hle_unified/selection_records.py"):
        result[relative]=digest(ROOT/relative)
    result["tools/evaluate_ft5_2b1.py"]=digest(Path(__file__))
    return result


def ids(suite):
    for item in suite:
        if isinstance(item,unittest.TestSuite):yield from ids(item)
        else:yield item.id()


def predecessor_expected():
    expected=[]
    for batch,module,cls in FT4_ROWS:
        p=json.loads((ROOT/"contracts/ft"/(batch+"_Protocol_v1.json")).read_text())
        expected += ["tests_ft4."+module+"."+cls+"."+m for m in p["method_ids"]]
    for batch,module,cls in (("FT5_1","test_reserve","ReserveTests"),
                             ("FT5_2a","test_native_reserve","NativeReserveTests")):
        p=json.loads((ROOT/"contracts/ft"/(batch+"_Protocol_v1.json")).read_text())
        expected += ["tests_ft5."+module+"."+cls+"."+m for m in p["method_ids"]]
    return sorted(expected)


def main(out):
    out.mkdir(parents=True,exist_ok=False);before=freeze()
    (out/"source_freeze.json").write_text(json.dumps(before,indent=2)+"\n")
    registered=json.loads((ROOT/"contracts/ft/FT5_2b1_Source_Freeze_v1.json").read_text())
    protocol_path=ROOT/"contracts/ft/FT5_2b1_Protocol_v1.json";protocol=json.loads(protocol_path.read_text())
    ph=digest(protocol_path);rh=(ROOT/"contracts/ft/FT5_2b1_Protocol_v1.json.sha256").read_text().split()[0]
    fixtures=all(digest(ROOT/p)==h for p,h in protocol["fixtures"].items())
    suite=unittest.defaultTestLoader.loadTestsFromName("tests_ft5.test_reserve_candidates")
    actual=sorted(ids(suite));expected=sorted("tests_ft5.test_reserve_candidates.ReserveCandidateTests."+m for m in protocol["method_ids"])
    (out/"method_ids.json").write_text(json.dumps(actual,indent=2)+"\n")
    with (out/"controls.log").open("w") as log: result=unittest.TextTestRunner(stream=log,verbosity=2).run(suite)
    modules=["tests_ft5.test_native_reserve","tests_ft5.test_reserve"]+["tests_ft4."+m for _,m,_ in FT4_ROWS]
    predecessor=sorted(ids(unittest.defaultTestLoader.loadTestsFromNames(modules)))
    pred_exact=predecessor==predecessor_expected() and len(predecessor)==159
    (out/"predecessor_method_ids.json").write_text(json.dumps(predecessor,indent=2)+"\n")
    witnesses=[]
    if result.wasSuccessful() and actual==expected:
        from tests_ft5.test_reserve_candidates import candidate_case,pay_preparation
        from full_theory.reserve_candidates_audit import audit_reserve_candidates
        for setting in ("canonical","workflow"):
            e,r,d,c,_=candidate_case(setting);witnesses.append(audit_reserve_candidates(e,c.checkpoint(e)))
            pay_preparation(setting,e,c);c.step(e,r,d,work_limit=1)
            witnesses.append(audit_reserve_candidates(e,c.checkpoint(e)))
            (out/(setting+"-candidate.json")).write_text(c.checkpoint(e))
    after=freeze();passed=(result.wasSuccessful() and actual==expected and pred_exact and before==after==registered
        and fixtures and ph==rh and len(witnesses)==4 and all(w["passed"] for w in witnesses))
    summary=dict(passed=passed,methods=result.testsRun,failures=len(result.failures),errors=len(result.errors),
        exact_methods=actual==expected,expected_methods=len(expected),predecessor_exact_methods=pred_exact,
        predecessor_methods=len(predecessor),source_unchanged=before==after,registered_freeze=before==registered,
        fixtures_unchanged=fixtures,protocol_sha256=ph,protocol_hash_registered=ph==rh,witnesses=witnesses,
        scope="FT5.2b1 readiness only; completion/interruption settlement and policy election remain open")
    (out/"summary.json").write_text(json.dumps(summary,indent=2,default=str)+"\n");print(json.dumps(summary,default=str),flush=True)
    return summary


if __name__=="__main__":sys.exit(not main(Path(sys.argv[1]).resolve())["passed"])
