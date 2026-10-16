"""A2 exact setup filter/copy verification; no engine or dependency execution."""
import argparse,ast,copy,hashlib,importlib.util,io,json,pathlib,shutil,unittest
from datetime import datetime,timezone


def sha(b):return hashlib.sha256(b).hexdigest()
def blob(b):return hashlib.sha1(b'blob '+str(len(b)).encode()+b'\0'+b).hexdigest()
def module(path,name):
    spec=importlib.util.spec_from_file_location(name,path);m=importlib.util.module_from_spec(spec);spec.loader.exec_module(m);return m
def assignment(tree):
    return next(n for n in ast.walk(tree) if isinstance(n,ast.Assign) and len(n.targets)==1 and isinstance(n.targets[0],ast.Name) and n.targets[0].id=='layer_files')
def code(nodes):return compile(ast.fix_missing_locations(ast.Module(body=nodes,type_ignores=[])),'<exact-overlay-segment>','exec')


def run():
    p=argparse.ArgumentParser();p.add_argument('old_setup');p.add_argument('output')
    p.add_argument('--public',required=True);p.add_argument('--owner',required=True);p.add_argument('--stop-at',required=True);a=p.parse_args()
    root=pathlib.Path(__file__).resolve().parents[1];public=pathlib.Path(a.public);out=pathlib.Path(a.output);out.mkdir(exist_ok=False)
    prefix='contracts/ft/FT_Setup_Tool_Overlay_A2_'
    protocol=json.loads((root/(prefix+'Protocol_v1.json')).read_text());binding=json.loads((root/(prefix+'Input_Tree_v1.json')).read_text())
    freeze=json.loads((root/(prefix+'Source_Freeze_v1.json')).read_text());prior=json.loads((root/protocol['prior_source_freeze']).read_text())
    oldpath=pathlib.Path(a.old_setup);oldtext=oldpath.read_text()
    def verify():
        s=json.loads((public/'docs/FT_Run_State.json').read_text());now=datetime.now(timezone.utc)
        if s['run_id']!=a.owner or not s['active_worker'] or s['status']!='running' or now>=datetime.fromisoformat(s['lease_expires_at']) or now>=datetime.fromisoformat(a.stop_at):raise ValueError('owner/lease/deadline')
        if sha(oldpath.read_bytes())!=protocol['old_setup_sha256']:raise ValueError('old setup binding')
        for name,h in freeze.items():
            if sha((root/name).read_bytes())!=h:raise ValueError('new freeze '+name)
        for name,h in prior.items():
            source=oldpath if name=='tools/prepare_workspace.py' else root/name
            if sha(source.read_bytes())!=h:raise ValueError('prior bridge '+name)
        for name,h in binding['source_blobs'].items():
            source=oldpath if name=='tools/prepare_workspace.py' else public/name
            if blob(source.read_bytes())!=h:raise ValueError('bound source '+name)
    verify();original=ast.parse(oldtext);changed=ast.parse((root/'tools/prepare_workspace.py').read_text());check=copy.deepcopy(changed)
    predicate=assignment(check).value.generators[0].ifs[0]
    matches=[n for n in ast.walk(predicate) if isinstance(n,ast.Tuple) and any(isinstance(x,ast.Constant) and x.value==protocol['additional_exact_tool'] for x in n.elts)]
    if len(matches)!=1:raise ValueError('one explicit continuation inclusion required')
    seq=matches[0];matching=[i for i,x in enumerate(seq.elts) if isinstance(x,ast.Constant) and x.value==protocol['additional_exact_tool']]
    if len(matching)!=1:raise ValueError('duplicate continuation inclusion')
    seq.elts.pop(matching[0])
    if ast.dump(check)!=ast.dump(original):raise ValueError('nonliteral setup AST change')
    mod=module(root/'tools/prepare_workspace.py','setup_a2_under_test')
    loop=next(n for n in ast.walk(changed) if isinstance(n,ast.For) and isinstance(n.iter,ast.Name) and n.iter.id=='layer_files')
    def execute(nodes,names,output=None):
        ns=dict(ROOT=public,output=output,run=lambda *a,**k:'\n'.join(names),safe_path=mod.safe_path,shutil=shutil)
        exec(code(copy.deepcopy(nodes)),ns);return ns['layer_files']
    tests=module(root/'tests_ft7/test_setup_continuation_overlay.py','setup_a2_tests');report={}
    tests.CONTEXT.update(names=binding['public_paths'],additional=protocol['additional_exact_tool'],prior=prior,
        public=public,module=mod,report=report,select=lambda names:execute([assignment(changed)],names),
        old_select=lambda names:execute([assignment(original)],names),copy=lambda names,output:execute([assignment(changed),loop],names,output))
    suite=unittest.defaultTestLoader.loadTestsFromTestCase(tests.SetupContinuationOverlayTests);names=[t._testMethodName for t in suite]
    if sorted(names)!=sorted(protocol['methods']):raise ValueError('method identity mismatch')
    log=io.StringIO();result=unittest.TextTestRunner(stream=log,verbosity=2).run(suite)
    (out/'tests.log').write_text(log.getvalue());(out/'copy_manifest.json').write_text(json.dumps(report,indent=2)+'\n');verify()
    summary=dict(passed=result.wasSuccessful(),methods=names,errors=len(result.errors),failures=len(result.failures),
        public_paths=len(binding['public_paths']),copied=len(report.get('copied',{})),source_identities=len(freeze),
        prior_source_identities=len(prior),sole_exact_path_delta=True,additional=protocol['additional_exact_tool'],
        dependency_rebuilds=0,native_work=0,accepted_gate_replays=0,ft9_accepted=False)
    (out/'summary.json').write_text(json.dumps(summary,indent=2)+'\n');print(json.dumps(summary))
    if not result.wasSuccessful():raise SystemExit(1)


if __name__=='__main__':run()
