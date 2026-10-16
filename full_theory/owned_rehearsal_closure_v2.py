"""A10R wrapper: preserve v1 paid evidence and retain exact native preflight rejection."""
from hashlib import sha256
from hle_unified import codec
from hle_unified.selection_records import loads,dumps
from hle_unified.workflow_records import WorkflowRequest
from hle_unified.particulars import DetailAddress
from .owned_content_rehearsal import OwnedContentRehearsal

VERSION='ft-owned-content-rehearsal-a10r-v1'
def digest(s):return sha256(s.encode()).hexdigest()
def request_for(base):
    row=base.plan[base.index]
    key='ft-rehearsal-a10:'+base.source_native_sha256+':'+str(base.index)
    return WorkflowRequest(key,base.actor,row['recipe'],row['context'],row['cue'],(row['source'],),
        tuple(DetailAddress(*x) for x in row['evidence']),row['target'])

class RehearsalClosure:
    def __init__(self,base):self.base=base;self.rejections=[]
    @property
    def phase(self):return 'complete' if self.rejections else self.base.phase
    def checkpoint(self,e):
        return dumps(dict(version=VERSION,base=self.base.checkpoint(e),rejections=self.rejections))
    def step(self,e,*,work_limit=1000000,cancel=False):
        if self.phase in ('complete','cancelled'):return
        before=e.checkpoint();base_before=self.base.checkpoint(e)
        try:self.base.step(e,work_limit=work_limit,cancel=cancel)
        except ValueError as error:
            b=self.base;row=b.plan[b.index]
            if cancel or b.setting!='workflow' or row['kind']!='intention' or row['recipe']!='workflow-use-personal-v1' or str(error)!='native output consumer required':raise
            req=request_for(b)
            if e.checkpoint()!=before or b.checkpoint(e)!=base_before or (b.actor,req.key) in e._jobs:raise ValueError('rejection mutated state')
            if b.index!=len(b.plan)-1:raise ValueError('only final fixed rejected candidate supported')
            self.rejections.append(dict(index=b.index,source=row['source'],recipe=row['recipe'],request_sha256=digest(codec.dumps(('WorkflowRequest',req.key,req.actor,req.recipe,req.context,req.cue,req.inputs,tuple((x.delivery,x.key) for x in req.evidence),req.target,req.stock,req.relation,req.peer,req.group,req.completed,req.clock,req.elements))),
                native_sha256=digest(before),message=str(error),status='rejected',energy=0,time=0))
    @classmethod
    def restore(cls,text,e,original,adapter,setting):
        from .owned_rehearsal_closure_audit_v2 import audit
        audit(e,original,adapter,setting,text);d=loads(text);v=loads(d['base']);v.pop('version')
        b=OwnedContentRehearsal.__new__(OwnedContentRehearsal);b.__dict__.update(v)
        o=cls(b);o.rejections=d['rejections']
        if o.checkpoint(e)!=text:raise ValueError('exact closure restore')
        return o
