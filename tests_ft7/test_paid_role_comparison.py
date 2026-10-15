import os
from pathlib import Path
import unittest
from unittest.mock import patch
from dataclasses import replace
from hle_unified.material import attrs,attributes
from hle_unified.selection_records import dumps,loads
from hle_unified.operations import address,record
from full_theory.paid_role_comparison import (PaidCanonicalRoleEngine,PaidWorkflowRoleEngine,
    RoleComparisonRequest,prepare_role_comparison,step_role_comparison,digest)
from full_theory.paid_role_comparison_audit import audit_paid_roles
from tests_ft7.test_social_live_outcome import read_record
from tests_ft7.test_owned_paid_comparison import paid_type


def role_type(setting):return PaidCanonicalRoleEngine if setting=='canonical' else PaidWorkflowRoleEngine
def raw(setting,stage):
    key,native,rows,result=read_record(Path(os.environ['FT7_PAID_ROLES_OUTPUT'])/'records'/(setting+'-'+stage+'.json.gz'))
    return key,native,loads(rows),loads(result)
def inputs(setting):return read_record(Path(os.environ['FT7_PAID_ROLES_INPUT'])/'records'/(setting+'-complete.json.gz'))


class PaidRoleComparisonTests(unittest.TestCase):
    def test_full_paid_domain(self):
        for setting,count in (('canonical',1728),('workflow',3612)):
            _,_,rows,result=raw(setting,'complete')
            self.assertEqual(len(rows),count);self.assertEqual(result['assignments'],rows)
            self.assertTrue(result['comparison_paid'])
            self.assertFalse(any(result[x] for x in ('execution_authorized','td5_admitted','history_choice')))
            self.assertEqual([x['ordinal'] for x in rows],list(range(count)))

    def test_partial_and_ready_no_result(self):
        for setting in ('canonical','workflow'):
            for stage in ('before','partial','ready','cancelled'):
                self.assertIsNone(raw(setting,stage)[3])

    def test_exact_native_debits(self):
        for setting in ('canonical','workflow'):
            row=inputs(setting);old=paid_type(setting).restore(row[8]);actor=loads(row[10])['request']['actor']
            _,native,rows,result=raw(setting,'complete');e=role_type(setting).restore(native)
            required=sum(x['required'] for x in rows)
            self.assertEqual(result['required'],required);self.assertGreater(required,0)
            self.assertEqual({u:old.wallet(actor)[u]-e.wallet(actor)[u] for u in ('energy','time')},dict(energy=required,time=required))

    def test_cancel_no_refund(self):
        for setting in ('canonical','workflow'):
            row=inputs(setting);old=paid_type(setting).restore(row[8]);actor=loads(row[10])['request']['actor']
            _,native,_,result=raw(setting,'cancelled');e=role_type(setting).restore(native)
            self.assertEqual(old.wallet(actor)['energy']-e.wallet(actor)['energy'],1)
            self.assertEqual(old.wallet(actor)['time']-e.wallet(actor)['time'],1);self.assertIsNone(result)

    def test_exact_restart_and_idempotence(self):
        for setting in ('canonical','workflow'):
            self.assertEqual(raw(setting,'complete')[1:],raw(setting,'restarted')[1:])
            row=inputs(setting);r=RoleComparisonRequest('ft-role-comparison:'+digest(row[10]),row[10],row[9],tuple(row[1:8]))
            native=raw(setting,'complete')[1];e=role_type(setting).restore(native)
            step_role_comparison(e,r);step_role_comparison(e,r)
            self.assertEqual(e.checkpoint(),native)

    def test_protected_evidence(self):
        row=inputs('canonical');old=paid_type('canonical').restore(row[8]);e,r=prepare_role_comparison(old,row[10],row[9],tuple(row[1:8]))
        actor=loads(row[10])['request']['actor'];ref=address('ftrc.result',actor,r.key)
        before=e.checkpoint()
        with self.assertRaises(ValueError):e.declare('forged-role-evidence',(record(ref,'Forged result',dict(payload='fake')),))
        self.assertEqual(before,e.checkpoint())

    def test_wrong_pair_and_unsettled(self):
        row=inputs('canonical');old=paid_type('canonical').restore(row[8]);e,r=prepare_role_comparison(old,row[10],row[9],tuple(row[1:8]))
        forged=loads(row[10]);forged['native_sha256']='0'*64
        with self.assertRaises(ValueError):step_role_comparison(e,replace(r,roles=dumps(forged)))
        for field in ('required','receipts'):
            p=loads(row[9]);p[field]=0 if field=='required' else [dict(p['receipts'][0],energy=0)]
            prepared=dumps(p);d=loads(row[10]);d['preparation_sha256']=digest(prepared);roles=dumps(d)
            forged=RoleComparisonRequest('ft-role-comparison:'+digest(roles),roles,prepared,tuple(row[1:8]))
            with self.assertRaises(ValueError):step_role_comparison(e,forged)
        partial=read_record(Path(os.environ['FT7_PAID_ROLES_INPUT'])/'records/canonical-partial.json.gz')
        old=paid_type('canonical').restore(partial[8]);e,r=prepare_role_comparison(old,partial[10],partial[9],tuple(partial[1:8]))
        with self.assertRaises(ValueError):step_role_comparison(e,r)

    def test_forged_result_rejected(self):
        row=inputs('canonical');old=paid_type('canonical').restore(row[8]);_,native,rows,_=raw('canonical','complete')
        e=role_type('canonical').restore(native)
        txs=list(e.world.journal());versions=list(txs[-1].versions)
        for i,v in enumerate(versions):
            if v.ref.identity.namespace=='ftrc.result':
                data=attrs(v);payload=loads(data['payload']);payload['execution_authorized']=True
                versions[i]=replace(v,attributes=attributes(dict(data,payload=dumps(payload))))
        txs[-1]=replace(txs[-1],versions=tuple(versions))
        with patch.object(e.world,'journal',return_value=tuple(txs)):
            with self.assertRaises(ValueError):audit_paid_roles(e,old,row[10],row[9])
