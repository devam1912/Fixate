"""Tests for the language toolchain abstraction and its routing."""

import os

import pytest

from fixate.errors import TracebackParseError
from fixate.languages import registry
from fixate.languages.base import TestSelection
from fixate.languages.cpp import CppToolchain
from fixate.languages.javascript import JavaScriptToolchain
from fixate.languages.javascript.failures import strip_ansi
from fixate.languages.python import PythonToolchain

JEST_LOG = """
 FAIL  src/cart.test.ts
  ● cart › applies discount correctly

    expect(received).toBe(expected)

    Expected: 90
    Received: 100

      at Object.<anonymous> (src/cart.test.ts:8:35)
      at applyDiscount (src/cart.ts:14:10)

Test Suites: 1 failed, 1 total
Tests:       1 failed, 2 total
"""

VITEST_LOG = """
 RUN  v1.2.0 /repo

 FAIL  src/cart.test.ts > cart > applies discount correctly
AssertionError: expected 100 to be 90

 ❯ src/cart.ts:14:10
 ❯ src/cart.test.ts:8:35

 Test Files  1 failed (1)
"""

PYTEST_LOG = """
=================================== FAILURES ===================================
______________________________ test_calculate_tax ______________________________
tax.py:3: in calculate_tax
    return amount / rate
E       ZeroDivisionError: division by zero
FAILED test_tax.py::test_calculate_tax - ZeroDivisionError: division by zero
"""


# --------------------------------------------------------------------------
# Registry routing
# --------------------------------------------------------------------------


def test_routes_files_to_the_owning_toolchain():
    assert registry.for_file("src/cart.ts").name == "javascript"
    assert registry.for_file("src/math.cpp").name == "cpp"
    assert registry.for_file("components/Button.tsx").name == "javascript"
    assert registry.for_file("legacy/util.js").name == "javascript"
    assert registry.for_file("app/models.py").name == "python"
    assert registry.for_file("README.md") is None


def test_routes_logs_by_the_runner_that_produced_them():
    """Mixed-language repos are routed by the failing log, not the file tree."""
    assert registry.for_log(JEST_LOG).name == "javascript"
    assert registry.for_log(VITEST_LOG).name == "javascript"
    assert registry.for_log(PYTEST_LOG).name == "python"
    assert registry.for_log("main.cpp:4:10: error: expected ';' after expression").name == "cpp"
    assert registry.for_log("") is None


def test_resolve_prefers_the_log_over_the_repository(tmp_path):
    """A Python backend with a JS frontend must heal whichever side broke."""
    (tmp_path / "requirements.txt").write_text("pytest\n", encoding="utf-8")
    (tmp_path / "package.json").write_text('{"devDependencies":{"jest":"29"}}', encoding="utf-8")

    assert registry.resolve(str(tmp_path), log=JEST_LOG).name == "javascript"
    assert registry.resolve(str(tmp_path), log=PYTEST_LOG).name == "python"

    # With no log, the suspect file decides.
    assert registry.resolve(str(tmp_path), log="", suspect_path="src/a.ts").name == "javascript"


def test_detects_languages_present_in_a_repository(tmp_path):
    (tmp_path / "package.json").write_text("{}", encoding="utf-8")
    names = [t.name for t in registry.for_repo(str(tmp_path))]
    assert names == ["javascript"]


def test_detects_language_from_extensions_when_no_manifest(tmp_path):
    (tmp_path / "script.py").write_text("x = 1\n", encoding="utf-8")
    assert [t.name for t in registry.for_repo(str(tmp_path))] == ["python"]


# --------------------------------------------------------------------------
# Python toolchain
# --------------------------------------------------------------------------


def test_python_syntax_gate():
    tc = PythonToolchain()
    assert tc.syntax_error("def f():\n    return 1\n", "a.py") is None

    issue = tc.syntax_error("def f(:\n", "a.py")
    assert issue is not None and "SyntaxError" in issue.message


