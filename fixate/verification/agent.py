"""Verification Agent enforcing bounded sandboxed execution retries (max 3 attempts)."""

import os
import shutil
import tempfile
import logging
from typing import List, Optional
from pydantic import BaseModel, Field

from fixate.patch.schema import GeneratedPatch, PatchRequest
from fixate.patch.agent import PatchGeneratorAgent
from fixate.patch.applicator import PatchApplicator
from fixate.verification.sandbox import DockerSandboxManager, SandboxRunResult
from fixate.verification.runner import TargetedTestRunner
from fixate.localization.agent import SuspectFunction
from fixate.localization.parser import ParsedFailure
from fixate.graph.builder import CodebaseGraphBuilder

logger = logging.getLogger(__name__)


class VerificationAttempt(BaseModel):
    attempt_number: int
    patch: GeneratedPatch
    sandbox_result: SandboxRunResult
    error_summary: Optional[str] = None


class VerificationResult(BaseModel):
    """Final outcome object produced by VerificationAgent."""
    success: bool = Field(..., description="True ONLY if verified by passing sandboxed test run")
    total_attempts: int = Field(..., description="Number of verification attempts made (max 3)")
    verified_patch: Optional[GeneratedPatch] = Field(None, description="Passing patch if successful")
    attempts_history: List[VerificationAttempt] = Field(default_factory=list)
    failure_report: Optional[str] = Field(None, description="Honest failure report if retries exhausted")


