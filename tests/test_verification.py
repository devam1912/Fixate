"""Unit tests for the sandbox, targeted test selection, and the verification loop."""

import os
import subprocess
import tempfile
from unittest import mock

import pytest

from fixate.errors import LLMUnavailableError
from fixate.graph.builder import CodebaseGraphBuilder
from fixate.llm.gemini import GeminiProvider
from fixate.localization.agent import SuspectFunction
from fixate.localization.parser import ParsedFailure
from fixate.patch.agent import PatchGeneratorAgent
from fixate.patch.schema import GeneratedPatch
from fixate.verification.agent import AttemptOutcome, VerificationAgent
from fixate.verification.sandbox import DockerSandboxManager, build_workspace_pythonpath
from tests.fakes import FakeLLMProvider

BROKEN_SOURCE = """def calculate_tax(amount):
    rate = 0
    return amount * rate
"""

TAX_TEST = """from tax import calculate_tax

def test_calculate_tax():
    assert calculate_tax(100.0) == 20.0
"""

WORKING_DIFF = """--- a/tax.py
+++ b/tax.py
@@ -2,1 +2,1 @@
-    rate = 0
+    rate = 0.2
"""

HALLUCINATED_DIFF = """--- a/tax.py
+++ b/tax.py
@@ -2,1 +2,1 @@
-    rate = self.nonexistent
+    rate = 0.2
"""


def _repo(tmp_dir: str) -> None:
    with open(os.path.join(tmp_dir, "tax.py"), "w", encoding="utf-8") as f:
        f.write(BROKEN_SOURCE)
    with open(os.path.join(tmp_dir, "test_tax.py"), "w", encoding="utf-8") as f:
        f.write(TAX_TEST)


def _suspect() -> SuspectFunction:
    return SuspectFunction(
        symbol_id="tax.py::calculate_tax",
        file_path="tax.py",
        name="calculate_tax",
        code=BROKEN_SOURCE,
        rank=1,
        plausibility_reason="Divides by a zero rate",
    )


def _failure() -> ParsedFailure:
    return ParsedFailure(
        test_name="test_calculate_tax",
        failing_file="tax.py",
        failing_line=3,
        exception_type="AssertionError",
        exception_message="assert 0.0 == 20.0",
        stack_frames=[],
        raw_traceback="E       assert 0.0 == 20.0",
    )


def _agent(diff: str) -> VerificationAgent:
    patch = GeneratedPatch(
        target_file="tax.py", unified_diff=diff, explanation="Set a real rate.", lines_changed=1
    )
    return VerificationAgent(
        patch_agent=PatchGeneratorAgent(llm_provider=FakeLLMProvider({"GeneratedPatch": patch})),
        max_attempts=3,
    )


# --------------------------------------------------------------------------
# Sandbox
# --------------------------------------------------------------------------


def test_pythonpath_builder_honours_posix_separator():
    """Simulates the in-container (Linux) case regardless of the host OS."""
    built = build_workspace_pythonpath("/tmp/repo", inherited="/opt/lib", sep=":")
    entries = [e.replace("\\", "/") for e in built.split(":")]
    assert entries == ["/tmp/repo", "/tmp/repo/src", "/opt/lib"]
    assert ";" not in built


def test_sandbox_subprocess_pythonpath_uses_platform_separator():
    """Workspace and src/ must be importable in the fallback, on Linux as on Windows."""
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp_dir:
        src_dir = os.path.join(tmp_dir, "src")
        os.makedirs(src_dir)
        with open(os.path.join(src_dir, "shipping.py"), "w", encoding="utf-8") as f:
            f.write("def rate():\n    return 7\n")
        with open(os.path.join(tmp_dir, "test_import.py"), "w", encoding="utf-8") as f:
            f.write("from shipping import rate\n\ndef test_rate():\n    assert rate() == 7\n")

        captured = {}
        real_run = subprocess.run

        def spy_run(*args, **kwargs):
            captured["env"] = kwargs.get("env", {})
            return real_run(*args, **kwargs)

        sandbox = DockerSandboxManager()
        sandbox._docker_client = None  # Force the subprocess fallback path

        with mock.patch.object(subprocess, "run", spy_run):
            result = sandbox.run_tests_in_sandbox(tmp_dir, test_command="python -m pytest")

        entries = captured["env"]["PYTHONPATH"].split(os.pathsep)
        assert tmp_dir in entries
        assert src_dir in entries
        assert result.passed is True, result.stdout + result.stderr


# --------------------------------------------------------------------------
# Verification loop
# --------------------------------------------------------------------------


def test_aborts_immediately_when_no_live_llm_is_configured():
    """A missing model is a config fault; retrying it three times buries the cause."""
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp_dir:
        _repo(tmp_dir)
        builder = CodebaseGraphBuilder()
        builder.build_from_directory(tmp_dir)

        agent = VerificationAgent(
            patch_agent=PatchGeneratorAgent(llm_provider=GeminiProvider(api_key=None)),
            max_attempts=3,
        )

        with pytest.raises(LLMUnavailableError):
            agent.verify_fix(
                repo_dir=tmp_dir, graph_builder=builder, suspect=_suspect(), failure=_failure()
            )


def test_verifies_and_writes_back_a_working_patch():
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp_dir:
        _repo(tmp_dir)
        builder = CodebaseGraphBuilder()
        builder.build_from_directory(tmp_dir)

        result = _agent(WORKING_DIFF).verify_fix(
            repo_dir=tmp_dir, graph_builder=builder, suspect=_suspect(), failure=_failure()
        )

        assert result.success is True
        assert result.total_attempts == 1
        assert result.attempts_history[0].outcome is AttemptOutcome.PASSED

        # The verified fix must land in the real workspace, not just the sandbox copy.
        with open(os.path.join(tmp_dir, "tax.py"), encoding="utf-8") as f:
            assert "rate = 0.2" in f.read()


def test_hallucinated_patch_is_rejected_and_never_reaches_the_sandbox():
    """The placebo-healing guard: unapplied patches must not be tested."""
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp_dir:
        _repo(tmp_dir)
        builder = CodebaseGraphBuilder()
        builder.build_from_directory(tmp_dir)

        agent = _agent(HALLUCINATED_DIFF)
        with mock.patch.object(agent.runner, "run_targeted_verification") as sandbox_call:
            result = agent.verify_fix(
                repo_dir=tmp_dir, graph_builder=builder, suspect=_suspect(), failure=_failure()
            )

        sandbox_call.assert_not_called()
        assert result.success is False
        assert result.total_attempts == 3
        assert all(a.outcome is AttemptOutcome.PATCH_REJECTED for a in result.attempts_history)

        # The workspace must be untouched by rejected attempts.
        with open(os.path.join(tmp_dir, "tax.py"), encoding="utf-8") as f:
            assert f.read() == BROKEN_SOURCE

        assert "never modified" in result.failure_report


def test_failed_attempts_feed_their_reason_into_the_next_prompt():
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp_dir:
        _repo(tmp_dir)
        builder = CodebaseGraphBuilder()
        builder.build_from_directory(tmp_dir)

        agent = _agent(HALLUCINATED_DIFF)
        agent.verify_fix(
            repo_dir=tmp_dir, graph_builder=builder, suspect=_suspect(), failure=_failure()
        )

        prompts = agent.patch_agent.llm.prompts
        assert len(prompts) == 3
        assert "previous attempt failed" not in prompts[0].lower()
        assert "context_not_found" in prompts[1]
        assert "context_not_found" in prompts[2]
