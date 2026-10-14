"""FT7.1b1 packet-mediated owned social support and native later use.

No peer success, route, recipe or certificate is supplied to the actor cycle.
Autonomous peer generation and social retention remain the next parent seam.
"""
from copy import deepcopy
from dataclasses import replace
from hashlib import sha256

from hle_unified.selection_records import dumps, loads, fields_of
from hle_unified.workflow_selection_records import WorkflowSelectionRequest
from hle_unified.self_content import decode
from .packet_channel import PacketChannel
from .reserve import ReserveLedger
from .reserve_cycle import ReserveAutonomousController, _same_scope, _support_request
from .retention import Demand
from .use_history import UseHistoryLedger, classifications_for, native_snapshot


class _PublicIntakeReserveController(ReserveAutonomousController):
    """Wrapper-local v1 public intake bridge; inherited request record stays exact."""

    def step(self, engine, historical_state, demand, *, work_limit=1):
        if self.phase!="scan":
            return super().step(engine,historical_state,demand,work_limit=work_limit)
        if type(demand) is not Demand or type(work_limit) is not int or work_limit<1:
            raise ValueError("exact demand and positive native work bound required")
        self.required=demand.record()
        request,cycle=self.demand_controller.cycle(engine,self.actor,historical_state)
        bridge=None
        if request is not None and type(request) is WorkflowSelectionRequest:
            view=engine.participant_view(self.actor)
            found=set()
            for detail in view.lookup(key="payload"):
                if detail.source.identity.namespace!="c7w.message":continue
                body=decode(detail.value)
                if (body.get("context"),body.get("target"))!=(request.context,request.target):continue
                own_offer=(body.get("kind")=="offer" and body.get("speaker")==self.actor
                           and body.get("receiver") in demand.support_allowed)
                peer_reply=(body.get("kind")=="reply" and body.get("speaker") in demand.support_allowed
                            and body.get("receiver")==self.actor)
                if own_offer or peer_reply:found.add(detail.source)
            before=tuple(request.accessible)
            after=tuple(sorted(set(before)|found,key=dumps))
            if len(after)>8:
                raise ValueError("owned workflow public intake exceeds unchanged eight-input bound")
            bridge=dict(policy="owned-public-workflow-intake-v1",base_request=fields_of(request),
                before=before,after=after,added=tuple(ref for ref in after if ref not in before),
                view_sha256=sha256(view.bytes().encode()).hexdigest())
            request=replace(request,accessible=after)
        if request is None:
            self.phase="deferred"
            self.terminal=self._record(kind="terminal",reason=cycle["request"]["reason"],
                request=None,candidate=None,consumer=None,settlement=None,effect=None,public_intake=bridge)
            return deepcopy(self.terminal)
        if not _same_scope(request,demand):
            raise ValueError("formed request differs from scoped social demand")
        self.request=_support_request(engine,request,demand)
        self.phase="route"
        return self._record(kind="scan",reason=cycle["request"]["reason"],request=fields_of(self.request),
            candidate=None,consumer=None,settlement=None,effect=None,public_intake=bridge)


