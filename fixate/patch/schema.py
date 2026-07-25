"""Pydantic schemas for machine-applicable structured patch generation."""

from typing import List, Optional
from pydantic import BaseModel, Field


class PatchRequest(BaseModel):
    """Input parameters passed to Patch Generation Agent."""
    target_file: str = Field(..., description="Target file path needing fix")
    suspect_function_name: str = Field(..., description="Suspect function name identified by localization")
    suspect_code: str = Field(..., description="Current implementation snippet of suspect function")
    exception_type: str = Field(..., description="Exception class name")
    exception_message: str = Field(..., description="Exception error message")
    failing_test_name: str = Field(..., description="Failing test name")
    related_code_context: List[str] = Field(default_factory=list, description="Snippets of related functions")
    past_fix_examples: List[str] = Field(default_factory=list, description="Past unified diff fix examples")
    previous_attempt_error: Optional[str] = Field(None, description="Error from previous failed verification attempt")


class GeneratedPatch(BaseModel):
    """Structured response output model for generated machine-applicable diffs."""
    target_file: str = Field(..., description="Relative file path being patched, e.g. services/tax.py")
    unified_diff: str = Field(
        ...,
        description="Valid machine-applicable unified diff format starting with --- a/file.py and +++ b/file.py",
    )
    explanation: str = Field(..., description="Minimal concise explanation of why this patch resolves the root cause")
    lines_changed: int = Field(..., description="Total line count modified by this minimal diff")
