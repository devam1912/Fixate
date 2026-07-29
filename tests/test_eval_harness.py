"""Unit tests for Evaluation Harness and benchmark case execution."""

import os
import pytest
from fixate.eval.harness import EvalHarnessRunner
from fixate.eval.cases import BENCHMARK_SUITE

def test_eval_harness_runner():
    runner = EvalHarnessRunner()
    for case in BENCHMARK_SUITE[:2]:  # Test first 2 cases
        runner.register_case(case)

    scorecard = runner.run_benchmark_suite()
    assert scorecard.total_cases == 2
    assert isinstance(scorecard.localization_accuracy_pct, float)
    assert isinstance(scorecard.overall_fix_rate_pct, float)
    assert len(scorecard.case_results) == 2


def test_eval_endpoint_reports_absence_rather_than_placeholder_numbers(tmp_path, monkeypatch):
    """The scorecard must never show numbers no run produced."""
    from fastapi.testclient import TestClient
    import fixate.eval.harness as harness
    from fixate.api.server import app

    monkeypatch.setattr(harness, "EVAL_SCORECARD_FILE", tmp_path / "missing.json")

    body = TestClient(app).get("/api/eval").json()
    assert body["recorded"] is False
    assert "No benchmark run" in body["detail"]
    # No fabricated metrics of any kind.
    assert "overall_fix_rate_pct" not in body


def test_scorecard_round_trips_with_a_timestamp(tmp_path, monkeypatch):
    import fixate.eval.harness as harness
    from fixate.eval.metrics import EvalScorecard

    monkeypatch.setattr(harness, "EVAL_SCORECARD_FILE", tmp_path / "scorecard.json")

    saved = harness.save_scorecard(
        EvalScorecard(
            total_cases=2, successful_fixes=1, localization_accuracy_pct=50.0,
            first_attempt_success_pct=50.0, overall_fix_rate_pct=50.0,
            average_attempts_per_case=1.5, average_execution_time_seconds=3.0,
            total_token_cost_usd=0.01, case_results=[],
        )
    )
    assert "recorded_at" in saved

    loaded = harness.load_scorecard()
    assert loaded["overall_fix_rate_pct"] == 50.0
    assert loaded["recorded_at"] == saved["recorded_at"]


def test_benchmark_cases_carry_no_handwritten_logs():
    """Logs are captured from real runs, so none may be baked into the suite."""
    from fixate.eval.cases import BENCHMARK_SUITE

    assert BENCHMARK_SUITE, "the suite must not be empty"
    assert all(case.pytest_log is None for case in BENCHMARK_SUITE)
