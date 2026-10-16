"""Frozen setup segment audit: public source bytes only, no dependency/native work."""
import argparse,ast,copy,hashlib,importlib.util,io,json,pathlib,shutil,unittest
from datetime import datetime,timezone


def sha(data):return hashlib.sha256(data).hexdigest()
def blob(data):return hashlib.sha1(b'blob '+str(len(data)).encode()+b'\0'+data).hexdigest()
def module(path,name):
    spec=importlib.util.spec_from_file_location(name,path);value=importlib.util.module_from_spec(spec)
    spec.loader.exec_module(value);return value
def assignment(tree):
    return next(n for n in ast.walk(tree) if isinstance(n,ast.Assign) and
                len(n.targets)==1 and isinstance(n.targets[0],ast.Name) and n.targets[0].id=='layer_files')
def code(nodes):return compile(ast.fix_missing_locations(ast.Module(body=nodes,type_ignores=[])),'<exact-setup-segment>','exec')


def run():
    p=argparse.ArgumentParser();p.add_argument('old_setup');p.add_argument('output')
    p.add_argument('--public',required=True);p.add_argument('--owner',required=True);p.add_argument('--stop-at',required=True);a=p.parse_args()
    root=pathlib.Path(__file__).resolve().parents[1];public=pathlib.Path(a.public);out=pathlib.Path(a.output);out.mkdir(exist_ok=False)
    prefix='contracts/ft/FT_Setup_Tool_Overlay_A1_'
    protocol=json.loads((root/(prefix+'Protocol_v1.json')).read_text())
    binding=json.loads((root/(prefix+'Input_Tree_v1.json')).read_text())
    freeze=json.loads((root/(prefix+'Source_Freeze_v1.json')).read_text())
    prior=json.loads((root/protocol['prior_source_freeze']).read_text())
    oldpath=pathlib.Path(a.old_setup);oldtext=oldpath.read_text()
    def guard():
        state=json.loads((public/'docs/FT_Run_State.json').read_text());now=datetime.now(timezone.utc)
        if state['run_id']!=a.owner or not state['active_worker'] or state['status']!='running' or now>=datetime.fromisoformat(state['lease_expires_at']) or now>=datetime.fromisoformat(a.stop_at):
            raise ValueError('owner/lease/deadline')
    def verify():
        guard()
        for name,h in freeze.items():
            if sha((root/name).read_bytes())!=h:raise ValueError('freeze '+name)
        for name,h in prior.items():
            source=oldpath if name=='tools/prepare_workspace.py' else root/name
            if sha(source.read_bytes())!=h:raise ValueError('prior source bridge '+name)
        for name,h in binding['blobs'].items():
            if name=='docs/FT_Run_State.json':continue
            source=oldpath if name=='tools/prepare_workspace.py' else public/name
            if blob(source.read_bytes())!=h:raise ValueError('public source '+name)
    verify()
    original=ast.parse(oldtext);changed=ast.parse((root/'tools/prepare_workspace.py').read_text())
    check=copy.deepcopy(changed);select_node=assignment(check);predicate=select_node.value.generators[0].ifs[0]
    if not isinstance(predicate,ast.BoolOp) or not isinstance(predicate.op,ast.Or) or len(predicate.values)!=3:
        raise ValueError('sole filter OR term')
    extra=predicate.values.pop()
    expected=ast.parse('name in '+repr(tuple(protocol['additional_exact_tools'])),mode='eval').body
    if ast.dump(extra)!=ast.dump(expected) or ast.dump(check)!=ast.dump(original):raise ValueError('setup AST delta')
    mod=module(root/'tools/prepare_workspace.py','setup_under_test')
    new_assignment=assignment(changed);old_assignment=assignment(original)
    copy_loop=next(n for n in ast.walk(changed) if isinstance(n,ast.For) and isinstance(n.iter,ast.Name) and n.iter.id=='layer_files')
    def execute(nodes,names,output=None):
        namespace=dict(ROOT=public,output=output,run=lambda *args,**kwargs:'\n'.join(names),safe_path=mod.safe_path,shutil=shutil)
        exec(code(copy.deepcopy(nodes)),namespace);return namespace['layer_files']
    tests=module(root/'tests_ft7/test_setup_tool_overlay.py','overlay_tests');report={}
    tests.CONTEXT.update(names=list(binding['blobs']),additional=protocol['additional_exact_tools'],prior_freeze=prior,
        public=public,module=mod,report=report,select=lambda names:execute([new_assignment],names),
        old_select=lambda names:execute([old_assignment],names),copy=lambda names,output:execute([new_assignment,copy_loop],names,output))
    suite=unittest.defaultTestLoader.loadTestsFromTestCase(tests.SetupToolOverlayTests)
    method_names=[test._testMethodName for test in suite]
    if sorted(method_names)!=sorted(protocol['gate']['methods']):raise ValueError('exact method identities')
    log=io.StringIO();result=unittest.TextTestRunner(stream=log,verbosity=2).run(suite)
    (out/'tests.log').write_text(log.getvalue());(out/'copy_manifest.json').write_text(json.dumps(report,indent=2)+'\n')
    verify()
    summary=dict(passed=result.wasSuccessful(),methods=method_names,failures=len(result.failures),errors=len(result.errors),
        pinned_public_blobs=len(binding['blobs']),overlay_files=len(report.get('copied',{})),additional_tools=protocol['additional_exact_tools'],
        prior_source_identities=len(prior),source_identities=len(freeze),sole_filter_ast_delta=True,
        dependency_rebuilds=0,native_work=0,accepted_test_replays=0,ft9_accepted=False)
    (out/'summary.json').write_text(json.dumps(summary,indent=2)+'\n');print(json.dumps(summary))
    if not result.wasSuccessful():raise SystemExit(1)


if __name__=='__main__':run()
