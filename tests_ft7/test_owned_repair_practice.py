import unittest
from types import SimpleNamespace
from hle_unified.records import ObjectId,ObjectRef,Procedure
from full_theory.owned_repair_practice import owned_plan
from full_theory.owned_repair_practice_audit import independent_plan

RESULTS=[]
PROBES=[]


class OwnedRepairPracticeTests(unittest.TestCase):
    def row(self,s,n):return next(x for x in RESULTS if x['setting']==s and x['record']==n)

    def test_exact_panel(self):
        expected={(s,n) for s in ('canonical','workflow') for n in
            ('before','practice-partial','read-partial','acquire-partial','complete','restarted','cancelled')}
        self.assertEqual({(r['setting'],r['record']) for r in RESULTS},expected)
        self.assertEqual(len(RESULTS),14);self.assertTrue(all(r['passed'] for r in RESULTS))

    def test_partial_withholds_acquisition(self):
        for s in ('canonical','workflow'):
            for n in ('before','practice-partial','read-partial','acquire-partial','cancelled'):
                self.assertFalse(self.row(s,n)['acquired'])
            self.assertEqual(self.row(s,'practice-partial')['successful_practices'],0)
            self.assertEqual(self.row(s,'acquire-partial')['successful_practices'],1)

    def test_native_paid_effects(self):
        for s in ('canonical','workflow'):
            r=self.row(s,'complete');self.assertTrue(r['acquired']);self.assertEqual(r['successful_practices'],1)
            self.assertEqual(r['energy'],8*(r['failed_practices']+1)+3);self.assertEqual(r['time'],r['energy'])

    def test_restart_and_cancel(self):
        for s in ('canonical','workflow'):
            for k in ('phase','candidates','successful_practices','failed_practices','acquired','energy','time'):
                self.assertEqual(self.row(s,'complete')[k],self.row(s,'restarted')[k])
            self.assertEqual(self.row(s,'cancelled')['energy'],1);self.assertEqual(self.row(s,'cancelled')['time'],1)
            self.assertEqual(self.row(s,'cancelled')['successful_practices'],0)

    def test_owned_domain(self):
        actor=ObjectId('test','actor');other=ObjectId('test','other');context=ObjectRef(ObjectId('test','context'),1)
        refs={k:ObjectRef(ObjectId('test',k),1) for k in ('procedure','target','tool','stock','foreign')}
        def view(*,observed=True,procedure=True,purpose=None,owner=actor,custodian=actor):
            ps=[]
            def add(ref,fields):
                for k,v in fields.items():ps.append(SimpleNamespace(source=ref,address=SimpleNamespace(key=k),value=v))
            if procedure:add(refs['procedure'],{'procedure':Procedure(inputs=('target','tool','stock'),preconditions=(),steps=(),effects=(),executor='u4.repair.v1')})
            for name,condition in (('target','damaged'),('tool','serviceable'),('stock','stock')):
                add(refs[name],{'name':name})
                if observed:add(ObjectRef(ObjectId('u4.observation',name),1),dict(primitive='inspect',outcome='succeeded',actor=actor,
                    context=context,target=refs[name],owner=owner,custodian=custodian,condition=condition,available=2))
            if purpose is not None:add(refs['stock'],{'purpose':purpose})
            return SimpleNamespace(snapshot=SimpleNamespace(particulars=tuple(ps)),can_use=lambda r,c:False)
        for kwargs,number in (({},1),({'observed':False},0),({'procedure':False},0),({'purpose':'care'},0),
                              ({'purpose':'repair'},1),({'owner':other},0),({'custodian':other},0)):
            v=view(**kwargs);runtime=owned_plan(v,actor,context);audit=independent_plan(v,actor,context)
            self.assertEqual(runtime,audit);self.assertEqual(len(runtime[1]),number)
            self.assertTrue(all(len({r.identity for r in row})==3 for row in runtime[1]))

    def test_saved_forgery_rejections(self):
        self.assertEqual({(r['setting'],r['field']) for r in PROBES},{(s,f) for s in ('canonical','workflow')
            for f in ('plan','source_native_sha256','skill_acquired','main_execution_authorized','payment')})
        self.assertEqual(len(PROBES),10);self.assertTrue(all(r['rejected'] for r in PROBES))
