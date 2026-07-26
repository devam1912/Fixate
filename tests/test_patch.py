"""Unit tests for Patch Applicator and Patch Generator Agent."""

import os
import tempfile
import pytest
from fixate.patch.applicator import PatchApplicator
from fixate.patch.agent import PatchGeneratorAgent
from fixate.patch.schema import PatchRequest
from fixate.llm.gemini import GeminiProvider

ORIGINAL_CODE = """def calculate_tax(amount: float) -> float:
    rate = 0
    return amount / rate
"""

VALID_DIFF = """--- a/tax.py
+++ b/tax.py
@@ -1,3 +1,3 @@
-    rate = 0
+    rate = 0.2
"""

INVALID_SYNTAX_DIFF = """--- a/tax.py
+++ b/tax.py
@@ -1,3 +1,3 @@
-    rate = 0
+    rate = = 0.2 def (
"""


def test_patch_applicator_success():
    applicator = PatchApplicator()
    res = applicator.apply_diff_to_text(ORIGINAL_CODE, VALID_DIFF)
    assert res.success is True
    assert "rate = 0.2" in res.patched_code
    assert res.error_message is None


def test_patch_applicator_syntax_error():
    applicator = PatchApplicator()
    res = applicator.apply_diff_to_text(ORIGINAL_CODE, INVALID_SYNTAX_DIFF)
    assert res.success is False
    assert res.error_message is not None
    assert "SyntaxError" in res.error_message or "AST" in res.error_message


def test_patch_generator_agent():
    llm = GeminiProvider(api_key=None)  # Simulation mode
    agent = PatchGeneratorAgent(llm_provider=llm)

    request = PatchRequest(
        target_file="services/tax.py",
        suspect_function_name="calculate_tax",
        suspect_code=ORIGINAL_CODE,
        exception_type="ZeroDivisionError",
        exception_message="division by zero",
        failing_test_name="test_calculate_tax",
    )

    patch, result = agent.generate_validated_patch(request)
    assert patch.target_file == "services/tax.py"
    assert isinstance(patch.unified_diff, str)
    assert result.success is True
