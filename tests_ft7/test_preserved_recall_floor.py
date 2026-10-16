import itertools
import unittest
from hle_unified.selection_records import loads,dumps
from full_theory.preserved_recall_floor import closure,analyze
from full_theory.preserved_recall_floor_audit import audit

CONTEXT={}

class PreservedRecallFloorTests(unittest.TestCase):
    def test_exact_saved_reports(self):
        for setting,native,report in CONTEXT['rows']:
            self.assertEqual(dumps(loads(report)),report)
            self.assertTrue(audit(native,report,setting)['passed'])

    def test_independent_report_forgery_rejection(self):
        for setting,native,report in CONTEXT['rows']:
            row=loads(report)
            changes={'floor':row['floor']+1,'preserved_roots':(), 'graph':(),
                'witness':(), 'scope':'all lawful organization', 'execution_authorized':True,
                'native_sha256':'0'*64, 'all_organization_impossible':True}
            for key,value in changes.items():
                forged=dict(row);forged[key]=value
                with self.assertRaises(ValueError):audit(native,dumps(forged),setting)
                CONTEXT['probes']+=1

    def test_input_binding_rejection(self):
        for setting,native,report in CONTEXT['rows']:
            for wrong in (native+' ', '{}'):
                with self.assertRaises(ValueError):analyze(wrong,setting)
                with self.assertRaises(ValueError):audit(wrong,report,setting)

    def test_boundary_32_33(self):
        for count in (31,32,33,34):
            graph={i:() for i in range(count)}
            result=closure(graph,tuple(graph))
            self.assertEqual(len(result),count)
            self.assertEqual(len(result)>32,count>=33)

    def test_cycles_historical_and_context(self):
        # Historical revisions are separate nodes; missing/other-context nodes
        # are absent from the exact contextual graph, not followed or counted.
        graph={'head':('old',),'old':('head','other-context','missing'),'isolated':()}
        self.assertEqual(closure(graph,('head','head')),('head','old'))

    def test_root_removal_monotonicity(self):
        graph={0:(3,),1:(2,),2:(3,),3:(0,),4:(5,),5:()}
        preserved=(0,);mutable=(1,2,4,5);floor=set(closure(graph,preserved))
        for n in range(5):
            for remaining in itertools.combinations(mutable,n):
                self.assertLessEqual(floor,set(closure(graph,preserved+remaining)))
