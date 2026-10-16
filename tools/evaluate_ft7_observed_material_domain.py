"""One serial saved-only A4 gate; never restores or invokes a paid engine."""
import argparse, gc, gzip, hashlib, json, pathlib, unittest
from dataclasses import replace
from datetime import datetime, timezone
from hle_unified import codec
from hle_unified.compact import unseal
from hle_unified.operations import NativeAccess
from hle_unified.particulars import ParticipantView
from hle_unified.selection_records import dumps, loads
from full_theory.paid_window_comparison import PaidCanonicalWindowEngine, PaidWorkflowWindowEngine
from full_theory.observed_material_domain import observed_material_domain, material_vocabulary
from full_theory.observed_material_domain_audit import audit_observed_material_domain


def sha(value):
    return hashlib.sha256(value.encode() if isinstance(value,str) else value).hexdigest()


def run():
    p=argparse.ArgumentParser(); p.add_argument('inputs'); p.add_argument('output')
    p.add_argument('--public',required=True); p.add_argument('--owner',required=True); p.add_argument('--stop-at',required=True)
    a=p.parse_args(); root=pathlib.Path(__file__).resolve().parents[1]; out=pathlib.Path(a.output); out.mkdir(exist_ok=False)
    protocol=json.loads((root/'contracts/ft/FT7_Observed_Reference_A4_Protocol_v1.json').read_text())
    freeze=json.loads((root/'contracts/ft/FT7_Observed_Reference_A4_Source_Freeze_v1.json').read_text())
    rows=[]; probes=[]; controls=[]; stage='initial'
    def note(kind,**kw):
        with (out/'events.jsonl').open('a') as f:
            f.write(json.dumps(dict(at=datetime.now(timezone.utc).isoformat(),stage=stage,kind=kind,**kw))+'\n'); f.flush()
    def verify():
        for name,h in freeze.items():
            if sha((root/name).read_bytes())!=h: raise ValueError('source identity changed: '+name)
    def guard():
        now=datetime.now(timezone.utc); state=json.loads((pathlib.Path(a.public)/'docs/FT_Run_State.json').read_text())
        if state['run_id']!=a.owner or not state['active_worker'] or state['status']!='running' or now>=datetime.fromisoformat(state['lease_expires_at']) or now>=datetime.fromisoformat(a.stop_at):
            raise SystemExit('owner/lease/deadline guard')
    def rejected(name,call):
        try: call()
        except ValueError: probes.append(dict(setting=setting,name=name,rejected=True))
        else: raise ValueError('accepted forgery: '+name)
    try:
        verify();guard();note('start',owner=a.owner)
        for entry in protocol['inputs']:
            setting=entry['setting']; label=entry['label']; stage=setting+'/'+label; guard()
            raw=(pathlib.Path(a.inputs)/entry['file']).read_bytes()
            if sha(raw)!=entry['sha256']: raise ValueError('raw input hash')
            tag,native,refresh=codec.loads(gzip.decompress(raw).decode()); c=loads(refresh)
            if tag!=label or sha(native)!=entry['native_sha256'] or sha(refresh)!=entry['refresh_sha256']: raise ValueError('decoded pair identity')
            typ=PaidCanonicalWindowEngine if setting=='canonical' else PaidWorkflowWindowEngine
            data=unseal(native,typ.SCHEMA); access=NativeAccess.restore(data['access']); view=access.view(c['actor'])
            before=access.checkpoint(); view_before=view.bytes(); guard()
            text=observed_material_domain(view,refresh,setting)
            result=audit_observed_material_domain(native,view,refresh,setting,text); d=loads(text)
            if dumps(d)!=text or access.checkpoint()!=before or view.bytes()!=view_before: raise ValueError('roundtrip or native access mutation')
            filename=setting+'-'+label+'.json.gz'
            with gzip.open(out/filename,'wt') as f: f.write(text)
            with gzip.open(out/filename,'rt') as f:
                if f.read()!=text: raise ValueError('saved projection roundtrip')
            with gzip.open(out/(setting+'-'+label+'.view.gz'),'wt') as f: f.write(view_before)
            if c['phase']=='complete':
                stock=d['pools']['stock']; refs=[r['value'] for r in stock[1:]]
                supported={s['observed_ref'] for r in stock[1:] for s in r['supports']}
                expected=({r for r in supported if not any(x.identity==r.identity and x.revision>r.revision for x in supported)}
                          if setting=='canonical' else supported)
                if set(refs)!=expected or len(refs)!=len(expected): raise ValueError('revision policy')
                if any(not r['supports'] for r in stock[1:]) or stock[0]!=dict(value=None,supports=()): raise ValueError('provenance or None')
            row=dict(setting=setting,record=label,file=filename,sha256=sha((out/filename).read_bytes()),
                     projection_sha256=sha(text),input_sha256=entry['sha256'],unchanged=True,revision_policy_exact=True,**result)
            rows.append(row);(out/'progress.json').write_text(json.dumps(rows,indent=2)+'\n');note('record_passed',record=label)
            print(json.dumps(row),flush=True)
            if label=='complete':
                for name,key,value in (('refresh_actor','actor','forged'),('refresh_extra','extra',True)):
                    bad=loads(refresh);bad[key]=value
                    rejected(name,lambda bad=bad:observed_material_domain(view,dumps(bad),setting))
                rejected('native_pair',lambda:audit_observed_material_domain(native+' ',view,refresh,setting,text))
                reversed_view=ParticipantView(replace(view.snapshot,particulars=tuple(reversed(view.snapshot.particulars)),receipts=tuple(reversed(view.snapshot.receipts))))
                rejected('view_pair',lambda:observed_material_domain(reversed_view,refresh,setting))
                rejected('unknown_setting',lambda:observed_material_domain(view,refresh,'unknown'))
                for name in ('output_authority','output_reference','output_evidence','output_missing_observation','output_extra'):
                    bad=loads(text)
                    if name=='output_authority': bad['execution_authorized']=True
                    elif name=='output_reference': bad['pools']['stock'][1]['value']=replace(bad['pools']['stock'][1]['value'],revision=999)
                    elif name=='output_evidence': bad['pools']['stock'][1]['supports']=()
                    elif name=='output_missing_observation': bad['observations']=bad['observations'][1:]
                    else: bad['extra']=True
                    rejected(name,lambda bad=bad:audit_observed_material_domain(native,view,refresh,setting,dumps(bad)))
                original_core=material_vocabulary(view,c,setting)
                if dumps(material_vocabulary(reversed_view,c,setting))!=dumps(original_core): raise ValueError('grammar order dependence')
                controls.append(dict(setting=setting,name='permutation',passed=True))
                direct=next(s['observed_ref'] for row in d['pools']['stock'][1:] for s in row['supports'] if s['kind']=='direct')
                details=tuple(replace(x,value=True) if x.source==direct and x.address.key=='quantity' else x for x in view.snapshot.particulars)
                boolean_view=ParticipantView(replace(view.snapshot,particulars=details))
                _,bp=material_vocabulary(boolean_view,c,setting)
                if any(s['kind']=='direct' and s['observed_ref']==direct for row in bp['stock'][1:] for s in row['supports']): raise ValueError('bool accepted as quantity')
                controls.append(dict(setting=setting,name='bool_quantity',passed=True))
                removed=d['observations'][0]['receipt']; missing=ParticipantView(replace(view.snapshot,receipts=tuple(r for r in view.snapshot.receipts if r.ref!=removed)))
                try: material_vocabulary(missing,c,setting)
                except ValueError: controls.append(dict(setting=setting,name='removed_read',passed=True))
                else: raise ValueError('missing read accepted')
                source=d['observations'][0]['source']; changed=replace(d['observations'][0]['target'],revision=999)
                changed_view=ParticipantView(replace(view.snapshot,particulars=tuple(replace(x,value=changed) if x.source==source and x.address.key=='target' else x for x in view.snapshot.particulars)))
                altered=material_vocabulary(changed_view,c,setting)
                if dumps(altered)==dumps(original_core) or changed not in [r['value'] for r in altered[1]['stock']]: raise ValueError('target perturbation ignored')
                controls.append(dict(setting=setting,name='changed_target',passed=True))
                (out/'probes.json').write_text(json.dumps(probes,indent=2)+'\n')
                (out/'controls.json').write_text(json.dumps(controls,indent=2)+'\n')
            del raw,native,refresh,c,data,access,view,before,view_before,text,d; gc.collect()
        stage='methods';guard();note('methods_start')
        import tests_ft7.test_observed_material_domain as tests
        tests.RESULTS=rows;tests.PROBES=probes;tests.CONTROLS=controls
        suite=unittest.defaultTestLoader.loadTestsFromModule(tests)
        identities=sorted(t.id().split('.')[-1] for group in suite for t in group)
        if identities!=sorted(protocol['gate']['methods']): raise ValueError('actual method identities')
        with (out/'tests.log').open('w') as f: result=unittest.TextTestRunner(stream=f,verbosity=2).run(suite)
        note('methods_finished',count=result.testsRun,passed=result.wasSuccessful())
        if not result.wasSuccessful() or result.testsRun!=6: raise ValueError('six exact methods')
        verify();guard();summary=dict(passed=True,methods=identities,records=rows,probes=probes,controls=controls,
            source_identities=len(freeze),prior_identities=461,native_work=0,comparison_paid=False,parent_accepted=False)
        (out/'summary.json').write_text(json.dumps(summary,indent=2)+'\n');note('closed_pass');print('A4 PASSED',flush=True)
    except BaseException as error:
        note('closed_nonpass',error_type=type(error).__name__,message=str(error));raise


if __name__=='__main__': run()
