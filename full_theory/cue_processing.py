"""Paid situated processing of every already received opportunity under a new cue."""
from copy import deepcopy
from hashlib import sha256
from pathlib import Path
import json
from hle_unified.records import ObjectRef
from hle_unified.particulars import DetailAddress
from hle_unified.shell_records import EncounterRequest
from hle_unified.shell_policy import facts
from hle_unified.material import attrs
from hle_unified.selection_records import loads,dumps
PROTOCOL=Path(__file__).resolve().parents[1]/'contracts/ft/FT7_Cue_Processing_A12D_Protocol_v1.json'
def digest(t):return sha256(t.encode()).hexdigest()
def owned_plan(view,actor,context):
    groups={}
    for p in view.snapshot.particulars:groups.setdefault(p.source,{})[p.address.key]=p.value
    targets=sorted({d['target'] for d in groups.values() if d.get('schema')=='u7.encounter-facts-v1' and d.get('receiver')==actor and d.get('context')==context and type(d.get('target')) is ObjectRef},key=dumps)
    if len(targets)>16:raise ValueError('registered opportunity bound')
    result=[]
    for target in targets:
        known,sources=facts(view,target,context)
        evidence=tuple((p.address.delivery,p.address.key) for source in sources for p in view.resolve(source))
        result.append(dict(target=target,known=known,sources=sources,evidence=evidence))
    return tuple(result)
class CueProcessing:
    VERSION='ft-owned-cue-processing-a12d-v1'
    def __init__(self,engine,windows):
        w=loads(windows);entry=json.loads(PROTOCOL.read_text())['inputs'].get(w['setting']);native=engine.checkpoint()
        if entry is None or (digest(native),digest(windows))!=(entry['native_sha256'],entry['windows_sha256']):raise ValueError('exact accepted A12C mask1 complete source')
        actor=w['actor'];key='ft-cue-comparison:'+digest(windows);job=engine.job_status(actor,key)
        if job['status']!='succeeded' or engine.window_result(actor,key) is None or actor in engine._locks:raise ValueError('settled unlocked source comparison')
        task=w['fresh_demand'];view=engine.participant_view(actor)
        if view._bindings[task['binding']].receipt!=task['receipt']:raise ValueError('current paid task')
        self.actor=actor;self.setting=w['setting'];self.context=task['context'];self.cue=task['cue'];self.task=task['binding']
        self.source_native_sha256=digest(native);self.source_windows_sha256=digest(windows);self.expected_native_sha256=digest(native);self.start_count=len(engine.world.journal())
        self.plan=owned_plan(view,actor,self.context);self.index=0;self.phase='active' if self.plan else 'complete';self.events=[];self.results=[]
        self.reserve=w['reserve'];self.history=w['history'];self.controller_prefix=w['controller_prefix']
        self.comparison_paid=False;self.execution_authorized=False;self.td5_admitted=False;self.history_choice=False;self.independent_credit=False;self.clearance_claim=False;self.skill_acquired=False
    def key(self):return 'ft-cue-processing:'+self.source_native_sha256+':'+str(self.index)
    def step(self,engine,*,work_limit=1,commit_ready=True,cancel=False):
        if type(work_limit) is not int or work_limit<1 or type(commit_ready) is not bool or type(cancel) is not bool:raise ValueError('exact lifecycle quantum/flags')
        if digest(engine.checkpoint())!=self.expected_native_sha256:raise ValueError('exact paired native state')
        if self.phase in ('complete','cancelled','failed'):return None
        item=self.index;key=self.key();cid=key+':step:'+str(len(self.events));row=self.plan[item];before=len(engine.world.journal());wallet=dict(engine.wallet(self.actor));cursor=engine._cursors[self.actor]
        existed=(self.actor,key) in engine._jobs
        if cancel and not existed:raise ValueError('existing partial job required')
        if not existed:
            request=EncounterRequest(key,self.actor,row['target'],self.context,self.cue,row['target'],ObjectRef(self.actor,1),tuple(DetailAddress(*a) for a in row['evidence']))
            engine.start(cid+':start',request)
        if cancel:engine.cancel(cid+':cancel',self.actor,key);self.phase='cancelled'
        else:
            status=engine.job_status(self.actor,key)['status']
            if status not in ('ready','succeeded','failed','cancelled'):engine.advance(cid+':work',self.actor,key,work_limit)
            if commit_ready and engine.job_status(self.actor,key)['status']=='ready':engine.commit(cid+':commit',self.actor,key)
        op=engine.job_status(self.actor,key);status=op['status']
        if not cancel and status in ('succeeded','failed'):
            encounter=op.get('encounter');data=None if encounter is None else attrs(engine.world.resolve(encounter))
            self.results.append(dict(index=item,job=key,status=status,encounter=encounter,intent=None if data is None else data['route'],reason=None if data is None else data['reason'],failure=op.get('failure')))
            if status=='failed':self.phase='failed'
            else:
                self.index+=1
                if self.index==len(self.plan):self.phase='complete'
        after=dict(engine.wallet(self.actor));event=dict(index=len(self.events),item=item,job=key,before=before,after=len(engine.world.journal()),work_limit=work_limit,commit_ready=commit_ready,cancel=cancel,status=status,wallet_before=wallet,wallet_after=after,debit={u:wallet[u]-after[u] for u in ('energy','time')},cursor_before=cursor,cursor_after=engine._cursors[self.actor])
        self.events.append(event);self.expected_native_sha256=digest(engine.checkpoint());return deepcopy(event)
    def checkpoint(self,engine):
        if digest(engine.checkpoint())!=self.expected_native_sha256:raise ValueError('exact native pairing')
        return dumps(dict(version=self.VERSION,**deepcopy(self.__dict__)))
    @classmethod
    def restore(cls,text,engine,original,windows):
        from .cue_processing_audit import audit
        audit(engine,original,windows,text);data=loads(text);data.pop('version');obj=cls.__new__(cls);obj.__dict__.update(data)
        if obj.checkpoint(engine)!=text:raise ValueError('adapter roundtrip')
        return obj
