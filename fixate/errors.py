"""Typed pipeline failures.

Every stage of the self-healing pipeline can fail for reasons that are worth
telling the operator about precisely. Raising one of these carries three things
to the orchestrator: which stage broke, what happened, and what the human can do
about it. Stages must never paper over a failure by inventing a plausible-looking
result -- an incident that reports FAILED with a clear reason is strictly more
useful than one that reports COMPLETED without having changed any code.
"""

from typing import Optional


class PipelineError(Exception):
    """Base class for unrecoverable failures inside a pipeline stage."""

    stage: str = "pipeline"

    def __init__(self, message: str, remedy: Optional[str] = None):
        super().__init__(message)
        self.message = message
        self.remedy = remedy

    def report(self) -> str:
        """Render an operator-facing failure report."""
        lines = [f"Pipeline halted during {self.stage}.", "", self.message]
        if self.remedy:
            lines.extend(["", f"Suggested action: {self.remedy}"])
        return "\n".join(lines)


class TracebackParseError(PipelineError):
    """The supplied pytest log contained no recognizable test failure."""

    stage = "traceback parsing"


class LocalizationError(PipelineError):
    """No plausible root-cause candidate could be identified in the codebase."""

    stage = "failure localization"


class LLMUnavailableError(PipelineError):
    """A stage that requires real model output has no live LLM to call."""

    stage = "patch generation"


class PatchGenerationError(PipelineError):
    """The model returned no usable patch for this attempt."""

    stage = "patch generation"


class VerificationError(PipelineError):
    """The verification loop could not run to completion."""

    stage = "sandbox verification"
