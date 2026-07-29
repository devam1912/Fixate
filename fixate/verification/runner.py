"""Selection and execution of the tests that verify a patch.

Running a whole suite to check a one-line fix is slow, and on a repository with
network-dependent or slow integration tests it is also unreliable. This module uses
the dependency graph to pick the smallest set of tests that actually exercise the
patched code, then asks the language's toolchain how to run them.

Test selection is an optimization, and it can be wrong -- the graph may miss a
dynamic call, or the chosen name may match nothing. Every runner reports that
somehow, and those cases escalate to the full suite rather than being reported as a
pass. A verification step that passes because it ran nothing is worse than one that
is merely slow.
"""

import logging
import os
from typing import Dict, List, Optional

from fixate.graph.builder import CodebaseGraphBuilder
from fixate.graph.traversal import GraphTraversal
from fixate.languages.base import LanguageToolchain, TestSelection
from fixate.verification.sandbox import DockerSandboxManager, SandboxRunResult

logger = logging.getLogger(__name__)

VERIFICATION_TIMEOUT_SECONDS = 300


class TargetedTestRunner:
    """Chooses the minimal relevant test set and runs it in the sandbox."""

    def __init__(
        self,
        sandbox_manager: Optional[DockerSandboxManager] = None,
        toolchain: Optional[LanguageToolchain] = None,
    ):
        self.sandbox = sandbox_manager or DockerSandboxManager()
        self._toolchain = toolchain

    @property
    def toolchain(self) -> LanguageToolchain:
        if self._toolchain is None:
            from fixate.languages import registry

            self._toolchain = registry.by_name("python")
        return self._toolchain

    def determine_targeted_tests(
        self,
        graph_builder: CodebaseGraphBuilder,
        patched_file: str,
        failing_test_name: str,
    ) -> List[str]:
        """Return test names exercising the patched file, most relevant first.

        The originally failing test always appears first: a patch that fixes
        everything except the reported failure has not fixed anything.
        """
        traversal = GraphTraversal(graph_builder)
        selected: List[str] = []

        def add(name: str) -> None:
            if name and name not in selected:
                selected.append(name)

        if failing_test_name:
            add(failing_test_name)

        patched_base = os.path.basename(patched_file) if patched_file else ""
        for symbol_id, symbol in graph_builder.symbols.items():
            if symbol.is_test or not patched_base:
                continue
            if os.path.basename(symbol.file_path) != patched_base:
                continue
            for test in traversal.get_tests_for_symbol(symbol_id):
                add(test.name)

        logger.info(
            "Selected %d test(s) covering %s: %s",
            len(selected),
            patched_base or "the repository",
            selected or ["<full suite>"],
        )
        return selected

    def get_affected_tests(
        self,
        graph_builder: CodebaseGraphBuilder,
        patched_file: str,
        failing_test_name: str,
    ) -> List[str]:
        """Alias retained for callers using the older name."""
        return self.determine_targeted_tests(graph_builder, patched_file, failing_test_name)

    def run_targeted_verification(
        self,
        workspace_dir: str,
        failing_test: str,
        affected_tests: List[str],
        run_full_suite_confirm: bool = False,
        custom_env: Optional[Dict[str, str]] = None,
        test_file: Optional[str] = None,
        executable: Optional[str] = None,
    ) -> SandboxRunResult:
        """Run the targeted tests, escalating to the full suite if selection missed."""
        toolchain = self.toolchain
        full_suite = toolchain.test_command(workspace_dir, TestSelection())

        if run_full_suite_confirm:
            return self._run(workspace_dir, full_suite, custom_env, executable)

        target = TestSelection(
            test_name=(affected_tests[0] if affected_tests else failing_test) or None,
            file_path=test_file or self._locate_test_file(workspace_dir, failing_test),
        )
        command = toolchain.test_command(workspace_dir, target)
        result = self._run(workspace_dir, command, custom_env, executable)

        combined = f"{result.stdout}\n{result.stderr}"
        if command != full_suite and toolchain.ran_nothing(result.exit_code, combined):
            logger.warning(
                "Targeted selection %s collected no tests (exit %d); escalating to the full suite.",
                command,
                result.exit_code,
            )
            result = self._run(workspace_dir, full_suite, custom_env, executable)

        return result

    def _locate_test_file(self, workspace_dir: str, failing_test: str) -> Optional[str]:
        """Find the file defining a test, so selection can use an exact target."""
        if not failing_test:
            return None

        toolchain = self.toolchain
        needles = (f"def {failing_test}(", f'"{failing_test}"', f"'{failing_test}'")

        for root, dirs, files in os.walk(workspace_dir):
            dirs[:] = [d for d in dirs if d not in _SKIP_DIRS]
            for filename in files:
                if not toolchain.owns_file(filename):
                    continue
                if not _looks_like_test_file(filename):
                    continue
                path = os.path.join(root, filename)
                try:
                    with open(path, "r", encoding="utf-8", errors="replace") as handle:
                        content = handle.read()
                except OSError:
                    continue
                if any(needle in content for needle in needles):
                    return os.path.relpath(path, workspace_dir).replace("\\", "/")
        return None

    def _run(
        self,
        workspace_dir: str,
        command: List[str],
        custom_env: Optional[Dict[str, str]],
        executable: Optional[str],
    ) -> SandboxRunResult:
        logger.info("Running verification command: %s", " ".join(command))
        return self.sandbox.run_tests_in_sandbox(
            workspace_dir=workspace_dir,
            pytest_cmd=command,
            timeout_seconds=VERIFICATION_TIMEOUT_SECONDS,
            custom_env=custom_env,
            env_overrides=self.toolchain.environment(workspace_dir),
            executable=executable,
        )


_SKIP_DIRS = {".git", "__pycache__", ".venv", "venv", "node_modules", "dist", "build", ".fixate_venv"}


def _looks_like_test_file(filename: str) -> bool:
    lowered = filename.lower()
    return (
        lowered.startswith("test_")
        or lowered.endswith("_test.py")
        or ".test." in lowered
        or ".spec." in lowered
    )
