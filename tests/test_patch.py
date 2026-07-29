"""Unit tests for the diff applicator and the patch generator agent."""

import ast

import pytest

from fixate.errors import LLMUnavailableError, PatchGenerationError
from fixate.llm.gemini import GeminiProvider
from fixate.patch.agent import PatchGeneratorAgent
from fixate.patch.applicator import PatchApplicator, PatchFailureReason
from fixate.patch.schema import GeneratedPatch, PatchRequest
from tests.fakes import FakeLLMProvider

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
+    rate = = 0.2
"""


def _request(**overrides) -> PatchRequest:
    defaults = dict(
        target_file="tax.py",
        suspect_function_name="calculate_tax",
        suspect_code=ORIGINAL_CODE,
        exception_type="ZeroDivisionError",
        exception_message="division by zero",
        failing_test_name="test_calculate_tax",
    )
    defaults.update(overrides)
    return PatchRequest(**defaults)


# --------------------------------------------------------------------------
# Applicator
# --------------------------------------------------------------------------


def test_applies_a_valid_diff():
    res = PatchApplicator().apply_diff_to_text(ORIGINAL_CODE, VALID_DIFF)
    assert res.success is True
    assert "rate = 0.2" in res.patched_code
    assert res.error_message is None
    assert res.lines_added == 1 and res.lines_removed == 1


def test_rejects_a_patch_that_breaks_syntax():
    res = PatchApplicator().apply_diff_to_text(ORIGINAL_CODE, INVALID_SYNTAX_DIFF)
    assert res.success is False
    assert res.reason is PatchFailureReason.SYNTAX_ERROR
    assert "SyntaxError" in res.error_message


def test_rejects_a_patch_whose_context_is_absent():
    """The hallucination case: the model quotes code that is not in the file."""
    diff = """--- a/tax.py
+++ b/tax.py
@@ -1,1 +1,1 @@
-    rate = self.nonexistent_attribute
+    rate = 0.2
"""
    res = PatchApplicator().apply_diff_to_text(ORIGINAL_CODE, diff)
    assert res.success is False
    assert res.reason is PatchFailureReason.CONTEXT_NOT_FOUND
    assert res.patched_code is None


def test_rejects_a_patch_that_changes_nothing():
    """The placebo guard: no change means the removal lines matched nothing."""
    diff = """--- a/tax.py
+++ b/tax.py
@@ -1,1 +1,1 @@
     rate = 0
"""
    res = PatchApplicator().apply_diff_to_text(ORIGINAL_CODE, diff)
    assert res.success is False
    assert res.reason is PatchFailureReason.NO_CHANGE


def test_locates_a_hunk_despite_a_corrupt_header():
    original = """class QueryPipelineHandler:
    def handle(self, context):
        if self.next_handler and context.success:
            self.next_handler.handle(context)
"""
    diff = """--- a/src/agent.py
+++ b/src/agent.py
@@ -80,1 +80,1 corrupt-header-text
-        if self.next_handler and context.success:
+        if self.next_handler is not None and context.success:
"""
    res = PatchApplicator().apply_diff_to_text(original, diff)
    assert res.success is True
    assert "self.next_handler is not None" in res.patched_code


def test_realigns_a_space_indented_diff_onto_a_tab_indented_file():
    """Indentation is swapped by prefix, so tabs are never mixed with spaces."""
    original = "class Handler:\n\tdef handle(self, ctx):\n\t\treturn ctx.value\n"
    diff = """--- a/h.py
+++ b/h.py
@@ -3,1 +3,1 @@
-        return ctx.value
+        return ctx.value or 0
"""
    res = PatchApplicator().apply_diff_to_text(original, diff)
    assert res.success is True
    assert "\t\treturn ctx.value or 0" in res.patched_code
    assert "    return ctx.value or 0" not in res.patched_code
    ast.parse(res.patched_code)


def test_preserves_nesting_when_reindenting_a_multi_line_block():
    original = "def f(items):\n\tfor item in items:\n\t\tprint(item)\n"
    diff = """--- a/f.py
+++ b/f.py
@@ -2,2 +2,3 @@
-    for item in items:
-        print(item)
+    for item in items:
+        if item:
+            print(item)
"""
    res = PatchApplicator().apply_diff_to_text(original, diff)
    assert res.success is True
    ast.parse(res.patched_code)
    assert "\t\tif item:" in res.patched_code


# --------------------------------------------------------------------------
# Patch generator
# --------------------------------------------------------------------------


def test_refuses_to_generate_without_a_live_llm():
    """The core guarantee: no model means no patch, not a fabricated one."""
    agent = PatchGeneratorAgent(llm_provider=GeminiProvider(api_key=None))

    with pytest.raises(LLMUnavailableError) as excinfo:
        agent.generate_patch(_request())

    assert "not configured" in str(excinfo.value)
    assert excinfo.value.remedy  # must tell the operator how to fix it


def test_generates_and_validates_a_patch_from_a_live_provider():
    patch = GeneratedPatch(
        target_file="tax.py",
        unified_diff=VALID_DIFF,
        explanation="Use a non-zero tax rate.",
        lines_changed=1,
    )
    agent = PatchGeneratorAgent(llm_provider=FakeLLMProvider({"GeneratedPatch": patch}))

    generated, applied = agent.generate_validated_patch(_request())

    assert applied.success is True
    assert "rate = 0.2" in applied.patched_code
    assert generated.target_file == "tax.py"


def test_rejects_a_response_containing_no_diff():
    patch = GeneratedPatch(
        target_file="tax.py",
        unified_diff="I would suggest changing the rate variable.",
        explanation="prose instead of a diff",
        lines_changed=0,
    )
    agent = PatchGeneratorAgent(llm_provider=FakeLLMProvider({"GeneratedPatch": patch}))

    with pytest.raises(PatchGenerationError, match="no diff lines"):
        agent.generate_patch(_request())


def test_prompt_carries_previous_failure_back_to_the_model():
    """Retries must tell the model what went wrong, or they just repeat it."""
    agent = PatchGeneratorAgent(llm_provider=FakeLLMProvider())
    prompt = agent.build_prompt(
        _request(previous_attempt_error="Attempt 1: the patch could not be applied (context_not_found).")
    )

    assert "previous attempt failed" in prompt.lower()
    assert "context_not_found" in prompt
    assert "Do not resubmit the same diff." in prompt
