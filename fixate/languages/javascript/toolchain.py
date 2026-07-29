"""JavaScript/TypeScript: Jest or Vitest, tree-sitter validation, npm dependencies."""

import json
import logging
import os
import shutil
import subprocess
from typing import Dict, List, Optional

from fixate.graph.base_parser import BaseLanguageParser
from fixate.graph.ts_parser import TypeScriptParser, has_syntax_error
from fixate.languages.diagnostics import (
    DiagnosticGate,
    EslintGate,
    JavaScriptSyntaxGate,
    TypeScriptCompilerGate,
)
from fixate.languages.base import (
    InstallResult,
    LanguageToolchain,
    SyntaxIssue,
    TestSelection,
    relative_to_workspace,
)
from fixate.languages.javascript.failures import JavaScriptFailureParser, owns_log
from fixate.localization.parser import ParsedFailure

logger = logging.getLogger(__name__)

INSTALL_TIMEOUT_SECONDS = 600

JEST = "jest"
VITEST = "vitest"

# Jest reports "no tests found" with the same exit code as a genuine failure, so
# selection misses have to be detected from output as well.
_RAN_NOTHING_MARKERS = (
    "No tests found",
    "no test files found",
    "No test files found",
    "matched 0 test suites",
    "Pattern: .* - 0 matches",
)


