"""scripts/release/report.py -- per-leg outcomes and the run summary (spec §2)."""

import importlib.util
import json
import subprocess
import sys

from tests.release_harness import ROOT
from tests.release_harness import write

SCRIPT = ROOT / "scripts/release/report.py"
sys.path.insert(0, str(SCRIPT.parent))
_spec = importlib.util.spec_from_file_location("report", SCRIPT)
report = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(report)


def rec(code, result="success", attempt=1):
    return {
        "code": code,
        "run_attempt": attempt,
        "from": "sha-a",
        "to": "v1.1.0",
        "result": result,
        "now_on": "sha-b",
    }


def test_outcome_derives_result_from_the_deploy_steps_outcome():
    assert (
        report.outcome("school-01", 1, "sha-a", "v1", "success", "sha-b")["result"]
        == "success"
    )
    for other in ("failure", "skipped", "cancelled", ""):
        assert (
            report.outcome("school-01", 1, "sha-a", "v1", other, "unknown")["result"]
            == "failure"
        )


def test_all_green_this_attempt_is_success():
    outs = {"school-01": rec("school-01"), "school-02": rec("school-02")}
    assert report.verdict("success", ["school-01", "school-02"], 1, outs) == "success"


def test_a_plan_refusal_is_fail_even_with_no_codes():
    """Otherwise "every planned code succeeded" is vacuously true.
    Mutant: return success when codes is empty."""
    assert report.verdict("failure", [], 1, {}) == "fail"
    assert report.verdict("success", [], 1, {}) == "fail"
    lines = report.table("failure", [], 1, {})
    assert any("plan refused" in ln for ln in lines)


def test_a_missing_artifact_is_a_no_result_fail():
    outs = {"school-01": rec("school-01")}
    assert report.verdict("success", ["school-01", "school-02"], 1, outs) == "fail"
    assert any(
        "school-02" in ln and "no result" in ln
        for ln in report.table("success", ["school-01", "school-02"], 1, outs)
    )


def test_an_earlier_attempts_green_is_marked_and_does_not_count():
    """Mutant: ignore run_attempt in verdict()."""
    outs = {"school-01": rec("school-01", attempt=1)}
    assert report.verdict("success", ["school-01"], 2, outs) == "fail"
    assert any(
        "(attempt 1)" in ln for ln in report.table("success", ["school-01"], 2, outs)
    )


def test_summarise_cli_tolerates_a_missing_outcomes_directory(tmp_path):
    summary = tmp_path / "summary.md"
    write(summary, "")
    result = subprocess.run(  # noqa: S603 -- fixed argv
        [
            sys.executable,
            str(SCRIPT),
            "summarise",
            "--plan-result",
            "failure",
            "--codes",
            "",
            "--attempt",
            "1",
            "--dir",
            str(tmp_path / "absent"),
            "--summary",
            str(summary),
        ],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == "fail"
    assert "plan refused" in summary.read_text(encoding="utf-8")


def test_summarise_cli_reads_the_artifacts(tmp_path):
    d = tmp_path / "outcomes"
    write(d / "outcome-school-01.json", json.dumps(rec("school-01")))
    summary = tmp_path / "summary.md"
    write(summary, "")
    result = subprocess.run(  # noqa: S603 -- fixed argv
        [
            sys.executable,
            str(SCRIPT),
            "summarise",
            "--plan-result",
            "success",
            "--codes",
            '["school-01"]',
            "--attempt",
            "1",
            "--dir",
            str(d),
            "--summary",
            str(summary),
        ],
        capture_output=True,
        text=True,
    )
    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == "success"
    assert "school-01" in summary.read_text(encoding="utf-8")
