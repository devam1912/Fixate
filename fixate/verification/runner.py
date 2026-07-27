"""Targeted test runner for affected test selection and verification execution.

Efficiency Design Note:
Running the entire test suite on every single patch attempt is inefficient and slow.
Using the Codebase AST Dependency Graph, Fixate selects ONLY:
1. The original failing test case.
2. Any test functions that directly call or import the patched target code symbol.
Once the targeted subset passes, a final full-suite confirmation pass can be run.
"""

import os
import logging
from typing import List, Optional

from fixate.graph.builder import CodebaseGraphBuilder
from fixate.graph.traversal import GraphTraversal
from fixate.verification.sandbox import DockerSandboxManager, SandboxRunResult

logger = logging.getLogger(__name__)


class TargetedTestRunner:
    """Selects affected test files/functions via dependency graph and executes targeted sandbox runs."""

    def __init__(self, sandbox_manager: Optional[DockerSandboxManager] = None):
        self.sandbox = sandbox_manager or DockerSandboxManager()

    def get_affected_tests(
        self,
        graph_builder: CodebaseGraphBuilder,
        patched_file: str,
        failing_test_name: str,
    ) -> List[str]:
        """Determine minimal subset of affected test files/functions using graph traversal."""
        affected_tests: List[str] = []

        # Always include the failing test if available
        if failing_test_name and "test" in failing_test_name.lower():
            affected_tests.append(failing_test_name)

        # Query dependency graph for tests exercising patched file symbols
        traversal = GraphTraversal(graph_builder)
        for sym_id, sym in graph_builder.symbols.items():
            if patched_file in sym.file_path and not sym.is_test:
                tests = traversal.get_tests_for_symbol(sym_id)
                for t in tests:
                    if t.name not in affected_tests and "test" in t.name.lower():
                        affected_tests.append(t.name)

        logger.info(f"Selected {len(affected_tests)} targeted tests for verification: {affected_tests}")
        return affected_tests

    def run_targeted_verification(
        self,
        workspace_dir: str,
        failing_test: str,
        affected_tests: List[str],
        run_full_suite_confirm: bool = False,
    ) -> SandboxRunResult:
        """Execute targeted tests inside isolated sandbox.
        
        Args:
            workspace_dir: Directory containing checkout with patch applied.
            failing_test: Original failing test name or file.
            affected_tests: List of affected test names from dependency graph.
            run_full_suite_confirm: If True, runs full pytest suite after targeted tests pass.
            
        Returns:
            SandboxRunResult with test execution pass/fail status and output logs.
        """
        # Filter for actual test function/class names containing 'test'
        valid_tests = [t for t in affected_tests if "test" in t.lower()]

        if valid_tests:
            k_expr = " or ".join(valid_tests)
            cmd = f'python -m pytest -k "{k_expr}"'
        elif failing_test and "test" in failing_test.lower():
            cmd = f'python -m pytest {failing_test}'
        else:
            cmd = "python -m pytest"

        logger.info(f"Executing targeted verification command: {cmd}")
        result = self.sandbox.run_tests_in_sandbox(workspace_dir, test_command=cmd)

        # Optional full suite confirmation pass if targeted run passed
        if result.passed and run_full_suite_confirm and valid_tests:
            logger.info("Targeted tests passed! Running final full-suite confirmation pass...")
            full_cmd = "python -m pytest"
            full_result = self.sandbox.run_tests_in_sandbox(workspace_dir, test_command=full_cmd)
            return full_result

        return result
