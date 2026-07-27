"""Unit tests for Evaluation Harness and benchmark case execution."""

import os
import pytest
from fixate.eval.harness import EvalHarnessRunner
from fixate.eval.cases import BENCHMARK_SUITE_15

def test_eval_harness_runner():
    runner = EvalHarnessRunner()
    for case in BENCHMARK_SUITE_15[:2]:  # Test first 2 cases
        runner.register_case(case)

    scorecard = runner.run_benchmark_suite()
    assert scorecard.total_cases == 2
    assert isinstance(scorecard.localization_accuracy_pct, float)
    assert isinstance(scorecard.overall_fix_rate_pct, float)
    assert len(scorecard.case_results) == 2
