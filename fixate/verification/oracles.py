"""What counts as proof that a patch worked.

The verification loop does not care *how* a fix is proved, only that something
independent and reproducible confirms it. Two oracles implement that contract:

* :class:`TestSuiteOracle` -- the repository's own tests must pass. Strongest
  evidence, and the default whenever tests exist.
* :class:`DiagnosticGateOracle` -- a checker (parser, type-checker, linter) that
  reported a specific problem must stop reporting it, without introducing new
  ones. Used when a repository has no runnable tests.

The second oracle carries the same discipline as the first. It is not enough for
the targeted complaint to disappear: the total set of diagnostics must not grow.
Otherwise "fixing" an undefined name by deleting the function that uses it would
count as a repair, which is precisely the kind of hollow win this codebase exists
to refuse.
"""

import logging
import time
from typing import Dict, List, Optional, Protocol

from fixate.languages.diagnostics import Diagnostic, DiagnosticGate, own_source_only
from fixate.verification.runner import TargetedTestRunner
from fixate.verification.sandbox import SandboxRunResult

logger = logging.getLogger(__name__)


class VerificationOracle(Protocol):
    """Something that can decide whether a patched workspace is fixed."""

    name: str

    def verify(self, workspace_dir: str) -> SandboxRunResult:
        """Check the patched workspace and report the outcome."""
        ...

    def describe(self) -> str:
        """One line explaining what a pass from this oracle proves."""
        ...


class TestSuiteOracle:
    """Proof by the repository's own tests."""

    name = "test-suite"

    def __init__(
        self,
        runner: TargetedTestRunner,
        failing_test: str,
        affected_tests: List[str],
        custom_env: Optional[Dict[str, str]] = None,
        test_file: Optional[str] = None,
        executable: Optional[str] = None,
    ):
        self.runner = runner
        self.failing_test = failing_test
        self.affected_tests = affected_tests
        self.custom_env = custom_env
        self.test_file = test_file
        self.executable = executable

    def verify(self, workspace_dir: str) -> SandboxRunResult:
        return self.runner.run_targeted_verification(
            workspace_dir=workspace_dir,
            failing_test=self.failing_test,
            affected_tests=self.affected_tests,
            custom_env=self.custom_env,
            test_file=self.test_file,
            executable=self.executable,
        )

    def describe(self) -> str:
        return "the failing test passes"


class DiagnosticGateOracle:
    """Proof by a checker that previously reported a specific problem."""

    def __init__(
        self,
        gate: DiagnosticGate,
        baseline: List[Diagnostic],
        target: Diagnostic,
        executable: Optional[str] = None,
    ):
        self.gate = gate
        self.baseline = baseline
        self.target = target
        self.executable = executable
        self.name = f"gate:{gate.name}"

    def verify(self, workspace_dir: str) -> SandboxRunResult:
        started = time.time()
        try:
            # Same filter used at selection time, so verification is judged against
            # the repository's own code and not against its dependencies.
            remaining = own_source_only(self.gate.run(workspace_dir, self.executable))
        except Exception as exc:
            logger.error("Gate %s failed to run during verification: %s", self.gate.name, exc)
            return SandboxRunResult(
                passed=False,
                exit_code=1,
                stdout="",
                stderr=f"The {self.gate.name} gate could not be run: {exc}",
                execution_time_seconds=time.time() - started,
            )

        elapsed = time.time() - started
        identities = {d.identity for d in remaining}
        resolved = self.target.identity not in identities

        # Regressions are judged against the baseline, so a patch cannot trade the
        # reported defect for a new one and still be called a fix.
        baseline_identities = {d.identity for d in self.baseline}
        introduced = [d for d in remaining if d.identity not in baseline_identities]

        if resolved and not introduced:
            return SandboxRunResult(
                passed=True,
                exit_code=0,
                stdout=(
                    f"{self.gate.name}: resolved {self.target.describe()}\n"
                    f"{len(remaining)} diagnostic(s) remain (was {len(self.baseline)})."
                ),
                stderr="",
                execution_time_seconds=elapsed,
            )

        problems: List[str] = []
        if not resolved:
            problems.append(
                f"The reported problem is still present: {self.target.describe()}"
            )
        if introduced:
            problems.append(
                f"The patch introduced {len(introduced)} new diagnostic(s):\n"
                + "\n".join(f"  {d.describe()}" for d in introduced[:10])
            )

        return SandboxRunResult(
            passed=False,
            exit_code=1,
            stdout=f"{self.gate.name}: {len(remaining)} diagnostic(s) reported.",
            stderr="\n".join(problems),
            execution_time_seconds=elapsed,
        )

    def describe(self) -> str:
        return f"{self.gate.proves} (verified by {self.gate.name})"
