"""Independent A10R wrapper audit over unchanged full v1 native audit."""
from hashlib import sha256
from hle_unified import codec
from hle_unified.selection_records import loads,dumps
from hle_unified.workflow_records import WorkflowRequest
from hle_unified.particulars import DetailAddress
from .owned_content_rehearsal_audit import audit as audit_base

def audit(engine,original,adapter,setting,text):
    def require(ok,why):
        if not ok:raise ValueError('A10R audit: '+why)
    d=loads(text);require(set(d)=={'version','base','rejections'} and d['version']=='ft-owned-content-rehearsal-a10r-v1','wrapper schema')
    result=audit_base(engine,original,adapter,setting,d['base']);b=loads(d['base']);rejected=d['rejections']
    require(type(rejected) is list and len(rejected)<=1,'bounded rejection')
    if rejected:
        require(setting=='workflow' and b['phase']=='rehearse' and b['index']==len(b['plan'])-1,'final original workflow row')
        row=b['plan'][b['index']];require(row['kind']=='intention' and row['recipe']=='workflow-use-personal-v1','native kind mismatch')
        key='ft-rehearsal-a10:'+b['source_native_sha256']+':'+str(b['index'])
        req=WorkflowRequest(key,b['actor'],row['recipe'],row['context'],row['cue'],(row['source'],),
            tuple(DetailAddress(*v) for v in row['evidence']),row['target'])
        before=engine.checkpoint();message=None
        try:engine._prepare_workflow(req)
        except ValueError as error:message=str(error)
        require(message=='native output consumer required' and engine.checkpoint()==before and (b['actor'],key) not in engine._jobs,'exact independent unchanged preflight')
        expected=dict(index=b['index'],source=row['source'],recipe=row['recipe'],request_sha256=sha256(codec.dumps(('WorkflowRequest',req.key,req.actor,req.recipe,req.context,req.cue,req.inputs,tuple((x.delivery,x.key) for x in req.evidence),req.target,req.stock,req.relation,req.peer,req.group,req.completed,req.clock,req.elements)).encode()).hexdigest(),
            native_sha256=sha256(before.encode()).hexdigest(),message=message,status='rejected',energy=0,time=0)
        require(rejected==[expected],'exact rejection witness')
        result.update(phase='complete',results=result['results']+('rejected',))
    result.update(rejections=len(rejected),rejection_debit=0)
    return result
