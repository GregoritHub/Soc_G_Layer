"""A2 identity hardening: exact old records, no paid commands or test-body replay."""
import argparse,ast,copy,gc,gzip,hashlib,json,pathlib
from datetime import datetime,timezone
from hle_unified import codec
from hle_unified.selection_records import loads,dumps
from hle_unified.compact import unseal,ValuePool
from hle_unified.material import OperationStore
from hle_unified.operations import NativeAccess
from full_theory.paid_window_comparison import PaidCanonicalWindowEngine,PaidWorkflowWindowEngine
from full_theory.owned_repair_practice import OwnedRepairPractice
from full_theory.owned_repair_practice_audit import audit_owned_repair_practice,baseline


def sha(b):return hashlib.sha256(b).hexdigest()


class SavedNative:
    """Decode immutable records only; deliberately exposes no native work API."""
    def __init__(self,text,typ):
        self.SCHEMA=typ.SCHEMA;self._registry=typ._registry;self._text=text
        data=unseal(text,self.SCHEMA);self.world=OperationStore.restore(data['world'])
        self.access=NativeAccess.restore(data['access']);self._pool=ValuePool(self._registry())
        self._pool.load_nodes(data['nodes']);self._events=tuple(self._pool.import_token(t) for t in data['commands'])
        self._locks={};self._before=(self.world.checkpoint(),self.access.checkpoint())
    def checkpoint(self):return self._text
    def participant_view(self,actor):return self.access.view(actor)
    def unchanged(self):return self._before==(self.world.checkpoint(),self.access.checkpoint())


