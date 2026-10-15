"""Resumable exact saved-binding stage; never runs paid engine work."""
from pathlib import Path
import gzip,hashlib,json,re,sys,unittest
ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT),str(ROOT/'baseline/HLE_Rebuild_R21B')]
def digest(p):return hashlib.sha256(p.read_bytes()).hexdigest()
def freeze():
    names=set(json.loads((ROOT/'contracts/ft/FT7_1b2b3a_Source_Freeze_v1.json').read_text()))
    names.update(('contracts/ft/FT7_1b2b3a_Source_Freeze_v1.json','contracts/ft/FT7_1b2b3a_Resume_Amendment_v1.json','contracts/ft/FT7_1b2b3a_Resume_Amendment_v1.sha256','tools/audit_ft7_1b2b3a_saved.py'))
    return {n:digest(ROOT/n) for n in sorted(names)}
def check():
    value=freeze();registered=json.loads((ROOT/'contracts/ft/FT7_1b2b3a_Saved_Audit_Source_Freeze_v1.json').read_text())
    old=json.loads((ROOT/'contracts/ft/FT7_1b2b3a_Source_Freeze_v1.json').read_text())
    if value!=registered or any(value[n]!=h for n,h in old.items()):raise ValueError('original or saved-reader source differs')
    return value

def inputs(source,attempt):
    from tools.audit_ft7_1b2b2b_saved import predecessor_ids,expected_methods
    from tools.evaluate_ft6_3b import ids
    p=json.loads((ROOT/'contracts/ft/FT7_1b2b3a_Protocol_v1.json').read_text());expected=sorted('tests_ft7.test_social_feedback_binding.SocialFeedbackBindingTests.'+m for m in p['registered_tests'])
    actual=sorted(ids(unittest.defaultTestLoader.loadTestsFromName('tests_ft7.test_social_feedback_binding')))
    log=(attempt/'controls.log').read_text();recorded=json.loads((attempt/'method_ids.json').read_text());passed=sorted(re.findall(r'^\w+ \((tests_ft7\.test_social_feedback_binding\.SocialFeedbackBindingTests\.\w+)\) \.\.\. ok$',log,re.M))
    if actual!=expected or recorded!=expected or passed!=expected or not re.search(r'Ran 8 tests in [\d.]+s\n\nOK\n?$',log):raise ValueError('original actual 8-method pass differs')
    old,split=expected_methods();current=sorted(ids(unittest.defaultTestLoader.loadTestsFromName('tests_ft7.test_social_reuse')))
    if old!=current or len(predecessor_ids()+current)!=352:raise ValueError('352 exact predecessor identities differ')
    expected_keys={s+'/'+m for s in ('canonical','workflow') for m in split['scenarios_per_setting']}|{s+'/'+m+'/restart-'+q for s in ('canonical','workflow') for m in split['restarts_per_setting'] for q in ('final','partial')}
    index=json.loads((source/'record_index.json').read_text());summary=json.loads((source/'summary.json').read_text())
    if len(index)!=24 or {x['key'] for x in index}!=expected_keys or not summary['passed'] or summary['aggregate_checksum_verified']['payload_sha256']!=p['input']['aggregate_payload_sha256']:raise ValueError('exact accepted input domain differs')
    return index,p

