import gc
import os
from pathlib import Path
import unittest
from hle_unified.selection_records import loads, dumps
from full_theory.owned_proposal_domain import owned_proposal_domain
from full_theory.owned_proposal_domain_audit import audit_owned_proposal_domain
from tests_ft7.test_social_live_outcome import source, read_record


def saved(setting,case):
    return read_record(Path(os.environ['FT7_DOMAIN_OUTPUT'])/'records'/(setting+'-'+case+'.json.gz'))


class OwnedProposalDomainTests(unittest.TestCase):
    def test_exact_cell_domain(self):
        for setting,n in (('canonical',33),('workflow',32)):
            for case in ('harder','partial-movement'):
                key,_,_,_,text=saved(setting,case);d=loads(text)
                self.assertEqual([x['cell'] for x in d['candidates']],list(range(n)))
                self.assertFalse(d['execution_authorized']);self.assertFalse(d['comparison_paid'])
            self.assertEqual(loads(saved(setting,'live')[-1])['candidates'],[])

    def test_owned_oldest_request(self):
        for setting in ('canonical','workflow'):
            _,_,s,_,text=saved(setting,'harder');d=loads(text)
            controller=loads(loads(s)['demand_controller']);ledger=loads(controller['ledger'])
            pending=[(k,x) for k,x in ledger['demands'].items() if x['status']=='pending' and k not in controller['outcomes']]
            first=min(pending,key=lambda pair:(pair[1]['first_seen'],pair[0]))
            self.assertEqual(d['formation']['selected'],first[0]);self.assertEqual(d['request']['demand'],first[1]['binding'])
            self.assertEqual(loads(saved(setting,'live')[-1])['formation']['reason'],'no_current_pending_need')

    def test_native_and_history_unchanged(self):
        for setting in ('canonical','workflow'):
            e,s,b=source(setting,'harder');before=e.checkpoint();text=owned_proposal_domain(e,s,b)
            self.assertEqual(e.checkpoint(),before);self.assertEqual(text,saved(setting,'harder')[-1])
            self.assertEqual(loads(b)['history'],loads(saved(setting,'harder')[3])['history'])
            del e,s,b,before,text;gc.collect()

    def test_independent_reconstruction(self):
        for setting in ('canonical','workflow'):
            e,s,b=source(setting,'harder');report=audit_owned_proposal_domain(e,s,b,saved(setting,'harder')[-1])
            self.assertTrue(report['passed']);self.assertGreater(report['comparison_required'],0)
            self.assertFalse(report['execution_authorized']);del e,s,b;gc.collect()

    def _reject(self,change):
        e,s,b=source('canonical','harder');d=loads(saved('canonical','harder')[-1]);change(d)
        with self.assertRaises(ValueError):audit_owned_proposal_domain(e,s,b,dumps(d))

    def test_omitted_cell_rejected(self):self._reject(lambda d:d['candidates'].pop())
    def test_forged_eligibility_rejected(self):
        self._reject(lambda d:d['candidates'][0].update(eligible=not d['candidates'][0]['eligible']))
    def test_unpaid_cost_forgery_rejected(self):
        self._reject(lambda d:d.update(comparison_required=d['comparison_required']-1))
    def test_hidden_content_rejected(self):
        self._reject(lambda d:d['snapshot']['items'].pop())
    def test_wrong_source_pair_rejected(self):
        self._reject(lambda d:d.update(source_sha256='0'*64))
    def test_false_completeness_rejected(self):
        self._reject(lambda d:d.update(bounded_search_complete=not d['bounded_search_complete']))
