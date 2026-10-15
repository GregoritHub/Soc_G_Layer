"""Bounded independent readback of the exact frozen 24-record method witness.

No method bodies or engine scenarios are rerun. The original aggregate and
actual passed method log remain immutable inputs; every saved record audits.
"""
from pathlib import Path
import gc,gzip,hashlib,json,re,sys,unittest
ROOT=Path(__file__).resolve().parents[1]
sys.path[:0]=[str(ROOT),str(ROOT/'baseline/HLE_Rebuild_R21B')]
from hle_unified import codec
from tools.evaluate_ft7_1b2b2b import audit_saved
from tools.evaluate_ft6_3b import ids,predecessor_identities


def digest(path):
    h=hashlib.sha256()
    with path.open('rb') as stream:
        for block in iter(lambda:stream.read(1024*1024),b''):h.update(block)
    return h.hexdigest()


def freeze():
    original=json.loads((ROOT/'contracts/ft/FT7_1b2b2b_Source_Freeze_v1.json').read_text())
    names=set(original)|{'contracts/ft/FT7_1b2b2b_Source_Freeze_v1.json',
        'tools/audit_ft7_1b2b2b_saved.py',
        'contracts/ft/FT7_1b2b2b_Saved_Record_Audit_Amendment_v1.json',
        'contracts/ft/FT7_1b2b2b_Saved_Record_Audit_Amendment_v1.sha256'}
    return {name:digest(ROOT/name) for name in sorted(names)}


def exact_records(path,receipt):
    """Stream canonical tuple elements and the original full payload SHA-256."""
    header='{"format":"hle-unified-typed-json-v1","payload":{"tuple":['
    hasher=hashlib.sha256(b'{"tuple":[')
    decoder=json.JSONDecoder(object_pairs_hook=codec._unique,
        parse_constant=lambda value:(_ for _ in ()).throw(ValueError('nonfinite JSON')))
    with path.open('r',encoding='ascii') as stream:
        if stream.read(len(header))!=header:raise ValueError('exact aggregate envelope required')
        buffer='';count=0
        def extend():
            nonlocal buffer
            block=stream.read(8*1024*1024)
            if not block:raise ValueError('incomplete aggregate evidence')
            buffer+=block
            if len(buffer)>512*1024*1024:raise ValueError('single evidence record exceeds declared reader bound')
        while True:
            if not buffer:extend()
            if buffer.startswith(']'):break
            while True:
                try:value,end=decoder.raw_decode(buffer);break
                except json.JSONDecodeError:extend()
            raw=buffer[:end];buffer=buffer[end:]
            if count:hasher.update(b',')
            hasher.update(raw.encode('ascii'))
            if codec.canonical(value)!=raw:raise ValueError('noncanonical typed aggregate record')
            row=codec.decode(value)
            if type(row) is not tuple or len(row)!=4 or codec.canonical(codec.encode(row))!=raw:
                raise ValueError('exact typed record roundtrip differs')
            count+=1
            yield count,row
            del row,value,raw
            if not buffer:extend()
            if buffer.startswith(','):buffer=buffer[1:]
            elif not buffer.startswith(']'):raise ValueError('aggregate separator differs')
        hasher.update(b']}')
        tail=buffer+stream.read()
        match=re.fullmatch(r'\]\},"sha256":"([0-9a-f]{64})"\}\n?',tail)
        if match is None or match[1]!=hasher.hexdigest():raise ValueError('full original aggregate checksum differs')
        receipt.update(passed=True,records=count,payload_sha256=hasher.hexdigest())


def expected_methods():
    p=json.loads((ROOT/'contracts/ft/FT7_1b2b2b_Protocol_v1.json').read_text())
    a=json.loads((ROOT/'contracts/ft/FT7_1b2b2b_Dimensionality_Amendment_v1.json').read_text())
    split=json.loads((ROOT/'contracts/ft/FT7_1b2b2b_Split_Comparison_Amendment_v1.json').read_text())['test_contract']
    methods=[m for m in p['registered_tests']+a['added_methods'] if m!=split['replace_method']]+split['replacement_methods']
    return sorted('tests_ft7.test_social_reuse.SocialReuseTests.'+m for m in methods),split


def predecessor_ids():
    found=predecessor_identities()
    for mod,cl,protocol in (
        ('tests_ft6.test_conditioning_release','ConditioningReleaseTests','FT6_3b'),
        ('tests_ft7.test_packet_channel','PacketChannelTests','FT7_1a'),
        ('tests_ft7.test_social_cycle','SocialCycleTests','FT7_1b1'),
        ('tests_ft7.test_peer_cycle','PeerCycleTests','FT7_1b2a'),
        ('tests_ft7.test_social_training','SocialTrainingTests','FT7_1b2b1'),
        ('tests_ft7.test_social_closure','SocialClosureTests','FT7_1b2b2a')):
        p=json.loads((ROOT/'contracts/ft'/(protocol+'_Protocol_v1.json')).read_text())
        actual=sorted(ids(unittest.defaultTestLoader.loadTestsFromName(mod)))
        if actual!=sorted(mod+'.'+cl+'.'+m for m in p['registered_tests']):raise ValueError('predecessor method identity differs')
        found+=actual
    if len(found)!=338 or len(set(found))!=338:raise ValueError('predecessor exact domain differs')
    return found