def test_python_test_command_prefers_exact_node_ids():
    tc = PythonToolchain()
    command = tc.test_command("/repo", TestSelection(test_name="test_tax", file_path="/repo/tests/test_tax.py"))
    assert command == ["python", "-m", "pytest", "tests/test_tax.py::test_tax"]

    assert tc.test_command("/repo", TestSelection()) == ["python", "-m", "pytest"]
    assert tc.test_command("/repo", TestSelection(test_name="test_x")) == [
        "python", "-m", "pytest", "-k", "test_x",
    ]


def test_python_ran_nothing_uses_pytest_exit_codes():
    tc = PythonToolchain()
    assert tc.ran_nothing(5, "collected 0 items") is True
    assert tc.ran_nothing(1, "1 failed") is False


# --------------------------------------------------------------------------
# JavaScript toolchain
# --------------------------------------------------------------------------


def test_strips_ansi_before_parsing():
    """Both runners colorize by default; escapes break naive line matching."""
    coloured = "\x1b[31m  ● cart › fails\x1b[0m"
    assert strip_ansi(coloured) == "  ● cart › fails"


def test_parses_jest_failure():
    failure = JavaScriptToolchain().parse_failure(JEST_LOG)

    assert failure.test_name == "applies discount correctly"
    assert failure.exception_type == "AssertionError"
    assert "90" in failure.exception_message
    # The defect is in the source under test, not the spec that caught it.
    assert failure.failing_file == "src/cart.ts"
    assert failure.failing_line == 14
    assert len(failure.stack_frames) == 2


def test_parses_vitest_failure():
    failure = JavaScriptToolchain().parse_failure(VITEST_LOG)

    assert failure.test_name == "applies discount correctly"
    assert failure.exception_type == "AssertionError"
    assert failure.failing_file == "src/cart.ts"
    assert failure.failing_line == 14


def test_empty_js_log_raises_rather_than_guessing():
    with pytest.raises(TracebackParseError):
        JavaScriptToolchain().parse_failure("   ")


def test_passing_js_log_raises():
    with pytest.raises(TracebackParseError):
        JavaScriptToolchain().parse_failure("Test Suites: 1 passed, 1 total\nTests: 3 passed")


def test_detects_runner_from_package_json(tmp_path):
    tc = JavaScriptToolchain()

    (tmp_path / "package.json").write_text('{"devDependencies": {"vitest": "^1.0.0"}}', encoding="utf-8")
    assert tc.detect_runner(str(tmp_path)) == "vitest"

    (tmp_path / "package.json").write_text('{"devDependencies": {"jest": "^29.0.0"}}', encoding="utf-8")
    assert tc.detect_runner(str(tmp_path)) == "jest"


def test_js_test_commands_target_individual_cases(tmp_path):
    tc = JavaScriptToolchain()
    (tmp_path / "package.json").write_text('{"devDependencies": {"vitest": "^1.0.0"}}', encoding="utf-8")

    command = tc.test_command(
        str(tmp_path), TestSelection(test_name="applies discount", file_path="src/cart.test.ts")
    )
    assert command[:3] == ["npx", "vitest", "run"]
    assert "src/cart.test.ts" in command
    assert command[-2:] == ["-t", "applies discount"]


def test_jest_ran_nothing_detected_from_output_not_exit_code():
    """Jest exits 1 for 'no tests found', the same code it uses for real failures."""
    tc = JavaScriptToolchain()
    assert tc.ran_nothing(1, "No tests found, exiting with code 1") is True
    assert tc.ran_nothing(1, "Tests: 1 failed, 2 total") is False


def test_js_syntax_gate():
    tc = JavaScriptToolchain()
    assert tc.syntax_error("export const x = 1;", "a.ts") is None

    issue = tc.syntax_error("function f( { return 1", "a.ts")
    assert issue is not None and "Invalid JavaScript" in issue.message


def test_js_environment_points_at_local_node_modules(tmp_path):
    env = JavaScriptToolchain().environment(str(tmp_path))
    assert env["NODE_PATH"] == os.path.join(str(tmp_path), "node_modules")
    assert env["CI"] == "true"


def test_install_skips_repos_without_a_manifest(tmp_path):
    result = JavaScriptToolchain().install_dependencies(str(tmp_path))
    assert result.succeeded is True
    assert "No package.json" in result.detail


