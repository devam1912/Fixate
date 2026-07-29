"""Verification oracles for repositories with no test suite.

A test is one way to state "this code is wrong, and here is how you know". It is
not the only one. A syntax error, a type error, and a lint violation are all
objective, reproducible, and located at a file and line -- which is everything the
pipeline actually needs from a failure signal.

So when a repository has no runnable tests, the engine falls back to these gates
rather than refusing outright. The core guarantee is unchanged and is *not*
weakened: a patch is still only accepted because an independent checker that failed
before the change passes after it. What changes is which checker plays that role.

Gates are ordered by how conclusive they are. A file that does not parse is
definitely broken; an unused import is a much weaker claim, and one that would be
reckless to let an autonomous agent rewrite code over. Selection stops at the first
gate that reports something.
"""

import json
import logging
import os
import subprocess
from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import List, Optional, Sequence

logger = logging.getLogger(__name__)

GATE_TIMEOUT_SECONDS = 180

# Directories no gate should ever descend into.
SKIP_DIRS = {
    ".git", "__pycache__", "node_modules", ".venv", "venv", "dist", "build",
    ".fixate_venv", ".pytest_cache", ".mypy_cache", "chroma_db", "coverage",
}


@dataclass
class Diagnostic:
    """One objective complaint about the code, located precisely."""

    file_path: str
    line: int
    message: str
    code: str = ""
    severity: str = "error"
    source: str = ""

    #: The exact replacement text the checker itself would write, when it offers
    #: one. Formatting and import rules have a single required form, and a model
    #: asked to guess at it will produce near-misses indefinitely; this is the
    #: checker's own answer, quoted verbatim.
    suggested_fix: str = ""

    #: The checker's confidence that its fix preserves behaviour. Only "safe"
    #: fixes are ever applied automatically.
    fix_applicability: str = ""

    @property
    def identity(self) -> str:
        """Stable key used to tell whether *this* diagnostic was resolved.

        Deliberately excludes the line number: a correct fix frequently shifts
        surrounding lines, and treating that as a different diagnostic would report
        a genuine repair as a failure.
        """
        return f"{os.path.basename(self.file_path)}::{self.code}::{self.message}"

    def describe(self) -> str:
        location = f"{self.file_path}:{self.line}"
        code = f" [{self.code}]" if self.code else ""
        return f"{location}{code} {self.message}"


class DiagnosticGate(ABC):
    """A checker that can both report a defect and later prove it resolved."""

    #: Stable identifier used in telemetry and reports.
    name: str = "gate"

    #: Human-readable description of what this gate proves.
    proves: str = "the code passes an objective check"

    #: How conclusive a failure from this gate is. Higher runs first.
    precedence: int = 0

    @abstractmethod
    def is_available(self, repo_dir: str, executable: Optional[str] = None) -> bool:
        """Whether this gate can run against the repository."""

    @abstractmethod
    def run(self, repo_dir: str, executable: Optional[str] = None) -> List[Diagnostic]:
        """Return every diagnostic the gate finds. Empty means clean."""

    def autofix(
        self, repo_dir: str, target: Diagnostic, executable: Optional[str] = None
    ) -> bool:
        """Apply the checker's own fix for ``target``, if it has one.

        Scoped to the targeted rule rather than "fix everything": a blanket
        auto-fix would make unrelated edits the incident never asked for, and
        some of them (deleting an unused import, say) are the kind of change
        that needs a human to agree it is wanted.

        Returns whether the repository was modified. A gate whose checker has no
        fix facility inherits this no-op, and the engine falls back to the model.
        """
        return False


def run_command(
    command: Sequence[str], cwd: str, timeout: int = GATE_TIMEOUT_SECONDS
) -> Optional[subprocess.CompletedProcess]:
    """Run a gate command, returning None if it could not be executed."""
    import shutil

    resolved = shutil.which(command[0])
    if resolved is None:
        return None

    try:
        return subprocess.run(
            [resolved, *command[1:]],
            cwd=cwd,
            capture_output=True,
            text=True,
            timeout=timeout,
        )
    except (subprocess.TimeoutExpired, OSError) as exc:
        logger.warning("Gate command %s failed to run: %s", command, exc)
        return None


