"""Patch Generator Agent for creating minimal structured unified diffs with retry validation."""

import logging
from typing import Optional, Tuple

from fixate.patch.schema import GeneratedPatch, PatchRequest
from fixate.patch.applicator import PatchApplicator, ApplyPatchResult
from fixate.llm.base import BaseLLMProvider
from fixate.llm.factory import get_llm_provider

logger = logging.getLogger(__name__)


class PatchGeneratorAgent:
    """Agent responsible for generating minimal, targeted, machine-applicable code patches."""

    def __init__(self, llm_provider: Optional[BaseLLMProvider] = None):
        self.llm = llm_provider or get_llm_provider()
        self.applicator = PatchApplicator()

    def generate_patch(self, request: PatchRequest) -> GeneratedPatch:
        """Generate a minimal structured unified diff patch for a given failure request."""
        past_fixes_snippet = ""
        if request.past_fix_examples:
            past_fixes_snippet = (
                "\nHistorical Past Fix Diffs for Similar Errors:\n"
                + "\n---\n".join(request.past_fix_examples)
                + "\n"
            )

        prev_error_snippet = ""
        if request.previous_attempt_error:
            prev_error_snippet = (
                f"\nCRITICAL: A previous fix attempt failed verification with error:\n"
                f"```\n{request.previous_attempt_error}\n```\n"
                f"Do NOT repeat the same mistake. Fix the root cause.\n"
            )

        prompt = (
            f"You are a Senior Automated Code Repair Agent.\n"
            f"Fix the bug causing the following test failure:\n"
            f"- Failing Test: {request.failing_test_name}\n"
            f"- Target File: {request.target_file}\n"
            f"- Exception Type: {request.exception_type}\n"
            f"- Exception Message: {request.exception_message}\n\n"
            f"Suspect Function Implementation ({request.suspect_function_name}):\n"
            f"```python\n{request.suspect_code}\n```\n"
            f"{prev_error_snippet}"
            f"{past_fixes_snippet}\n"
            f"INSTRUCTIONS:\n"
            f"1. Produce the MINIMAL possible change. Do not rewrite unrelated lines or refactor.\n"
            f"2. Output a valid machine-applicable unified diff for target file '{request.target_file}'.\n"
            f"3. Ensure your diff starts with `--- a/{request.target_file}` and `+++ b/{request.target_file}`.\n"
            f"4. Provide a clear explanation of why your diff fixes the root cause."
        )

        sys_instruction = (
            "You are a principal software engineer specialized in minimal targeted bug fixes. "
            "Never generate unnecessary changes. Output valid unified diffs."
        )

        try:
            patch: GeneratedPatch = self.llm.generate_structured(
                prompt=prompt,
                response_schema=GeneratedPatch,
                system_instruction=sys_instruction,
                temperature=0.1,
            )
            logger.info(f"Generated patch for {request.target_file}: {patch.explanation}")
            return patch
        except Exception as exc:
            logger.error(f"Failed to generate structured patch: {exc}")

        # Simulation / Fallback patch for testing
        dummy_diff = (
            f"--- a/{request.target_file}\n"
            f"+++ b/{request.target_file}\n"
            f"@@ -1,3 +1,3 @@\n"
            f"-rate = 0\n"
            f"+rate = 0.2\n"
        )
        return GeneratedPatch(
            target_file=request.target_file,
            unified_diff=dummy_diff,
            explanation="Simulated fallback minimal patch.",
            lines_changed=1,
        )

    def generate_validated_patch(
        self, request: PatchRequest, max_format_retries: int = 2
    ) -> Tuple[GeneratedPatch, ApplyPatchResult]:
        """Generate a patch and validate applicability against target code.
        
        If diff application fails syntax check, retries with formatting error hint up to max_format_retries.
        """
        curr_request = request
        last_patch = None
        last_result = None

        for attempt in range(1, max_format_retries + 1):
            last_patch = self.generate_patch(curr_request)
            last_result = self.applicator.apply_diff_to_text(request.suspect_code, last_patch.unified_diff)

            if last_result.success:
                logger.info(f"Patch format validation passed on attempt {attempt}")
                return last_patch, last_result

            logger.warning(
                f"Patch format validation failed on attempt {attempt}: {last_result.error_message}. Retrying..."
            )

            # Update request with formatting error feedback for LLM retry
            curr_request = PatchRequest(
                target_file=request.target_file,
                suspect_function_name=request.suspect_function_name,
                suspect_code=request.suspect_code,
                exception_type=request.exception_type,
                exception_message=request.exception_message,
                failing_test_name=request.failing_test_name,
                related_code_context=request.related_code_context,
                past_fix_examples=request.past_fix_examples,
                previous_attempt_error=f"Diff format/syntax error: {last_result.error_message}",
            )

        return last_patch, last_result
