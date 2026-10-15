import gzip, os, unittest
from pathlib import Path
from hle_unified import codec
from hle_unified.selection_records import dumps, loads
from hle_unified.self_content import decode
from full_theory.fresh_task_intake import FreshTaskIntake
from full_theory.fresh_task_intake_audit import audit_fresh_task_intake
from tests_ft7.test_social_live_outcome import engine_type
from tools.evaluate_ft7_1b2b3b2b2b2b2b2a import input_row


def saved(setting, stage):
    path = Path(os.environ['FT7_FRESH_OUTPUT'])/'records'/(setting+'-'+stage+'.json.gz')
    with gzip.open(path,'rt') as stream: return codec.loads(stream.read())


class FreshTaskIntakeTests(unittest.TestCase):
    def test_fixed_panel(self):
        for setting in ('canonical','workflow'):
            values = []
            for mask in range(1,16):
                d = loads(saved(setting,'mask-'+str(mask))[2]); values.append(d['mask'])
                payload = decode(d['payload'])
                self.assertEqual(payload['weights' if setting == 'canonical' else 'priorities'],
                    tuple(10 if mask & (1 << i) else 0 for i in range(4)))
                self.assertIsNotNone(d['receipt'])
            self.assertEqual(values,list(range(1,16)))

    def test_actual_native_payment(self):
        for setting in ('canonical','workflow'):
            oldrow = input_row(setting,'live'); old = engine_type(setting).restore(oldrow[1])
            for mask in range(1,16):
                row = saved(setting,'mask-'+str(mask)); d = loads(row[2])
                self.assertEqual({u:sum(x['debit'][u] for x in d['events']) for u in ('energy','time')},dict(energy=5,time=5))
                e = engine_type(setting).restore(row[1]);actor=d['actor']
                self.assertEqual({u:old.wallet(actor)[u]-e.wallet(actor)[u] for u in ('energy','time')},dict(energy=5,time=5))

    def test_partial_has_no_receipt(self):
        for setting in ('canonical','workflow'):
            for stage,cost in (('before',0),('read-partial',1),('read-complete',2),('bind-partial',3)):
                row=saved(setting,stage); d=loads(row[2]); self.assertIsNone(d['receipt'])
                self.assertEqual(sum(x['debit']['energy'] for x in d['events']),cost)
                e=engine_type(setting).restore(row[1]); self.assertNotIn(d['task'],e.participant_view(d['actor'])._bindings)

    def test_exact_restarts_and_terminal(self):
        for setting in ('canonical','workflow'):
            complete=saved(setting,'mask-1')
            for stage in ('read-restarted','bind-restarted'):
                self.assertEqual(saved(setting,stage)[1:],complete[1:])
            original=input_row(setting,'live');old=engine_type(setting).restore(original[1])
            e=engine_type(setting).restore(complete[1])
            c=FreshTaskIntake.restore(complete[2],e,old,original[2],original[3])
            c.step(e);c.step(e)
            self.assertEqual((e.checkpoint(),c.checkpoint(e)),complete[1:])

    def test_exact_prefixes(self):
        for setting in ('canonical','workflow'):
            original=input_row(setting,'live');s=loads(original[2]);b=loads(original[3])
            old=engine_type(setting).restore(original[1]);row=saved(setting,'mask-15')
            e=engine_type(setting).restore(row[1]);d=loads(row[2])
            self.assertEqual(tuple(e.world.journal())[:len(old.world.journal())],tuple(old.world.journal()))
            self.assertEqual((d['reserve'],d['history'],d['controller_prefix']),(b['reserve'],b['history'],s['demand_controller']))

    def test_older_demand_rejected(self):
        for setting in ('canonical','workflow'):
            for case in ('harder','partial-movement'):
                row=input_row(setting,case);e=engine_type(setting).restore(row[1]);before=e.checkpoint()
                with self.assertRaises(ValueError):FreshTaskIntake(e,row[2],row[3],1)
                self.assertEqual(e.checkpoint(),before)

    def test_forged_payload_receipt_prefix(self):
        original=input_row('canonical','live');old=engine_type('canonical').restore(original[1])
        row=saved('canonical','mask-1');e=engine_type('canonical').restore(row[1])
        for field,value in (('payload','forged'),('receipt',None),('source_sha256','0'*64)):
            data=loads(row[2]);data[field]=value
            with self.assertRaises(ValueError):audit_fresh_task_intake(e,old,original[2],original[3],dumps(data))

    def test_route_free_scope(self):
        for setting in ('canonical','workflow'):
            for mask in range(1,16):
                d=loads(saved(setting,'mask-'+str(mask))[2])
                self.assertFalse(any(d[k] for k in ('comparison_paid','execution_authorized','td5_admitted','history_choice')))
                self.assertTrue(all(x['kind'] in ('read','bind') for x in d['events']))
                self.assertFalse({'route','recipe','peer','stock','tool','success'} & set(decode(d['payload'])))
