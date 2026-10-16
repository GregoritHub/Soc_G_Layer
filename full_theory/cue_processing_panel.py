"""A12D2 exact-input panel adapter; inherited v1 transition policy unchanged."""
from pathlib import Path
import json
from hle_unified.selection_records import loads
from .cue_processing import CueProcessing, owned_plan, digest
PROTOCOL=Path(__file__).resolve().parents[1]/'contracts/ft/FT7_Cue_Processing_Panel_A12D2_Protocol_v1.json'
class CueProcessingPanel(CueProcessing):
    VERSION='ft-owned-cue-processing-panel-a12d2-v2'
    def __init__(self,engine,windows):
        w=loads(windows);native=engine.checkpoint();entries=json.loads(PROTOCOL.read_text())['inputs'];matches=[(k,v) for k,v in entries.items() if k.startswith(w['setting']+'-') and (digest(native),digest(windows))==(v['native_sha256'],v['windows_sha256'])];entry=matches[0][1] if len(matches)==1 else None
        if entry is None or entry['already_processed_a12d']:raise ValueError('exact unprocessed accepted A12C panel source')
        self.source_mask=int(matches[0][0].split('-')[1])
        actor=w['actor'];key='ft-cue-comparison:'+digest(windows);job=engine.job_status(actor,key)
        if job['status']!='succeeded' or engine.window_result(actor,key) is None or actor in engine._locks:raise ValueError('settled unlocked source comparison')
        task=w['fresh_demand'];view=engine.participant_view(actor)
        if view._bindings[task['binding']].receipt!=task['receipt']:raise ValueError('current paid task')
        self.actor=actor;self.setting=w['setting'];self.context=task['context'];self.cue=task['cue'];self.task=task['binding']
        self.source_native_sha256=digest(native);self.source_windows_sha256=digest(windows);self.expected_native_sha256=digest(native);self.start_count=len(engine.world.journal())
        self.plan=owned_plan(view,actor,self.context);self.index=0;self.phase='active' if self.plan else 'complete';self.events=[];self.results=[]
        self.reserve=w['reserve'];self.history=w['history'];self.controller_prefix=w['controller_prefix']
        self.comparison_paid=False;self.execution_authorized=False;self.td5_admitted=False;self.history_choice=False;self.independent_credit=False;self.clearance_claim=False;self.skill_acquired=False
    @classmethod
    def restore(cls,text,engine,original,windows):
        from .cue_processing_panel_audit import audit
        audit(engine,original,windows,text)
        data=loads(text);data.pop('version');obj=cls.__new__(cls);obj.__dict__.update(data)
        if obj.checkpoint(engine)!=text:raise ValueError('v2 adapter roundtrip')
        return obj

