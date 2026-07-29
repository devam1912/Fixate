"""Tests for diagnostic gates: verification for repositories with no test suite."""

import ast
import os

import pytest

from fixate.languages import registry
from fixate.languages.diagnostics import (
    Diagnostic,
    JavaScriptSyntaxGate,
    PythonSyntaxGate,
    select_gate,
)
from fixate.orchestrator.engine import OrchestrationEngine, OrchestrationState
from fixate.patch.schema import GeneratedPatch
from fixate.telemetry.logger import TelemetryLogger
from fixate.verification.oracles import DiagnosticGateOracle
from tests.fakes import FakeLLMProvider

BROKEN_PY = 'def apply_discount(price, pct):\n    return price - pct\n\n\ndef cart_total(items)\n    return 0\n'
FIXED_DIFF = """--- a/app.py
+++ b/app.py
@@ -5,1 +5,1 @@
-def cart_total(items)
+def cart_total(items):
"""


def _untested_repo(tmp_path, source=BROKEN_PY):
    (tmp_path / "app.py").write_text(source, encoding="utf-8")
    (tmp_path / "requirements.txt").write_text("requests\n", encoding="utf-8")
    return str(tmp_path)


# --------------------------------------------------------------------------
# Gates
# --------------------------------------------------------------------------


def test_python_syntax_gate_needs_no_external_tooling(tmp_path):
    """The most valuable gate must work on a bare repo with nothing installed."""
    repo = _untested_repo(tmp_path)
    gate = PythonSyntaxGate()

    assert gate.is_available(repo) is True
    diagnostics = gate.run(repo)
    assert len(diagnostics) == 1
    assert diagnostics[0].file_path == "app.py"
    assert diagnostics[0].line == 5
    assert diagnostics[0].code == "SyntaxError"


def test_syntax_gate_is_clean_on_valid_code(tmp_path):
    repo = _untested_repo(tmp_path, "def f(x):\n    return x + 1\n")
    assert PythonSyntaxGate().run(repo) == []


def test_javascript_syntax_gate_detects_parse_errors(tmp_path):
    (tmp_path / "cart.ts").write_text("export function f( { return 1", encoding="utf-8")
    diagnostics = JavaScriptSyntaxGate().run(str(tmp_path))

    assert len(diagnostics) == 1
    assert diagnostics[0].file_path == "cart.ts"
    assert diagnostics[0].code == "ParseError"


def test_gate_selection_prefers_the_most_conclusive(tmp_path):
    """A file that does not parse outranks a lint opinion."""
    repo = _untested_repo(tmp_path)
    gate, diagnostics = select_gate(registry.by_name("python").diagnostic_gates(), repo)

    assert gate.name == "python-syntax"
    assert diagnostics


def test_no_gate_selected_when_everything_is_clean(tmp_path):
    repo = _untested_repo(tmp_path, "def f(x):\n    return x + 1\n")
    assert select_gate(registry.by_name("python").diagnostic_gates(), repo) is None


# --------------------------------------------------------------------------
# The oracle
# --------------------------------------------------------------------------


def test_gate_oracle_passes_only_when_the_defect_is_resolved(tmp_path):
    repo = _untested_repo(tmp_path)
    gate = PythonSyntaxGate()
    baseline = gate.run(repo)
    oracle = DiagnosticGateOracle(gate=gate, baseline=baseline, target=baseline[0])

    # Still broken -> must not pass.
    assert oracle.verify(repo).passed is False

    (tmp_path / "app.py").write_text(BROKEN_PY.replace("(items)\n", "(items):\n"), encoding="utf-8")
    assert oracle.verify(repo).passed is True


def test_gate_oracle_rejects_a_patch_that_introduces_new_problems(tmp_path):
    """Trading the reported defect for a new one is not a repair."""
    repo = _untested_repo(tmp_path)
    gate = PythonSyntaxGate()
    baseline = gate.run(repo)
    oracle = DiagnosticGateOracle(gate=gate, baseline=baseline, target=baseline[0])

    # Fix the reported file, but break a different one.
    (tmp_path / "app.py").write_text(BROKEN_PY.replace("(items)\n", "(items):\n"), encoding="utf-8")
    (tmp_path / "other.py").write_text("def g(:\n", encoding="utf-8")

    result = oracle.verify(repo)
    assert result.passed is False
    assert "new diagnostic" in result.stderr


