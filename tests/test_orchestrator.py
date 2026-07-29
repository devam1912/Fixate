"""Unit tests for Orchestration Engine, Telemetry Logger, and Safety Approval Gate."""

import os
import tempfile
import pytest
from fixate.safety.approval import HumanApprovalChecker
from fixate.telemetry.logger import TelemetryLogger
from fixate.orchestrator.engine import OrchestrationEngine, OrchestrationState
from fixate.patch.schema import GeneratedPatch
from fixate.llm.gemini import GeminiProvider
from tests.fakes import FakeLLMProvider

SAMPLE_TAX_CODE = """def calculate_tax(amount: float) -> float:
    rate = 0
    return amount / rate
"""

SAMPLE_TAX_TEST = """from tax import calculate_tax

def test_calculate_tax():
    res = calculate_tax(100.0)
    assert res == 20.0
"""

SAMPLE_PYTEST_LOG = """
=================================== FAILURES ===================================
______________________________ test_calculate_tax ______________________________
File "tax.py", line 3, in calculate_tax
    return amount / rate
ZeroDivisionError: division by zero
FAILED test_tax.py::test_calculate_tax - ZeroDivisionError: division by zero
"""


def test_human_approval_checker_risk():
    checker = HumanApprovalChecker()

    # Standard code patch -> LOW risk
    res_low = checker.evaluate_patch_risk("services/tax.py", "calculate_tax", "+rate = 0.2")
    assert res_low.is_risky is False
    assert res_low.risk_level == "LOW"

    # Auth patch -> HIGH risk
    res_high = checker.evaluate_patch_risk("services/auth.py", "login_user", "+check_password()")
    assert res_high.is_risky is True
    assert res_high.risk_level == "HIGH"
    assert "auth" in res_high.matched_keywords or "password" in res_high.matched_keywords


def test_telemetry_logger():
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp_dir:
        logger = TelemetryLogger(log_dir=tmp_dir)

        evt = logger.log_event(
            incident_id="inc_test123",
            agent="LocalizationAgent",
            action="LOCALIZE",
            input_summary="Pytest log",
            output_summary="calculate_tax",
            result="SUCCESS",
        )

        assert evt.incident_id == "inc_test123"
        events = logger.get_incident_events("inc_test123")
        assert len(events) == 1
        assert events[0].agent == "LocalizationAgent"


def test_orchestration_engine():
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp_dir:
        tax_file = os.path.join(tmp_dir, "tax.py")
        test_file = os.path.join(tmp_dir, "test_tax.py")

        with open(tax_file, "w", encoding="utf-8") as f:
            f.write(SAMPLE_TAX_CODE)
        with open(test_file, "w", encoding="utf-8") as f:
            f.write(SAMPLE_TAX_TEST)

        telemetry = TelemetryLogger(log_dir=os.path.join(tmp_dir, "telemetry"))
        llm = GeminiProvider(api_key=None)  # Simulation mode

        engine = OrchestrationEngine(telemetry_logger=telemetry, llm_provider=llm)

        summary = engine.run_self_healing_pipeline(
            repo_dir=tmp_dir,
            pytest_log=SAMPLE_PYTEST_LOG,
            human_approval_required=True,
        )

        assert summary.incident_id.startswith("inc_")
        assert summary.state in (OrchestrationState.COMPLETED, OrchestrationState.PENDING_APPROVAL, OrchestrationState.FAILED)
        assert len(summary.telemetry_events) >= 3


REPAIR_DIFF = """--- a/tax.py
+++ b/tax.py
@@ -2,1 +2,1 @@
-    rate = 0
+    rate = 0.2
"""

MULTIPLY_SOURCE = """def calculate_tax(amount):
    rate = 0
    return amount * rate
"""

MULTIPLY_TEST = """from tax import calculate_tax

def test_calculate_tax():
    assert calculate_tax(100.0) == 20.0
"""

FAILING_LOG = """
=================================== FAILURES ===================================
______________________________ test_calculate_tax ______________________________
test_tax.py:4: in test_calculate_tax
    assert calculate_tax(100.0) == 20.0
E       assert 0.0 == 20.0
tax.py:3: AssertionError
=========================== short test summary info ============================
FAILED test_tax.py::test_calculate_tax - assert 0.0 == 20.0
"""


