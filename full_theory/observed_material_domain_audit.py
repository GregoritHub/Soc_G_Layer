"""Independent A4 reconstruction from pinned saved input and owned particulars."""
import json
from hashlib import sha256
from pathlib import Path
from hle_unified.records import ObjectId, ObjectRef
from hle_unified.selection_records import dumps, loads


def audit_observed_material_domain(native, view, refresh_text, setting, text):
    def require(ok, message):
        if not ok:
            raise ValueError('observed material audit: '+message)
    def h(value):
        return sha256(value.encode()).hexdigest()
    c = loads(refresh_text); candidate = loads(text)
    p = Path(__file__).resolve().parents[1]/'contracts/ft/FT7_Observed_Reference_A4_Protocol_v1.json'
    inputs = json.loads(p.read_text())['inputs']
    require(any(row['setting']==setting and row['native_sha256']==h(native)
                and row['refresh_sha256']==h(refresh_text) and row['view_sha256']==h(view.bytes())
                for row in inputs),'exact independently hashed input pair and view')
    require(c['expected_native_sha256']==h(native) and c['actor']==view.snapshot.actor,'native and actor pairing')
    observations = []; evidence_rows = []
    def field_map(details):
        values = {}
        for detail in details:
            k = detail.address.key
            require(k not in values or (type(values[k]) is type(detail.value) and values[k]==detail.value),'conflicting fields')
            values[k] = detail.value
        return values
    def addresses(details):
        return tuple(sorted(set((x.source,x.address.delivery,x.address.key) for x in details),key=dumps))
    if c['phase']=='complete':
        for source in sorted({x.source for x in view.snapshot.particulars},key=dumps):
            details = [x for x in view.snapshot.particulars if x.source==source]
            f = field_map(details)
            if type(f.get('quantity')) is int and type(f.get('owner')) is ObjectId and type(f.get('custodian')) is ObjectId:
                evidence_rows.append((source,dict(kind='direct',observed_ref=source,evidence=addresses(details))))
        expected_deliveries = ['ft-skill-refresh:'+c['source_native_sha256']+':'+str(r['index'])+':delivery' for r in c['receipts']]
        require(len(set(expected_deliveries))==len(expected_deliveries),'unique reads')
        for delivery in sorted(expected_deliveries):
            details = [x for x in view.snapshot.particulars if x.address.delivery==delivery]
            sources = {x.source for x in details}; require(len(sources)==1,'unique observation source')
            source = next(iter(sources)); f = field_map(details)
            receipts = [r for r in view.snapshot.receipts if r.actor==c['actor'] and r.operation=='read'
                        and r.work_key==delivery and r.inputs==(source,) and (r.required,r.completed,r.spent)==(2,2,2)]
            require(len(receipts)==1,'fully paid owned receipt')
            require(f.get('actor')==c['actor'] and f.get('context')==c['context'] and
                    f.get('primitive')=='inspect' and f.get('outcome')=='succeeded','actual scoped observation')
            require(type(f.get('target')) is ObjectRef and type(f.get('owner')) is ObjectId and
                    type(f.get('custodian')) is ObjectId,'typed material facts')
            evidence = addresses(details)
            observations.append(dict(source=source,target=f['target'],facts=f,evidence=evidence,receipt=receipts[0].ref))
            evidence_rows.append((f['target'],dict(kind='observation',observed_ref=f['target'],evidence=evidence)))
    roles = ('stock','tool','repair_stock') if setting=='canonical' else ('stock',)
    pools = {}
    if c['phase']=='complete':
        refs = {ref for ref,_ in evidence_rows}
        if setting=='canonical':
            refs = {ref for ref in refs if not any(other.identity==ref.identity and other.revision>ref.revision for other in refs)}
        rows = [dict(value=None,supports=())]
        for ref in sorted(refs,key=dumps):
            support = {dumps(row):row for original,row in evidence_rows if
                       (original.identity==ref.identity if setting=='canonical' else original==ref)}
            rows.append(dict(value=ref,supports=tuple(support[k] for k in sorted(support))))
        pools = {role:rows for role in roles}
    expected = dict(version='ft-observed-material-domain-a4-v1',setting=setting,native_sha256=h(native),
        refresh_sha256=h(refresh_text),view_sha256=h(view.bytes()),actor=c['actor'],context=c['context'],
        settled=c['phase']=='complete',observations=tuple(sorted(observations,key=dumps)),pools=pools,
        role_order=tuple(pools),coverage='explicit-material-vocabulary-only',comparison_paid=False,
        execution_authorized=False,td5_admitted=False,history_choice=False,parent_accepted=False)
    require(dumps(candidate)==dumps(expected),'complete independent output equality')
    require(text==dumps(candidate),'typed canonical roundtrip')
    return dict(passed=True,settled=expected['settled'],observations=len(observations),
        alternatives={k:len(v) for k,v in pools.items()},
        revision2=sum(r['value'] is not None and r['value'].revision==2 for r in pools.get('stock',[])),
        foreign_observations=sum(o['facts']['owner']!=c['actor'] for o in observations),
        native_sha256=h(native),view_sha256=h(view.bytes()),native_work=0)
