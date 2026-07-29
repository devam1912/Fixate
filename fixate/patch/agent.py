"""Generation of minimal unified-diff repairs.

This stage requires a real model. It has no scripted-fix table and no simulation
mode: when there is no live LLM, it raises :class:`LLMUnavailableError` instead of
producing something patch-shaped. That is a deliberate reversal of the previous
design, where an unconfigured provider returned schema-shaped placeholder output
that flowed downstream and got applied to real source files.

Deterministic patches still have a place -- in tests, supplied through a fake
provider. They do not belong in the production path, where their only effect is to
disguise "there was no model" as "the model tried and failed".
"""

import logging
import os
from typing import List, Optional, Tuple

from fixate.errors import LLMUnavailableError, PatchGenerationError
from fixate.llm.base import BaseLLMProvider
from fixate.llm.factory import get_llm_provider
from fixate.patch.applicator import ApplyPatchResult, PatchApplicator
from fixate.patch.schema import GeneratedPatch, PatchRequest

logger = logging.getLogger(__name__)

SYSTEM_INSTRUCTION = (
    "You are a senior engineer repairing a specific test failure. You produce minimal, "
    "surgical unified diffs. You never restructure working code, never add features, and "
    "never edit tests to make them pass. Every line you quote in a diff must be reproduced "
    "byte-for-byte from the source you were given, including its exact indentation."
)

DIFF_FORMAT_RULES = """\
Return a unified diff in exactly this format:

--- a/{path}
+++ b/{path}
@@ -<start>,<count> +<start>,<count> @@
 unchanged context line
-line being removed
+line replacing it

Requirements:
- Removed ('-') lines MUST match the source exactly, including indentation.
- Include at least one unchanged context line where practical, so the hunk can be located.
- Change only what is necessary to fix the described failure.
- Do not wrap the diff in markdown fences or add prose around it."""


class PatchGeneratorAgent:
    """Asks a live model for a minimal diff repairing the localized defect."""

    def __init__(self, llm_provider: Optional[BaseLLMProvider] = None):
        self.llm = llm_provider or get_llm_provider()
        self.applicator = PatchApplicator()

    def generate_patch(self, request: PatchRequest) -> GeneratedPatch:
        """Generate a candidate patch.

        Raises:
            LLMUnavailableError: no live model is configured.
            PatchGenerationError: the model returned nothing usable.
        """
        self._require_live_llm()

        prompt = self.build_prompt(request)
        try:
            patch: GeneratedPatch = self.llm.generate_structured(
                prompt=prompt,
                response_schema=GeneratedPatch,
                system_instruction=SYSTEM_INSTRUCTION,
                temperature=0.05,
            )
        except Exception as exc:
            raise PatchGenerationError(
                f"The {self.llm.name} provider failed while generating a patch: {exc}",
                remedy="Check the provider's API key, quota, and network reachability.",
            ) from exc

        self._reject_unusable(patch, request)

        # The model is prompted with the target path but routinely echoes a
        # normalized or truncated version of it; the request is authoritative.
        patch.target_file = request.target_file

        logger.info(
            "Generated candidate patch for %s (%d lines changed): %s",
            os.path.basename(request.target_file),
            patch.lines_changed,
            patch.explanation,
        )
        return patch

    def generate_validated_patch(
        self, request: PatchRequest
    ) -> Tuple[GeneratedPatch, ApplyPatchResult]:
        """Generate a patch and dry-run it against ``request.suspect_code``.

        Only meaningful when ``suspect_code`` holds the complete file. The
        verification loop instead applies to the real file on disk, which is the
        authoritative check.
        """
        patch = self.generate_patch(request)
        result = self.applicator.apply_diff_to_text(request.suspect_code, patch.unified_diff)
        if not result.success:
            logger.warning("Candidate patch failed dry-run application: %s", result.error_message)
        return patch, result

    def build_prompt(self, request: PatchRequest) -> str:
        """Assemble the repair prompt from the failure and its retrieved context."""
        # The opener has to name the real acceptance criterion. Telling the model
        # "a test is failing" when the oracle is a linter describes the wrong job,
        # and it optimises for the wrong thing accordingly.
        requirement = request.proof_requirement or "the failing test passes"
        sections: List[str] = [
            f"A check is failing. Produce a minimal patch that fixes the defect in the "
            f"source code. The patch is accepted only when {requirement}.",
            "",
            "## Failure",
            f"Reported by: {request.failing_test_name}",
            f"Diagnostic: {request.exception_type}: {request.exception_message}",
            "",
            f"## Source to repair: {request.target_file}",
            f"Suspect symbol: {request.suspect_function_name}",
            f"```python\n{request.suspect_code}\n```",
        ]

        if request.checker_guidance:
            sections += [
                "",
                "## The checker's own required form",
                "The tool that reports this problem states the exact text it expects. "
                "Reproduce it byte-for-byte, including blank lines -- these rules accept "
                "one form only, and an arrangement that merely looks equivalent will "
                "still be reported.",
                f"```\n{request.checker_guidance}\n```",
            ]

        if request.test_code_context:
            sections += [
                "",
                "## The failing test",
                "Fix the source so this test passes. Do not modify the test itself.",
                f"```python\n{request.test_code_context}\n```",
            ]

        if request.related_code_context:
            sections += ["", "## Related code retrieved from the repository"]
            sections += [f"```python\n{snippet}\n```" for snippet in request.related_code_context]

        if request.past_fix_examples:
            sections += [
                "",
                "## Diffs that resolved similar failures previously",
                "Use these as evidence of house style, not as templates to copy.",
            ]
            sections += [f"```diff\n{example}\n```" for example in request.past_fix_examples]

        if request.previous_attempt_error:
            sections += [
                "",
                "## Your previous attempt failed",
                request.previous_attempt_error,
                "",
                "Diagnose why that attempt failed before proposing another. If the failure "
                "was that your quoted lines did not match the file, re-read the source above "
                "and copy the target lines exactly. Do not resubmit the same diff.",
            ]

        sections += ["", "## Output format", DIFF_FORMAT_RULES.format(path=request.target_file)]
        return "\n".join(sections)

    def _require_live_llm(self) -> None:
        if not self.llm.is_live:
            raise LLMUnavailableError(
                f"Patch generation requires a live LLM, but provider '{self.llm.name}' is "
                f"not configured with credentials and would return placeholder output.",
                remedy=(
                    "Set the provider's API key in the environment (for example GEMINI_API_KEY "
                    "or MISTRAL_API_KEY) and ensure it is passed through to the running "
                    "container, then re-trigger the incident."
                ),
            )

    def _reject_unusable(self, patch: GeneratedPatch, request: PatchRequest) -> None:
        """Reject output that cannot possibly be a patch before anything acts on it."""
        diff = (patch.unified_diff or "").strip()
        if not diff:
            raise PatchGenerationError(
                "The model returned an empty diff for "
                f"{request.suspect_function_name} in {request.target_file}."
            )

        if not any(line.startswith(("+", "-", "@@")) for line in diff.splitlines()):
            raise PatchGenerationError(
                "The model's response contained no diff lines. Expected a unified diff "
                f"with '+'/'-' lines, received: {diff[:200]}"
            )