class JavaScriptToolchain(LanguageToolchain):
    name = "javascript"
    extensions = (".js", ".jsx", ".mjs", ".cjs", ".ts", ".tsx", ".mts", ".cts")
    manifests = ("package.json",)

    # Vitest exits 1 on failure; Jest uses 1 for failures too. Neither has a
    # dedicated "collected nothing" code, so ran_nothing() inspects output.
    selection_failure_exit_codes = ()

    no_tests_markers = (
        "no tests found",
        "no test files found",
        "no test suites found",
        "found no test files",
    )

    def __init__(self) -> None:
        self._parser = TypeScriptParser()
        self._failures = JavaScriptFailureParser()

    def parser(self) -> BaseLanguageParser:
        return self._parser

    def diagnostic_gates(self) -> List[DiagnosticGate]:
        return [JavaScriptSyntaxGate(), TypeScriptCompilerGate(), EslintGate()]

    def owns_log(self, log: str) -> bool:
        return owns_log(log)

    def parse_failure(self, log: str) -> ParsedFailure:
        return self._failures.parse_log(log)

    def syntax_error(self, source: str, file_path: str) -> Optional[SyntaxIssue]:
        problem = has_syntax_error(source, file_path)
        if problem is None:
            return None
        message, line = problem
        return SyntaxIssue(message=f"Invalid JavaScript/TypeScript: {message}", line=line)

    def detect_runner(self, repo_dir: str) -> str:
        """Identify the test runner from the package manifest and config files."""
        manifest = self._read_package_json(repo_dir)
        dependencies = {
            **manifest.get("devDependencies", {}),
            **manifest.get("dependencies", {}),
        }
        test_script = str(manifest.get("scripts", {}).get("test", "")).lower()

        if VITEST in dependencies or VITEST in test_script:
            return VITEST
        if JEST in dependencies or JEST in test_script:
            return JEST

        for filename in os.listdir(repo_dir) if os.path.isdir(repo_dir) else []:
            lowered = filename.lower()
            if lowered.startswith("vitest.config") or lowered.startswith("vite.config"):
                return VITEST
            if lowered.startswith("jest.config"):
                return JEST

        # Only guess at Jest for a repository that is at least a Node project. A
        # directory with no package.json has no test setup to infer, and guessing
        # there had a real cost: `npx jest` downloads Jest from the network into
        # the container and runs it against a repository that never asked for it.
        # Jest then crashes inside its own config loader, and that crash -- with
        # frames pointing into the npx cache -- becomes the "failure" the engine
        # tries to localize.
        if not manifest:
            return ""

        # An explicit `npm test` script is the safest generic fallback.
        return JEST if not test_script else ""

    def has_test_setup(self, repo_dir: str) -> bool:
        """A Node project with something to run: a known runner or a test script.

        An empty ``detect_runner`` is not the same as "nothing to run" -- it means
        `npm test` is the right invocation -- so the test script counts on its own.
        """
        manifest = self._read_package_json(repo_dir)
        if not manifest:
            return False
        has_script = bool(str(manifest.get("scripts", {}).get("test", "")).strip())
        return has_script or bool(self.detect_runner(repo_dir))

    def test_command(self, workspace_dir: str, target: TestSelection) -> List[str]:
        runner = self.detect_runner(workspace_dir)

        if not runner:
            return ["npm", "test", "--silent"]

        if runner == VITEST:
            command = ["npx", "vitest", "run", "--reporter=verbose"]
            if target.file_path:
                command.append(self._relative(workspace_dir, target.file_path))
            if target.test_name:
                command += ["-t", target.test_name]
            return command

        command = ["npx", "jest", "--ci", "--colors=false"]
        if target.file_path:
            command += ["--runTestsByPath", self._relative(workspace_dir, target.file_path)]
        if target.test_name:
            command += ["-t", target.test_name]
        return command

    def ran_nothing(self, exit_code: int, output: str) -> bool:
        return any(marker.lower() in (output or "").lower() for marker in _RAN_NOTHING_MARKERS)

    def environment(self, workspace_dir: str) -> Dict[str, str]:
        node_modules = os.path.join(workspace_dir, "node_modules")
        return {
            "NODE_PATH": node_modules,
            # Silences interactive/watch behaviour in both runners.
            "CI": "true",
            "FORCE_COLOR": "0",
        }

    def install_dependencies(self, repo_dir: str) -> InstallResult:
        """Install node_modules with lifecycle scripts disabled.

        npm runs `preinstall`/`postinstall` from every package in the tree by
        default, which is arbitrary code execution from an untrusted repository and
        a well-travelled supply-chain vector. Packages that genuinely need their
        install scripts will fail loudly here, which is the correct trade for a tool
        that clones whatever URL it is given.
        """
        if not os.path.exists(os.path.join(repo_dir, "package.json")):
            return InstallResult(succeeded=True, detail="No package.json present.")

        if shutil.which("npm") is None:
            return InstallResult(
                succeeded=False,
                detail="npm is not available in this environment; cannot prepare JavaScript dependencies.",
            )

        has_lockfile = os.path.exists(os.path.join(repo_dir, "package-lock.json"))
        command = ["npm", "ci" if has_lockfile else "install", "--ignore-scripts", "--no-audit", "--no-fund"]

        result = self._run(command, repo_dir)
        if result is None:
            return InstallResult(
                succeeded=False, detail=f"npm install exceeded {INSTALL_TIMEOUT_SECONDS}s."
            )

        # `npm ci` refuses to run when the lockfile is out of sync with the
        # manifest; falling back to `install` recovers repositories with a stale
        # lockfile rather than abandoning the incident.
        if result.returncode != 0 and has_lockfile:
            logger.info("npm ci failed; retrying with npm install.")
            result = self._run(
                ["npm", "install", "--ignore-scripts", "--no-audit", "--no-fund"], repo_dir
            )
            if result is None:
                return InstallResult(
                    succeeded=False, detail=f"npm install exceeded {INSTALL_TIMEOUT_SECONDS}s."
                )

        if result.returncode != 0:
            return InstallResult(
                succeeded=False,
                detail=f"npm install failed: {(result.stderr or '').strip()[:500]}",
            )

        logger.info("Installed JavaScript dependencies in %s", repo_dir)
        return InstallResult(succeeded=True, detail="Installed node_modules (scripts ignored).")

    def _run(self, command: List[str], cwd: str):
        try:
            return subprocess.run(
                command,
                cwd=cwd,
                capture_output=True,
                text=True,
                timeout=INSTALL_TIMEOUT_SECONDS,
                shell=(os.name == "nt"),
            )
        except subprocess.TimeoutExpired:
            return None

    def _read_package_json(self, repo_dir: str) -> dict:
        path = os.path.join(repo_dir, "package.json")
        if not os.path.exists(path):
            return {}
        try:
            with open(path, "r", encoding="utf-8", errors="replace") as handle:
                return json.load(handle)
        except (OSError, json.JSONDecodeError) as exc:
            logger.warning("Could not read %s: %s", path, exc)
            return {}

    @staticmethod
    def _relative(workspace_dir: str, file_path: str) -> str:
        return relative_to_workspace(workspace_dir, file_path)
