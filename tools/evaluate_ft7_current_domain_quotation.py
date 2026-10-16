"""Run the single bounded A12E2 quotation gate from saved A12E1 records."""
import argparse
import copy
import gzip
import hashlib
import json
import os
import pathlib
import shutil
import unittest
from datetime import datetime, timezone

from hle_unified import codec
from hle_unified.selection_records import dumps, loads

from full_theory.current_domain_quotation import CurrentDomainQuotation
from full_theory.current_domain_quotation_audit import CurrentDomainQuotationAudit


def run():
    parser = argparse.ArgumentParser()
    parser.add_argument("a12e1")
    parser.add_argument("output")
    parser.add_argument("--public", required=True)
    parser.add_argument("--owner", required=True)
    parser.add_argument("--stop-at", required=True)
    parser.add_argument("--only-branch")
    parser.add_argument("--finish", action="store_true")
    parser.add_argument("--retain-from")
    parser.add_argument("--parts-root")
    args = parser.parse_args()
    root = pathlib.Path(__file__).resolve().parents[1]
    source = pathlib.Path(args.a12e1)
    output = pathlib.Path(args.output)
    output.mkdir(exist_ok=False)
    for name in ("records", "audits", "backups", "jobs"):
        (output / name).mkdir()
    protocol = json.loads(
        (root / "contracts/ft/FT7_Current_Domain_Quotation_A12E2_Protocol_v1.json").read_text()
    )
    freeze = json.loads(
        (root / "contracts/ft/FT7_Current_Domain_Quotation_A12E2_Source_Freeze_v1.json").read_text()
    )
    stop_at = datetime.fromisoformat(args.stop_at)

    def sha(value):
        return hashlib.sha256(value.encode() if isinstance(value, str) else value).hexdigest()

    def note(kind, **fields):
        row = {"at": datetime.now(timezone.utc).isoformat(), "kind": kind, **fields}
        with (output / "events.jsonl").open("a") as handle:
            handle.write(json.dumps(row, sort_keys=True) + "\n")
            handle.flush()
            os.fsync(handle.fileno())
        print(kind, fields, flush=True)

    def guard():
        state = json.loads((pathlib.Path(args.public) / "docs/FT_Run_State.json").read_text())
        now = datetime.now(timezone.utc)
        if (
            state["run_id"] != args.owner
            or state["active_worker"] is not True
            or state["status"] != "running"
            or now >= datetime.fromisoformat(state["lease_expires_at"])
            or now >= stop_at
        ):
            raise SystemExit("ownership/lease/deadline")

    def verify_source():
        if len(freeze) != 614:
            raise ValueError("exact 614-identity freeze required")
        prior = json.loads(
            (root / "contracts/ft/FT7_Post_Processing_Domain_A12E1_Source_Freeze_v1.json").read_text()
        )
        if len(prior) != 600 or any(freeze.get(name) != value for name, value in prior.items()):
            raise ValueError("all 600 A12E1 predecessors must remain exact")
        for name, expected in freeze.items():
            if sha((root / name).read_bytes()) != expected:
                raise ValueError("source changed: " + name)

    def atomic_bytes(path, data):
        temporary = path.with_name("." + path.name + ".tmp")
        with temporary.open("xb") as handle:
            handle.write(data)
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
        directory = os.open(path.parent, os.O_DIRECTORY)
        try:
            os.fsync(directory)
        finally:
            os.close(directory)

    def persist(path, data):
        atomic_bytes(path, data)
        backup = output / "backups" / (path.parent.name + "--" + path.name)
        atomic_bytes(backup, data)
        if path.read_bytes() != data or backup.read_bytes() != data:
            raise ValueError("persistent readback or independent backup mismatch")

    def begin_job(job):
        marker = output / "jobs" / (job + ".running")
        with marker.open("x") as handle:
            handle.write(
                json.dumps({"job": job, "started_at": datetime.now(timezone.utc).isoformat()})
                + "\n"
            )
            handle.flush()
            os.fsync(handle.fileno())
        return marker

    def close_job(marker, passed=True, **fields):
        outcome = marker.with_name(marker.name.removesuffix(".running") + ".outcome.json")
        payload = {
            "job": marker.name.removesuffix(".running"),
            "passed": passed,
            "closed_at": datetime.now(timezone.utc).isoformat(),
            **fields,
        }
        atomic_bytes(outcome, (json.dumps(payload, indent=2, sort_keys=True) + "\n").encode())
        marker.unlink()

    summaries = []
    probes = {"canonical": [], "workflow": []}
    ordered_reports = 0
    native_view_calls = 0
    audit_view_calls = 0

    def reject(setting, name, call):
        try:
            call()
        except (ValueError, TypeError, KeyError):
            probes[setting].append(name)
        else:
            raise ValueError("forgery accepted: " + setting + ":" + name)

    def report_probe_set(setting, text, expected, auditor, native, domain, mask, raw_sha256):
        decoded = loads(text)

        def changed_root(name, value):
            bad = dict(decoded)
            bad[name] = value
            return dumps(bad)

        def changed_row(name, value):
            bad = dict(decoded)
            rows = list(bad["rows"])
            first = dict(rows[0])
            first[name] = value
            rows[0] = first
            bad["rows"] = tuple(rows)
            return dumps(bad)

        reject(setting, "raw_binding", lambda: CurrentDomainQuotation(native, domain, setting, mask, "0" * 64))
        reject(setting, "native_binding", lambda: CurrentDomainQuotation(native + "x", domain, setting, mask, raw_sha256))
        reject(setting, "domain_binding", lambda: CurrentDomainQuotation(native, domain + "x", setting, mask, raw_sha256))
        reject(setting, "native_audit_binding", lambda: CurrentDomainQuotationAudit(native + "x", domain, setting, mask, raw_sha256))
        reject(setting, "omitted_ordinal", lambda: auditor.audit(changed_root("rows", tuple(decoded["rows"][1:])), expected))
        reject(setting, "reordered_ordinals", lambda: auditor.audit(changed_root("rows", tuple(reversed(decoded["rows"]))), expected))
        reject(setting, "request_sha256", lambda: auditor.audit(changed_row("request_sha256", "forged"), expected))
        reject(setting, "snapshot_sha256", lambda: auditor.audit(changed_row("snapshot_sha256", "forged"), expected))
        reject(setting, "candidates_sha256", lambda: auditor.audit(changed_row("candidates_sha256", "forged"), expected))
        reject(setting, "rejection", lambda: auditor.audit(changed_row("rejection", "forged"), expected))
        reject(setting, "row_cost", lambda: auditor.audit(changed_row("required", decoded["rows"][0]["required"] + 1), expected))
        reject(setting, "total_cost", lambda: auditor.audit(changed_root("required_energy", decoded["required_energy"] + 1), expected))
        reject(setting, "wallet", lambda: auditor.audit(changed_root("energy", decoded["energy"] + 1), expected))
        reject(setting, "affordability", lambda: auditor.audit(changed_root("status", "forged"), expected))
        reject(setting, "truncation", lambda: auditor.audit(changed_root("assignments", decoded["assignments"] - 1), expected))
        reject(setting, "policy_version", lambda: auditor.audit(changed_root("version", "forged"), expected))
        reject(setting, "native_mutation_claim", lambda: auditor.audit(changed_root("native_state_unchanged", False), expected))
        reject(setting, "launch_authority", lambda: auditor.audit(changed_root("may_launch", True), expected))
        reject(setting, "payment_authority", lambda: auditor.audit(changed_root("comparison_paid", True), expected))
        reject(setting, "execution_authority", lambda: auditor.audit(changed_root("execution_authorized", True), expected))
        reject(setting, "td5_authority", lambda: auditor.audit(changed_root("td5_admitted", True), expected))
        reject(setting, "history_authority", lambda: auditor.audit(changed_root("history_choice", True), expected))

    try:
        guard()
        verify_source()
        note("start", owner=args.owner, inputs=len(protocol["inputs"]))
        if args.finish:
            if args.only_branch or not args.retain_from or not args.parts_root:
                raise ValueError("exact continuation merge roots required")
            retained = pathlib.Path(args.retain_from)
            parts = pathlib.Path(args.parts_root)
            retained_labels = {"canonical-01", "canonical-02"}
            for setting in ("canonical", "workflow"):
                for mask in range(1, 16):
                    label = f"{setting}-{mask:02d}"
                    branch_root = retained if label in retained_labels else parts / label
                    if not branch_root.is_dir() or list((branch_root / "jobs").glob("*.running")):
                        raise ValueError("closed branch root required: " + label)
                    record_data = (branch_root / "records" / (label + ".json.gz")).read_bytes()
                    audit_data = (branch_root / "audits" / (label + ".json")).read_bytes()
                    persist(output / "records" / (label + ".json.gz"), record_data)
                    persist(output / "audits" / (label + ".json"), audit_data)
                    for kind in ("quote", "audit"):
                        outcome = branch_root / "jobs" / (kind + "-" + label + ".outcome.json")
                        payload = json.loads(outcome.read_text())
                        if payload.get("passed") is not True or payload.get("job") != kind + "-" + label:
                            raise ValueError("exact closed outcome required: " + kind + "-" + label)
                        atomic_bytes(output / "jobs" / outcome.name, outcome.read_bytes())
                    report_text = gzip.decompress(record_data).decode()
                    report = loads(report_text)
                    audit = json.loads(audit_data)
                    rows = report["rows"]
                    formula_exact = all(
                        row["required"]
                        == (
                            1
                            if row["rejection"] is not None
                            else 1
                            + (
                                row["scanned"] + row["foreign_total"]
                                if setting == "canonical"
                                else row["items"]
                            )
                            + row["candidate_count"]
                            + sum(row["examined"])
                        )
                        for row in rows
                    )
                    if (
                        report["setting"] != setting
                        or report["mask"] != mask
                        or audit.get("passed") is not True
                        or audit.get("assignments") != len(rows)
                        or tuple(row["ordinal"] for row in rows) != tuple(range(len(rows)))
                        or not formula_exact
                    ):
                        raise ValueError("exact saved branch binding required: " + label)
                    if label not in retained_labels:
                        branch_summary = json.loads((branch_root / "branch-summary.json").read_text())
                        if branch_summary["branch"] != label:
                            raise ValueError("branch summary binding")
                        for name in probes:
                            if branch_summary["probes"].get(name):
                                if probes[name]:
                                    raise ValueError("duplicate setting forgery panel")
                                probes[name] = branch_summary["probes"][name]
                    summaries.append(
                        {
                            "branch": label,
                            "setting": setting,
                            "mask": mask,
                            "record_sha256": sha(record_data),
                            "payload_sha256": sha(report_text),
                            "audit_sha256": sha(audit_data),
                            "assignments": len(rows),
                            "required": report["required_energy"],
                            "energy": report["energy"],
                            "time": report["time"],
                            "status": report["status"],
                            "rejected": audit["rejected"],
                            "formula_exact": True,
                            "native_state_unchanged": audit["native_state_unchanged"],
                        }
                    )
                    ordered_reports += 1
                    native_view_calls += len(rows)
                    audit_view_calls += len(rows)
            if len(summaries) != 30 or any(len(rows) < 16 for rows in probes.values()):
                raise ValueError("complete continuation merge and forgery panels required")
        for setting in ("canonical", "workflow"):
            for mask in range(1, 16):
                if args.finish:
                    continue
                guard()
                label = f"{setting}-{mask:02d}"
                if args.only_branch and label != args.only_branch:
                    continue
                entry = protocol["inputs"][label]
                raw_path = source / "records" / (label + ".json.gz")
                raw = raw_path.read_bytes()
                if sha(raw) != entry["raw_sha256"]:
                    raise ValueError("exact A12E1 raw required: " + label)
                decoded = codec.loads(gzip.decompress(raw).decode())
                if (
                    type(decoded) is not tuple
                    or len(decoded) != 6
                    or decoded[0] != setting
                    or decoded[1] != mask
                ):
                    raise ValueError("exact six-field A12E1 record required: " + label)
                _, _, native, _, _, domain = decoded
                if (
                    sha(native),
                    sha(domain),
                    loads(domain)["assignments"],
                ) != (
                    entry["native_sha256"],
                    entry["domain_sha256"],
                    entry["assignments"],
                ):
                    raise ValueError("registered A12E1 binding mismatch: " + label)

                quote_marker = begin_job("quote-" + label)
                quote = CurrentDomainQuotation(native, domain, setting, mask, sha(raw))
                rows = []
                for ordinal in range(entry["assignments"]):
                    if ordinal % 256 == 0:
                        guard()
                    if ordinal % 2048 == 0:
                        note("quote_progress", branch=label, completed=ordinal)
                    rows.append(quote.row(ordinal))
                if not quote.unchanged():
                    raise ValueError("quotation changed native state: " + label)
                text = quote.report(rows)
                if loads(text)["native_state_unchanged"] is not True:
                    raise ValueError("saved unchanged assertion required")
                record_data = gzip.compress(text.encode(), mtime=0)
                persist(output / "records" / (label + ".json.gz"), record_data)
                if gzip.decompress((output / "records" / (label + ".json.gz")).read_bytes()).decode() != text:
                    raise ValueError("typed persistent report readback")
                close_job(
                    quote_marker,
                    assignments=len(rows),
                    required=sum(row["required"] for row in rows),
                )
                native_view_calls += len(rows)

                audit_marker = begin_job("audit-" + label)
                auditor = CurrentDomainQuotationAudit(native, domain, setting, mask, sha(raw))
                expected = auditor.reconstruct(
                    guard,
                    lambda completed, label=label: (
                        note("audit_progress", branch=label, completed=completed)
                        if completed % 2048 == 0
                        else None
                    ),
                )
                if loads(text) != expected:
                    raise ValueError("runtime and independent full reconstruction differ: " + label)
                audit = auditor.audit(text, expected)
                if not auditor.unchanged():
                    raise ValueError("audit changed native state: " + label)
                audit_data = (json.dumps(audit, indent=2, sort_keys=True) + "\n").encode()
                persist(output / "audits" / (label + ".json"), audit_data)
                if label in ("canonical-03", "workflow-01"):
                    report_probe_set(setting, text, expected, auditor, native, domain, mask, sha(raw))
                close_job(audit_marker, assignments=audit["assignments"], required=audit["required"])
                audit_view_calls += len(rows)
                formula_exact = all(
                    row["required"]
                    == (
                        1
                        if row["rejection"] is not None
                        else 1
                        + (
                            row["scanned"] + row["foreign_total"]
                            if setting == "canonical"
                            else row["items"]
                        )
                        + row["candidate_count"]
                        + sum(row["examined"])
                    )
                    for row in rows
                )
                if not formula_exact:
                    raise ValueError("cost formula mismatch: " + label)
                report = loads(text)
                ordered_reports += int(
                    tuple(row["ordinal"] for row in rows) == tuple(range(len(rows)))
                )
                summaries.append(
                    {
                        "branch": label,
                        "setting": setting,
                        "mask": mask,
                        "record_sha256": sha(record_data),
                        "payload_sha256": sha(text),
                        "audit_sha256": sha(audit_data),
                        "assignments": len(rows),
                        "required": report["required_energy"],
                        "energy": report["energy"],
                        "time": report["time"],
                        "status": report["status"],
                        "rejected": audit["rejected"],
                        "formula_exact": formula_exact,
                        "native_state_unchanged": True,
                    }
                )
                note(
                    "branch_closed",
                    branch=label,
                    required=report["required_energy"],
                    status=report["status"],
                )
                verify_source()

        if args.only_branch:
            if len(summaries) != 1 or summaries[0]["branch"] != args.only_branch:
                raise ValueError("one exact branch required")
            branch_summary = {
                **summaries[0],
                "probes": probes,
                "native_view_calls": native_view_calls,
                "audit_view_calls": audit_view_calls,
                "source_identities": len(freeze),
                "prior_identities": 600,
            }
            atomic_bytes(
                output / "branch-summary.json",
                (json.dumps(branch_summary, indent=2, sort_keys=True) + "\n").encode(),
            )
            verify_source()
            note("closed_branch_pass", branch=args.only_branch)
            return

        methods_marker = begin_job("methods")
        summary = {
            "passed": True,
            "records": len(summaries),
            "audits": len(summaries),
            "settings": [row["setting"] for row in summaries],
            "canonical_assignments": [
                row["assignments"] for row in summaries if row["setting"] == "canonical"
            ],
            "workflow_assignments": [
                row["assignments"] for row in summaries if row["setting"] == "workflow"
            ],
            "ordered_reports": ordered_reports,
            "all_formula_exact": all(row["formula_exact"] for row in summaries),
            "native_view_calls": native_view_calls,
            "audit_view_calls": audit_view_calls,
            "affordable": sum(row["status"] == "affordable_quote_only" for row in summaries),
            "insufficient": sum(row["status"] == "insufficient_exact_quote" for row in summaries),
            "wallets_exact": True,
            "native_work_calls": 0,
            "accepted_stage_replays": 0,
            "native_states_unchanged": all(
                row["native_state_unchanged"] for row in summaries
            ),
            "forgery_rejections": {name: len(rows) for name, rows in probes.items()},
            "forgery_names": probes,
            "truncation_rejected": all("truncation" in rows for rows in probes.values()),
            "source_identities": len(freeze),
            "prior_identities": 600,
            "branches": summaries,
            "comparison_paid": False,
            "td5_admitted": False,
            "execution_authorized": False,
            "history_choice": False,
            "parent_accepted": False,
        }
        import tests_ft7.test_current_domain_quotation as tests

        tests.SUMMARY = summary
        suite = unittest.defaultTestLoader.loadTestsFromModule(tests)
        actual = [test._testMethodName for group in suite for test in group]
        if sorted(actual) != sorted(protocol["methods"]):
            raise ValueError("exact six method identities required")
        with (output / "tests.log").open("w") as handle:
            result = unittest.TextTestRunner(stream=handle, verbosity=2).run(suite)
            handle.flush()
            os.fsync(handle.fileno())
        if result.testsRun != 6 or not result.wasSuccessful():
            raise ValueError("six exact methods must pass")
        summary["methods"] = actual
        close_job(methods_marker, methods=len(actual))

        aggregate_marker = begin_job("aggregate")
        guard()
        verify_source()
        if (
            len(list((output / "records").glob("*.json.gz"))) != 30
            or len(list((output / "audits").glob("*.json"))) != 30
            or len(list((output / "backups").iterdir())) != 60
        ):
            raise ValueError("complete persistent record/audit/backup gate")
        summary_data = (json.dumps(summary, indent=2, sort_keys=True) + "\n").encode()
        persist(output / "summary.json", summary_data)
        aggregate = {
            "passed": True,
            "records": 30,
            "audits": 30,
            "methods": 6,
            "closed_jobs": 62,
            "failed_jobs": 0,
            "source_identities": 614,
            "prior_identities": 600,
            "native_view_calls": native_view_calls,
            "audit_view_calls": audit_view_calls,
            "forgery_rejections": summary["forgery_rejections"],
            "comparison_paid": False,
            "native_work": False,
            "accepted_stage_replays": 0,
            "parent_accepted": False,
        }
        aggregate_data = (json.dumps(aggregate, indent=2, sort_keys=True) + "\n").encode()
        persist(output / "aggregate.json", aggregate_data)
        close_job(aggregate_marker, **aggregate)
        verify_source()
        note("closed_pass", records=30, audits=30, methods=6)
    except BaseException as error:
        note(
            "closed_nonpass",
            error_type=type(error).__name__,
            message=str(error),
        )
        raise


if __name__ == "__main__":
    run()

