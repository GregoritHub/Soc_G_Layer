import unittest
from types import SimpleNamespace
from full_theory.observed_field_reads import field_plan
from hle_unified.records import ObjectId,ObjectRef

RESULTS=[]
PROBES=[]
CONTROLS=[]


class ObservedFieldReadsTests(unittest.TestCase):
    def row(self,s,n):return next(x for x in RESULTS if x['setting']==s and x['record']==n)

    def test_exact_panel(self):
        self.assertEqual(len(RESULTS),10)
        self.assertEqual({(r['setting'],r['record']) for r in RESULTS},
            {(s,n) for s in ('canonical','workflow') for n in ('before','partial','complete','restarted','cancelled')})
        self.assertTrue(all(x['passed'] for x in RESULTS))

    def test_paid_fields_and_limited_paths(self):
        for s,lengths in (('canonical',[7,7,7]),('workflow',[1,7,1])):
            r=self.row(s,'complete');self.assertEqual(r['selectors'],lengths)
            self.assertEqual(r['targets'],3);self.assertEqual(r['receipts'],3)
            self.assertEqual(r['new_fields'],sum(lengths));self.assertEqual((r['energy'],r['time']),(6,6))
        # No world API or arbitrary target path is available to this pure planner.
        ref=ObjectRef(ObjectId('test','material'),2)
        old=SimpleNamespace(source=ObjectRef(ref.identity,1),address=SimpleNamespace(delivery='known',key='name'),category='name',path=('label',))
        v=SimpleNamespace(snapshot=SimpleNamespace(particulars=(old,)),resolve=lambda r:())
        plan=field_plan(v,{'observations':({'target':ref},)})
        self.assertEqual(plan[0]['selectors'],(('name','name',('label',)),))
        conflicting=SimpleNamespace(**{**old.__dict__,'path':('secret',)})
        v.snapshot.particulars=(old,conflicting)
        with self.assertRaises(ValueError):field_plan(v,{'observations':({'target':ref},)})

    def test_partial_cancel_no_credit(self):
        for s in ('canonical','workflow'):
            for name in ('before','partial','cancelled'):
                r=self.row(s,name);self.assertEqual((r['receipts'],r['new_fields']),(0,0))
                cost=0 if name=='before' else 1
                self.assertEqual((r['energy'],r['time']),(cost,cost))
            self.assertEqual(self.row(s,'cancelled')['phase'],'cancelled')

    def test_restart_terminal_exact(self):
        self.assertEqual({(x['setting'],x['name']) for x in CONTROLS},
                         {(s,n) for s in ('canonical','workflow') for n in ('restart','terminal')})
        self.assertTrue(all(x['exact'] for x in CONTROLS))
        for s in ('canonical','workflow'):
            for k in ('phase','targets','selectors','receipts','new_fields','energy','time'):
                self.assertEqual(self.row(s,'complete')[k],self.row(s,'restarted')[k])

    def test_independent_forgery_rejection(self):
        names=('refresh_pair_constructor','projection_pair_constructor','refresh_pair_auditor','projection_pair_auditor',
               'plan','source','receipts','authority','payment','selector_path')
        self.assertEqual(len(PROBES),20)
        self.assertEqual({(x['setting'],x['name']) for x in PROBES},{(s,n) for s in ('canonical','workflow') for n in names})
        self.assertTrue(all(x['rejected'] for x in PROBES))

    def test_prefixes_and_no_authority(self):
        self.assertTrue(all(all(x[k] for k in ('prefixes_exact','physical_unchanged','acquired_preserved','no_authority')) for x in RESULTS))
