"""Offline regression checks for the internal Strix artifact reader."""

# This standalone unittest module does not require a package or engine imports.
# ruff: noqa: INP001

from __future__ import annotations

import hashlib
import importlib.util
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path


SCRIPT = Path(__file__).resolve().parents[2] / "skills/patrik-strix/scripts/inspect_run.py"
SPEC = importlib.util.spec_from_file_location("patrik_strix_artifacts", SCRIPT)
assert SPEC is not None and SPEC.loader is not None
READER = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(READER)


class ArtifactReaderTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory(prefix="patrik-strix-artifacts-")
        self.addCleanup(self.temporary.cleanup)
        self.run_dir = Path(self.temporary.name)
        self.record = {
            "run_id": "fixture-run",
            "status": "completed",
            "end_time": "2026-10-28T22:00:00+00:00",
            "llm_usage": {"cost": 0.4},
            "instruction": "PRIVATE_TEST_CREDENTIAL_DO_NOT_PRINT",
        }
        self.coverage = {
            "schema_version": 1,
            "run_id": "fixture-run",
            "completeness": {"complete": True},
            "gaps": [],
        }
        self.write_json("run.json", self.record)
        self.write_json("coverage.json", self.coverage)
        self.write_json("vulnerabilities.json", [])
        (self.run_dir / "penetration_test_report.md").write_text("Fixture report", encoding="utf-8")

    def write_json(self, name: str, value: object) -> None:
        (self.run_dir / name).write_text(json.dumps(value), encoding="utf-8")

    def test_completed_empty_result_still_requires_review_and_hashes_exact_bytes(self) -> None:
        summary = READER.inspect_run(self.run_dir, 1.0)
        self.assertEqual(summary["assessment"], "review_required")
        self.assertEqual(summary["finding_count"], 0)
        expected = hashlib.sha256((self.run_dir / "run.json").read_bytes()).hexdigest()
        self.assertEqual(summary["artifacts"]["run.json"]["sha256"], expected)
        self.assertNotIn("PRIVATE_TEST_CREDENTIAL_DO_NOT_PRINT", json.dumps(summary))

    def test_stopped_failed_interrupted_and_live_runs_are_incomplete(self) -> None:
        for status in ("stopped", "failed", "interrupted", "running", "error", "future_status"):
            with self.subTest(status=status):
                self.record["status"] = status
                self.write_json("run.json", self.record)
                self.assertEqual(READER.inspect_run(self.run_dir)["assessment"], "incomplete")

    def test_budget_reached_overrides_completed_record(self) -> None:
        self.record["llm_usage"]["cost"] = 1.1
        self.write_json("run.json", self.record)
        summary = READER.inspect_run(self.run_dir, 1.0)
        self.assertEqual(summary["assessment"], "incomplete")
        self.assertTrue(summary["reported_budget_reached"])

    def test_budget_warning_below_limit_does_not_become_a_security_pass(self) -> None:
        (self.run_dir / "penetration_test_report.md").write_text(
            "Finished early after a budget warning; auth routes not tested.", encoding="utf-8"
        )
        summary = READER.inspect_run(self.run_dir, 1.0)
        self.assertEqual(summary["assessment"], "review_required")
        self.assertFalse(summary["reported_budget_reached"])
        self.assertTrue(any("Budget warnings" in item for item in summary["limitations"]))

    def test_absent_finding_index_is_unknown_not_zero(self) -> None:
        (self.run_dir / "vulnerabilities.json").unlink()
        summary = READER.inspect_run(self.run_dir)
        self.assertIsNone(summary["finding_count"])
        self.assertEqual(summary["artifacts"]["vulnerabilities.json"]["state"], "missing")

    def test_findings_are_counted_without_echoing_payloads(self) -> None:
        self.write_json(
            "vulnerabilities.json",
            [
                {"id": "vuln-0001", "severity": "high", "title": "PRIVATE_TITLE"},
                {"id": "vuln-0002", "severity": "high"},
                {"id": "vuln-0003", "severity": "unexpected"},
            ],
        )
        summary = READER.inspect_run(self.run_dir)
        self.assertEqual(summary["finding_count"], 3)
        self.assertEqual(summary["severities"], {"high": 2, "unknown": 1})
        self.assertNotIn("PRIVATE_TITLE", json.dumps(summary))

    def test_missing_report_or_coverage_remains_incomplete(self) -> None:
        (self.run_dir / "penetration_test_report.md").unlink()
        self.assertEqual(READER.inspect_run(self.run_dir)["assessment"], "incomplete")
        (self.run_dir / "penetration_test_report.md").write_text("Fixture", encoding="utf-8")
        (self.run_dir / "coverage.json").unlink()
        self.assertEqual(READER.inspect_run(self.run_dir)["assessment"], "incomplete")

    def test_coverage_gaps_and_negative_completeness_override_run_status(self) -> None:
        for complete, gaps in ((False, []), (True, [{"reason": "not tested"}])):
            with self.subTest(complete=complete, gaps=gaps):
                self.coverage["completeness"]["complete"] = complete
                self.coverage["gaps"] = gaps
                self.write_json("coverage.json", self.coverage)
                self.assertEqual(READER.inspect_run(self.run_dir)["assessment"], "incomplete")

    def test_malformed_or_wrong_shape_artifacts_are_invalid(self) -> None:
        for name in ("run.json", "vulnerabilities.json", "coverage.json"):
            original = (self.run_dir / name).read_bytes()
            for payload in (b"broken{", b'"a string"', b""):
                with self.subTest(name=name, payload=payload):
                    (self.run_dir / name).write_bytes(payload)
                    self.assertEqual(
                        READER.inspect_run(self.run_dir)["assessment"], "invalid_artifacts"
                    )
            (self.run_dir / name).write_bytes(original)

    def test_deeply_nested_json_cli_returns_invalid_artifacts_without_traceback(self) -> None:
        (self.run_dir / "run.json").write_bytes(b"[" * 100_000 + b"]" * 100_000)
        result = subprocess.run(  # noqa: S603 - fixed local reader and owned fixture, no shell
            [sys.executable, "-B", str(SCRIPT), str(self.run_dir)],
            check=False,
            capture_output=True,
            text=True,
            timeout=10,
        )
        self.assertEqual(result.returncode, 2)
        self.assertEqual(result.stderr, "")
        summary = json.loads(result.stdout)
        self.assertEqual(summary["assessment"], "invalid_artifacts")
        self.assertIn("run.json: invalid_json", summary["errors"])

    def test_mismatched_coverage_and_invalid_cost_are_invalid(self) -> None:
        self.coverage["run_id"] = "other-run"
        self.write_json("coverage.json", self.coverage)
        self.assertEqual(READER.inspect_run(self.run_dir)["assessment"], "invalid_artifacts")
        self.coverage["run_id"] = "fixture-run"
        self.write_json("coverage.json", self.coverage)
        for cost in (float("nan"), float("inf"), 10**1000, -1, "0", True):
            with self.subTest(cost=cost):
                self.record["llm_usage"]["cost"] = cost
                self.write_json("run.json", self.record)
                self.assertEqual(
                    READER.inspect_run(self.run_dir)["assessment"], "invalid_artifacts"
                )

    def test_absent_run_identity_and_invalid_report_encoding_are_rejected(self) -> None:
        del self.record["run_id"]
        self.write_json("run.json", self.record)
        self.assertEqual(READER.inspect_run(self.run_dir)["assessment"], "invalid_artifacts")
        self.record["run_id"] = "fixture-run"
        self.write_json("run.json", self.record)
        (self.run_dir / "penetration_test_report.md").write_bytes(b"\xff\xfe")
        self.assertEqual(READER.inspect_run(self.run_dir)["assessment"], "invalid_artifacts")

    def test_completed_record_without_end_time_is_incomplete(self) -> None:
        self.record["end_time"] = None
        self.write_json("run.json", self.record)
        self.assertEqual(READER.inspect_run(self.run_dir)["assessment"], "incomplete")

    def test_missing_run_and_symlink_are_rejected(self) -> None:
        path = self.run_dir / "run.json"
        path.unlink()
        self.assertEqual(READER.inspect_run(self.run_dir)["assessment"], "invalid_artifacts")
        path.symlink_to(self.run_dir / "coverage.json")
        summary = READER.inspect_run(self.run_dir)
        self.assertEqual(summary["assessment"], "invalid_artifacts")
        self.assertEqual(summary["artifacts"]["run.json"]["reason"], "symlink_not_read")


if __name__ == "__main__":
    unittest.main()
