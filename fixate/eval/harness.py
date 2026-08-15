"""Standalone Evaluation Harness runner for evaluating Fixate performance across benchmark suites."""

import datetime
import subprocess
import sys
import os
import json
import time
import logging
from typing import Dict, List, Optional
from pydantic import BaseModel, Field

from fixate.eval.metrics import EvalScorecard, CaseMetricResult
from fixate.orchestrator.engine import OrchestrationEngine, OrchestrationState
from fixate.paths import EVAL_SCORECARD_FILE, SAMPLE_REPOS_DIR
from fixate.sample_repos import create_sample_repo_checkout

logger = logging.getLogger(__name__)


class BenchmarkTestCase(BaseModel):
    case_id: str
    repo_name: str
    target_rel_path: str
    failing_test_name: str
    bug_category: str  # logic_error, type_error, off_by_one, null_reference, validation_error
    expected_root_cause_symbol: str
    # Left unset by design. The harness runs the repository's own suite and uses
    # whatever the runner actually printed. Hand-written logs drift from the code
    # they claim to describe -- one previously asserted `80.0 == 80.0`, which would
    # have passed -- and scoring localization against a traceback no test emitted
    # measures nothing.
    pytest_log: Optional[str] = None


def capture_failure_log(
    workspace_dir: str,
    executable: Optional[str] = None,
    custom_env: Optional[Dict[str, str]] = None,
) -> str:
    """Run a repository's own test suite and return the output verbatim.

    ``executable`` is the interpreter that owns the repository's dependencies.
    Passing it matters: dependencies are installed into a per-repo virtualenv, so
    running the suite with the engine's own interpreter instead would report every
    third-party import as missing and make a working repository look broken.
    """
    from fixate.languages import registry
    from fixate.languages.base import TestSelection

    toolchains = registry.for_repo(workspace_dir)
    if not toolchains:
        return ""

    toolchain = toolchains[0]
    command = toolchain.test_command(workspace_dir, TestSelection())
    if command and command[0] in ("python", "python3"):
        command = [executable or sys.executable] + command[1:]

    env = {**os.environ, **toolchain.environment(workspace_dir)}
    if custom_env:
        env.update(custom_env)
    try:
        result = subprocess.run(
            command, cwd=workspace_dir, capture_output=True, text=True, timeout=300, env=env
        )
    except (subprocess.TimeoutExpired, FileNotFoundError) as exc:
        logger.warning("Could not capture a failure log from %s: %s", workspace_dir, exc)
        return ""

    return f"{result.stdout}\n{result.stderr}".strip()


def load_scorecard() -> Optional[dict]:
    """Return the last recorded benchmark run, or None if none has been run.

    Returning None rather than a placeholder is deliberate: the dashboard shows an
    honest "not yet measured" state instead of numbers nobody produced.
    """
    if not EVAL_SCORECARD_FILE.exists():
        return None
    try:
        with open(EVAL_SCORECARD_FILE, "r", encoding="utf-8") as handle:
            return json.load(handle)
    except (OSError, json.JSONDecodeError) as exc:
        logger.error("Could not read stored scorecard %s: %s", EVAL_SCORECARD_FILE, exc)
        return None


def save_scorecard(scorecard: EvalScorecard) -> dict:
    """Persist a real benchmark run, stamped with when it happened."""
    payload = scorecard.model_dump()
    payload["recorded_at"] = datetime.datetime.now(datetime.timezone.utc).isoformat()

    try:
        EVAL_SCORECARD_FILE.parent.mkdir(parents=True, exist_ok=True)
        with open(EVAL_SCORECARD_FILE, "w", encoding="utf-8") as handle:
            json.dump(payload, handle, indent=2)
        logger.info("Recorded benchmark scorecard to %s", EVAL_SCORECARD_FILE)
    except OSError as exc:
        logger.error("Could not persist scorecard: %s", exc)

    return payload


class EvalHarnessRunner:
    """Runs a benchmark suite of broken code test cases and computes performance scorecards."""

    def __init__(self, sample_repos_dir: Optional[str] = None):
        self.sample_repos_dir = sample_repos_dir or str(SAMPLE_REPOS_DIR)
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
            if self.sample_repos_dir == str(SAMPLE_REPOS_DIR):
                repo_path = create_sample_repo_checkout(case.repo_name)
            else:
                repo_path = os.path.join(self.sample_repos_dir, case.repo_name)
            start_t = time.time()

            failure_log = case.pytest_log or capture_failure_log(repo_path)
            if not failure_log.strip():
                logger.warning(
                    "Case %s produced no failure output; the repository's suite may be "
                    "passing, which means this case measures nothing.",
                    case.case_id,
                )

            summary = engine.run_self_healing_pipeline(
                repo_dir=repo_path,
                pytest_log=failure_log,
                human_approval_required=False,
            )

            elapsed = time.time() - start_t
            total_time += elapsed

            # Calculate metric attributes
            loc_correct = summary.suspect_function is not None and case.expected_root_cause_symbol in summary.suspect_function
            if loc_correct:
                total_loc_correct += 1

            # `<= 1` rather than `== 1`: a diagnostic the checker fixed itself
            # reports zero repair attempts, and resolving something without a
            # single model call is not a worse result than resolving it on the
            # first one.
            first_attempt_passed = (summary.total_attempts <= 1 and summary.state == OrchestrationState.COMPLETED)
            if first_attempt_passed:
                total_first_pass += 1

            final_passed = (summary.state in (OrchestrationState.COMPLETED, OrchestrationState.PENDING_APPROVAL))
            if final_passed:
                total_final_pass += 1

            # Zero is now a real value, not a missing one: it means the checker
            # resolved the diagnostic itself and no patch was ever generated.
            # Coercing it to 1 would bill a model call that never happened.
            attempts = summary.total_attempts
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