def test_diagnostic_identity_survives_line_shifts():
    """A correct fix often moves lines; that must not read as a different defect."""
    first = Diagnostic(file_path="a.py", line=5, message="expected ':'", code="SyntaxError")
    moved = Diagnostic(file_path="a.py", line=9, message="expected ':'", code="SyntaxError")
    assert first.identity == moved.identity


# --------------------------------------------------------------------------
# End to end
# --------------------------------------------------------------------------


def test_pipeline_heals_an_untested_repository_via_the_syntax_gate(tmp_path):
    """No tests, no linter installed -- and the repair is still verified."""
    repo = _untested_repo(tmp_path)
    patch = GeneratedPatch(
        target_file="app.py",
        unified_diff=FIXED_DIFF,
        explanation="The function definition was missing its colon.",
        lines_changed=1,
    )
    engine = OrchestrationEngine(
        llm_provider=FakeLLMProvider({"GeneratedPatch": patch}),
        telemetry_logger=TelemetryLogger(log_dir=str(tmp_path / "telemetry")),
    )

    summary = engine.run_self_healing_pipeline(
        repo_dir=repo,
        pytest_log="collected 0 items\n\nno tests ran in 0.01s",
        human_approval_required=False,
    )

    assert summary.state == OrchestrationState.COMPLETED
    assert summary.language == "python"
    assert summary.exception_type == "SyntaxError"
    assert summary.total_attempts == 1

    # The proof: the file parses now, which is what the gate asserted.
    ast.parse((tmp_path / "app.py").read_text(encoding="utf-8"))

    actions = [e.action for e in summary.telemetry_events]
    assert "GATE_FALLBACK_SELECTED" in actions


def test_untested_and_clean_repository_reports_nothing_to_fix(tmp_path):
    """No tests and no diagnostics means no defect -- not a silent success."""
    repo = _untested_repo(tmp_path, "def f(x):\n    return x + 1\n")
    engine = OrchestrationEngine(
        llm_provider=FakeLLMProvider(),
        telemetry_logger=TelemetryLogger(log_dir=str(tmp_path / "telemetry")),
    )

    summary = engine.run_self_healing_pipeline(
        repo_dir=repo,
        pytest_log="collected 0 items\n\nno tests ran in 0.01s",
        human_approval_required=False,
    )

    assert summary.state == OrchestrationState.FAILED
    assert "no runnable tests" in summary.failure_report
    assert "reports it as clean" in summary.failure_report


def test_vendored_paths_are_never_treated_as_the_defect():
    """Gates walk whatever they are pointed at, including Fixate's own venv."""
    from fixate.languages.diagnostics import is_vendored

    # Dot-prefixed directories are the trap: a character-wise strip turns
    # ".fixate_venv" into "fixate_venv" and lets the whole tree through.
    assert is_vendored(".fixate_venv/Scripts/activate_this.py") is True
    assert is_vendored("./node_modules/lib/index.js") is True
    assert is_vendored("venv/lib/site-packages/x.py") is True

    assert is_vendored("app.py") is False
    assert is_vendored("./src/cart.ts") is False


def test_gate_ignores_diagnostics_from_installed_dependencies(tmp_path):
    """A dependency's lint problems are not the repository's defect."""
    from fixate.languages.diagnostics import Diagnostic, own_source_only

    diagnostics = [
        Diagnostic(file_path=".fixate_venv/Scripts/activate_this.py", line=29, message="x"),
        Diagnostic(file_path="node_modules/dep/index.js", line=3, message="y"),
        Diagnostic(file_path="app.py", line=5, message="the real one"),
    ]
    kept = own_source_only(diagnostics)

    assert [d.file_path for d in kept] == ["app.py"]


# --------------------------------------------------------------------------
# Checker auto-fix
# --------------------------------------------------------------------------

# The literal file that defeated three LLM attempts in production: ruff's I001
# has exactly one accepted form, and every generated patch missed the blank line
# separating the stdlib group from the third-party one.
UNSORTED_IMPORTS = (
    '"""Snake Eater."""\n'
    "\n"
    "import pygame, sys, time, random\n"
    "\n"
    "print(pygame, sys, time, random)\n"
)


