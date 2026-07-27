"""Standalone Evaluation Harness runner for evaluating Fixate performance across benchmark suites."""

import os
import json
import time
import logging
from typing import List, Optional
from pydantic import BaseModel, Field

from fixate.eval.metrics import EvalScorecard, CaseMetricResult
from fixate.orchestrator.engine import OrchestrationEngine, OrchestrationState

logger = logging.getLogger(__name__)


class BenchmarkTestCase(BaseModel):
    case_id: str
    repo_name: str
    target_rel_path: str
    failing_test_name: str
    bug_category: str  # logic_error, type_error, off_by_one, null_reference, validation_error
    expected_root_cause_symbol: str
    pytest_log: str


class EvalHarnessRunner:
    """Runs a benchmark suite of broken code test cases and computes performance scorecards."""

    def __init__(self, sample_repos_dir: Optional[str] = None):
        self.sample_repos_dir = sample_repos_dir or os.path.join(os.getcwd(), "sample_repos")
        self.benchmark_cases: List[BenchmarkTestCase] = []

    def register_case(self, case: BenchmarkTestCase):
        self.benchmark_cases.append(case)

    def run_benchmark_suite(self) -> EvalScorecard:
        """Run all registered benchmark cases through OrchestrationEngine and output scorecard."""
        engine = OrchestrationEngine()
        results: List[CaseMetricResult] = []

        total_cases = len(self.benchmark_cases)
        logger.info(f"=== Starting Eval Harness Benchmark Run: {total_cases} cases ===")

        total_loc_correct = 0
        total_first_pass = 0
        total_final_pass = 0
        total_attempts = 0
        total_time = 0.0
        total_cost = 0.0

        for case in self.benchmark_cases:
            repo_path = os.path.join(self.sample_repos_dir, case.repo_name)
            start_t = time.time()

            summary = engine.run_self_healing_pipeline(
                repo_dir=repo_path,
                pytest_log=case.pytest_log,
                human_approval_required=False,
            )

            elapsed = time.time() - start_t
            total_time += elapsed

            # Calculate metric attributes
            loc_correct = summary.suspect_function is not None and case.expected_root_cause_symbol in summary.suspect_function
            if loc_correct:
                total_loc_correct += 1

            first_attempt_passed = (summary.total_attempts == 1 and summary.state == OrchestrationState.COMPLETED)
            if first_attempt_passed:
                total_first_pass += 1

            final_passed = (summary.state in (OrchestrationState.COMPLETED, OrchestrationState.PENDING_APPROVAL))
            if final_passed:
                total_final_pass += 1

            attempts = summary.total_attempts or 1
            total_attempts += attempts

            # Estimated token cost ($0.0002 / 1k tokens estimate)
            cost = round(attempts * 0.0015, 4)
            total_cost += cost

            results.append(
                CaseMetricResult(
                    case_id=case.case_id,
                    bug_category=case.bug_category,
                    localization_correct=loc_correct,
                    first_attempt_passed=first_attempt_passed,
                    final_verified_passed=final_passed,
                    attempts_used=attempts,
                    execution_time_seconds=round(elapsed, 2),
                    estimated_token_cost=cost,
                )
            )

        scorecard = EvalScorecard(
            total_cases=total_cases,
            successful_fixes=total_final_pass,
            localization_accuracy_pct=round((total_loc_correct / total_cases * 100) if total_cases else 0, 1),
            first_attempt_success_pct=round((total_first_pass / total_cases * 100) if total_cases else 0, 1),
            overall_fix_rate_pct=round((total_final_pass / total_cases * 100) if total_cases else 0, 1),
            average_attempts_per_case=round((total_attempts / total_cases) if total_cases else 0, 2),
            average_execution_time_seconds=round((total_time / total_cases) if total_cases else 0, 2),
            total_token_cost_usd=round(total_cost, 4),
            case_results=results,
        )

        return scorecard


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO)
    print("Fixate Evaluation Harness Scorecard Engine Ready.")
