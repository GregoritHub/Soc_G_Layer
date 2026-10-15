import copy
import unittest
from tests_ft4.test_demands import need,withdraw,state
from tests_c3 import fixtures as ca
from tests_c7_workflow import fixtures as wf
from hle_unified.selection_execution import SelectionEngine
from hle_unified.workflow_selection_execution import WorkflowSelectionEngine
from hle_unified.store import next_version
from hle_unified.material import attrs,attributes
from full_theory.demands import DemandLedger
from full_theory.demand_audit import audit_demands
from full_theory.demand_requests import form_request
from full_theory.request_audit import audit_request


def fixture(setting,content=1):
    e=(ca.setup_c3(engine_type=SelectionEngine) if setting=='canonical'
       else wf.setup_workflow(engine_type=WorkflowSelectionEngine))
    need(e,setting)
    if setting=='workflow':
        for i in range(content):wf.authored(e,'content-'+str(i))
    l=DemandLedger();l.scan(e,ca.ALICE,state())
    return e,l


def witness(setting):
    e,l=fixture(setting);v=e.participant_view(ca.ALICE)
    request,row=form_request(v,l.demands)
    admission=audit_demands(e.world.journal(),e.access.checkpoint(),l.events)
    report=audit_request(v.bytes(),l.demands,row)
    native=(e.selection_view(request) if setting=='canonical' else e.workflow_selection_view(request))
    return e,l,v,row,dict(**report,admission=admission,native_scope_valid=native['request']['demand']==request.demand)


class RequestTests(unittest.TestCase):
    def test_native_request_both_settings(self):
        for setting in ('canonical','workflow'):
            e,l,v,row,report=witness(setting)
            self.assertTrue(report['passed']);self.assertTrue(report['native_scope_valid'])
            self.assertNotIn('recipe',row['request']);self.assertNotIn('route',row['request'])
            self.assertIsNone(row['request']['peer'])

    def test_inaccessible_withdrawn_and_stale_needs_defer(self):
        for setting in ('canonical','workflow'):
            e,l=fixture(setting)
            self.assertIsNone(form_request(e.participant_view(ca.BOB),l.demands)[0])
            withdraw(e,ca.ref('need'))
            v=e.participant_view(ca.ALICE);r,row=form_request(v,l.demands)
            self.assertIsNone(r);self.assertEqual(row['reason'],'no_current_pending_need')
            self.assertTrue(audit_request(v.bytes(),l.demands,row)['passed'])
            l.scan(e,ca.ALICE,state());self.assertIsNone(form_request(v,l.demands)[0])
            self.assertIsNone(form_request(v,{})[0])

    def test_oldest_demand_selected(self):
        for setting in ('canonical','workflow'):
            e,l=fixture(setting);need(e,setting,key='aaa-newer');l.scan(e,ca.ALICE,state())
            reversed_demands=dict(reversed(tuple(l.demands.items())))
            r,row=form_request(e.participant_view(ca.ALICE),reversed_demands)
            self.assertEqual(r.demand,ca.ref('need'))
            self.assertTrue(audit_request(e.participant_view(ca.ALICE).bytes(),l.demands,row)['passed'])

    def test_hidden_revision_does_not_change_request(self):
        for setting in ('canonical','workflow'):
            e,l=fixture(setting);before=form_request(e.participant_view(ca.ALICE),l.demands)[1]
            old=e.world.resolve(ca.ref('need'))
            e.declare('hidden',(next_version(old,attributes=attributes({**attrs(old),'endorsement':'retracted'})),))
            self.assertEqual(before,form_request(e.participant_view(ca.ALICE),l.demands)[1])

    def test_new_paid_content_changes_request(self):
        e,l=fixture('workflow');before=form_request(e.participant_view(ca.ALICE),l.demands)[1]
        energy=e.wallet(ca.ALICE)['energy'];wf.authored(e,'new-content')
        after=form_request(e.participant_view(ca.ALICE),l.demands)[1]
        self.assertLess(e.wallet(ca.ALICE)['energy'],energy)
        self.assertEqual(len(before['content']),1);self.assertEqual(len(after['content']),2)
        self.assertTrue(audit_request(e.participant_view(ca.ALICE).bytes(),l.demands,after)['passed'])

    def test_workflow_bounds_preserve_omissions(self):
        for count in (0,9):
            e,l=fixture('workflow',count);v=e.participant_view(ca.ALICE);r,row=form_request(v,l.demands)
            self.assertIsNone(r);self.assertEqual(len(row['content']),count)
            self.assertEqual(row['reason'],'no_owned_workflow_content' if count==0 else 'workflow_content_bound_exceeded')
            self.assertTrue(audit_request(v.bytes(),l.demands,row)['passed'])

    def test_exact_restart_and_no_mutation(self):
        for setting in ('canonical','workflow'):
            e,l=fixture(setting);before=e.checkpoint();ledger=l.checkpoint()
            r,row=form_request(e.participant_view(ca.ALICE),l.demands)
            other=type(e).restore(before);restored=DemandLedger.restore(ledger)
            self.assertEqual(row,form_request(other.participant_view(ca.ALICE),restored.demands)[1])
            self.assertEqual(e.checkpoint(),before);self.assertEqual(l.checkpoint(),ledger)

    def test_independent_auditor_rejects_forgery(self):
        e,l,v,row,report=witness('workflow')
        for field,value in (('actor',ca.BOB),('target',ca.CUE5),('key','chosen-route'),('accessible',())):
            bad=copy.deepcopy(row);bad['request'][field]=value
            with self.assertRaises(ValueError):audit_request(v.bytes(),l.demands,bad)
        bad=copy.deepcopy(row);bad['selected']='invented'
        with self.assertRaises(ValueError):audit_request(v.bytes(),l.demands,bad)
