"""The bounded generate-apply-test-learn loop.

Each attempt runs against a fresh copy of the repository, so a failed attempt
cannot leave debris that contaminates the next one, and the working tree is only
touched once a patch has actually passed its tests.

Three properties of this loop were established by production failures and must be
preserved by any future change:

1. A patch that fails to apply never reaches the sandbox. Testing an unmodified
   file measures the flakiness of the test suite, not the quality of the patch --
   and if the suite happens to pass, the engine claims a repair it never made.
2. The file is confirmed changed on disk before tests run. This is deliberate
   redundancy behind the applicator's own no-op check, because the consequence of
   a miss is a false "healed" verdict rather than a crash.
3. A missing LLM aborts the loop immediately. Burning three identical attempts on
   a provider that cannot answer wastes minutes and buries the real cause under
   three misleading patch-application errors.
"""

import difflib
import logging
import os
import shutil
import tempfile
from enum import Enum
from typing import Dict, List, Optional

from pydantic import BaseModel, Field

from fixate.errors import LLMUnavailableError, PatchGenerationError, VerificationError
from fixate.graph.builder import CodebaseGraphBuilder
from fixate.languages.base import LanguageToolchain
from fixate.localization.agent import SuspectFunction
from fixate.localization.parser import ParsedFailure
from fixate.patch.agent import PatchGeneratorAgent
from fixate.patch.applicator import PatchApplicator
from fixate.patch.schema import GeneratedPatch, PatchRequest
from fixate.verification.oracles import (
    DiagnosticGateOracle,
    TestSuiteOracle,
    VerificationOracle,
)
from fixate.verification.runner import TargetedTestRunner
from fixate.verification.sandbox import SandboxRunResult

logger = logging.getLogger(__name__)

MAX_FEEDBACK_CHARS = 4000


class AttemptOutcome(str, Enum):
    """What actually happened on one attempt."""

    PASSED = "passed"
    AUTOFIXED = "autofixed"
    CHECK_FAILED = "check_failed"
    PATCH_REJECTED = "patch_rejected"
    GENERATION_FAILED = "generation_failed"


class VerificationAttempt(BaseModel):
    attempt_number: int
    proposed_patch: GeneratedPatch
    sandbox_result: SandboxRunResult
    learned_feedback: str
    outcome: AttemptOutcome = AttemptOutcome.CHECK_FAILED


class VerificationResult(BaseModel):
    success: bool
    verified_patch: Optional[GeneratedPatch] = None
    total_attempts: int
    attempts_history: List[VerificationAttempt] = Field(default_factory=list)
    failure_report: Optional[str] = None


def _no_run(message: str) -> SandboxRunResult:
    """A placeholder result for attempts where the sandbox deliberately never ran."""
    return SandboxRunResult(
        passed=False, exit_code=-1, stdout="", stderr=message, execution_time_seconds=0.0
    )


