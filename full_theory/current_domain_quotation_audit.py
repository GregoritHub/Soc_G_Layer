"""Independent A12E2 reconstruction; never imports the new quotation runtime."""
import json
from hashlib import sha256
from math import prod
from pathlib import Path

from hle_unified import codec
from hle_unified.material import attrs
from hle_unified.operation_records import SIGNATURES
from hle_unified.operations import wallet_address
from hle_unified.records import Procedure
from hle_unified.selection_audit import reference as canonical_reference
from hle_unified.selection_execution import SelectionEngine
from hle_unified.selection_records import SelectionRequest, dumps, fields_of, loads
from hle_unified.workflow_selection_audit import reference as workflow_reference
from hle_unified.workflow_selection_execution import WorkflowFinalSelectionEngine
from hle_unified.workflow_selection_records import (
    WorkflowCapacitySelectionRequest,
    WorkflowSelectionRequest,
)

from .cue_comparison import CueCanonicalEngine, CueWorkflowEngine
from .owned_proposal_domain_audit import _snapshot
ROOT = Path(__file__).resolve().parents[1]
PROTOCOL = ROOT / "contracts/ft/FT7_Current_Domain_Quotation_A12E2_Protocol_v1.json"
CANONICAL_KEYS = (
    "cell", "recipe", "origin", "destination", "face", "inputs", "eligible",
    "benefit", "grounding", "effort", "score", "examined", "deferred",
)
WORKFLOW_KEYS = (
    "cell", "recipe", "inputs", "eligible", "priority", "preference",
    "effort", "coverage", "examined", "deferred",
)


def digest(value):
    return sha256(value.encode() if isinstance(value, str) else value).hexdigest()


def independently_reconstruct_request(d, ordinal):
    names = d["role_order"]
    radices = (len(d["windows"]),) + tuple(len(d["pools"][name]) for name in names)
    require(radices == d["radices"] and prod(radices) == d["assignments"], "factor sizes")
    require(type(ordinal) is int and 0 <= ordinal < prod(radices), "ordered ordinal")
    remaining = ordinal
    backward = []
    for radix in reversed(radices):
        remaining, digit = divmod(remaining, radix)
        backward.append(digit)
    digits = tuple(reversed(backward))
    fields = dict(d["windows"][digits[0]])
    for name, digit in zip(names, digits[1:]):
        fields[name] = d["pools"][name][digit]["value"]
    fields["key"] = d["namespace"] + str(ordinal)
    if d["setting"] == "canonical":
        return SelectionRequest(**fields)
    if fields.get("procedure") is not None:
        return WorkflowCapacitySelectionRequest(**fields)
    fields.pop("procedure", None)
    return WorkflowSelectionRequest(**fields)


def snapshot_digest(snapshot, setting):
    if setting == "canonical":
        return digest(dumps(snapshot))

    def pack(value):
        if type(value) is dict:
            if any(type(key) is not str for key in value):
                raise ValueError("quotation audit: string workflow snapshot keys")
            return ("map", tuple((key, pack(value[key])) for key in sorted(value)))
        if type(value) is tuple:
            return ("tuple", tuple(pack(item) for item in value))
        if type(value) is list:
            return ("list", tuple(pack(item) for item in value))
        return ("leaf", value)

    return digest(codec.dumps(pack(snapshot)))


def require(condition, reason):
    if not condition:
        raise ValueError("current-domain quotation audit: " + reason)