# --------------------------------------------------------------------------
# C++ toolchain
# --------------------------------------------------------------------------


def test_cpp_compiler_error_is_parseable():
    failure = CppToolchain().parse_failure(
        "src/main.cpp:12:5: error: use of undeclared identifier 'total'"
    )

    assert failure.test_name == "c++ build"
    assert failure.exception_type == "CompilerError"
    assert failure.failing_file == "src/main.cpp"
    assert failure.failing_line == 12


def test_cpp_cmake_project_counts_as_test_setup(tmp_path):
    (tmp_path / "CMakeLists.txt").write_text("cmake_minimum_required(VERSION 3.20)\n", encoding="utf-8")
    assert CppToolchain().has_test_setup(str(tmp_path)) is True


def test_distinguishes_no_tests_from_failing_tests():
    """A repo with no tests is a different condition from one whose tests fail."""
    py = PythonToolchain()
    assert py.collected_nothing("collected 0 items\n\nno tests ran in 0.01s") is True
    assert py.collected_nothing("1 failed, 2 passed in 0.4s") is False

    js = JavaScriptToolchain()
    assert js.collected_nothing("No test files found, exiting with code 1") is True
    assert js.collected_nothing("Tests: 1 failed, 2 total") is False


def test_production_traceback_localizes_without_any_test_suite(tmp_path):
    """The documented fallback for untested repos must actually work.

    Verification is impossible without tests, but localization is not: a real
    traceback still names a file, a line, and a call chain.
    """
    from fixate.graph.builder import CodebaseGraphBuilder
    from fixate.llm.gemini import GeminiProvider
    from fixate.localization.agent import FailureLocalizationAgent

    (tmp_path / "app.py").write_text(
        "def apply_discount(price, pct):\n    return price - pct\n", encoding="utf-8"
    )

    traceback = (
        'Traceback (most recent call last):\n'
        '  File "/srv/app/server.py", line 88, in handle_checkout\n'
        '    total = apply_discount(cart_price, promo_pct)\n'
        f'  File "{tmp_path / "app.py"}", line 2, in apply_discount\n'
        "    return price - pct\n"
        'TypeError: unsupported operand type(s) for -: "float" and "str"\n'
    )

    toolchain = registry.for_log(traceback)
    assert toolchain.name == "python"

    failure = toolchain.parse_failure(traceback)
    assert failure.exception_type == "TypeError"

    builder = CodebaseGraphBuilder()
    builder.build_from_directory(str(tmp_path))
    result = FailureLocalizationAgent(
        graph_builder=builder, llm_provider=GeminiProvider(api_key=None)
    ).localize_parsed_failure(failure)

    assert result.suspect_functions[0].name == "apply_discount"


# --------------------------------------------------------------------------
# Repositories with no test setup
# --------------------------------------------------------------------------


def _browser_app(tmp_path):
    """A plain browser JS app: source, markup, styles -- and no Node project."""
    (tmp_path / "app.js").write_text(
        "function newGame() {\n  return Array(9).fill('');\n}\n", encoding="utf-8"
    )
    (tmp_path / "index.html").write_text("<html></html>", encoding="utf-8")
    (tmp_path / "style.css").write_text("body { margin: 0; }", encoding="utf-8")
    return str(tmp_path)


def test_no_runner_is_invented_for_a_repository_without_a_manifest(tmp_path):
    """Guessing Jest here ran `npx jest`, which downloads it and then crashes."""
    repo = _browser_app(tmp_path)
    toolchain = JavaScriptToolchain()

    assert toolchain.detect_runner(repo) == ""
    assert toolchain.has_test_setup(repo) is False

    # Nothing in the built command may reach out to the network.
    assert "npx" not in toolchain.test_command(repo, TestSelection())


def test_npm_test_script_alone_counts_as_a_test_setup(tmp_path):
    """An empty detect_runner means "use npm test", not "nothing to run"."""
    (tmp_path / "package.json").write_text(
        '{"scripts": {"test": "node --test"}}', encoding="utf-8"
    )
    toolchain = JavaScriptToolchain()

    assert toolchain.detect_runner(str(tmp_path)) == ""
    assert toolchain.has_test_setup(str(tmp_path)) is True