class VerificationAgent:
    """Core Verification Agent enforcing real execution in isolated sandboxes with bounded retries."""

    def __init__(
        self,
        patch_agent: Optional[PatchGeneratorAgent] = None,
        sandbox_manager: Optional[DockerSandboxManager] = None,
        max_attempts: int = 3,
    ):
        self.patch_agent = patch_agent or PatchGeneratorAgent()
        self.sandbox = sandbox_manager or DockerSandboxManager()
        self.runner = TargetedTestRunner(sandbox_manager=self.sandbox)
        self.applicator = PatchApplicator()
        self.max_attempts = max_attempts

    def generate_honest_failure_report(
        self,
        suspect: SuspectFunction,
        failure: ParsedFailure,
        attempts: List[VerificationAttempt],
    ) -> str:
        """Produce a comprehensive, honest diagnostic trail when retries are exhausted."""
        report = []
        report.append(f"# Diagnostic Failure Report: Fixate Agent Unresolved Issue")
        report.append(f"**Target Suspect Function**: `{suspect.name}` ({suspect.file_path})")
        report.append(f"**Original Failure**: {failure.exception_type}: {failure.exception_message} in `{failure.test_name}`")
        report.append(f"**Attempts Exhausted**: {len(attempts)} / {self.max_attempts}\n")
        report.append(f"## Summary of Attempts & Learned Information:")

        for att in attempts:
            report.append(f"### Attempt #{att.attempt_number}:")
            report.append(f"- **Explanation**: {att.patch.explanation}")
            report.append(f"- **Proposed Diff**:\n```diff\n{att.patch.unified_diff}\n```")
            report.append(f"- **Result**: FAILED (Exit Code {att.sandbox_result.exit_code})")
            if att.error_summary:
                report.append(f"- **Sandbox Error Output**:\n```\n{att.error_summary[:400]}\n```\n")

        report.append(f"## Human Engineer Recommendation:")
        report.append(
            f"The agent attempted {len(attempts)} distinct patch variations, but sandboxed test execution did not pass.\n"
            f"Human review recommended for `{suspect.file_path}` around line {suspect.code.splitlines()[0] if suspect.code else 1}.\n"
            f"Check if structural refactoring or external API contract changes are required."
        )
        return "\n".join(report)

    def verify_fix(
        self,
        repo_dir: str,
        graph_builder: CodebaseGraphBuilder,
        suspect: SuspectFunction,
        failure: ParsedFailure,
        past_fix_examples: List[str] = None,
    ) -> VerificationResult:
        """Run the bounded retry verification loop (max 3 attempts)."""
        attempts_history: List[VerificationAttempt] = []
        previous_error: Optional[str] = None

        affected_tests = self.runner.get_affected_tests(
            graph_builder=graph_builder,
            patched_file=suspect.file_path,
            failing_test_name=failure.test_name,
        )

        for attempt in range(1, self.max_attempts + 1):
            logger.info(f"--- Verification Attempt {attempt}/{self.max_attempts} ---")

            tmp_checkout = tempfile.mkdtemp(prefix=f"fixate_sandbox_attempt_{attempt}_")
            try:
                for item in os.listdir(repo_dir):
                    if item in (".git", "__pycache__", "venv", ".venv", "chroma_db"):
                        continue
                    s = os.path.join(repo_dir, item)
                    d = os.path.join(tmp_checkout, item)
                    if os.path.isdir(s):
                        shutil.copytree(s, d)
                    else:
                        shutil.copy2(s, d)

                request = PatchRequest(
                    target_file=suspect.file_path,
                    suspect_function_name=suspect.name,
                    suspect_code=suspect.code,
                    exception_type=failure.exception_type,
                    exception_message=failure.exception_message,
                    failing_test_name=failure.test_name,
                    past_fix_examples=past_fix_examples or [],
                    previous_attempt_error=previous_error,
                )

                patch, apply_res = self.patch_agent.generate_validated_patch(request)

                if not apply_res.success:
                    err_msg = f"Patch application failed: {apply_res.error_message}"
                    logger.warning(f"Attempt {attempt}: {err_msg}")
                    attempts_history.append(
                        VerificationAttempt(
                            attempt_number=attempt,
                            patch=patch,
                            sandbox_result=SandboxRunResult(
                                passed=False, exit_code=1, stdout="", stderr=err_msg, execution_time_seconds=0
                            ),
                            error_summary=err_msg,
                        )
                    )
                    previous_error = err_msg
                    continue

                # Locate target disk file cleanly inside tmp_checkout
                target_disk_file = os.path.join(tmp_checkout, suspect.file_path)
                if not os.path.exists(target_disk_file):
                    base_name = os.path.basename(suspect.file_path)
                    for root, dirs, files in os.walk(tmp_checkout):
                        if base_name in files:
                            target_disk_file = os.path.join(root, base_name)
                            break

                if os.path.exists(target_disk_file):
                    self.applicator.apply_patch_to_file(target_disk_file, patch.unified_diff)
                else:
                    logger.warning(f"Target disk file not found for patch application: {suspect.file_path}")

                run_res = self.runner.run_targeted_verification(
                    workspace_dir=tmp_checkout,
                    failing_test=failure.failing_file,
                    affected_tests=affected_tests,
                    run_full_suite_confirm=(attempt == 1 or attempt == self.max_attempts),
                )

                attempt_record = VerificationAttempt(
                    attempt_number=attempt,
                    patch=patch,
                    sandbox_result=run_res,
                    error_summary=None if run_res.passed else (run_res.stderr or run_res.stdout[:500]),
                )
                attempts_history.append(attempt_record)

                if run_res.passed:
                    logger.info(f"SUCCESS: Patch verified cleanly by passing sandboxed test run on attempt {attempt}!")
                    return VerificationResult(
                        success=True,
                        total_attempts=attempt,
                        verified_patch=patch,
                        attempts_history=attempts_history,
                        failure_report=None,
                    )

                previous_error = run_res.stderr or run_res.stdout[-1000:]
                logger.warning(f"Attempt {attempt} failed tests in sandbox. Feed back error into next attempt.")

            finally:
                shutil.rmtree(tmp_checkout, ignore_errors=True)

        # Retry cap exhausted: generate honest failure diagnostic report
        failure_report = self.generate_honest_failure_report(
            suspect=suspect,
            failure=failure,
            attempts=attempts_history,
        )

        return VerificationResult(
            success=False,
            total_attempts=self.max_attempts,
            verified_patch=None,
            attempts_history=attempts_history,
            failure_report=failure_report,
        )