class CurrentDomainQuotationAudit:
    def __init__(self, native, domain, setting, mask, raw_sha256):
        entry = json.loads(PROTOCOL.read_text())["inputs"].get(f"{setting}-{mask:02d}")
        require(entry is not None, "registered branch")
        require(
            (digest(native), digest(domain), raw_sha256)
            == (entry["native_sha256"], entry["domain_sha256"], entry["raw_sha256"]),
            "exact accepted source binding",
        )
        d = loads(domain)
        require(
            (
                d.get("version"),
                d.get("setting"),
                d.get("mask"),
                d.get("assignments"),
                d.get("current_native_sha256"),
            )
            == (
                "ft-post-processing-domain-a12e1-v1",
                setting,
                mask,
                entry["assignments"],
                digest(native),
            ),
            "complete current domain",
        )
        cls = CueCanonicalEngine if setting == "canonical" else CueWorkflowEngine
        self.engine = cls.restore(native)
        self.native = native
        self.domain = domain
        self.setting = setting
        self.mask = mask
        self.raw_sha256 = raw_sha256
        self.d = d
        self.before = native
        self.wallet_ref = self.engine.world.head(wallet_address(d["actor"]).identity)
        self.wallet = attrs(self.wallet_ref)
        self.view = self.engine.participant_view(d["actor"])

    def unchanged(self):
        return self.engine.checkpoint() == self.before

    def row(self, ordinal):
        request = independently_reconstruct_request(self.d, ordinal)
        fields = fields_of(request)
        common = {"ordinal": ordinal, "request_sha256": digest(dumps(fields))}
        try:
            snapshot = _snapshot(self.engine, self.view, request, self.setting)
        except ValueError as error:
            return {
                **common,
                "rejection": str(error),
                "required": 1,
                "snapshot_sha256": None,
                "candidates_sha256": None,
                "nominee": None,
                "candidate_count": 0,
                "examined": (),
                "scanned": None,
                "foreign_total": None,
                "items": None,
            }
        if self.setting == "workflow":
            procedure_ref = getattr(request, "procedure", None)
            definition = None
            acquired = ()
            if procedure_ref is not None:
                definitions = [
                    particular.value
                    for particular in self.view.resolve(procedure_ref)
                    if type(particular.value) is Procedure
                ]
                require(len(definitions) == 1, "paid exact repair procedure")
                procedure = definitions[0]
                require(
                    procedure.executor == "u4.repair.v1"
                    and procedure.inputs == SIGNATURES["repair"]
                    and not procedure.steps
                    and not procedure.preconditions
                    and not procedure.effects,
                    "supported native repair procedure",
                )
                definition = {
                    "executor": procedure.executor,
                    "inputs": procedure.inputs,
                    "preconditions": procedure.preconditions,
                    "steps": procedure.steps,
                    "effects": procedure.effects,
                }
                acquired = tuple(
                    (row.procedure, row.context, row.receipt)
                    for row in self.view.snapshot.acquired
                    if row.procedure == procedure_ref and row.context == request.context
                )
            snapshot = dict(
                snapshot,
                policy="c7-workflow-selection-v4",
                procedure=definition,
                acquired=acquired,
            )
        if self.setting == "canonical":
            rows = [dict(canonical_reference(snapshot, cell), cell=cell) for cell in range(33)]
            nominee = min(
                (row for row in rows if row["eligible"] and row["score"] > 0),
                key=lambda row: (-row["score"], row["cell"], dumps(row["inputs"])),
                default=None,
            )
            keys = CANONICAL_KEYS
            required = (
                1
                + snapshot["scanned"]
                + snapshot["foreign_total"]
                + len(rows)
                + sum(row["examined"] for row in rows)
            )
            metadata = {
                "scanned": snapshot["scanned"],
                "foreign_total": snapshot["foreign_total"],
                "items": None,
            }
        else:
            rows, nominee = workflow_reference(snapshot)
            keys = WORKFLOW_KEYS
            required = (
                1
                + len(snapshot["items"])
                + len(rows)
                + sum(row["examined"] for row in rows)
            )
            metadata = {
                "scanned": None,
                "foreign_total": None,
                "items": len(snapshot["items"]),
            }
        projection = tuple({key: row[key] for key in keys} for row in rows)
        examined = tuple(row["examined"] for row in rows)
        expected_cells = 33 if self.setting == "canonical" else 32
        require(
            len(rows) == expected_cells
            and all(type(value) is int and value >= 0 for value in examined),
            "exact native candidate extent",
        )
        return {
            **common,
            "rejection": None,
            "required": required,
            "snapshot_sha256": snapshot_digest(snapshot, self.setting),
            "candidates_sha256": digest(dumps(projection)),
            "nominee": None if nominee is None else nominee["cell"],
            "candidate_count": len(rows),
            "examined": examined,
            **metadata,
        }

    def reconstruct(self, guard=None, progress=None):
        rows = []
        for ordinal in range(self.d["assignments"]):
            if ordinal % 256 == 0:
                if guard is not None:
                    guard()
                if progress is not None:
                    progress(ordinal)
            rows.append(self.row(ordinal))
        total = sum(row["required"] for row in rows)
        energy = self.wallet["energy"]
        time = self.wallet["time"]
        require(self.unchanged(), "native state changed during reconstruction")
        return {
            "version": "ft-current-domain-quotation-a12e2-v1",
            "setting": self.setting,
            "mask": self.mask,
            "raw_sha256": self.raw_sha256,
            "native_sha256": digest(self.native),
            "domain_sha256": digest(self.domain),
            "actor": self.d["actor"],
            "wallet": self.wallet_ref.ref,
            "energy": energy,
            "time": time,
            "assignments": len(rows),
            "rows": tuple(rows),
            "required_energy": total,
            "required_time": total,
            "energy_deficit": max(0, total - energy),
            "time_deficit": max(0, total - time),
            "status": (
                "affordable_quote_only"
                if total <= min(energy, time)
                else "insufficient_exact_quote"
            ),
            "exact_quote": True,
            "may_launch": False,
            "engine_restored": True,
            "native_state_unchanged": True,
            "native_work": False,
            "comparison_paid": False,
            "execution_authorized": False,
            "td5_admitted": False,
            "history_choice": False,
            "parent_accepted": False,
        }

    def audit(self, text, expected):
        decoded = loads(text)
        require(decoded == expected, "exact full independent report")
        require(dumps(decoded) == text, "typed report roundtrip")
        require(
            tuple(row["ordinal"] for row in decoded["rows"])
            == tuple(range(decoded["assignments"])),
            "complete ordered ordinals",
        )
        require(self.unchanged(), "native state changed")
        return {
            "passed": True,
            "setting": self.setting,
            "mask": self.mask,
            "assignments": decoded["assignments"],
            "required": decoded["required_energy"],
            "energy": decoded["energy"],
            "time": decoded["time"],
            "status": decoded["status"],
            "rejected": sum(row["rejection"] is not None for row in decoded["rows"]),
            "native_state_unchanged": True,
            "native_work": False,
            "comparison_paid": False,
            "execution_authorized": False,
            "td5_admitted": False,
            "history_choice": False,
        }