def iter_source_files(repo_dir: str, extensions: Sequence[str]) -> List[str]:
    """Collect source files of interest, skipping vendored trees."""
    found: List[str] = []
    for root, dirs, files in os.walk(repo_dir):
        dirs[:] = [d for d in dirs if d not in SKIP_DIRS]
        for filename in files:
            if filename.lower().endswith(tuple(extensions)):
                found.append(os.path.join(root, filename))
    return found


# ---------------------------------------------------------------------------
# Python gates
# ---------------------------------------------------------------------------


class PythonSyntaxGate(DiagnosticGate):
    """Every Python file must parse.

    Needs no external tooling, so it is always available -- which matters, because
    a repository with neither tests nor a linter installed still gets a real
    verification oracle.
    """

    name = "python-syntax"
    proves = "every Python file compiles"
    precedence = 100

    def is_available(self, repo_dir: str, executable: Optional[str] = None) -> bool:
        return bool(iter_source_files(repo_dir, (".py",)))

    def run(self, repo_dir: str, executable: Optional[str] = None) -> List[Diagnostic]:
        diagnostics: List[Diagnostic] = []
        for path in iter_source_files(repo_dir, (".py",)):
            try:
                with open(path, "r", encoding="utf-8", errors="replace") as handle:
                    source = handle.read()
                # compile(), not ast.parse(): this is what `python -m py_compile`
                # runs, and it catches a class of errors the parser alone does not
                # -- 'return' outside a function, 'break' outside a loop, 'await'
                # outside async. Done in-process rather than by shelling out to
                # py_compile so no .pyc files are written into the repository.
                compile(source, path, "exec")
            except SyntaxError as exc:
                diagnostics.append(
                    Diagnostic(
                        file_path=os.path.relpath(path, repo_dir).replace("\\", "/"),
                        line=exc.lineno or 1,
                        message=exc.msg or "invalid syntax",
                        code="SyntaxError",
                        source=self.name,
                    )
                )
            except OSError:
                continue
        return diagnostics


class RuffGate(DiagnosticGate):
    """Ruff, run with the repository's own configuration when it has one."""

    name = "ruff"
    proves = "the code passes ruff's lint rules"
    precedence = 60

    def is_available(self, repo_dir: str, executable: Optional[str] = None) -> bool:
        import shutil

        return shutil.which("ruff") is not None and bool(iter_source_files(repo_dir, (".py",)))

    def run(self, repo_dir: str, executable: Optional[str] = None) -> List[Diagnostic]:
        result = run_command(["ruff", "check", "--output-format=json", "."], repo_dir)
        if result is None:
            return []

        try:
            payload = json.loads(result.stdout or "[]")
        except json.JSONDecodeError:
            logger.warning("Could not parse ruff output as JSON.")
            return []

        diagnostics: List[Diagnostic] = []
        for item in payload:
            location = item.get("location") or {}
            fix = item.get("fix") or {}
            # Ruff ships the literal replacement text with the diagnostic. Keeping
            # it means neither the engine nor the model has to reconstruct the one
            # form the rule accepts.
            replacement = "".join(edit.get("content", "") for edit in fix.get("edits") or [])
            diagnostics.append(
                Diagnostic(
                    file_path=os.path.relpath(item.get("filename", ""), repo_dir).replace("\\", "/"),
                    line=int(location.get("row") or 1),
                    message=item.get("message", "lint violation"),
                    code=item.get("code") or "",
                    source=self.name,
                    suggested_fix=replacement,
                    fix_applicability=fix.get("applicability", ""),
                )
            )
        return diagnostics

    def autofix(
        self, repo_dir: str, target: Diagnostic, executable: Optional[str] = None
    ) -> bool:
        # "safe" is ruff's own judgement that the edit preserves behaviour.
        # Unsafe fixes stay behind the model, which at least has to justify them.
        if not target.code or target.fix_applicability != "safe":
            return False

        result = run_command(
            ["ruff", "check", "--fix", "--select", target.code, "--output-format=concise", "."],
            repo_dir,
        )
        if result is None:
            return False

        # Re-running the gate is the only trustworthy signal here: ruff exits 0
        # once it has fixed everything it can, which is indistinguishable from
        # having had nothing to do.
        return target.identity not in {d.identity for d in self.run(repo_dir, executable)}


