"""Data schemas for patch generation requests and structured output diffs."""

from typing import List, Optional
from pydantic import BaseModel, Field


class PatchRequest(BaseModel):
    """Input payload for generating a targeted code repair patch."""
    target_file: str = Field(..., description="Target source file path relative to repository root")
    suspect_function_name: str = Field(..., description="Name of suspect function being repaired")
    suspect_code: str = Field(..., description="Source code snippet of suspect function")
    exception_type: str = Field(..., description="Exception type raised by failing test (e.g. KeyError)")
    exception_message: str = Field(..., description="Exception error message string")
    failing_test_name: str = Field(..., description="Name of failing test function")
    test_code_context: Optional[str] = Field(None, description="Source code and assertions of failing test case")
    related_code_context: List[str] = Field(default=[], description="Code snippets of related symbols retrieved via Code-RAG")
    past_fix_examples: List[str] = Field(default=[], description="Past verified diffs for similar failure patterns")
    previous_attempt_error: Optional[str] = Field(None, description="Error log from previous failed patch attempt, if retrying")
    checker_guidance: Optional[str] = Field(None, description="The checker's own stated fix for the diagnostic, when it offers one verbatim")
    proof_requirement: Optional[str] = Field(None, description="What must hold for the patch to be accepted, phrased by the verifying oracle")


class GeneratedPatch(BaseModel):
    """Structured LLM output containing verified unified diff."""
    target_file: str = Field(..., description="Target file path matching patch request")
    unified_diff: str = Field(..., description="Valid unified machine diff starting with --- a/ and +++ b/")
    explanation: str = Field(..., description="Concise architectural explanation of why this patch fixes the bug")
    lines_changed: int = Field(..., description="Total number of modified/added/deleted lines in diff")