def _tax_repo(tmp_dir):
    with open(os.path.join(tmp_dir, "tax.py"), "w", encoding="utf-8") as f:
        f.write(MULTIPLY_SOURCE)
    with open(os.path.join(tmp_dir, "test_tax.py"), "w", encoding="utf-8") as f:
        f.write(MULTIPLY_TEST)


def test_pipeline_heals_a_repository_end_to_end():
    """All five stages, from raw pytest log to a verified patch written back."""
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp_dir:
        _tax_repo(tmp_dir)
        patch = GeneratedPatch(
            target_file="tax.py",
            unified_diff=REPAIR_DIFF,
            explanation="The tax rate was zero, so every computed tax was zero.",
            lines_changed=1,
        )
        engine = OrchestrationEngine(
            llm_provider=FakeLLMProvider({"GeneratedPatch": patch}),
            telemetry_logger=TelemetryLogger(log_dir=os.path.join(tmp_dir, "telemetry")),
        )

        summary = engine.run_self_healing_pipeline(
            repo_dir=tmp_dir, pytest_log=FAILING_LOG, human_approval_required=True
        )

        assert summary.state == OrchestrationState.COMPLETED
        assert summary.failing_test == "test_calculate_tax"
        assert summary.suspect_function == "calculate_tax"
        assert summary.verified_patch is not None
        assert summary.risk_assessment.risk_level == "LOW"
        assert summary.failure_report is None

        with open(os.path.join(tmp_dir, "tax.py"), encoding="utf-8") as f:
            assert "rate = 0.2" in f.read()

        actions = [e.action for e in summary.telemetry_events]
        assert "LOCALIZE_ROOT_CAUSE" in actions
        assert "RETRIEVE_CONTEXT" in actions
        assert "VERIFY_PATCH_SANDBOX" in actions
        assert "AUTO_APPLY_APPROVED" in actions


def test_pipeline_fails_loudly_without_a_live_llm():
    """No model must produce an actionable FAILED report, never a fabricated fix."""
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp_dir:
        _tax_repo(tmp_dir)
        engine = OrchestrationEngine(
            llm_provider=GeminiProvider(api_key=None),
            telemetry_logger=TelemetryLogger(log_dir=os.path.join(tmp_dir, "telemetry")),
        )

        summary = engine.run_self_healing_pipeline(
            repo_dir=tmp_dir, pytest_log=FAILING_LOG, human_approval_required=True
        )

        assert summary.state == OrchestrationState.FAILED
        assert summary.verified_patch is None
        assert "requires a live LLM" in summary.failure_report
        assert "Suggested action" in summary.failure_report

        # Localization still ran, so the operator learns where the defect is.
        assert summary.suspect_function == "calculate_tax"

        # The repository must be untouched.
        with open(os.path.join(tmp_dir, "tax.py"), encoding="utf-8") as f:
            assert f.read() == MULTIPLY_SOURCE


def test_unparseable_log_is_reported_not_guessed():
    """An unusable log must halt, not invent a placeholder failure to chase."""
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp_dir:
        _tax_repo(tmp_dir)
        engine = OrchestrationEngine(
            llm_provider=FakeLLMProvider(),
            telemetry_logger=TelemetryLogger(log_dir=os.path.join(tmp_dir, "telemetry")),
        )

        summary = engine.run_self_healing_pipeline(
            repo_dir=tmp_dir, pytest_log="   ", human_approval_required=True
        )

        assert summary.state == OrchestrationState.FAILED
        assert "empty" in summary.failure_report.lower()


JS_REPAIR_DIFF = """--- a/src/cart.js
+++ b/src/cart.js
@@ -6,1 +6,1 @@
-  return price - discountPercent;
+  return price * (1 - discountPercent / 100);
"""

JS_CART_SOURCE = """/** Shopping cart pricing rules. */

export function applyDiscount(price, discountPercent) {
  // INTENTIONAL BUG: subtracts the percentage value directly instead of
  // computing the percentage of the price.
  return price - discountPercent;
}

export function cartTotal(items) {
  return items.reduce((sum, item) => sum + item.price * item.quantity, 0);
}
"""

JS_CART_TEST = """import { describe, it, expect } from 'vitest';
import { applyDiscount, cartTotal } from './cart.js';

describe('cart', () => {
  it('applies a percentage discount', () => {
    expect(applyDiscount(200, 10)).toBe(180);
  });
});
"""

