import unittest
from copy import deepcopy
from dataclasses import replace
from hle.contracts import ClaimStatus
from hle_unified.records import ObjectId, ObjectRef
from hle_unified.particulars import BindingView, ViewSnapshot, ParticipantView
from full_theory.recall_feasibility import analyze
from full_theory.recall_feasibility_audit import audit


def ref(key, ns='generated', revision=1):
    return ObjectRef(ObjectId(ns, key), revision)


class RecallFeasibilityTests(unittest.TestCase):
    def fixture(self, count=33):
        actor=ObjectId('actor','a'); cue=ref('cue'); context=ref('context')
        refs=[ref('mutable','workshop')]+[ref(str(i)) for i in range(count-1)]
        bindings=tuple(BindingView(r,actor,ref('target'),cue,context,'owned',(),
                        ClaimStatus.ENDORSED,None,(),(refs[(i+1)%count],),ref('receipt'))
                       for i,r in enumerate(refs))
        return ViewSnapshot(actor,(),(),(),bindings,(),()),cue,context

    def test_cycle_and_linked_archived_root(self):
        s,c,x=self.fixture(); v=ParticipantView(s); before=v.bytes()
        r=analyze(v,c,x,ref('task')); self.assertTrue(audit(s,r))
        self.assertEqual(r['best_reachable'],33)
        self.assertTrue(all(z['truncated'] for z in r['rows']))
        self.assertEqual(before,v.bytes())

    def test_current_revision_foreign_and_missing_links(self):
        s,c,x=self.fixture(2); old=s.bindings[0]
        newer=replace(old,ref=ref('mutable','workshop',2),cue=ref('archive'),links=())
        foreign=replace(s.bindings[1],ref=ref('foreign'),context=ref('elsewhere'))
        kept=replace(s.bindings[1],links=(old.ref,foreign.ref,ref('missing')))
        s=replace(s,bindings=(old,kept,newer,foreign)); r=analyze(ParticipantView(s),c,x,ref('task'))
        self.assertTrue(audit(s,r)); self.assertEqual(r['eligible_roots'],())
        self.assertEqual(set(r['rows'][0]['reachable']),{old.ref,kept.ref})

    def test_task_exclusion_and_root_bound(self):
        s,c,x=self.fixture(1); r=analyze(ParticipantView(s),c,x,s.bindings[0].ref)
        self.assertEqual(r['eligible_roots'],()); self.assertTrue(audit(s,r))
        s=replace(s,bindings=tuple(replace(s.bindings[0],ref=ref(str(i),'workshop')) for i in range(3)))
        with self.assertRaises(ValueError): analyze(ParticipantView(s),c,x,ref('task'))

    def test_forged_closure_and_authority_rejected(self):
        s,c,x=self.fixture(); r=analyze(ParticipantView(s),c,x,ref('task'))
        for key,value in [('execution_authorized',True),('visit_limit',33),('best_reachable',32)]:
            bad=deepcopy(r); bad[key]=value
            with self.assertRaises(ValueError): audit(s,bad)
        bad=deepcopy(r); bad['rows'][0]['reachable']=()
        with self.assertRaises(ValueError): audit(s,bad)

if __name__=='__main__': unittest.main()
