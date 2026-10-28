#!/usr/bin/env python3
"""Read Strix 1.7 run artifacts without executing or trusting their contents."""

from __future__ import annotations

import argparse
import hashlib
import json
import math
import stat
import sys
from collections import Counter
from pathlib import Path
from typing import Any


MAX_ARTIFACT_BYTES = 32 * 1024 * 1024
SEVERITIES = frozenset({"critical", "high", "medium", "low", "info"})
RUN_STATUSES = frozenset({"completed", "running", "stopped", "failed", "interrupted"})


def _read_artifact(run_dir: Path, name: str) -> tuple[bytes | None, dict[str, Any]]:
    path = run_dir / name
    try:
        if path.is_symlink():
            return None, {"state": "invalid", "reason": "symlink_not_read"}
        metadata = path.stat()
        if not stat.S_ISREG(metadata.st_mode):
            return None, {"state": "invalid", "reason": "not_regular_file"}
        with path.open("rb") as source:
            data = source.read(MAX_ARTIFACT_BYTES + 1)
        if len(data) > MAX_ARTIFACT_BYTES:
            return None, {"state": "invalid", "reason": "artifact_exceeds_32_mib"}
        return data, {
            "state": "read",
            "bytes": len(data),
            "sha256": hashlib.sha256(data).hexdigest(),
        }
    except FileNotFoundError:
        return None, {"state": "missing"}
    except OSError:
        return None, {"state": "invalid", "reason": "unreadable"}


def _decode_json(data: bytes, name: str, errors: list[str]) -> Any:
    try:
        return json.loads(data)
    except (ValueError, UnicodeDecodeError, RecursionError):
        errors.append(f"{name}: invalid_json")
        return None


def _finite_nonnegative(value: Any) -> bool:
    if not isinstance(value, int | float) or isinstance(value, bool):
        return False
    try:
        return math.isfinite(value) and value >= 0
    except OverflowError:
        return False


def _run_record(data: bytes | None, errors: list[str]) -> dict[str, Any]:
    record = _decode_json(data, "run.json", errors) if data else None
    if not isinstance(record, dict):
        errors.append("run.json: missing_or_not_an_object")
        return {}
    if not isinstance(record.get("status"), str) or not record.get("status"):
        errors.append("run.json: missing_or_invalid_status")
    if not isinstance(record.get("run_id"), str) or not record.get("run_id"):
        errors.append("run.json: missing_or_invalid_run_id")
    return record


def _cost_summary(
    record: dict[str, Any],
    max_budget: float | None,
    errors: list[str],
    limitations: list[str],
) -> tuple[int | float | None, bool]:
    usage = record.get("llm_usage")
    cost = usage.get("cost") if isinstance(usage, dict) else None
    if cost is not None and not _finite_nonnegative(cost):
        errors.append("run.json: invalid_llm_usage_cost")
        cost = None
    if cost is None:
        limitations.append("Reported model cost is unavailable.")
    else:
        limitations.append("Reported cost can be incomplete; zero is not proof of no cost.")
    budget_reached = max_budget is not None and cost is not None and cost >= max_budget
    if budget_reached:
        limitations.append("Reported cost reached the supplied budget; inspect stop and coverage.")
    limitations.append("Budget warnings can cause an early finish even with status completed.")
    return cost, budget_reached


def _findings_summary(
    data: bytes | None, errors: list[str], limitations: list[str]
) -> tuple[int | None, dict[str, int]]:
    count: int | None = None
    severities: dict[str, int] = {}
    if data is None:
        limitations.append("Finding index is absent; finding count is unknown, not zero.")
    else:
        findings = _decode_json(data, "vulnerabilities.json", errors)
        if not isinstance(findings, list) or any(not isinstance(item, dict) for item in findings):
            errors.append("vulnerabilities.json: expected_list_of_objects")
        else:
            count = len(findings)
            counts: Counter[str] = Counter()
            for item in findings:
                raw = item.get("severity")
                severity = raw.lower() if isinstance(raw, str) else "unknown"
                counts[severity if severity in SEVERITIES else "unknown"] += 1
            severities = dict(sorted(counts.items()))
    return count, severities


