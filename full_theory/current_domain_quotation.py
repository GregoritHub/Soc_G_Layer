"""A12E2 exact read-only native quotation over every current A12E1 request."""
import json
from hashlib import sha256
from math import prod
from pathlib import Path

from hle_unified import codec
from hle_unified.material import attrs
from hle_unified.operations import wallet_address
from hle_unified.selection_execution import SelectionEngine
from hle_unified.selection_records import SelectionRequest, dumps, fields_of, loads
from hle_unified.workflow_selection_execution import WorkflowFinalSelectionEngine
from hle_unified.workflow_selection_records import (
    WorkflowCapacitySelectionRequest,
    WorkflowSelectionRequest,
)

from .cue_comparison import CueCanonicalEngine, CueWorkflowEngine
VERSION = "ft-current-domain-quotation-a12e2-v1"
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


def request_from_decoded_domain(d, ordinal):
    names = d["role_order"]
    radices = (len(d["windows"]),) + tuple(len(d["pools"][name]) for name in names)
    if radices != d["radices"] or prod(radices) != d["assignments"]:
        raise ValueError("factor sizes")
    if type(ordinal) is not int or not 0 <= ordinal < prod(radices):
        raise ValueError("ordinal outside complete product")
    remaining = ordinal
    reversed_digits = []
    for radix in reversed(radices):
        remaining, digit = divmod(remaining, radix)
        reversed_digits.append(digit)
    digits = tuple(reversed(reversed_digits))
    fields = dict(d["windows"][digits[0]])
    fields.update(
        (name, d["pools"][name][digit]["value"])
        for name, digit in zip(names, digits[1:])
    )
    fields["key"] = d["namespace"] + str(ordinal)
    if d["setting"] == "canonical":
        return SelectionRequest(**fields)
    if fields.get("procedure") is not None:
        return WorkflowCapacitySelectionRequest(**fields)
    fields.pop("procedure", None)
    return WorkflowSelectionRequest(**fields)


def snapshot_text(snapshot, setting):
    if setting == "canonical":
        return dumps(snapshot)

    def pack(value):
        if type(value) is dict:
            if any(type(key) is not str for key in value):
                raise ValueError("string workflow snapshot keys required")
            return ("map", tuple((key, pack(value[key])) for key in sorted(value)))
        if type(value) is tuple:
            return ("tuple", tuple(pack(item) for item in value))
        if type(value) is list:
            return ("list", tuple(pack(item) for item in value))
        return ("leaf", value)

    return codec.dumps(pack(snapshot))


class CurrentDomainQuotation:
    """Read-only facade around an exact saved native selection engine."""

    def __init__(self, native, domain, setting, mask, raw_sha256):
        entry = json.loads(PROTOCOL.read_text())["inputs"].get(f"{setting}-{mask:02d}")
        if entry is None:
            raise ValueError("registered A12E2 branch required")
        if (
            digest(native),
            digest(domain),
            raw_sha256,
            entry["assignments"],
        ) != (
            entry["native_sha256"],
            entry["domain_sha256"],
            entry["raw_sha256"],
            loads(domain).get("assignments"),
        ):
            raise ValueError("exact accepted A12E1 source binding required")
        d = loads(domain)
        if (
            d.get("version"),
            d.get("setting"),
            d.get("mask"),
            d.get("current_native_sha256"),
        ) != (
            "ft-post-processing-domain-a12e1-v1",
            setting,
            mask,
            digest(native),
        ):
            raise ValueError("complete current domain required")
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

    def unchanged(self):
        return self.engine.checkpoint() == self.before

    def row(self, ordinal):
        request = request_from_decoded_domain(self.d, ordinal)
        common = {
            "ordinal": ordinal,
            "request_sha256": digest(dumps(fields_of(request))),
        }
        try:
            if self.setting == "canonical":
                snapshot = self.engine.selection_view(request)
                rows, nominee = self.engine._select_policy(snapshot)
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
                snapshot = self.engine.workflow_selection_view(request)
                rows, nominee = self.engine._workflow_policy(snapshot)
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
        projection = tuple({key: row[key] for key in keys} for row in rows)
        examined = tuple(row["examined"] for row in rows)
        expected_cells = 33 if self.setting == "canonical" else 32
        if len(rows) != expected_cells or any(type(value) is not int or value < 0 for value in examined):
            raise ValueError("exact native cell domain and integer extent required")
        return {
            **common,
            "rejection": None,
            "required": required,
            "snapshot_sha256": digest(snapshot_text(snapshot, self.setting)),
            "candidates_sha256": digest(dumps(projection)),
            "nominee": None if nominee is None else nominee["cell"],
            "candidate_count": len(rows),
            "examined": examined,
            **metadata,
        }

    def report(self, rows):
        if len(rows) != self.d["assignments"]:
            raise ValueError("complete request cardinality required")
        if tuple(row["ordinal"] for row in rows) != tuple(range(len(rows))):
            raise ValueError("all exact ordered ordinals required")
        total = sum(row["required"] for row in rows)
        energy = self.wallet["energy"]
        time = self.wallet["time"]
        return dumps(
            {
                "version": VERSION,
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
                "native_state_unchanged": self.unchanged(),
                "native_work": False,
                "comparison_paid": False,
                "execution_authorized": False,
                "td5_admitted": False,
                "history_choice": False,
                "parent_accepted": False,
            }
        )

