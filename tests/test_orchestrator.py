"""Unit tests for Orchestration Engine, Telemetry Logger, and Safety Approval Gate."""

import os
import tempfile
import pytest
from fixate.safety.approval import HumanApprovalChecker
from fixate.telemetry.logger import TelemetryLogger
from fixate.orchestrator.engine import OrchestrationEngine, OrchestrationState
from fixate.llm.gemini import GeminiProvider

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
