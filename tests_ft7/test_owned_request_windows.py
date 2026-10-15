import gc,gzip,os,unittest
from pathlib import Path
from hle_unified import codec
from hle_unified.selection_records import loads,dumps
from hle_unified.workflow_selection_records import WorkflowSelectionRequest
from full_theory.owned_request_windows import owned_request_windows
from full_theory.owned_request_windows_audit import audit_owned_request_windows
from tools.evaluate_ft7_1b2b3b2b2b2b2b2b1 import input_row,original_row
from tests_ft7.test_social_live_outcome import engine_type

def saved(setting,stage):
    with gzip.open(Path(os.environ['FT7_REQUEST_WINDOWS_OUTPUT'])/'records'/(setting+'-'+stage+'.json.gz'),'rt') as f:return codec.loads(f.read())

class OwnedRequestWindowTests(unittest.TestCase):
    def test_exact_full_panel(self):
        for setting in ('canonical','workflow'):
            for mask in range(1,16):
                d=loads(saved(setting,'mask-'+str(mask))[2]);i=loads(input_row(setting,'mask-'+str(mask))[2])
                self.assertEqual(len(d['requests']),1 if setting=='canonical' else 510)
                self.assertEqual({dumps(r['demand']) for r in d['requests']},{dumps(i['task'])})
                self.assertEqual(len({r['key'] for r in d['requests']}),len(d['requests']))
                self.assertEqual(d['fresh_demand']['binding'],i['task'])

    def test_every_legal_subset(self):
        from math import comb
        for mask in range(1,16):
            d=loads(saved('workflow','mask-'+str(mask))[2]);inventory=d['content_inventory']
            subsets=[r['accessible'] for r in d['requests']]
            self.assertEqual(len(inventory),9)
            self.assertEqual(len(set(subsets)),510)
            self.assertEqual({n:sum(len(s)==n for s in subsets) for n in range(1,9)},{n:comb(9,n) for n in range(1,9)})
            for ref in inventory:self.assertEqual(sum(ref in s for s in subsets),255)
            self.assertEqual(set().union(*(set(s) for s in subsets)),set(inventory))

    def test_old_bound_preserved(self):
        for mask in range(1,16):
            d=loads(saved('workflow','mask-'+str(mask))[2]);f=d['original_formation']
            self.assertEqual(f['policy'],'owned-native-request-v1')
            self.assertEqual(f['reason'],'workflow_content_bound_exceeded');self.assertIsNone(f['request'])
            r=dict(d['requests'][0]);r['accessible']=d['content_inventory']
            with self.assertRaises(ValueError):WorkflowSelectionRequest(**r)
            for r in d['requests']:
                self.assertTrue(1<=len(WorkflowSelectionRequest(**r).accessible)<=8)

    def test_typed_roundtrip_and_restart(self):
        for setting in ('canonical','workflow'):
            for mask in range(1,16):
                row=saved(setting,'mask-'+str(mask));self.assertEqual(codec.loads(codec.dumps(row)),row)
            self.assertEqual(saved(setting,'mask-1')[1:],saved(setting,'restarted')[1:])

    def test_incomplete_intake_rejected(self):
        for setting in ('canonical','workflow'):
            original=original_row(setting);old=engine_type(setting).restore(original[1])
            for stage in ('before','read-partial','read-complete','bind-partial'):
                row=input_row(setting,stage);e=engine_type(setting).restore(row[1])
                with self.assertRaises(ValueError):owned_request_windows(e,old,original[2],original[3],row[2])
                self.assertEqual(e.checkpoint(),row[1]);del e,row;gc.collect()
            del old,original;gc.collect()

    def test_forged_domain_rejected(self):
        for setting in ('canonical','workflow'):
            original=original_row(setting);old=engine_type(setting).restore(original[1])
            row=input_row(setting,'mask-1');e=engine_type(setting).restore(row[1]);text=saved(setting,'mask-1')[2]
            for field,value in (('requests',[]),('source_sha256','0'*64),('comparison_paid',True),('controller_prefix','forged')):
                d=loads(text);d[field]=value
                with self.assertRaises(ValueError):audit_owned_request_windows(e,old,original[2],original[3],row[2],dumps(d))
            d=loads(text);d['requests'][0]['demand']=None
            with self.assertRaises(ValueError):audit_owned_request_windows(e,old,original[2],original[3],row[2],dumps(d))
            i=loads(row[2]);i['receipt']['energy']=0
            with self.assertRaises(ValueError):owned_request_windows(e,old,original[2],original[3],dumps(i))
            self.assertEqual(e.checkpoint(),row[1]);del old,e,row,original;gc.collect()

    def test_exact_prefixes_and_no_native_work(self):
        for setting in ('canonical','workflow'):
            original=original_row(setting)
            for mask in range(1,16):
                row=saved(setting,'mask-'+str(mask));i=input_row(setting,'mask-'+str(mask))
                self.assertEqual(row[1],i[1])
                d=loads(row[2]);self.assertEqual(d['controller_prefix'],loads(original[2])['demand_controller'])
                self.assertEqual(d['original_formation']['content'],d['content_inventory'])

    def test_no_routes_roles_or_authority(self):
        for setting in ('canonical','workflow'):
            for mask in range(1,16):
                d=loads(saved(setting,'mask-'+str(mask))[2])
                self.assertEqual(d['policy'],'owned-accessible-window-domain-v2')
                self.assertFalse(any(d[k] for k in ('native_view_probed','comparison_paid','execution_authorized','td5_admitted','history_choice')))
                self.assertEqual(d['receipt_scope'],'intake_only')
                for r in d['requests']:
                    self.assertFalse({'route','recipe','success','history_score'} & set(r))
                    for role in ('stock','tool','repair_stock','peer','group','relation','procedure'):
                        if role in r:self.assertIsNone(r[role])
