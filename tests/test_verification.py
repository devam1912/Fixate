"""Unit tests for Verification Agent, Docker Sandbox Manager, and Retry Bounds."""

import os
import tempfile
import pytest
from fixate.verification.sandbox import DockerSandboxManager
from fixate.verification.runner import TargetedTestRunner
from fixate.verification.agent import VerificationAgent, VerificationResult
from fixate.patch.agent import PatchGeneratorAgent
from fixate.localization.agent import SuspectFunction
from fixate.localization.parser import ParsedFailure
from fixate.graph.builder import CodebaseGraphBuilder
from fixate.llm.gemini import GeminiProvider

SAMPLE_APP_CODE = """def calculate_tax(amount: float) -> float:
    rate = 0
    return amount / rate
"""

SAMPLE_TEST_CODE = """from tax import calculate_tax

def test_calculate_tax():
    res = calculate_tax(100.0)
    assert res == 20.0
"""


def test_sandbox_manager_execution():
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp_dir:
        test_file = os.path.join(tmp_dir, "test_sample.py")
        with open(test_file, "w", encoding="utf-8") as f:
            f.write("def test_pass():\n    assert 1 + 1 == 2\n")

        sandbox = DockerSandboxManager()
        result = sandbox.run_tests_in_sandbox(tmp_dir, test_command="python -m pytest")
        assert result.passed is True
        assert result.exit_code == 0


def test_verification_agent_end_to_end():
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp_dir:
        tax_file = os.path.join(tmp_dir, "tax.py")
        test_file = os.path.join(tmp_dir, "test_tax.py")

        with open(tax_file, "w", encoding="utf-8") as f:
            f.write(SAMPLE_APP_CODE)
        with open(test_file, "w", encoding="utf-8") as f:
            f.write(SAMPLE_TEST_CODE)

        builder = CodebaseGraphBuilder()
        builder.build_from_directory(tmp_dir)

        llm = GeminiProvider(api_key=None)  # Simulation mode
        patch_agent = PatchGeneratorAgent(llm_provider=llm)
        ver_agent = VerificationAgent(patch_agent=patch_agent, max_attempts=3)

        suspect = SuspectFunction(
            symbol_id="tax.py::calculate_tax",
            file_path="tax.py",
            name="calculate_tax",
            code=SAMPLE_APP_CODE,
            rank=1,
            plausibility_reason="Division by zero",
        )

        failure = ParsedFailure(
            failing_file="test_tax.py",
            failing_line=4,
            exception_type="ZeroDivisionError",
            exception_message="division by zero",
            test_name="test_calculate_tax",
            raw_traceback="ZeroDivisionError: division by zero",
            stack_frames=[],
        )

        result: VerificationResult = ver_agent.verify_fix(
            repo_dir=tmp_dir,
            graph_builder=builder,
            suspect=suspect,
            failure=failure,
        )

        assert result.total_attempts <= 3
        assert isinstance(result.success, bool)
        assert len(result.attempts_history) > 0