def test_jest_is_still_inferred_for_a_real_node_project(tmp_path):
    """The fallback is narrowed, not removed."""
    (tmp_path / "package.json").write_text('{"devDependencies": {}}', encoding="utf-8")
    toolchain = JavaScriptToolchain()

    assert toolchain.detect_runner(str(tmp_path)) == "jest"
    assert toolchain.has_test_setup(str(tmp_path)) is True


def test_python_repositories_keep_asking_the_runner(tmp_path):
    """pytest is always installed here, so its own report stays authoritative."""
    (tmp_path / "app.py").write_text("def f():\n    return 1\n", encoding="utf-8")
    assert PythonToolchain().has_test_setup(str(tmp_path)) is True


# --------------------------------------------------------------------------
# Failures raised outside the repository
# --------------------------------------------------------------------------


def test_failure_inside_a_dependency_is_not_this_repositorys_defect(tmp_path):
    """The observed crash pointed into the npx download cache."""
    from fixate.localization.parser import ParsedFailure, StackFrame
    from fixate.orchestrator.engine import OrchestrationEngine

    repo = _browser_app(tmp_path)
    npx_cache = (
        "/home/fixate/.npm/_npx/b8d86e6551a4f492/node_modules/jest-config/build/index.js"
    )
    failure = ParsedFailure(
        test_name="jest",
        failing_file=npx_cache,
        failing_line=1,
        exception_type="Error",
        exception_message="Could not find a config file",
        stack_frames=[StackFrame(file_path=npx_cache, line_number=1, function_name="readConfig")],
        raw_traceback=npx_cache,
    )

    assert OrchestrationEngine._failure_is_in_repo(failure, repo) is False


def test_failure_inside_the_repository_is_accepted(tmp_path):
    from fixate.localization.parser import ParsedFailure, StackFrame
    from fixate.orchestrator.engine import OrchestrationEngine

    repo = _browser_app(tmp_path)
    target = os.path.join(repo, "app.js")
    failure = ParsedFailure(
        test_name="jest",
        failing_file=target,
        failing_line=2,
        exception_type="AssertionError",
        exception_message="boom",
        stack_frames=[StackFrame(file_path=target, line_number=2, function_name="newGame")],
        raw_traceback=target,
    )

    assert OrchestrationEngine._failure_is_in_repo(failure, repo) is True


def test_relative_frames_are_treated_as_in_repo(tmp_path):
    """Runners routinely print repository-relative paths."""
    from fixate.localization.parser import ParsedFailure, StackFrame
    from fixate.orchestrator.engine import OrchestrationEngine

    repo = _browser_app(tmp_path)
    failure = ParsedFailure(
        test_name="jest",
        failing_file="app.js",
        failing_line=2,
        exception_type="AssertionError",
        exception_message="boom",
        stack_frames=[StackFrame(file_path="app.js", line_number=2, function_name="newGame")],
        raw_traceback="app.js",
    )

    assert OrchestrationEngine._failure_is_in_repo(failure, repo) is True


def test_a_vendored_frame_does_not_mask_a_real_one(tmp_path):
    """Runner frames often sit above the application frame; one in-repo frame is enough."""
    from fixate.localization.parser import ParsedFailure, StackFrame
    from fixate.orchestrator.engine import OrchestrationEngine

    repo = _browser_app(tmp_path)
    failure = ParsedFailure(
        test_name="jest",
        failing_file="/somewhere/node_modules/jest-circus/run.js",
        failing_line=1,
        exception_type="AssertionError",
        exception_message="boom",
        stack_frames=[
            StackFrame(
                file_path="/somewhere/node_modules/jest-circus/run.js",
                line_number=1,
                function_name="run",
            ),
            StackFrame(
                file_path=os.path.join(repo, "app.js"), line_number=2, function_name="newGame"
            ),
        ],
        raw_traceback="",
    )

    assert OrchestrationEngine._failure_is_in_repo(failure, repo) is True
