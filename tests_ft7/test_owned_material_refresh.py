import unittest
from types import SimpleNamespace
from hle_unified.records import ObjectId,ObjectRef
from full_theory.owned_material_refresh import inventory

RESULTS=[]
PROBES=[]


class OwnedMaterialRefreshTests(unittest.TestCase):
    def row(self,s,n):return next(x for x in RESULTS if x['setting']==s and x['record']==n)

    def test_exact_panel(self):
        names=('before','inspect-partial','read-partial','complete','restarted','cancelled')
        self.assertEqual({(r['setting'],r['record']) for r in RESULTS},{(s,n) for s in ('canonical','workflow') for n in names})
        self.assertEqual(len(RESULTS),12);self.assertTrue(all(r['passed'] for r in RESULTS))

    def test_partial_receipts(self):
        for s in ('canonical','workflow'):
            for n in ('before','inspect-partial','read-partial','cancelled'):
                self.assertEqual(self.row(s,n)['receipts'],0)
            self.assertEqual(self.row(s,'read-partial')['energy'],4)

    def test_paid_refresh(self):
        for s in ('canonical','workflow'):
            r=self.row(s,'complete');self.assertGreater(r['receipts'],0)
            self.assertEqual(r['receipts']+r['rejected'],r['inventory'])
            self.assertEqual(r['energy'],5*r['receipts']);self.assertEqual(r['time'],r['energy'])
            self.assertTrue(r['acquired_preserved'])
            self.assertTrue(any(revision>1 for revision in r['current_observation_revisions']))

    def test_restart_and_cancel(self):
        for s in ('canonical','workflow'):
            for k in ('phase','inventory','receipts','rejected','energy','time','current_observation_revisions','acquired_preserved'):
                self.assertEqual(self.row(s,'complete')[k],self.row(s,'restarted')[k])
            self.assertEqual(self.row(s,'cancelled')['energy'],1);self.assertEqual(self.row(s,'cancelled')['time'],1)

    def test_inventory_and_pairing(self):
        a=ObjectId('test','a');b=ObjectId('test','b')
        def p(i,r,category,key,value):return SimpleNamespace(source=ObjectRef(i,r),category=category,address=SimpleNamespace(key=key),value=value)
        v=SimpleNamespace(snapshot=SimpleNamespace(particulars=(p(a,1,'name','name','a'),p(a,2,'detail','condition','damaged'),p(b,1,'detail','quantity',True))))
        self.assertEqual(inventory(v),(ObjectRef(a,2),))
        self.assertEqual({(r['setting'],r['field'],r['api']) for r in PROBES if 'api' in r},
                         {(s,f,a) for s in ('canonical','workflow') for f in ('actor','context','unregistered_extra') for a in ('constructor','auditor')})

    def test_saved_forgery_rejections(self):
        self.assertEqual({(r['setting'],r['field']) for r in PROBES if 'api' not in r},
                         {(s,f) for s in ('canonical','workflow') for f in ('plan','source_native_sha256','receipts','main_execution_authorized','payment')})
        self.assertEqual(len(PROBES),22);self.assertTrue(all(r['rejected'] for r in PROBES))