def _lf(text):
    """Normalize line endings so assertions describe content, not platform."""
    return text.replace("\r\n", "\n")


def _ruff_selection(tmp_path, source=UNSORTED_IMPORTS, filename="Snake Game.py"):
    """Build a repo whose only complaint is an import-sorting violation."""
    (tmp_path / filename).write_text(source, encoding="utf-8")
    repo = str(tmp_path)
    from fixate.languages.diagnostics import RuffGate

    gate = RuffGate()
    if not gate.is_available(repo):
        pytest.skip("ruff is not installed")
    return repo, gate


def test_ruff_diagnostic_carries_the_checkers_own_required_text(tmp_path):
    """The fix ruff ships with the diagnostic is kept, not discarded."""
    repo, gate = _ruff_selection(tmp_path)

    target = next(d for d in gate.run(repo) if d.code == "I001")

    assert target.fix_applicability == "safe"
    # The blank line between groups is the whole point -- it is what three
    # generated patches omitted. Ruff writes the fix with the file's own line
    # endings, so compare on normalized text rather than asserting a platform.
    assert "import time\n\nimport pygame" in _lf(target.suggested_fix)


def test_checker_autofix_resolves_what_the_model_could_not(tmp_path):
    """A rule with one accepted form is fixed by the tool, with no LLM call."""
    repo, gate = _ruff_selection(tmp_path)
    target = next(d for d in gate.run(repo) if d.code == "I001")
    oracle = DiagnosticGateOracle(gate=gate, baseline=gate.run(repo), target=target)

    assert gate.autofix(repo, target) is True

    remaining = {d.identity for d in gate.run(repo)}
    assert target.identity not in remaining
    assert oracle.verify(repo).passed is True


def test_autofix_short_circuits_the_repair_loop_without_calling_the_model(tmp_path):
    """The verification agent takes the tool's fix and never reaches the provider."""
    from fixate.graph.builder import CodebaseGraphBuilder
    from fixate.localization.agent import SuspectFunction
    from fixate.localization.parser import ParsedFailure
    from fixate.patch.agent import PatchGeneratorAgent
    from fixate.verification.agent import AttemptOutcome, VerificationAgent

    repo, gate = _ruff_selection(tmp_path)
    baseline = gate.run(repo)
    target = next(d for d in baseline if d.code == "I001")
    oracle = DiagnosticGateOracle(gate=gate, baseline=baseline, target=target)

    # No queued response: any call into this provider raises, which is exactly
    # the assertion -- the model must not be consulted for a rule the tool owns.
    provider = FakeLLMProvider(responses={})
    agent = VerificationAgent(
        patch_agent=PatchGeneratorAgent(llm_provider=provider),
        oracle=oracle,
    )

    result = agent.verify_fix(
        repo_dir=repo,
        graph_builder=CodebaseGraphBuilder(),
        suspect=SuspectFunction(
            symbol_id=f"{target.file_path}::module",
            file_path=os.path.join(repo, target.file_path),
            name="module",
            code=UNSORTED_IMPORTS,
            rank=1,
            plausibility_reason="import block",
        ),
        failure=ParsedFailure(
            test_name="ruff check",
            failing_file=target.file_path,
            failing_line=target.line,
            exception_type=target.code,
            exception_message=target.message,
            stack_frames=[],
            raw_traceback=target.describe(),
        ),
    )

    assert result.success is True
    assert provider.prompts == []
    assert result.attempts_history[0].outcome is AttemptOutcome.AUTOFIXED
    assert "no model was involved" in result.verified_patch.explanation.lower()

    # The repository on disk is actually fixed, not just the throwaway workspace.
    healed = (tmp_path / "Snake Game.py").read_text(encoding="utf-8")
    assert "import time\n\nimport pygame" in _lf(healed)


def test_unsafe_fixes_are_left_to_the_model(tmp_path):
    """Auto-fix applies only what the checker itself calls behaviour-preserving."""
    repo, gate = _ruff_selection(tmp_path)
    target = next(d for d in gate.run(repo) if d.code == "I001")

    target.fix_applicability = "unsafe"
    assert gate.autofix(repo, target) is False
    assert (tmp_path / "Snake Game.py").read_text(encoding="utf-8") == UNSORTED_IMPORTS