def _coverage_summary(
    data: bytes | None, record: dict[str, Any], errors: list[str], limitations: list[str]
) -> tuple[bool | None, int | None]:
    coverage_complete: bool | None = None
    coverage_gaps: int | None = None
    if data is None:
        limitations.append("Coverage artifact is missing.")
    else:
        coverage = _decode_json(data, "coverage.json", errors)
        completeness = coverage.get("completeness") if isinstance(coverage, dict) else None
        gaps = coverage.get("gaps") if isinstance(coverage, dict) else None
        if (
            not isinstance(coverage, dict)
            or coverage.get("schema_version") != 1
            or not isinstance(completeness, dict)
            or not isinstance(completeness.get("complete"), bool)
            or not isinstance(gaps, list)
        ):
            errors.append("coverage.json: unsupported_or_invalid_schema")
        else:
            coverage_complete = completeness["complete"]
            coverage_gaps = len(gaps)
            if not coverage_complete or coverage_gaps:
                limitations.append("Coverage records incomplete work or unresolved gaps.")
            if coverage.get("run_id") != record.get("run_id"):
                errors.append("coverage.json: run_id_mismatch")
    return coverage_complete, coverage_gaps


def _report_available(data: bytes | None, errors: list[str], limitations: list[str]) -> bool:
    if not data or not data.strip():
        limitations.append("Executive report is missing or empty.")
        return False
    try:
        data.decode("utf-8")
    except UnicodeDecodeError:
        errors.append("penetration_test_report.md: invalid_utf8")
        return False
    return True


def inspect_run(run_dir: Path, max_budget: float | None = None) -> dict[str, Any]:
    """Summarize snapshots of fixed artifact paths; never infer a security pass."""
    if max_budget is not None and (not _finite_nonnegative(max_budget) or max_budget == 0):
        raise ValueError("max_budget must be finite and greater than zero")
    errors: list[str] = []
    limitations = ["Coverage and finding evidence require review; this is not a security verdict."]
    artifacts: dict[str, dict[str, Any]] = {}
    payloads: dict[str, bytes | None] = {}
    for name in ("run.json", "vulnerabilities.json", "penetration_test_report.md", "coverage.json"):
        payloads[name], artifacts[name] = _read_artifact(run_dir, name)
        if artifacts[name]["state"] == "invalid":
            errors.append(f"{name}: {artifacts[name]['reason']}")

    record = _run_record(payloads["run.json"], errors)
    raw_status = record.get("status")
    status = raw_status if isinstance(raw_status, str) and raw_status in RUN_STATUSES else "unknown"
    completed = status == "completed"
    if not completed:
        limitations.append("Run is not recorded as completed.")
    if completed and (not isinstance(record.get("end_time"), str) or not record.get("end_time")):
        completed = False
        limitations.append("Completed record has no valid end_time.")

    cost, budget_reached = _cost_summary(record, max_budget, errors, limitations)
    count, severities = _findings_summary(payloads["vulnerabilities.json"], errors, limitations)
    coverage_complete, coverage_gaps = _coverage_summary(
        payloads["coverage.json"], record, errors, limitations
    )
    report_available = _report_available(
        payloads["penetration_test_report.md"], errors, limitations
    )
    completed = completed and report_available and coverage_complete is True and not coverage_gaps
    completed = completed and not budget_reached

    assessment = "invalid_artifacts" if errors else "review_required" if completed else "incomplete"
    return {
        "assessment": assessment,
        "recorded_status": status,
        "finding_count": count,
        "severities": severities,
        "reported_cost_usd": cost,
        "supplied_budget_usd": max_budget,
        "reported_budget_reached": budget_reached,
        "coverage_recorded_complete": coverage_complete,
        "coverage_gap_count": coverage_gaps,
        "artifacts": artifacts,
        "limitations": limitations,
        "errors": errors,
    }


def _positive_budget(text: str) -> float:
    try:
        value = float(text)
    except ValueError as error:
        raise argparse.ArgumentTypeError("budget must be a number") from error
    if not math.isfinite(value) or value <= 0:
        raise argparse.ArgumentTypeError("budget must be finite and greater than zero")
    return value


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("run_dir", type=Path, help="Exact run directory from Strix output")
    parser.add_argument(
        "--max-budget", type=_positive_budget, help="Budget used for this run, in USD"
    )
    args = parser.parse_args()
    summary = inspect_run(args.run_dir, args.max_budget)
    sys.stdout.write(json.dumps(summary, ensure_ascii=False, indent=2, allow_nan=False) + "\n")
    return {"review_required": 0, "invalid_artifacts": 2, "incomplete": 3}[summary["assessment"]]


if __name__ == "__main__":
    raise SystemExit(main())