VITEST_FAILURE_LOG = """
 \u276f src/cart.test.js  (1 test | 1 failed) 10ms
   \u276f src/cart.test.js > cart > applies a percentage discount
     \u2192 expected 190 to be 180 // Object.is equality

 FAIL  src/cart.test.js > cart > applies a percentage discount
AssertionError: expected 190 to be 180 // Object.is equality

- Expected
+ Received

- 180
+ 190

 \u276f src/cart.test.js:6:36

 Test Files  1 failed (1)
      Tests  1 failed (1)
"""


def _vitest_available():
    """The sample repo needs its node_modules installed to actually run."""
    return os.path.isdir(
        os.path.join("sample_repos", "ts_cart_app", "node_modules", "vitest")
    )


def test_pipeline_identifies_javascript_defects():
    """Localization and language routing work on a real Vitest failure."""
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp_dir:
        src = os.path.join(tmp_dir, "src")
        os.makedirs(src)
        with open(os.path.join(src, "cart.js"), "w", encoding="utf-8") as f:
            f.write(JS_CART_SOURCE)
        with open(os.path.join(src, "cart.test.js"), "w", encoding="utf-8") as f:
            f.write(JS_CART_TEST)
        with open(os.path.join(tmp_dir, "package.json"), "w", encoding="utf-8") as f:
            f.write('{"devDependencies": {"vitest": "^1.6.0"}}')

        patch = GeneratedPatch(
            target_file="src/cart.js",
            unified_diff=JS_REPAIR_DIFF,
            explanation="Discount was subtracted as a raw value rather than a percentage.",
            lines_changed=1,
        )
        engine = OrchestrationEngine(
            llm_provider=FakeLLMProvider({"GeneratedPatch": patch}),
            telemetry_logger=TelemetryLogger(log_dir=os.path.join(tmp_dir, "telemetry")),
        )

        summary = engine.run_self_healing_pipeline(
            repo_dir=tmp_dir, pytest_log=VITEST_FAILURE_LOG, human_approval_required=False
        )

        # The incident is routed to the JavaScript toolchain purely from the log.
        assert summary.language == "javascript"
        assert summary.failing_test == "applies a percentage discount"
        assert summary.suspect_function == "applyDiscount"
        assert summary.target_file.endswith("cart.js")


@pytest.mark.skipif(not _vitest_available(), reason="sample_repos/ts_cart_app node_modules not installed")
def test_pipeline_heals_a_javascript_repository_end_to_end():
    """Full parity: a JS defect is localized, patched, and proved with Vitest."""
    from fixate.sample_repos import create_sample_repo_checkout

    repo = create_sample_repo_checkout("ts_cart_app")
    patch = GeneratedPatch(
        target_file="src/cart.js",
        unified_diff=JS_REPAIR_DIFF,
        explanation="Discount was subtracted as a raw value rather than a percentage.",
        lines_changed=1,
    )
    engine = OrchestrationEngine(
        llm_provider=FakeLLMProvider({"GeneratedPatch": patch}),
        telemetry_logger=TelemetryLogger(log_dir=os.path.join(repo, "telemetry")),
    )

    summary = engine.run_self_healing_pipeline(
        repo_dir=repo, pytest_log=VITEST_FAILURE_LOG, human_approval_required=False
    )

    assert summary.language == "javascript"
    assert summary.state == OrchestrationState.COMPLETED, summary.failure_report
    assert summary.verified_patch is not None

    with open(os.path.join(repo, "src", "cart.js"), encoding="utf-8") as f:
        assert "price * (1 - discountPercent / 100)" in f.read()


def test_failed_incident_emits_a_terminal_transition():
    """Live subscribers close on a terminal transition.

    Without one, a finished-but-failed incident leaves the dashboard spinning on
    keepalives forever even though the run is over.
    """
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp_dir:
        _tax_repo(tmp_dir)
        engine = OrchestrationEngine(
            llm_provider=GeminiProvider(api_key=None),  # forces a failure
            telemetry_logger=TelemetryLogger(log_dir=os.path.join(tmp_dir, "telemetry")),
        )

        summary = engine.run_self_healing_pipeline(
            repo_dir=tmp_dir, pytest_log=FAILING_LOG, human_approval_required=True
        )

        assert summary.state == OrchestrationState.FAILED
        terminal = [
            e for e in summary.telemetry_events
            if e.action == "STATE_TRANSITION" and e.output_summary == "FAILED"
        ]
        assert terminal, "a FAILED transition must be broadcast so streams close"
