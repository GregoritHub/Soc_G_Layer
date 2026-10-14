"""Independent owned task/content opportunities; no training response/practice supplied."""
from tests_c5 import fixtures as f
from tests_ft7.peer_fixtures import opportunity
from tests_ft7.test_peer_cycle import finish
from tests_ft4.test_autonomous_closure import install_shell_opportunities
from dataclasses import replace
from hle_unified.operation_records import OperationRequest
from tests_c3 import fixtures as ca
from tests_c7_workflow import fixtures as wf
from full_theory.peer_cycle import AutonomousPeerCycle
from full_theory.social_training import SocialTrainingController
from full_theory.content import ContentBridge
from hle_unified.shell_records import Effect


def training_opportunity(setting,mode='independent'):
    e,d=opportunity(setting)
    c=AutonomousPeerCycle(e,f.ALICE,f.BOB,setting);finish(e,c,d)
    if c.phase!='complete':raise AssertionError('social entry fixture did not complete: '+setting+'/'+mode+':'+c.phase)
    training=SocialTrainingController(e,c)
    install_shell_opportunities(e)
    pattern=e._patterns[f.dev.inject(e,Effect('approval'),key='training-pattern')]
    for i,target in enumerate((f.SAW,f.SAW2)):
        if mode!='missing-correction':f.dev.release8(e,'training-release-'+str(i),pattern,target)
        f.dev.supply8(e,'training-current-'+str(i),target=target,approved=mode=='supported')
    if mode!='missing-content':
        for i,target in enumerate((f.SAW,f.SAW2)):
            key='training-content-'+str(i)
            source=ca.SUPPLY if setting=='canonical' else target
            event=f.perform(e,OperationRequest(key+'-inspect',f.ALICE,'inspect',f.ROOM,target=source,evidence=f.evidence(e,f.ALICE,source)),limit=100000)
            observation=f.receive(e,event,f.ALICE,key+'-observation')
            request=(replace(ca.req(e,key+'-model','organize-accumulation-v1',(observation,)),target=target,evidence=f.evidence(e,f.ALICE,target)) if setting=='canonical' else wf.request(e,key+'-model','Organize','accumulation',(observation,),target=target))
            ContentBridge(e).execute(request,consumed=(observation,))
    return e,training,d