class PyflakesGate(DiagnosticGate):
    """Pyflakes: undefined names and unused imports, without style opinions."""

    name = "pyflakes"
    proves = "the code passes pyflakes"
    precedence = 50

    def is_available(self, repo_dir: str, executable: Optional[str] = None) -> bool:
        import importlib.util

        return (
            importlib.util.find_spec("pyflakes") is not None
            and bool(iter_source_files(repo_dir, (".py",)))
        )

    def run(self, repo_dir: str, executable: Optional[str] = None) -> List[Diagnostic]:
        import sys

        result = run_command([sys.executable, "-m", "pyflakes", "."], repo_dir)
        if result is None:
            return []

        diagnostics: List[Diagnostic] = []
        for line in (result.stdout or "").splitlines():
            # "path/to/file.py:12:5 undefined name 'foo'"
            parts = line.split(":", 3)
            if len(parts) < 3:
                continue
            try:
                line_number = int(parts[1])
            except ValueError:
                continue
            diagnostics.append(
                Diagnostic(
                    file_path=parts[0].replace("\\", "/"),
                    line=line_number,
                    message=parts[-1].strip(),
                    code="pyflakes",
                    source=self.name,
                )
            )
        return diagnostics


# ---------------------------------------------------------------------------
# JavaScript / TypeScript gates
# ---------------------------------------------------------------------------


class JavaScriptSyntaxGate(DiagnosticGate):
    """Every JS/TS file must parse, checked with tree-sitter.

    Like its Python counterpart this needs no external tooling, so an untested
    repository with no node_modules still has a usable oracle.
    """

    name = "js-syntax"
    proves = "every JavaScript/TypeScript file parses"
    precedence = 100

    EXTENSIONS = (".js", ".jsx", ".mjs", ".cjs", ".ts", ".tsx", ".mts", ".cts")

    def is_available(self, repo_dir: str, executable: Optional[str] = None) -> bool:
        return bool(iter_source_files(repo_dir, self.EXTENSIONS))

    def run(self, repo_dir: str, executable: Optional[str] = None) -> List[Diagnostic]:
        from fixate.graph.ts_parser import has_syntax_error

        diagnostics: List[Diagnostic] = []
        for path in iter_source_files(repo_dir, self.EXTENSIONS):
            try:
                with open(path, "r", encoding="utf-8", errors="replace") as handle:
                    source = handle.read()
            except OSError:
                continue

            problem = has_syntax_error(source, path)
            if problem is not None:
                message, line = problem
                diagnostics.append(
                    Diagnostic(
                        file_path=os.path.relpath(path, repo_dir).replace("\\", "/"),
                        line=line,
                        message=message,
                        code="ParseError",
                        source=self.name,
                    )
                )
        return diagnostics


class TypeScriptCompilerGate(DiagnosticGate):
    """`tsc --noEmit`, using the repository's own tsconfig."""

    name = "tsc"
    proves = "the project type-checks"
    precedence = 80

    def is_available(self, repo_dir: str, executable: Optional[str] = None) -> bool:
        import shutil

        return os.path.exists(os.path.join(repo_dir, "tsconfig.json")) and shutil.which("npx") is not None

    def run(self, repo_dir: str, executable: Optional[str] = None) -> List[Diagnostic]:
        result = run_command(["npx", "--no-install", "tsc", "--noEmit", "--pretty", "false"], repo_dir)
        if result is None:
            return []

        diagnostics: List[Diagnostic] = []
        for line in f"{result.stdout}\n{result.stderr}".splitlines():
            # "src/cart.ts(14,3): error TS2345: Argument of type ..."
            if "): error TS" not in line and "): warning TS" not in line:
                continue
            try:
                location, remainder = line.split("):", 1)
                path, position = location.split("(", 1)
                line_number = int(position.split(",")[0])
                severity, _, detail = remainder.strip().partition(" ")
                code, _, message = detail.partition(":")
            except (ValueError, IndexError):
                continue

            diagnostics.append(
                Diagnostic(
                    file_path=path.strip().replace("\\", "/"),
                    line=line_number,
                    message=message.strip() or detail.strip(),
                    code=code.strip(),
                    severity=severity.strip(" :"),
                    source=self.name,
                )
            )
        return [d for d in diagnostics if d.severity != "warning"]


