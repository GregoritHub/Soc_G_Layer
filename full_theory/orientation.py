"""Exact native cp orientation fee; a read never claims a traversal or skill."""
from copy import deepcopy
from hashlib import sha256
from hle_unified.records import Account
from hle_unified.operation_records import OperationRequest
from hle_unified.particulars import Selector, DetailAddress
from hle_unified.selection_records import fields_of, dumps, loads
from .route_means import inventory_route_means


class PaidOrientation:
    VERSION='ft-cp-orientation-v1'

    def __init__(self):
        self.attempts=[]
        self.events=[]

    def _attempt(self,request):
        return next((x for x in self.attempts if (x['actor'],x['key'])==(request.actor,request.key)),None)

    def ticket(self,engine,request):
        attempt=self._attempt(request)
        if attempt is None or attempt['request']!=fields_of(request):return None
        try:current=inventory_route_means(engine,request)
        except ValueError:return None
        if current['active_seat']!=attempt['origin_seat']:return None
        d=engine.job_status(request.actor,attempt['job'])
        if (d['status']!='succeeded' or d['completed']!=2 or d['required']!=2 or d['spent']!=2
                or d.get('input.0')!=request.demand or d['delivery']!=attempt['delivery']):return None
        p=engine.participant_view(request.actor).detail(DetailAddress(attempt['delivery'],'ft.cp.task'))
        if p is None or p.source!=request.demand or p.value!=attempt['payload']:return None
        return dict(job=attempt['job'],operation=engine._jobs[request.actor,attempt['job']],
                    actor=request.actor,demand=request.demand,delivery=attempt['delivery'],
                    energy=2,time=2,origin_seat=attempt['origin_seat'],target_seat=attempt['target_seat'],
                    traversal_claim=False,completion_claim=False)

    def step(self,engine,request,*,work_limit=1):
        if type(work_limit) is not int or work_limit<1:raise ValueError('positive integer read work bound required')
        attempt=self._attempt(request)
        if attempt is not None and attempt['request']!=fields_of(request):raise ValueError('immutable orientation request required')
        if attempt is None:
            inventory=inventory_route_means(engine,request);cp=inventory['options'][2]
            if not cp['eligible']:raise ValueError('full orientation fee must be affordable at admission')
            if request.actor in engine._locks:raise ValueError('free actor required before orientation admission')
            job=cp['orientation_read'];delivery='ft-cp-delivery:'+request.key
            if (request.actor,job) in engine._jobs:raise ValueError('cannot adopt existing orientation work')
            binding=engine.participant_view(request.actor)._bindings[request.demand]
            source=engine.world.resolve(request.demand)
            accounts=[(i,f) for i,f in enumerate(source.facets) if type(f) is Account]
            if len(accounts)!=1 or accounts[0][1].content!=binding.content or accounts[0][1].holder!=request.actor:
                raise ValueError('exact owned source account required')
            path=('facets',str(accounts[0][0]),'content','0','object')
            attempt=dict(actor=request.actor,key=request.key,request=fields_of(request),
                job=job,delivery=delivery,payload=binding.content[0].object,path=path,
                origin_seat=cp['origin_seat'],target_seat=cp['target_seat'],tim=inventory['tim'],
                setting=inventory['setting'],admission_view=inventory['view'],inventory=inventory)
        before=len(engine.world.journal());wallet=dict(engine.wallet(request.actor))
        cid='ft-cp:'+request.key+':'+str(len(self.events))
        if self._attempt(request) is None:
            engine.disclose(attempt['delivery'],request.actor,request.demand,
                (Selector('ft.cp.task','definition',attempt['path']),),request.demand)
            engine.start(cid+':start',OperationRequest(attempt['job'],request.actor,'read',
                         request.context,delivery=attempt['delivery']))
            self.attempts.append(attempt)
        d=engine.job_status(request.actor,attempt['job'])
        if d['status'] not in ('succeeded','failed','cancelled'):
            if d['status']!='ready' and not engine.resource_exhausted(request.actor,attempt['job']):
                engine.advance(cid+':work',request.actor,attempt['job'],work_limit)
            if engine.job_status(request.actor,attempt['job'])['status']=='ready':
                engine.commit(cid+':commit',request.actor,attempt['job'])
        d=engine.job_status(request.actor,attempt['job']);after_wallet=dict(engine.wallet(request.actor))
        row=dict(index=len(self.events),actor=request.actor,key=request.key,job=attempt['job'],
            before=before,after=len(engine.world.journal()),wallet_before=wallet,wallet_after=after_wallet,
            debit={u:wallet[u]-after_wallet[u] for u in ('energy','time')},work_limit=work_limit,
            status=d['status'],ticket=self.ticket(engine,request),view=engine.participant_view(request.actor).bytes())
        self.events.append(row)
        return deepcopy(row)

    def checkpoint(self,engine):
        return dumps(dict(version=self.VERSION,native_sha256=sha256(engine.checkpoint().encode()).hexdigest(),
                          attempts=self.attempts,events=self.events))

    @classmethod
    def restore(cls,text,engine):
        d=loads(text)
        if set(d)!={'version','native_sha256','attempts','events'} or d['version']!=cls.VERSION or d['native_sha256']!=sha256(engine.checkpoint().encode()).hexdigest():
            raise ValueError('exact paired orientation checkpoint required')
        if any(e['index']!=i for i,e in enumerate(d['events'])):raise ValueError('invalid orientation event order')
        result=cls();result.attempts=d['attempts'];result.events=d['events'];return result
