import gc, os
from hashlib import sha256
from itertools import product
from pathlib import Path
import unittest
from hle_unified.selection_records import dumps,loads,fields_of
from hle_unified.records import ObjectId
from full_theory.owned_role_domain import role_requests
from full_theory.owned_role_domain_audit import audit_role_payload
from tests_ft7.test_social_live_outcome import read_record
from tests_ft7.test_owned_paid_comparison import paid_type


def saved(setting,stage):
    return read_record(Path(os.environ['FT7_ROLE_DOMAIN_OUTPUT'])/'records'/(setting+'-'+stage+'.json.gz'))


def payload_check(row,text=None):
    e=paid_type(row[0].split('/')[0]).restore(row[8]);p=loads(row[9]);v=e.participant_view(p['actor'])
    return audit_role_payload(v.snapshot,p['request'],row[0].split('/')[0],
        len(p['receipts'])==p['required'],row[10] if text is None else text,
        sha256(e.checkpoint().encode()).hexdigest(),sha256(row[9].encode()).hexdigest(),
        sha256(v.bytes().encode()).hexdigest())


class OwnedRoleDomainTests(unittest.TestCase):
    def test_unsettled_empty(self):
        for setting in ('canonical','workflow'):
            for stage in ('before','partial'):
                r=saved(setting,stage);d=loads(r[10])
                self.assertFalse(d['settled']);self.assertEqual(d['pools'],{})
                self.assertEqual(d['assignments'],0);self.assertEqual(list(role_requests(r[10])),[])
                del r,d;gc.collect()

    def test_exact_cartesian_requests(self):
        for setting in ('canonical','workflow'):
            r=saved(setting,'complete');d=loads(r[10]);names=d['role_order'];seen=set();count=0
            choices=product(*(d['pools'][name] for name in names))
            for ordinal,(request,values) in enumerate(zip(role_requests(r[10]),choices,strict=True)):
                expected=dict(d['request']);expected.update((n,v['value']) for n,v in zip(names,values))
                expected['key']='ft-owned-roles:'+d['preparation_sha256']+':'+str(ordinal)
                if setting=='workflow' and expected.get('procedure') is None:expected.pop('procedure',None)
                self.assertEqual(fields_of(request),expected);self.assertNotIn(request.key,seen)
                seen.add(request.key);count+=1
            self.assertEqual(count,d['assignments']);self.assertGreater(count,1)
            self.assertEqual(d['request'],loads(r[9])['request']);del r,d;gc.collect()

    def test_restart_exact(self):
        for setting in ('canonical','workflow'):
            a=saved(setting,'complete');b=saved(setting,'restarted')
            self.assertEqual(a[1:],b[1:]);del a,b;gc.collect()

    def test_no_authority_or_paid_comparison(self):
        for setting in ('canonical','workflow'):
            r=saved(setting,'complete');d=loads(r[10])
            for k in ('execution_authorized','td5_admitted','history_choice','comparison_paid'):self.assertIs(d[k],False)
            self.assertEqual(d['coverage'],'explicit-paid-observation-grammar-only')
            self.assertEqual(loads(r[3])['reserve'],loads(r[9])['reserve'])
            del r,d;gc.collect()

    def test_foreign_and_unacquired_retained(self):
        for setting in ('canonical','workflow'):
            r=saved(setting,'complete');d=loads(r[10]);e=paid_type(setting).restore(r[8]);v=e.participant_view(d['request']['actor'])
            stocks=[x['value'] for x in d['pools']['stock'] if x['value'] is not None]
            self.assertTrue(any({p.address.key:p.value for p in v.resolve(ref)}.get('owner')!=d['request']['actor'] for ref in stocks))
            procedures=[x['value'] for x in d['pools']['procedure'] if x['value'] is not None]
            self.assertTrue(procedures);self.assertTrue(any(not v.can_use(ref,d['request']['context']) for ref in procedures))
            if setting=='workflow':
                relations=[x['value'] for x in d['pools']['relation'] if x['value'] is not None]
                self.assertTrue(any({p.address.key for p in v.resolve(ref)}=={'name'} for ref in relations))
            del r,d,e,v;gc.collect()

    def test_omission_and_forgery_rejected(self):
        r=saved('canonical','complete')
        for mutation in ('omit','foreign','authority','count'):
            d=loads(r[10])
            if mutation=='omit':d['pools']['stock'].pop()
            elif mutation=='foreign':d['pools']['peer'].append(dict(value=ObjectId('forged','peer'),evidence=()))
            elif mutation=='authority':d['comparison_paid']=True
            else:d['assignments']+=1
            with self.assertRaises(ValueError):payload_check(r,dumps(d))

    def test_wrong_native_pair_rejected(self):
        r=saved('workflow','complete');d=loads(r[10]);d['native_sha256']='0'*64
        with self.assertRaises(ValueError):payload_check(r,dumps(d))

    def test_native_role_views_preserve_inputs(self):
        for setting in ('canonical','workflow'):
            r=saved(setting,'complete');e=paid_type(setting).restore(r[8]);d=loads(r[10]);count=0;rejected=0
            for request in role_requests(r[10]):
                try:
                    snapshot=e.selection_view(request) if setting=='canonical' else e.workflow_selection_view(request)
                    self.assertEqual(snapshot['request']['demand'],d['request']['demand'])
                    self.assertEqual(snapshot['request']['actor'],d['request']['actor'])
                except ValueError:rejected+=1
                count+=1
            self.assertEqual(count,d['assignments']);self.assertEqual(e.checkpoint(),r[8])
            print(setting+' native view probes: '+str(count)+', rejected: '+str(rejected),flush=True)
            del r,e,d;gc.collect()