def run():
    p=argparse.ArgumentParser();p.add_argument('inputs');p.add_argument('records');p.add_argument('operations');p.add_argument('old_source');p.add_argument('output')
    p.add_argument('--owner',required=True);p.add_argument('--public',required=True);p.add_argument('--stop-at',required=True);a=p.parse_args()
    root=pathlib.Path(__file__).resolve().parents[1];out=pathlib.Path(a.output);out.mkdir(exist_ok=False)
    records=pathlib.Path(a.records);operations=pathlib.Path(a.operations);oldsource=pathlib.Path(a.old_source)
    freeze=json.loads((root/'contracts/ft/FT7_Skill_Practice_A2_Identity_Source_Freeze_v1.json').read_text())
    binding=json.loads((root/'contracts/ft/FT7_Skill_Practice_A2_Closed_Binding_v1.json').read_text())
    protocol=json.loads((root/'contracts/ft/FT7_Skill_Practice_A2_Protocol_v1.json').read_text())
    amendment=json.loads((root/'contracts/ft/FT7_Skill_Practice_A2_Identity_Amendment_v1.json').read_text())
    def verify():
        for n,h in freeze.items():
            if sha((root/n).read_bytes())!=h:raise ValueError('saved freeze: '+n)
        for key,folder in (('records',records),('operations',operations),('old_source',oldsource)):
            files={str(x.relative_to(folder)):sha(x.read_bytes()) for x in folder.rglob('*') if x.is_file()}
            if files!=binding[key]:raise ValueError('closed input changed: '+key)
    def guard():
        s=json.loads((pathlib.Path(a.public)/'docs/FT_Run_State.json').read_text());now=datetime.now(timezone.utc)
        if s['run_id']!=a.owner or not s['active_worker'] or s['status']!='running' or now>=datetime.fromisoformat(s['lease_expires_at']) or now>=datetime.fromisoformat(a.stop_at):
            raise SystemExit('saved reader owner/lease/deadline guard')
    verify();guard()
    # Removing only the two declared identity checks must yield the original ASTs.
    pairs=repr(amendment['pairs'])
    specs=(('full_theory/owned_repair_practice.py','__init__',
        "if digest(intake) != "+pairs+".get(digest(native)):\n    raise ValueError('exact accepted intake identity')"),
        ('full_theory/owned_repair_practice_audit.py','audit_owned_repair_practice',
        "require(digest(intake) == "+pairs+".get(digest(original)), 'exact accepted intake identity')"))
    bridge=[]
    for name,func,check in specs:
        original=ast.parse((oldsource/name).read_text());changed=ast.parse((root/name).read_text());needle=ast.dump(ast.parse(check).body[0])
        matches=[]
        for node in ast.walk(changed):
            if isinstance(node,ast.FunctionDef) and node.name==func:
                for j,statement in enumerate(node.body):
                    if ast.dump(statement)==needle:matches.append((node,j))
        if len(matches)!=1:raise ValueError('exact sole added guard: '+name)
        node,j=matches[0];node.body.pop(j)
        if ast.dump(original)!=ast.dump(changed):raise ValueError('other governed code changed: '+name)
        bridge.append(name)
    original_freeze=json.loads((root/'contracts/ft/FT7_Skill_Practice_A2_Source_Freeze_v1.json').read_text())
    for name,h in original_freeze.items():
        folder=oldsource if name in bridge else root
        if sha((folder/name).read_bytes())!=h:raise ValueError('original identity bridge: '+name)
    original_summary=json.loads((records/'summary.json').read_text())
    if not original_summary['passed'] or original_summary['methods']!=6 or len(original_summary['records'])!=14:raise ValueError('original gate incomplete')
    events=[json.loads(x) for x in (operations/'events.jsonl').read_text().splitlines()]
    if events[-1]['kind']!='closed_pass' or sum(x['kind']=='methods_start' for x in events)!=1:raise ValueError('original closure')
    results=[];rejections=[]
    for setting,typ in (('canonical',PaidCanonicalWindowEngine),('workflow',PaidWorkflowWindowEngine)):
        entry=protocol['inputs'][setting];raw=(pathlib.Path(a.inputs)/entry['file']).read_bytes()
        if sha(raw)!=entry['sha256']:raise ValueError('original accepted intake')
        _,original,intake=codec.loads(gzip.decompress(raw).decode())
        for row in original_summary['records']:
            if row['setting']!=setting:continue
            guard();raw=(records/row['file']).read_bytes()
            if sha(raw)!=row['sha256']:raise ValueError('original saved record hash')
            name,native,text=codec.loads(gzip.decompress(raw).decode())
            print('auditing '+setting+'/'+name,flush=True);engine=SavedNative(native,typ)
            result=audit_owned_repair_practice(engine,original,intake,text)
            if any(result[k]!=row[k] for k in result):raise ValueError('original audit result differs')
            if dumps(loads(text))!=text:raise ValueError('typed adapter readback')
            if name=='before':
                if OwnedRepairPractice(engine,intake).checkpoint(engine)!=text:raise ValueError('corrected constructor changed valid before record')
                for field,value in (('actor','forged actor'),('context',None),('unregistered_extra',True)):
                    bad=loads(intake);bad[field]=value;bad=dumps(bad)
                    for api in ('constructor','auditor'):
                        try:
                            if api=='constructor':OwnedRepairPractice(engine,bad)
                            else:audit_owned_repair_practice(engine,original,bad,text)
                        except ValueError as error:
                            if 'exact accepted intake identity' not in str(error):raise
                            rejections.append(dict(setting=setting,field=field,api=api,error=str(error)))
                        else:raise ValueError('pairing forgery accepted')
            if engine.checkpoint()!=native or not engine.unchanged():raise ValueError('saved reader changed native')
            result=dict(setting=setting,record=name,sha256=row['sha256'],native_unchanged=True,**result)
            results.append(result);(out/'progress.json').write_text(json.dumps(results,indent=2)+'\n')
            (out/'rejections.json').write_text(json.dumps(rejections,indent=2)+'\n');print(json.dumps(result),flush=True)
            del engine;baseline.cache_clear();gc.collect()
    verify()
    if len(results)!=14 or len(rejections)!=12:raise ValueError('exact saved panel')
    summary=dict(passed=True,records=results,pairing_rejections=rejections,original_methods_preserved=6,original_negative_probes_preserved=10,
        changed_files=bridge,original_source_identities=len(original_freeze),source_identities=len(freeze),prior_identities=427,
        native_work_calls=0,engine_restore_calls=0,test_body_replays=0,parent_accepted=False)
    (out/'summary.json').write_text(json.dumps(summary,indent=2)+'\n');print(json.dumps(summary),flush=True)


if __name__=='__main__':run()
