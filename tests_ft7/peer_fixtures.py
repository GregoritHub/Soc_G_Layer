"""Fixed owned opportunities; no supplied peer request, reply, or receiver uptake."""
from hle_unified.selection_execution import SelectionEngine
from hle_unified.workflow_selection_execution import WorkflowFinalSelectionEngine
from hle_unified.self_content import encode
from tests_c3 import fixtures as ca
from tests_c6 import fixtures as c6
from tests_c7_workflow import fixtures as wf
from full_theory.retention import Demand


def opportunity(setting, consent=True, stance=True, offer=True):
    if setting=='canonical':
        e=c6.setup(tim='eii',engine_type=SelectionEngine)
        c6.dev.supply8(e,'neutral')
        source=ca.model(e,'peer-model')
        group=ca.join(e,ca.group(e,'peer-group'),key='peer-join')['ref']
        for actor in (ca.ALICE,ca.BOB):ca.expose_group(e,actor,group)
        offer_ref=None
        if offer:
            ca.work(e,ca.req(e,'peer-offer','offer-system-v1',(source,),peer=ca.BOB,group=group,demand=1))
            offer_ref=e.job_status(ca.ALICE,'peer-offer')['public.0'];ca.expose(e,ca.ALICE,offer_ref)
        if stance:ca.seed_intent(e,'peer-owned-stance',cap=2,consent=consent,actor=ca.BOB)
        target=ca.SAW
        for obj in (c6.SAW,c6.KIT,c6.STOCK,c6.SUPPLY):c6.expose(e,ca.ALICE,e.world.head(obj.identity).ref)
        c6.need(e,'peer-owned-need',weights=(0,0,10,0),collective=True)
    else:
        e=wf.setup_workflow(tim='eii',engine_type=WorkflowFinalSelectionEngine)
        source=wf.model(e,'peer-model')
        group=ca.join(e,ca.group(e,'peer-group'),key='peer-join')['ref']
        for actor in (ca.ALICE,ca.BOB):ca.expose_group(e,actor,group)
        rows=wf.data(e,source)['tasks'];own=wf.authored(e,'peer-offer-stance',rows,kind='stance')
        offer_ref=None
        if offer:
            wf.work(e,wf.request(e,'peer-offer','offer-system',None,(source,own),peer=ca.BOB,group=group,completed=(rows[0][0],),clock=1))
            offer_ref=e.job_status(ca.ALICE,'peer-offer')['public.0'];wf.expose(e,ca.ALICE,offer_ref)
        if stance:wf.authored(e,'peer-owned-stance',rows,actor=ca.BOB,kind='stance',consent=consent)
        target=wf.DEVICE
        ca.seed(e,'peer-owned-need',encode(dict(kind='workflow_need',priorities=(0,0,10,0),externalize=False)),target=target,relation='c7ws.need')
    if offer_ref is not None and e.participant_view(ca.BOB).resolve(offer_ref):raise AssertionError('peer must require paid offer uptake')
    if any(owner==ca.BOB and 'reply' in key for owner,key in e._jobs):raise AssertionError('peer production must start empty')
    return e,Demand(setting,ca.ROOM,ca.CUE5,target,requirements=('experience','norms','situation','time'),load=1,support_allowed=(ca.BOB,))
