"""Python: pytest, AST syntax validation, and venv-isolated dependencies."""

import ast
import logging
import os
import subprocess
import sys
from typing import Dict, List, Optional, Tuple

from fixate.graph.base_parser import BaseLanguageParser
from fixate.graph.python_parser import PythonASTParser
from fixate.languages.diagnostics import (
    DiagnosticGate,
    PyflakesGate,
    PythonSyntaxGate,
    RuffGate,
)
from fixate.languages.base import (
    InstallResult,
    LanguageToolchain,
    SyntaxIssue,
    TestSelection,
    relative_to_workspace,
)
from fixate.localization.parser import FailureTracebackParser, ParsedFailure

logger = logging.getLogger(__name__)

INSTALL_TIMEOUT_SECONDS = 300

# Markers that identify pytest output. Kept specific enough that a JavaScript log
# quoting the word "test" cannot claim to be a pytest run.
_LOG_MARKERS = (
    "=== FAILURES ===",
    "==== FAILURES ====",
    "short test summary info",
    "test session starts",
    "conftest.py",
    "Traceback (most recent call last)",
)


class PythonToolchain(LanguageToolchain):
    name = "python"
    extensions = (".py",)
    manifests = ("requirements.txt", "pyproject.toml", "setup.py", "setup.cfg", "Pipfile")

    # 4 = usage error (bad node id), 5 = no tests collected.
    selection_failure_exit_codes = (4, 5)

    no_tests_markers = ("no tests ran", "collected 0 items")

    def __init__(self) -> None:
        self._parser = PythonASTParser()
        self._failures = FailureTracebackParser()

    def parser(self) -> BaseLanguageParser:
        return self._parser

    def diagnostic_gates(self) -> List[DiagnosticGate]:
        return [PythonSyntaxGate(), RuffGate(), PyflakesGate()]

    def owns_log(self, log: str) -> bool:
        if any(marker in log for marker in _LOG_MARKERS):
            return True
        # A bare "FAILED path.py::test - Error" summary line is unambiguous too.
        return "FAILED " in log and ".py::" in log

    def parse_failure(self, log: str) -> ParsedFailure:
        return self._failures.parse_log(log)

    def syntax_error(self, source: str, file_path: str) -> Optional[SyntaxIssue]:
        try:
            ast.parse(source, filename=file_path)
            return None
        except SyntaxError as exc:
            return SyntaxIssue(message=f"SyntaxError: {exc.msg}", line=exc.lineno)

    def test_command(self, workspace_dir: str, target: TestSelection) -> List[str]:
        base = ["python", "-m", "pytest"]
        if target.is_whole_suite:
            return base

        if target.test_name and target.file_path:
            # An exact node id cannot accidentally widen to a same-named test in
            # another module, which bare -k matching can.
            return base + [f"{self._relative(workspace_dir, target.file_path)}::{target.test_name}"]
        if target.file_path:
            return base + [self._relative(workspace_dir, target.file_path)]
        return base + ["-k", target.test_name]

    def environment(self, workspace_dir: str) -> Dict[str, str]:
        from fixate.verification.sandbox import build_workspace_pythonpath

        inherited = os.environ.get("PYTHONPATH", "")
        return {"PYTHONPATH": build_workspace_pythonpath(workspace_dir, inherited)}

    def install_dependencies(self, repo_dir: str) -> InstallResult:
        """Install into a virtualenv inside the repository, never system-wide.

        Installing a cloned repository's requirements executes arbitrary code from
        build hooks and setup.py. Confining that to a per-repo environment keeps it
        out of the engine's own interpreter, where it would run with the engine's
        privileges and persist across incidents.
        """
        requirements = os.path.join(repo_dir, "requirements.txt")
        if not os.path.exists(requirements):
            return InstallResult(succeeded=True, detail="No requirements.txt present.")

        venv_dir = os.path.join(repo_dir, ".fixate_venv")
        created, python_exe = self._create_venv(venv_dir)
        if not created:
            logger.warning("Could not create an isolated venv; skipping dependency install.")
            return InstallResult(
                succeeded=False,
                detail="Virtualenv creation failed; dependencies were not installed.",
            )

        try:
            result = subprocess.run(
                [
                    sys.executable, "-m", "uv", "pip", "install",
                    "--python", python_exe,
                    "-r", requirements,
                    "--quiet",
                ],
                cwd=repo_dir,
                capture_output=True,
                text=True,
                timeout=INSTALL_TIMEOUT_SECONDS,
            )
        except subprocess.TimeoutExpired:
            return InstallResult(
                succeeded=False,
                detail=f"Dependency install exceeded {INSTALL_TIMEOUT_SECONDS}s.",
            )

        if result.returncode != 0:
            return InstallResult(
                succeeded=False,
                detail=f"uv pip install failed: {(result.stderr or '').strip()[:500]}",
                executable=python_exe,
            )

        logger.info("Installed Python dependencies into %s", venv_dir)
        return InstallResult(
            succeeded=True,
            detail=f"Installed requirements.txt into {venv_dir}",
            executable=python_exe,
        )

    def _create_venv(self, venv_dir: str) -> Tuple[bool, str]:
        """Create a venv and return (created, interpreter path)."""
        python_exe = os.path.join(
            venv_dir, "Scripts" if os.name == "nt" else "bin", "python.exe" if os.name == "nt" else "python"
        )
        if os.path.exists(python_exe):
            return True, python_exe

        try:
            result = subprocess.run(
                [sys.executable, "-m", "uv", "venv", venv_dir, "--system-site-packages"],
                capture_output=True,
                text=True,
                timeout=120,
            )
            if result.returncode == 0 and os.path.exists(python_exe):
                return True, python_exe
            logger.warning("uv venv failed: %s", (result.stderr or "").strip()[:300])
        except Exception as exc:
            logger.warning("Could not create venv at %s: %s", venv_dir, exc)

        return False, sys.executable

    @staticmethod
    def _relative(workspace_dir: str, file_path: str) -> str:
        return relative_to_workspace(workspace_dir, file_path)