class VerificationAgent:
    """Iterates patch generation against sandboxed tests until one passes."""

    def __init__(
        self,
        patch_agent: Optional[PatchGeneratorAgent] = None,
        max_attempts: int = 3,
        toolchain: Optional["LanguageToolchain"] = None,
        executable: Optional[str] = None,
        oracle: Optional[VerificationOracle] = None,
    ):
        self.max_attempts = max_attempts
        self.patch_agent = patch_agent or PatchGeneratorAgent()
        self.applicator = PatchApplicator()
        self.toolchain = toolchain
        self.executable = executable
        self.runner = TargetedTestRunner(toolchain=toolchain)
        # When supplied, this replaces the test suite as the thing that must pass.
        # Used for repositories with no tests, where a parser, type-checker, or
        # linter provides the objective signal instead.
        self.oracle = oracle

    def verify_fix(
        self,
        repo_dir: str,
        graph_builder: CodebaseGraphBuilder,
        suspect: SuspectFunction,
        failure: ParsedFailure,
        past_fix_examples: Optional[List[str]] = None,
        custom_env: Optional[Dict[str, str]] = None,
        related_code_context: Optional[List[str]] = None,
    ) -> VerificationResult:
        """Run the bounded retry loop.

        Raises:
            LLMUnavailableError: no live model is configured to generate patches.
        """
        target_relative = self._relative_target(suspect.file_path, repo_dir)
        affected_tests = self.runner.determine_targeted_tests(
            graph_builder=graph_builder,
            patched_file=target_relative,
            failing_test_name=failure.test_name,
        )
        test_context = self._read_test_source(repo_dir, failure)
        relevant_history = self._filter_history(past_fix_examples, target_relative)

        # Some diagnostics have exactly one accepted form, and the checker that
        # reports them can write it. Asking a model to reconstruct that form burns
        # three attempts producing near-misses; the tool produces it correctly on
        # the first try, for free. The proof obligation is unchanged either way --
        # the oracle still has to agree afterwards.
        autofixed = self._try_checker_autofix(repo_dir, target_relative)
        if autofixed is not None:
            return autofixed

        attempts: List[VerificationAttempt] = []
        previous_error: Optional[str] = None

        for attempt_number in range(1, self.max_attempts + 1):
            logger.info("--- Verification attempt %d/%d ---", attempt_number, self.max_attempts)
            workspace = tempfile.mkdtemp(prefix=f"fixate_attempt_{attempt_number}_")

            try:
                shutil.copytree(
                    repo_dir, workspace, dirs_exist_ok=True, ignore=shutil.ignore_patterns(".git")
                )
                target_path = os.path.join(workspace, target_relative)
                if not os.path.exists(target_path):
                    raise VerificationError(
                        f"Suspect file {target_relative} does not exist inside the repository copy.",
                        remedy="Confirm the localized path is inside the repository being healed.",
                    )

                with open(target_path, "r", encoding="utf-8") as handle:
                    source_before = handle.read()

                request = PatchRequest(
                    target_file=target_relative,
                    suspect_function_name=suspect.name,
                    suspect_code=source_before,
                    exception_type=failure.exception_type,
                    exception_message=failure.exception_message,
                    failing_test_name=failure.test_name,
                    test_code_context=test_context,
                    related_code_context=related_code_context or [],
                    past_fix_examples=relevant_history,
                    previous_attempt_error=previous_error,
                    checker_guidance=self._checker_guidance(),
                    proof_requirement=(
                        self.oracle.describe() if self.oracle else "the failing test passes"
                    ),
                )

                # A missing model is a configuration fault, not a bad attempt;
                # retrying cannot change the outcome.
                try:
                    patch = self.patch_agent.generate_patch(request)
                except LLMUnavailableError:
                    raise
                except PatchGenerationError as exc:
                    feedback = f"Attempt {attempt_number}: patch generation failed -- {exc.message}"
                    logger.warning(feedback)
                    previous_error = feedback
                    attempts.append(
                        VerificationAttempt(
                            attempt_number=attempt_number,
                            proposed_patch=GeneratedPatch(
                                target_file=target_relative,
                                unified_diff="",
                                explanation=exc.message,
                                lines_changed=0,
                            ),
                            sandbox_result=_no_run(feedback),
                            learned_feedback=feedback,
                            outcome=AttemptOutcome.GENERATION_FAILED,
                        )
                    )
                    continue

                applied = self.applicator.apply_patch_to_file(target_path, patch.unified_diff)
                if not applied.success:
                    feedback = (
                        f"Attempt {attempt_number}: the patch could not be applied "
                        f"({applied.reason.value if applied.reason else 'unknown'}). "
                        f"{applied.error_message}"
                    )
                    logger.warning(feedback)
                    previous_error = feedback
                    attempts.append(
                        VerificationAttempt(
                            attempt_number=attempt_number,
                            proposed_patch=patch,
                            sandbox_result=_no_run(feedback),
                            learned_feedback=feedback,
                            outcome=AttemptOutcome.PATCH_REJECTED,
                        )
                    )
                    continue

                with open(target_path, "r", encoding="utf-8") as handle:
                    source_after = handle.read()
                if source_after == source_before:
                    feedback = (
                        f"Attempt {attempt_number}: the patch reported success but left "
                        f"{target_relative} byte-identical. Refusing to credit an unchanged "
                        "file with a repair."
                    )
                    logger.error(feedback)
                    previous_error = feedback
                    attempts.append(
                        VerificationAttempt(
                            attempt_number=attempt_number,
                            proposed_patch=patch,
                            sandbox_result=_no_run(feedback),
                            learned_feedback=feedback,
                            outcome=AttemptOutcome.PATCH_REJECTED,
                        )
                    )
                    continue

                oracle = self.oracle or TestSuiteOracle(
                    runner=self.runner,
                    failing_test=failure.test_name,
                    affected_tests=affected_tests,
                    custom_env=custom_env,
                    # The test file is found by locating the test's definition;
                    # failure.failing_file points at the defect, not the spec.
                    test_file=self._test_file_from(failure),
                    executable=self.executable,
                )
                run = oracle.verify(workspace)
                feedback = self._describe_run(attempt_number, run, oracle)
                attempts.append(
                    VerificationAttempt(
                        attempt_number=attempt_number,
                        proposed_patch=patch,
                        sandbox_result=run,
                        learned_feedback=feedback,
                        outcome=AttemptOutcome.PASSED if run.passed else AttemptOutcome.CHECK_FAILED,
                    )
                )

                if run.passed:
                    logger.info("Verification succeeded on attempt %d.", attempt_number)
                    shutil.copytree(
                        workspace,
                        repo_dir,
                        dirs_exist_ok=True,
                        ignore=shutil.ignore_patterns(".git"),
                    )
                    return VerificationResult(
                        success=True,
                        verified_patch=patch,
                        total_attempts=attempt_number,
                        attempts_history=attempts,
                        failure_report=None,
                    )

                logger.warning(
                    "Attempt %d failed with exit code %d; feeding the output back.",
                    attempt_number,
                    run.exit_code,
                )
                previous_error = feedback

            finally:
                shutil.rmtree(workspace, ignore_errors=True)

        return VerificationResult(
            success=False,
            verified_patch=None,
            total_attempts=len(attempts),
            attempts_history=attempts,
            failure_report=self.generate_failure_report(suspect, attempts, self.oracle),
        )

    def _checker_guidance(self) -> Optional[str]:
        """The checker's own required text for the targeted diagnostic, if it has one."""
        if isinstance(self.oracle, DiagnosticGateOracle) and self.oracle.target.suggested_fix:
            return self.oracle.target.suggested_fix
        return None

    def _try_checker_autofix(
        self, repo_dir: str, target_relative: str
    ) -> Optional[VerificationResult]:
        """Let the checker repair its own diagnostic, if it can and the oracle agrees.

        Returns None -- meaning "hand over to the model" -- whenever the gate has
        no fix, declines to apply it, or applies one the oracle still rejects. A
        tool fix earns acceptance on exactly the same terms as a generated patch:
        the targeted diagnostic is gone and nothing new appeared.
        """
        oracle = self.oracle
        if not isinstance(oracle, DiagnosticGateOracle):
            return None

        workspace = tempfile.mkdtemp(prefix="fixate_autofix_")
        try:
            shutil.copytree(
                repo_dir, workspace, dirs_exist_ok=True, ignore=shutil.ignore_patterns(".git")
            )
            target_path = os.path.join(workspace, target_relative)
            if not os.path.exists(target_path):
                # The main loop raises a precise error for this; don't pre-empt it.
                return None

            with open(target_path, "r", encoding="utf-8", errors="replace") as handle:
                before = handle.read()

            try:
                changed = oracle.gate.autofix(workspace, oracle.target, self.executable)
            except Exception as exc:
                logger.warning("Gate %s failed while auto-fixing: %s", oracle.gate.name, exc)
                return None

            if not changed:
                logger.info(
                    "Gate %s has no automatic fix for %s; handing over to the model.",
                    oracle.gate.name,
                    oracle.target.identity,
                )
                return None

            run = oracle.verify(workspace)
            if not run.passed:
                logger.info(
                    "The %s auto-fix did not satisfy the oracle; handing over to the model.",
                    oracle.gate.name,
                )
                return None

            with open(target_path, "r", encoding="utf-8", errors="replace") as handle:
                after = handle.read()

            patch = GeneratedPatch(
                target_file=target_relative,
                unified_diff="".join(
                    difflib.unified_diff(
                        before.splitlines(keepends=True),
                        after.splitlines(keepends=True),
                        fromfile=f"a/{target_relative}",
                        tofile=f"b/{target_relative}",
                    )
                ),
                explanation=(
                    f"Applied {oracle.gate.name}'s own fix for "
                    f"{oracle.target.code or 'the reported diagnostic'}. This rule has a "
                    f"single accepted form, which the checker supplies directly -- no model "
                    f"was involved in writing this change."
                ),
                lines_changed=abs(len(after.splitlines()) - len(before.splitlines())) or 1,
            )

            logger.info("Gate %s auto-fixed %s.", oracle.gate.name, oracle.target.identity)
            shutil.copytree(
                workspace, repo_dir, dirs_exist_ok=True, ignore=shutil.ignore_patterns(".git")
            )
            return VerificationResult(
                success=True,
                verified_patch=patch,
                total_attempts=0,
                attempts_history=[
                    VerificationAttempt(
                        attempt_number=0,
                        proposed_patch=patch,
                        sandbox_result=run,
                        learned_feedback=(
                            f"Resolved by {oracle.gate.name} itself, before the repair loop ran."
                        ),
                        outcome=AttemptOutcome.AUTOFIXED,
                    )
                ],
                failure_report=None,
            )
        finally:
            shutil.rmtree(workspace, ignore_errors=True)

    def generate_failure_report(
        self,
        suspect: SuspectFunction,
        attempts: List[VerificationAttempt],
        oracle: Optional["VerificationOracle"] = None,
    ) -> str:
        """Write the operator-facing report handed over when the loop gives up."""
        lines = [
            "# Automated Repair Failed",
            "",
            f"**Target**: `{suspect.name}` in `{suspect.file_path}`",
            f"**Why it was suspected**: {suspect.plausibility_reason}",
            f"**Attempts**: {len(attempts)}",
            f"**Proof required**: {oracle.describe() if oracle else 'the failing test passes'}",
            "",
            "## What was tried",
        ]

        for attempt in attempts:
            lines += [
                "",
                f"### Attempt {attempt.attempt_number} -- {attempt.outcome.value.replace('_', ' ')}",
                f"*Rationale*: {attempt.proposed_patch.explanation}",
            ]
            if attempt.proposed_patch.unified_diff.strip():
                lines += ["", f"```diff\n{attempt.proposed_patch.unified_diff}\n```"]
            detail = (attempt.sandbox_result.stderr or attempt.sandbox_result.stdout or "").strip()
            if detail:
                lines += ["", f"```\n{detail[:1500]}\n```"]

        lines += ["", "## Recommended next step", self._recommendation(attempts, suspect, oracle)]
        return "\n".join(lines)

    def _recommendation(
        self,
        attempts: List[VerificationAttempt],
        suspect: SuspectFunction,
        oracle: Optional["VerificationOracle"] = None,
    ) -> str:
        """Turn the pattern of failures into concrete advice."""
        outcomes = {attempt.outcome for attempt in attempts}

        if outcomes == {AttemptOutcome.PATCH_REJECTED}:
            return (
                "Every proposed patch was rejected before any test ran, so the code was "
                f"never modified and `{suspect.file_path}` is unchanged. The model could not "
                "quote the source accurately, which usually means the localized symbol is not "
                "where the defect actually is. Re-check the localization before re-running."
            )
        if AttemptOutcome.GENERATION_FAILED in outcomes:
            return (
                "The model failed to return a usable patch. Check provider quota and "
                "connectivity, then re-trigger the incident."
            )
        if outcomes == {AttemptOutcome.CHECK_FAILED}:
            if oracle is not None and oracle.name.startswith("gate:"):
                return (
                    f"Every patch applied cleanly, but the checker still reports the same "
                    f"problem, so none of them actually satisfied it. Run the checker "
                    f"directly to see its expected output -- many formatting and import "
                    f"rules have an exact required form that a near-miss will not match, "
                    f"and some can be resolved automatically by the tool itself."
                )
            return (
                "Patches applied cleanly but the tests still failed. The defect is likely "
                "not confined to the localized symbol, or the failing test depends on "
                "external state (network, database, environment) that the sandbox does not "
                "reproduce. Human review is recommended."
            )
        return (
            "Attempts failed for mixed reasons; review the individual attempts above. "
            "Human review is recommended."
        )

    def _describe_run(
        self,
        attempt_number: int,
        run: SandboxRunResult,
        oracle: Optional[VerificationOracle] = None,
    ) -> str:
        body = f"{run.stdout}\n{run.stderr}".strip()
        if len(body) > MAX_FEEDBACK_CHARS:
            # Keep both ends: the head carries collection errors, the tail carries
            # the assertion summary.
            half = MAX_FEEDBACK_CHARS // 2
            body = f"{body[:half]}\n...\n[truncated]\n...\n{body[-half:]}"
        # Feedback names what actually had to hold. Saying "tests failed" when the
        # oracle is a linter or type-checker misdescribes the run to the operator,
        # and misleads the model on the next attempt.
        expectation = oracle.describe() if oracle else "the failing test passes"
        if run.passed:
            return f"Attempt {attempt_number}: satisfied -- {expectation}."
        return (
            f"Attempt {attempt_number}: still not satisfied -- required that "
            f"{expectation} (exit code {run.exit_code}).\n{body}"
        )

    @staticmethod
    def _test_file_from(failure: ParsedFailure) -> Optional[str]:
        """Pick the spec file out of the traceback, if one is identifiable.

        Only frames that look like test files qualify; the deepest frame is the
        source under test and would target the wrong file.
        """
        for frame in failure.stack_frames:
            normalized = frame.file_path.replace("\\", "/").lower()
            base = normalized.rsplit("/", 1)[-1]
            if (
                base.startswith("test_")
                or base.endswith("_test.py")
                or ".test." in base
                or ".spec." in base
                or "/tests/" in normalized
                or "/__tests__/" in normalized
            ):
                return frame.file_path
        return None

    def _relative_target(self, file_path: str, repo_dir: str) -> str:
        """Express the suspect's path relative to the repository root."""
        if os.path.isabs(file_path):
            try:
                return os.path.relpath(file_path, repo_dir)
            except ValueError:
                return os.path.basename(file_path)
        return file_path

    def _read_test_source(self, repo_dir: str, failure: ParsedFailure) -> str:
        """Read the failing test's source so the model can see the assertion."""
        if not failure.failing_file:
            return ""

        candidate = os.path.join(repo_dir, failure.failing_file.split(":")[0])
        if not os.path.exists(candidate):
            basename = os.path.basename(failure.failing_file.split(":")[0])
            candidate = ""
            for root, dirs, files in os.walk(repo_dir):
                dirs[:] = [d for d in dirs if d not in (".git", "__pycache__", ".venv", "venv")]
                if basename in files:
                    candidate = os.path.join(root, basename)
                    break

        if not candidate or not os.path.exists(candidate):
            return ""

        try:
            with open(candidate, "r", encoding="utf-8", errors="replace") as handle:
                return handle.read()
        except OSError as exc:
            logger.warning("Could not read test source %s: %s", candidate, exc)
            return ""

    def _filter_history(self, examples: Optional[List[str]], target_relative: str) -> List[str]:
        """Keep only prior diffs that touched this file.

        A diff from an unrelated module reads as an instruction to make similar
        edits here, which historically produced patches aimed at the wrong file.
        """
        if not examples:
            return []
        basename = os.path.basename(target_relative)
        return [example for example in examples if basename in example]