class SocialSupportCycle:
    VERSION = "ft-packet-mediated-support-cycle-v1"

    def __init__(self, engine, actor, participants):
        self.actor = actor
        self.channel = PacketChannel(engine, participants)
        if actor not in self.channel.participants:
            raise ValueError("cycle actor must be a declared channel participant")
        self.cycle = _PublicIntakeReserveController(engine, ReserveLedger(actor,"load-v1",initial=4))
        self.history = UseHistoryLedger(actor,"success-v1",tuple(engine.world.journal()))
        self.baseline = native_snapshot(tuple(engine.world.journal()),actor)
        self.packet_key = None
        self.required = None
        self.phase = "intake"
        self.turn = 0
        self.events = []
        self.terminal = None

    def queue_reply(self, sender, operation_key, output=None):
        if self.turn or self.packet_key is not None or sender == self.actor:
            raise ValueError("one pre-cycle peer opportunity may be queued")
        key="social-reply:"+sha256(dumps((sender,operation_key,output,self.actor)).encode()).hexdigest()
        packet=self.channel.emit(key,sender,operation_key,self.actor,output)
        self.packet_key=key
        return packet

    def _history_settlement(self, engine):
        transactions=tuple(engine.world.journal())
        before=transactions[:self.baseline["journal_count"]]
        if native_snapshot(before,self.actor)!=self.baseline:
            raise ValueError("immutable pre-cycle journal baseline changed")
        completed=self.cycle.phase=="complete"
        supported=bool(completed and self.cycle.effects[-1]["supported"])
        tag="supported" if supported else "independent" if completed else "failed"
        outcome=dict(status="succeeded" if completed else "cancelled" if self.cycle.phase=="cancelled" else "failed",
            supported=supported,rehearsal=False,demand_id=self.cycle.request.key,
            route_id=self.cycle.request.key)
        current=native_snapshot(transactions,self.actor)
        delta=sum(current["counts"][e]-self.baseline["counts"][e] for e in current["counts"])
        rows=classifications_for(before,transactions,self.actor,1,tag,outcome) if delta else ()
        return self.history.observe(transactions,1,rows)

    def _link(self):
        if self.cycle.phase!="complete" or not self.cycle.effects[-1]["supported"]:
            return None
        route=self.cycle.candidates.route_policy._attempt(self.cycle.request)
        support=route["support"]
        receipt=self.channel.bridge.receipts.get(self.packet_key)
        packet=self.channel.bridge.packets.get(self.packet_key)
        if receipt is None or packet is None or support["ref"]!=packet["output"]:
            raise ValueError("supported completion must consume the received peer reply")
        movement=route["traversal"]
        settlement=self.cycle.terminal["settlement"]
        return dict(packet=self.packet_key,sender=packet["sender"],receiver=self.actor,
            peer_operation=packet["operation"],source=packet["output"],uptake_receipt=receipt["receipt"],
            support=deepcopy(support),selection=movement["selection"],movement=movement["movement"],
            movement_output=movement["movement_output"],consumer_key=self.cycle.consumer_key,
            consumer_output=settlement["consumer_output"],supported=True,independent_capability=False)

    def step(self, engine, historical_state, demand, *, available, work_limit=1):
        if engine is not self.channel.bridge.engine or type(demand) is not Demand:
            raise ValueError("exact native owner and scoped demand required")
        if type(work_limit) is not int or work_limit<1:
            raise ValueError("positive exact native work bound required")
        if self.required is not None and self.required!=demand.record():
            raise ValueError("cycle demand identity cannot change")
        if self.terminal is not None:
            return deepcopy(self.terminal)
        self.required=demand.record();self.turn+=1
        before=len(engine.world.journal())
        intake=self.channel.step(available=available,work_limit=work_limit)
        waiting=self.packet_key is not None and self.channel.queue[self.packet_key]["status"]!="delivered"
        cycle_event=None;history_event=None;link=None
        if waiting:
            reason="pending_paid_peer_uptake"
        else:
            self.phase="cycle"
            cycle_event=self.cycle.step(engine,historical_state,demand,work_limit=work_limit)
            reason=cycle_event["reason"]
            if self.cycle.terminal is not None:
                self.phase=self.cycle.phase
                history_event=self._history_settlement(engine)
                link=self._link()
        event=dict(index=len(self.events),turn=self.turn,phase=self.phase,reason=reason,
            before=before,after=len(engine.world.journal()),intake=intake,
            cycle_event=cycle_event,history_event=history_event,causal_link=link)
        self.events.append(event)
        if self.cycle.terminal is not None:self.terminal=deepcopy(event)
        return deepcopy(event)

    def checkpoint(self, engine):
        if engine is not self.channel.bridge.engine:
            raise ValueError("paired native engine required")
        return dumps(dict(version=self.VERSION,native_sha256=sha256(engine.checkpoint().encode()).hexdigest(),
            actor=self.actor,baseline=deepcopy(self.baseline),packet_key=self.packet_key,required=self.required,
            phase=self.phase,turn=self.turn,channel=self.channel.checkpoint(),cycle=self.cycle.checkpoint(engine),
            history=self.history.checkpoint(),events=deepcopy(self.events),terminal=deepcopy(self.terminal)))

    @classmethod
    def restore(cls, text, engine):
        d=loads(text)
        if d.get("version")!=cls.VERSION or d.get("native_sha256")!=sha256(engine.checkpoint().encode()).hexdigest():
            raise ValueError("exact paired social-cycle checkpoint required")
        from .social_cycle_audit import audit_social_cycle
        audit_social_cycle(engine,text)
        result=cls.__new__(cls)
        for name in ("actor","baseline","packet_key","required","phase","turn","events","terminal"):
            setattr(result,name,deepcopy(d[name]))
        result.channel=PacketChannel.restore(d["channel"],engine)
        result.cycle=_PublicIntakeReserveController.restore(d["cycle"],engine)
        result.history=UseHistoryLedger.restore(d["history"])
        if result.checkpoint(engine)!=text:
            raise ValueError("social-cycle restoration differs")
        return result
