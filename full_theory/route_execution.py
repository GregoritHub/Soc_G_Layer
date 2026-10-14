"""Bounded native execution bridge; no route choice or result supplied by caller.

FT4.2b1 retains native ranking. The full TD5 means policy is a later gate.
Job status is used only to advance owned work, never as content for selection.
"""
from copy import deepcopy
from hashlib import sha256

from hle_unified.material import attrs
from hle_unified.operations import address
from hle_unified.selection_records import SelectionRequest, fields_of, dumps, loads
from hle_unified.workflow_selection_records import WorkflowSelectionRequest
from .route_means import inventory_route_means

TERMINAL = ('succeeded', 'failed', 'cancelled')


class NativeRouteController:
    VERSION = 'ft-native-turn-v1'

    def __init__(self):
        self.attempts = []
        self.events = []

    def step(self, engine, request, *, work_limit=1):
        if type(request) not in (SelectionRequest, WorkflowSelectionRequest):
            raise ValueError('exact route-free native request required')
        if type(work_limit) is not int or work_limit < 1:
            raise ValueError('positive integer work bound required')
        actor, key = request.actor, request.key
        fields = fields_of(request)
        attempt = next((a for a in self.attempts if (a['actor'],a['key']) == (actor,key)), None)
        if attempt is not None and attempt['request'] != fields:
            raise ValueError('attempt identity cannot change its request')
        if attempt is None:
            inventory_route_means(engine, request)  # current exact paid owned request
            if (actor,key) in engine._jobs:
                raise ValueError('cannot adopt an externally started selection')
        before = len(engine.world.journal())
        wallet = dict(engine.wallet(actor))
        event = dict(index=len(self.events), actor=actor, request=fields,
            setting='canonical' if type(request) is SelectionRequest else 'workflow',
            before=before, wallet_before=wallet, work_limit=work_limit,
            action=None, job=None, completion_claim=False)
        cid = 'ft-native-turn:' + str(len(self.events)) + ':' + key
        if attempt is None and actor in engine._locks:
            event.update(action='blocked', state='busy_actor')
        else:
            if attempt is None:
                engine.start(cid+':start', request)
                attempt = dict(actor=actor,key=key,request=fields,setting=event['setting'])
                self.attempts.append(attempt)
            keys = (key,key+':admission',key+':movement')
            active = next((k for k in keys if (actor,k) in engine._jobs
                           and engine.job_status(actor,k)['status'] not in TERMINAL), None)
            if active is not None:
                event['job'] = active
                status = engine.job_status(actor,active)
                if status['status'] != 'ready' and engine.resource_exhausted(actor,active):
                    event.update(action='blocked',state='exhausted')
                else:
                    if status['status'] != 'ready':
                        engine.advance(cid+':work',actor,active,work_limit)
                    if engine.job_status(actor,active)['status'] == 'ready':
                        engine.commit(cid+':commit',actor,active)
                    event.update(action='advance',state=engine.job_status(actor,active)['status'])
            else:
                event.update(action='observe',state='no_active_child')
            parent = engine.job_status(actor,key)
            if parent['status'] in ('failed','cancelled'):
                event['state'] = parent['status']
            namespace = 'c7ws.decision' if event['setting']=='workflow' else 'c6.decision'
            try:
                decision = attrs(engine.world.head(address(namespace,actor,key).identity))
            except KeyError:
                decision = None
            if decision is not None:
                if decision['failure'] is not None:
                    event['state'] = 'native_rejected'
                elif decision['status']=='deferred':
                    event['state'] = 'deferred'
            if (actor,key+':movement') in engine._jobs:
                status=engine.job_status(actor,key+':movement')['status']
                if status in TERMINAL:
                    event['state']='movement_complete' if status=='succeeded' else status
            elif (actor,key+':admission') in engine._jobs:
                status=engine.job_status(actor,key+':admission')['status']
                if status in ('failed','cancelled'):event['state']=status
        event.update(after=len(engine.world.journal()),wallet_after=dict(engine.wallet(actor)))
        event['debit']={unit:wallet[unit]-event['wallet_after'][unit] for unit in ('energy','time')}
        self.events.append(event)
        return deepcopy(event)

    def checkpoint(self,engine):
        return dumps(dict(version=self.VERSION,native_sha256=sha256(engine.checkpoint().encode()).hexdigest(),
                          attempts=self.attempts,events=self.events))

    @classmethod
    def restore(cls,text,engine):
        data=loads(text)
        if (set(data)!={'version','native_sha256','attempts','events'} or data['version']!=cls.VERSION
                or data['native_sha256']!=sha256(engine.checkpoint().encode()).hexdigest()):
            raise ValueError('exact paired native checkpoint required')
        if any(e['index']!=i for i,e in enumerate(data['events'])):
            raise ValueError('invalid turn order')
        result=cls();result.attempts=data['attempts'];result.events=data['events']
        return result
