"""Paid need fixtures; no supplied route or successful endpoint enters admission."""
import copy
from dataclasses import replace
import unittest
from tests_c3 import fixtures as ca
from tests_c7_workflow import fixtures as wf
from hle_unified.records import Account, Proposition, ObjectVersion, Role, Occurrence, Moment, TimeScope, ClaimStatus
from hle_unified.material import attributes, attrs
from hle_unified.store import next_version
from hle_unified.operation_records import OperationRequest
from hle_unified.self_content import encode
from hle_unified.selection_records import dumps
from full_theory.demands import DemandLedger
from full_theory.demand_audit import audit_demands
from full_theory.historical import HistoricalController, C, packet, clock


def setup(setting='canonical',tim='iee'):
    return ca.setup_c3(tim) if setting=='canonical' else wf.setup_workflow(tim)


def need(e,setting='canonical',key='need',actor=ca.ALICE,partial=None,weights=(0,0,0,10)):
    target=ca.SAW if setting=='canonical' else wf.DEVICE
    value=(dict(kind='need',weights=weights,commit=False,scope='quantity',amount=4,collective=False)
           if setting=='canonical' else dict(kind='workflow_need',priorities=weights,externalize=False))
    addresses=ca.evidence(e,actor,target)
    source=e.participant_view(actor).detail(addresses[0]).source
    ref=ca.ref(key)
    draft=ObjectVersion(ref,ca.WRITER,'Initial owned need',(Role.INTERPRETATION,),
        (Account(target,(Proposition(target,'c6.need' if setting=='canonical' else 'c7ws.need',
            encode(value),ca.ROOM,TimeScope(Moment(0,0),None)),),Moment(0,0),actor,(source,)),),
        occurrence=Occurrence.INTERPRETATION,attributes=attributes(dict(cue=ca.CUE5,context=ca.ROOM,
            meaning='Initial task state, not invented goal',endorsement='tentative',confidence=None)))
    e.declare('declare:'+key,(draft,))
    r=OperationRequest('bind:'+key,actor,'bind',ca.ROOM,binding=ref,evidence=addresses)
    if partial is None:
        ca.perform(e,r,limit=100000)
    elif partial:
        e.start('start:'+key,r);e.advance('partial:'+key,actor,r.key,1)
    return ref,r


def withdraw(e,ref,status='retracted'):
    old=e.world.resolve(ref);new=next_version(old,attributes=attributes({**attrs(old),'endorsement':status}))
    e.declare('revise:'+ref.identity.key,(new,))
    b=e.participant_view(ca.ALICE)._bindings[ref]
    ca.perform(e,OperationRequest('revise:'+ref.identity.key,ca.ALICE,'bind',ca.ROOM,
        binding=new.ref,evidence=b.particulars),limit=100000)
    return new.ref


def state(tim='iee',pending=False,empty=True):
    st=HistoricalController(tim).agents['A'].st
    positions=list(st.positions)
    positions[1]=replace(positions[1],charge=frozenset() if empty else frozenset({'experience'}))
    return replace(st,positions=tuple(positions),pending=(packet(C.element_at(tim,3)),) if pending else ())


def witness(setting):
    e=setup(setting); ledger=DemandLedger();st=state()
    need(e,setting,key='one');need(e,setting,key='two',weights=(10,0,0,0))
    ledger.scan(e,ca.ALICE,st,limit=1);ledger.scan(e,ca.ALICE,st,limit=1)
    withdraw(e,ca.ref('one'));ledger.scan(e,ca.ALICE,st)
    report=audit_demands(e.world.journal(),e.access.checkpoint(),ledger.events)
    return e,ledger,report