def main(source,out):
    out.mkdir(parents=True,exist_ok=False);(out/'records').mkdir()
    before=freeze();registered=json.loads((ROOT/'contracts/ft/FT7_1b2b2b_Saved_Audit_Source_Freeze_v1.json').read_text())
    if before!=registered:raise ValueError('saved-audit registered freeze mismatch')
    original=json.loads((source/'source_freeze.json').read_text())
    if original!=json.loads((ROOT/'contracts/ft/FT7_1b2b2b_Source_Freeze_v1.json').read_text()):raise ValueError('original witness freeze differs')
    if any(digest(ROOT/n)!=h for n,h in original.items()):raise ValueError('actual method witness source changed')
    expected,split=expected_methods();actual=sorted(ids(unittest.defaultTestLoader.loadTestsFromName('tests_ft7.test_social_reuse')))
    recorded=json.loads((source/'method_ids.json').read_text());log=(source/'controls.log').read_text()
    passed_ids=sorted(re.findall(r'^\w+ \((tests_ft7\.test_social_reuse\.SocialReuseTests\.\w+)\) \.\.\. ok$',log,re.M))
    if actual!=expected or recorded!=expected or passed_ids!=expected or not re.search(r'Ran 14 tests in [\d.]+s\n\nOK\n?$',log):
        raise ValueError('actual complete frozen method-body log/identity differs')
    predecessors=predecessor_ids()
    expected_keys={s+'/'+m for s in ('canonical','workflow') for m in split['scenarios_per_setting']}|{
        s+'/'+m+'/restart-'+part for s in ('canonical','workflow') for m in split['restarts_per_setting'] for part in ('final','partial')}
    receipt={};audits={};manifest=[];roundtrips={}
    rawpath=source/'raw_reuse_evidence.json'
    for index,row in exact_records(rawpath,receipt):
        key,txs,wrapper,native=row
        if key in audits or key not in expected_keys:raise ValueError('unexpected or duplicate exact saved record key')
        path=out/'records'/(str(index).zfill(2)+'.json.gz')
        with gzip.open(path,'wt',encoding='ascii') as stream:stream.write(codec.dumps(row)+'\n')
        with gzip.open(path,'rt',encoding='ascii') as stream:decoded=codec.loads(stream.read())
        roundtrips[key]=decoded==row
        if not roundtrips[key]:raise ValueError('compressed exact saved record roundtrip differs')
        del decoded
        try:audits[key]=audit_saved(key,txs,wrapper,native)
        except Exception as exc:audits[key]=dict(passed=False,error=type(exc).__name__+': '+str(exc))
        manifest.append(dict(key=key,file=str(path.relative_to(out)),sha256=digest(path)))
        (out/'record_index.json').write_text(json.dumps(manifest,indent=2)+'\n')
        (out/'decoded_audits.json').write_text(json.dumps(audits,indent=2)+'\n')
        print(key+': '+str(audits[key]['passed']),flush=True)
        del txs,wrapper,native,row;gc.collect()
    unchanged=before==freeze() and all(digest(ROOT/n)==h for n,h in original.items())
    passed=receipt.get('passed') is True and len(manifest)==24 and set(audits)==expected_keys and all(x['passed'] for x in audits.values()) and unchanged and all(roundtrips.values())
    summary=dict(passed=passed,methods=14,failures=0,errors=0,exact_methods=True,
        actual_method_bodies_passed=True,method_witness_freeze='83d057cb5700c6fa0676cc5d83b422c622d420b4',
        predecessor_identities=len(predecessors),saved_records=len(manifest),exact_record_domain=set(audits)==expected_keys,
        raw_roundtrip_exact=all(roundtrips.values()),aggregate_checksum_verified=receipt,decoded_independent_audits=all(x['passed'] for x in audits.values()),
        source_unchanged=unchanged,registered_freeze=before==registered,protocol_sha256=digest(ROOT/'contracts/ft/FT7_1b2b2b_Protocol_v1.json'),
        claim='Strict success-versus-deferral and separate one-facet equal-main-cost retained priority; FT8 unchanged; integrated reserve/history feedback pending')
    (out/'summary.json').write_text(json.dumps(summary,indent=2)+'\n')
    (out/'source_freeze.json').write_text(json.dumps(before,indent=2)+'\n')
    (out/'input_hashes.json').write_text(json.dumps({p.name:digest(p) for p in source.iterdir() if p.is_file()},indent=2)+'\n')
    print(json.dumps(summary,indent=2),flush=True)
    if not passed:raise SystemExit(1)
if __name__=='__main__':main(Path(sys.argv[1]).resolve(),Path(sys.argv[2]).resolve())
