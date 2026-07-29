"""Patch Generation Package."""

from fixate.patch.schema import GeneratedPatch, PatchRequest
from fixate.patch.applicator import PatchApplicator

UnifiedDiffApplicator = PatchApplicator

__all__ = ["GeneratedPatch", "PatchRequest", "PatchApplicator", "UnifiedDiffApplicator"]
