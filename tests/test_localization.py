"""Unit tests for Failure Localization Agent and Traceback Parser."""

import os
import tempfile
import pytest
from fixate.localization.parser import FailureTracebackParser
from fixate.localization.agent import FailureLocalizationAgent
from fixate.graph.builder import CodebaseGraphBuilder
from fixate.llm.gemini import GeminiProvider

SAMPLE_PYTEST_LOG = """
=================================== FAILURES ===================================
______________________________ test_process_order ______________________________

    def test_process_order():
>       res = process_order(100)

tests/test_services.py:5: 
_ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _
services/payment.py:12: in process_order
    tax = calculate_tax(amount)
services/tax.py:4: in calculate_tax
    return amount / rate
_ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _ _

amount = 100, rate = 0

    def calculate_tax(amount):
        rate = 0
>       return amount / rate
E       ZeroDivisionError: division by zero

services/tax.py:4: ZeroDivisionError
=========================== short test summary info ============================
FAILED tests/test_services.py::test_process_order - ZeroDivisionError: division by zero
"""

SAMPLE_CODE = """
def calculate_tax(amount: float) -> float:
    rate = 0
    return amount / rate

def process_order(amount: float) -> float:
    return calculate_tax(amount)

def test_process_order():
    res = process_order(100)
    assert res > 0
"""


def test_traceback_parser():
    parser = FailureTracebackParser()
    failure = parser.parse_log(SAMPLE_PYTEST_LOG)

    assert failure.test_name == "test_process_order"
    assert failure.exception_type == "ZeroDivisionError"
    assert failure.exception_message == "division by zero"
    assert "tax.py" in failure.failing_file
    assert failure.failing_line == 4
    assert len(failure.stack_frames) >= 2


def test_failure_localization_agent():
    with tempfile.TemporaryDirectory() as tmp_dir:
        file_path = os.path.join(tmp_dir, "tax.py")
        with open(file_path, "w", encoding="utf-8") as f:
            f.write(SAMPLE_CODE)

        builder = CodebaseGraphBuilder()
        builder.build_from_directory(tmp_dir)

        llm = GeminiProvider(api_key=None)  # Simulation mode
        agent = FailureLocalizationAgent(graph_builder=builder, llm_provider=llm)

        result = agent.localize_failure(SAMPLE_PYTEST_LOG)

        assert result.failing_test == "test_process_order"
        assert result.exception_type == "ZeroDivisionError"
        assert len(result.suspect_functions) >= 1
        assert any("calculate_tax" in s.name or "process_order" in s.name for s in result.suspect_functions)