class EslintGate(DiagnosticGate):
    """ESLint, using the repository's own configuration."""

    name = "eslint"
    proves = "the code passes the project's ESLint rules"
    precedence = 60

    CONFIGS = (
        "eslint.config.js", "eslint.config.mjs", "eslint.config.cjs",
        ".eslintrc", ".eslintrc.js", ".eslintrc.cjs", ".eslintrc.json", ".eslintrc.yml",
    )

    def is_available(self, repo_dir: str, executable: Optional[str] = None) -> bool:
        import shutil

        has_config = any(os.path.exists(os.path.join(repo_dir, name)) for name in self.CONFIGS)
        return has_config and shutil.which("npx") is not None

    def run(self, repo_dir: str, executable: Optional[str] = None) -> List[Diagnostic]:
        result = run_command(["npx", "--no-install", "eslint", ".", "-f", "json"], repo_dir)
        if result is None:
            return []

        try:
            payload = json.loads(result.stdout or "[]")
        except json.JSONDecodeError:
            return []

        diagnostics: List[Diagnostic] = []
        for file_report in payload:
            path = os.path.relpath(file_report.get("filePath", ""), repo_dir).replace("\\", "/")
            for item in file_report.get("messages", []):
                # severity 2 is an error; 1 is a warning and too weak a basis for
                # an autonomous rewrite.
                if item.get("severity") != 2:
                    continue
                diagnostics.append(
                    Diagnostic(
                        file_path=path,
                        line=int(item.get("line") or 1),
                        message=item.get("message", "lint error"),
                        code=item.get("ruleId") or "eslint",
                        source=self.name,
                    )
                )
        return diagnostics


def is_vendored(relative_path: str) -> bool:
    """Whether a path belongs to dependencies rather than the repository's own code."""
    normalized = relative_path.replace("\\", "/")
    # Trim a leading "./" only. str.strip("./") strips *characters*, which would
    # turn ".fixate_venv" into "fixate_venv" and let every dot-prefixed vendored
    # directory slip through.
    while normalized.startswith("./"):
        normalized = normalized[2:]
    return any(segment in SKIP_DIRS for segment in normalized.split("/") if segment)


def own_source_only(diagnostics: Sequence[Diagnostic]) -> List[Diagnostic]:
    """Drop diagnostics that point outside the repository's own source.

    External checkers walk whatever they are pointed at, which includes installed
    dependencies and the virtualenv Fixate itself creates during preparation.
    Without this filter the engine will happily target a third-party package -- or
    its own venv bootstrap script -- as the defect to repair.
    """
    kept: List[Diagnostic] = []
    for diagnostic in diagnostics:
        if is_vendored(diagnostic.file_path):
            logger.debug("Ignoring vendored diagnostic: %s", diagnostic.describe())
            continue
        kept.append(diagnostic)
    return kept


def select_gate(
    gates: Sequence[DiagnosticGate], repo_dir: str, executable: Optional[str] = None
) -> Optional[tuple]:
    """Find the most conclusive gate that actually reports a problem.

    Returns ``(gate, diagnostics)`` or None when every available gate is clean --
    which means there is no defect to repair, not that verification is impossible.
    """
    for gate in sorted(gates, key=lambda g: -g.precedence):
        if not gate.is_available(repo_dir, executable):
            logger.debug("Gate %s is not available for %s.", gate.name, repo_dir)
            continue

        diagnostics = own_source_only(gate.run(repo_dir, executable))
        if diagnostics:
            logger.info(
                "Gate %s reported %d diagnostic(s); using it as the verification oracle.",
                gate.name,
                len(diagnostics),
            )
            return gate, diagnostics

        logger.info("Gate %s is clean.", gate.name)

    return None
