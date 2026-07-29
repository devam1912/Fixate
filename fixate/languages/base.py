"""The language seam.

Every stage of the pipeline needs to do something language-specific: parse symbols,
read a failure log, check that a patch still compiles, install dependencies, run a
subset of tests. Those decisions used to be welded into the stages themselves --
pytest commands in the runner, ``ast.parse`` in the applicator, PYTHONPATH in the
sandbox -- which is why the engine could rank a JavaScript file as its top suspect
and then have no way to patch or verify it.

A toolchain gathers all of those decisions behind one interface so the stages stay
language-agnostic. Adding a language means implementing this class and registering
it; it should not mean touching the orchestrator.
"""

import os
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Dict, List, Optional, Tuple

from fixate.graph.base_parser import BaseLanguageParser
from fixate.languages.diagnostics import DiagnosticGate
from fixate.localization.parser import ParsedFailure


def relative_to_workspace(workspace_dir: str, file_path: str) -> str:
    """Express a path relative to the workspace, in forward-slash form.

    Test runners are invoked with the workspace as their working directory, so a
    selection argument must be relative to it. Containment is tested with
    ``commonpath`` rather than ``os.path.isabs``: recent Python no longer treats a
    leading-slash POSIX path as absolute on Windows, so an ``isabs`` guard silently
    passes the untouched absolute path through to the runner.
    """
    if not file_path:
        return file_path

    normalized_file = os.path.normpath(file_path)
    normalized_workspace = os.path.normpath(workspace_dir) if workspace_dir else ""

    if normalized_workspace:
        try:
            if os.path.commonpath([normalized_file, normalized_workspace]) == normalized_workspace:
                normalized_file = os.path.relpath(normalized_file, normalized_workspace)
        except ValueError:
            # Different drives, or one path relative and the other absolute.
            pass

    return normalized_file.replace("\\", "/")


@dataclass
class SyntaxIssue:
    """A structural defect in patched source, reported back to the model."""

    message: str
    line: Optional[int] = None

    def describe(self) -> str:
        return f"{self.message} at line {self.line}" if self.line else self.message


@dataclass
class InstallResult:
    """Outcome of preparing a repository's third-party dependencies."""

    succeeded: bool
    detail: str = ""
    # Interpreter or runtime to execute tests with, when the install created an
    # isolated environment rather than using the ambient one.
    executable: Optional[str] = None
    packages: List[str] = field(default_factory=list)


@dataclass
class TestSelection:
    """What the verification stage wants to run.

    Either a specific test, a specific file, or the whole suite. Toolchains
    translate this into their runner's own selection syntax.
    """

    #: Tells pytest not to collect this as a test class on account of its name.
    __test__ = False

    test_name: Optional[str] = None
    file_path: Optional[str] = None

    @property
    def is_whole_suite(self) -> bool:
        return not (self.test_name or self.file_path)


class LanguageToolchain(ABC):
    """Everything the pipeline needs to know about one language."""

    #: Stable identifier used in telemetry and summaries, e.g. "python".
    name: str = "unknown"

    #: File extensions this toolchain owns, lowercase and dot-prefixed.
    extensions: Tuple[str, ...] = ()

    #: Manifest filenames whose presence indicates the language is in use.
    manifests: Tuple[str, ...] = ()

    #: Runner exit codes meaning "the selection matched nothing", as distinct from
    #: "the tests failed". These escalate to a full-suite run rather than being
    #: reported as a pass -- a verification step that passes because it ran
    #: nothing is worse than one that is merely slow.
    selection_failure_exit_codes: Tuple[int, ...] = ()

    def owns_file(self, file_path: str) -> bool:
        return file_path.lower().endswith(self.extensions)

    def detects(self, repo_dir: str) -> bool:
        """Whether this language appears to be used in the repository."""
        import os

        return any(os.path.exists(os.path.join(repo_dir, m)) for m in self.manifests)

    @abstractmethod
    def parser(self) -> BaseLanguageParser:
        """Return the symbol extractor for this language."""

    @abstractmethod
    def owns_log(self, log: str) -> bool:
        """Whether this toolchain's test runner produced the given output."""

    @abstractmethod
    def parse_failure(self, log: str) -> ParsedFailure:
        """Extract the first failure from this runner's output.

        Raises:
            TracebackParseError: if the log describes no identifiable failure.
        """

    @abstractmethod
    def syntax_error(self, source: str, file_path: str) -> Optional[SyntaxIssue]:
        """Return a structural defect in the source, or None if it is well-formed.

        This backs the applicator's guarantee that a patch never leaves a file
        unparseable. Verification would catch it later via a collection error;
        catching it here costs nothing and names the real cause.
        """

    @abstractmethod
    def test_command(self, workspace_dir: str, target: TestSelection) -> List[str]:
        """Build the runner invocation for a target."""

    def diagnostic_gates(self) -> List["DiagnosticGate"]:
        """Checkers usable as a verification oracle when there is no test suite.

        A repository without tests still has objective, reproducible signals -- it
        must parse, it must type-check, it must satisfy its own lint rules. Those
        can play the same role a failing test does: fail before the patch, pass
        after it.
        """
        return []

    def install_dependencies(self, repo_dir: str) -> InstallResult:
        """Prepare third-party dependencies. Default: nothing to do."""
        return InstallResult(succeeded=True, detail="No dependency step for this language.")

    def environment(self, workspace_dir: str) -> Dict[str, str]:
        """Environment overrides needed to import the workspace's own modules."""
        return {}

    #: Phrases a runner prints when it found no tests to run at all, as opposed to
    #: running tests that failed.
    no_tests_markers: Tuple[str, ...] = ()

    def has_test_setup(self, repo_dir: str) -> bool:
        """Whether this repository is configured to run tests at all.

        Decided from the repository's own files, before anything is executed. The
        alternative -- invoke a runner and interpret whatever it prints -- fails
        badly when the runner is not installed or has nothing to configure itself
        from: its crash output looks like a genuine failure, and the engine then
        hunts for a defect inside the runner's own source.

        Default True, so a toolchain that does not override this keeps the old
        behaviour of asking the runner.
        """
        return True

    def collected_nothing(self, output: str) -> bool:
        """Whether the runner found no tests in the repository.

        This is a different condition from "tests failed", and the difference
        matters: a repository with no tests cannot be self-healed at all, because
        the engine's entire guarantee is that a patch passed its tests. Reporting it
        as a parse failure sends the user looking for a broken traceback that was
        never there.
        """
        lowered = (output or "").lower()
        return any(marker.lower() in lowered for marker in self.no_tests_markers)

    def ran_nothing(self, exit_code: int, output: str) -> bool:
        """Whether a finished run failed to select any tests.

        Exit codes alone are not always sufficient -- some runners report "no tests
        found" with the same code they use for genuine failures -- so toolchains may
        also inspect output.
        """
        return exit_code in self.selection_failure_exit_codes

    def __repr__(self) -> str:  # pragma: no cover - diagnostic only
        return f"<{type(self).__name__} name={self.name!r}>"