class DemandTests(unittest.TestCase):
    def test_owned_need_in_both_settings(self):
        for setting in ('canonical','workflow'):
            e,l,r=witness(setting)
            self.assertTrue(r['passed']);self.assertEqual((r['demands'],r['pending'],r['suspended']),(2,1,1))
            self.assertTrue(all(d['status']!='fulfilled' for d in l.demands.values()))

    def test_unread_and_partial_cannot_admit(self):
        for setting in ('canonical','workflow'):
            for partial in (False,True):
                e=setup(setting);ref,r=need(e,setting,partial=partial);l=DemandLedger()
                self.assertFalse(l.scan(e,ca.ALICE,state())['admitted'])
                self.assertTrue(audit_demands(e.world.journal(),e.access.checkpoint(),l.events)['passed'])
                if partial:
                    e.advance('finish-partial',ca.ALICE,r.key,100000);e.commit('commit-partial',ca.ALICE,r.key)
                else:
                    ca.perform(e,r,limit=100000)
                self.assertEqual(len(l.scan(e,ca.ALICE,state())['admitted']),1)

    def test_foreign_need_rejected(self):
        for setting in ('canonical','workflow'):
            e=setup(setting);need(e,setting,actor=ca.BOB);l=DemandLedger()
            self.assertFalse(l.scan(e,ca.ALICE,state())['admitted'])
            self.assertTrue(audit_demands(e.world.journal(),e.access.checkpoint(),l.events)['passed'])

    def test_withdrawn_need_suspended(self):
        for setting in ('canonical','workflow'):
            for status in ('retracted','disputed'):
                e=setup(setting);ref,_=need(e,setting);l=DemandLedger();l.scan(e,ca.ALICE,state())
                withdraw(e,ref,status);row=l.scan(e,ca.ALICE,state())
                self.assertEqual(len(row['suspended']),1);self.assertEqual(len(l.demands),1)
                self.assertTrue(audit_demands(e.world.journal(),e.access.checkpoint(),l.events)['passed'])

    def test_hidden_revision_has_no_effect(self):
        for setting in ('canonical','workflow'):
            e=setup(setting);ref,_=need(e,setting);l=DemandLedger();before=l.scan(e,ca.ALICE,state())
            old=e.world.resolve(ref);new=next_version(old,attributes=attributes({**attrs(old),'endorsement':'retracted'}))
            e.declare('hidden-revision',(new,));after=l.scan(e,ca.ALICE,state())
            self.assertEqual(before['demands'],after['demands']);self.assertEqual(before['eligible'],after['eligible'])
            self.assertTrue(audit_demands(e.world.journal(),e.access.checkpoint(),l.events)['passed'])

    def test_new_paid_need_changes_admission(self):
        for setting in ('canonical','workflow'):
            e=setup(setting);l=DemandLedger();self.assertFalse(l.scan(e,ca.ALICE,state())['admitted'])
            before=e.wallet(ca.ALICE)['energy'];need(e,setting)
            self.assertLess(e.wallet(ca.ALICE)['energy'],before)
            self.assertEqual(len(l.scan(e,ca.ALICE,state())['admitted']),1)
            self.assertTrue(audit_demands(e.world.journal(),e.access.checkpoint(),l.events)['passed'])

    def test_duplicate_scan_preserves_age(self):
        e=setup();need(e);l=DemandLedger();a=l.scan(e,ca.ALICE,state());b=l.scan(e,ca.ALICE,state())
        self.assertEqual(a['demands'],b['demands']);self.assertFalse(b['admitted'])
        self.assertTrue(audit_demands(e.world.journal(),e.access.checkpoint(),l.events)['passed'])

    def test_conflicting_needs_stay_distinct(self):
        for setting in ('canonical','workflow'):
            e=setup(setting);need(e,setting,key='a');need(e,setting,key='b',weights=(10,0,0,0))
            l=DemandLedger();l.scan(e,ca.ALICE,state());self.assertEqual(len(l.demands),2)
            self.assertEqual(len({dumps(d['payload']) for d in l.demands.values()}),2)

    def test_bounded_scan_resumes_without_loss(self):
        e=setup()
        for k in ('c','b','a'):need(e,key=k)
        l=DemandLedger();first=l.scan(e,ca.ALICE,state(),limit=1)
        self.assertEqual(len(first['omitted']),2);self.assertEqual(first['cursor'],first['omitted'][0])
        second=l.scan(e,ca.ALICE,state(),limit=1);third=l.scan(e,ca.ALICE,state(),limit=1)
        self.assertEqual(len(l.demands),3);self.assertIsNone(third['cursor'])
        self.assertEqual(first['omitted'],second['admitted']+third['admitted'])
        self.assertEqual({d['first_seen'] for d in l.demands.values()},{0})
        self.assertTrue(audit_demands(e.world.journal(),e.access.checkpoint(),l.events)['passed'])

    def test_checkpoint_exact_continuation(self):
        for setting in ('canonical','workflow'):
            e=setup(setting);need(e,setting,key='a');need(e,setting,key='b');l=DemandLedger()
            l.scan(e,ca.ALICE,state(),limit=1);restored=DemandLedger.restore(l.checkpoint())
            other=type(e).restore(e.checkpoint())
            self.assertEqual(l.scan(e,ca.ALICE,state(),limit=1),restored.scan(other,ca.ALICE,state(),limit=1))
            self.assertEqual(l.checkpoint(),restored.checkpoint());self.assertEqual(e.checkpoint(),other.checkpoint())

    def test_auditor_rejects_scope_and_age_forgery(self):
        e,l,_=witness('canonical')
        for field,value in (('actor',ca.BOB),('target',ca.CUE5),('receipt',ca.SAW),('first_seen',-1)):
            events=copy.deepcopy(l.events);key=next(iter(events[0]['demands']))
            events[0]['demands'][key][field]=value
            with self.assertRaises(ValueError):audit_demands(e.world.journal(),e.access.checkpoint(),events)
        for field,value in (('omitted',[]),('admitted',[]),('cursor',None)):
            events=copy.deepcopy(l.events);events[0][field]=value
            with self.assertRaises(ValueError):audit_demands(e.world.journal(),e.access.checkpoint(),events)
        events=copy.deepcopy(l.events);events[-1]['pressure']['active']=True
        with self.assertRaises(ValueError):audit_demands(e.world.journal(),e.access.checkpoint(),events)

    def test_pressure_truth_table_all_types(self):
        e=setup();l=DemandLedger();cells=[]
        for tim in C.TIMS:
            for pending in (False,True):
                for empty in (False,True):
                    st=state(tim,pending,empty);before=copy.deepcopy(st)
                    row=l.scan(e,ca.ALICE,st)
                    self.assertEqual(row['pressure']['active'],pending and empty)
                    self.assertEqual(row['pressure']['active'],clock.pressure(st));self.assertEqual(st,before)
                    self.assertFalse(row['admitted']);cells.append((tim,pending,empty))
        self.assertEqual(len(cells),64)
        self.assertTrue(audit_demands(e.world.journal(),e.access.checkpoint(),l.events)['passed'])
