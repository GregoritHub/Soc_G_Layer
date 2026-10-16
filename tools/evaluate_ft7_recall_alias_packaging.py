"""A11P exact alias and actual setup selection check; no accepted gate replay."""
import argparse,ast,hashlib,json,pathlib
from datetime import datetime,timezone

def main():
    p=argparse.ArgumentParser();p.add_argument('output');p.add_argument('--public',required=True);p.add_argument('--owner',required=True);a=p.parse_args()
    root=pathlib.Path(__file__).resolve().parents[1];out=pathlib.Path(a.output);out.mkdir(exist_ok=False)
    prefix='contracts/ft/FT7_Preserved_Recall_Floor_A11P_'
    protocol=json.loads((root/(prefix+'Protocol_v1.json')).read_text());freeze=json.loads((root/(prefix+'Source_Freeze_v1.json')).read_text());prior=json.loads((root/protocol['prior_source_freeze']).read_text())
    state=json.loads((pathlib.Path(a.public)/'docs/FT_Run_State.json').read_text())
    assert state['run_id']==a.owner and state['active_worker'] and state['status']=='running' and datetime.now(timezone.utc)<datetime.fromisoformat(state['lease_expires_at'])
    for mapping in (freeze,prior):
        for n,h in mapping.items():assert hashlib.sha256((root/n).read_bytes()).hexdigest()==h,n
    source,alias=protocol['source'],protocol['alias'];assert (root/source).read_bytes()==(root/alias).read_bytes()
    tree=ast.parse((root/'tools/prepare_workspace.py').read_text())
    nodes=[n for n in ast.walk(tree) if isinstance(n,ast.Assign) and any(isinstance(t,ast.Name) and t.id=='layer_files' for t in n.targets)];assert len(nodes)==1
    scope=dict(ROOT=root,run=lambda *args,**kwargs:'\n'.join((source,alias)))
    exec(compile(ast.fix_missing_locations(ast.Module(body=nodes,type_ignores=[])),'<actual-setup-filter>','exec'),scope)
    assert alias in scope['layer_files'] and source not in scope['layer_files']
    summary=dict(passed=True,checks=protocol['checks'],source_identities=len(freeze),prior_identities=len(prior),selected=scope['layer_files'],alias_sha256=hashlib.sha256((root/alias).read_bytes()).hexdigest(),accepted_gate_replays=0,native_work=0,setup_source_changed=False,full_preparation_claim=False)
    (out/'summary.json').write_text(json.dumps(summary,indent=2)+'\n');print(json.dumps(summary))

if __name__=='__main__':main()