def unit(source,attempt,out,number):
    from hle_unified import codec
    from hle_unified.selection_execution import SelectionEngine
    from hle_unified.workflow_selection_execution import WorkflowFinalSelectionEngine
    from full_theory.social_feedback_binding import SocialPostUseBinding
    from full_theory.social_feedback_binding_audit import audit_social_feedback_binding
    from tools.evaluate_ft7_1b2b2b import audit_saved
    before=check();index,p=inputs(source,attempt);item=index[number-1]
    if not 1<=number<=24 or digest(source/item['file'])!=item['sha256']:raise ValueError('source identity differs')
    folder=out/'units'/str(number).zfill(2);folder.mkdir(parents=True,exist_ok=True);record=folder/'record.json.gz';receipt=folder/'receipt.json'
    if receipt.exists():
        r=json.loads(receipt.read_text())
        if r['key']!=item['key'] or r['source_sha256']!=item['sha256'] or r['record_sha256']!=digest(record) or r['source_freeze']!=before or not r['passed']:raise ValueError('completed unit receipt differs')
        with gzip.open(record,'rt',encoding='ascii') as f:saved=codec.loads(f.read())
        if saved[0]!=item['key'] or saved[1]!=item['sha256'] or codec.loads(codec.dumps(saved))!=saved:raise ValueError('completed unit roundtrip differs')
        check();print(item['key']+': verified completed unit',flush=True);return
    with gzip.open(source/item['file'],'rt',encoding='ascii') as f:key,txs,wrapper,native=codec.loads(f.read())
    if key!=item['key']:raise ValueError('decoded source key differs')
    source_audit=audit_saved(key,txs,wrapper,native)
    engine=(SelectionEngine if key.startswith('canonical/') else WorkflowFinalSelectionEngine).restore(native)
    binding=SocialPostUseBinding(engine,wrapper);text=binding.checkpoint();row=(key,item['sha256'],hashlib.sha256(wrapper.encode()).hexdigest(),text)
    original_index=json.loads((attempt/'record_index.json').read_text())
    previous=next((x for x in original_index if x['key']==key),None)
    if previous:
        path=attempt/previous['file']
        if digest(path)!=previous['sha256']:raise ValueError('surviving original binding hash differs')
        with gzip.open(path,'rt',encoding='ascii') as f:old=codec.loads(f.read())
        if old!=row:raise ValueError('surviving binding differs from unchanged source reconstruction')
    with gzip.open(record,'wt',encoding='ascii') as f:f.write(codec.dumps(row)+'\n')
    with gzip.open(record,'rt',encoding='ascii') as f:decoded=codec.loads(f.read())
    if decoded!=row:raise ValueError('saved binding exact readback differs')
    audit=audit_social_feedback_binding(engine,wrapper,decoded[3])
    if engine.checkpoint()!=native or before!=check():raise ValueError('native or frozen source changed')
    result=dict(key=key,passed=source_audit['passed'] and audit['passed'],source=source_audit,binding=audit,source_file=item['file'],source_sha256=item['sha256'],record_sha256=digest(record),source_freeze=before,original_surviving_binding_exact=previous is not None,raw_roundtrip_exact=True,native_unchanged=True)
    receipt.write_text(json.dumps(result,indent=2)+'\n');print(key+': '+str(result['passed']),flush=True)
    if not result['passed']:raise SystemExit(1)

def finalize(source,attempt,out):
    from hle_unified import codec
    before=check();index,p=inputs(source,attempt);audits={};records=[]
    for number,item in enumerate(index,1):
        folder=out/'units'/str(number).zfill(2);path=folder/'record.json.gz';r=json.loads((folder/'receipt.json').read_text())
        if r['key']!=item['key'] or r['source_sha256']!=digest(source/item['file']) or r['source_sha256']!=item['sha256'] or r['record_sha256']!=digest(path) or r['source_freeze']!=before or not r['passed'] or not r['raw_roundtrip_exact'] or not r['native_unchanged']:raise ValueError('full saved unit identity/audit receipt differs')
        with gzip.open(path,'rt',encoding='ascii') as f:row=codec.loads(f.read())
        if row[0]!=item['key'] or row[1]!=item['sha256'] or codec.loads(codec.dumps(row))!=row:raise ValueError('full typed readback differs')
        audits[item['key']]=dict(passed=True,source=r['source'],binding=r['binding']);records.append(dict(key=item['key'],file=str(path.relative_to(out)),sha256=r['record_sha256'],source_file=item['file'],source_sha256=item['sha256']))
    summary=dict(batch=p['batch'],passed=len(audits)==24 and before==check(),methods=8,failures=0,errors=0,exact_methods=True,actual_method_bodies_passed=True,method_witness_freeze='b1a69956df8401f264b67b4716b21ef54941226a',predecessor_identities=352,saved_records=len(records),exact_record_domain=True,raw_roundtrip_exact=True,decoded_independent_audits=True,source_unchanged=True,registered_freeze=True,protocol_sha256=digest(ROOT/'contracts/ft/FT7_1b2b3a_Protocol_v1.json'),claim='Exact immutable-prefix native reserve/history accounting observer only; no choice causality; FT7.1b2b3b and FT8-FT9 mandatory')
    for name,value in [('summary.json',summary),('source_freeze.json',before),('record_index.json',records),('decoded_audits.json',audits),('input_index.json',index)]:
        (out/name).write_text(json.dumps(value,indent=2)+'\n')
    print(json.dumps(summary,indent=2),flush=True)
if __name__=='__main__':
    source,attempt,out=map(lambda p:Path(p).resolve(),sys.argv[1:4]);out.mkdir(parents=True,exist_ok=True)
    if sys.argv[4]=='finalize':finalize(source,attempt,out)
    else:unit(source,attempt,out,int(sys.argv[4]))
