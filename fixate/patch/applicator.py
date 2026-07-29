"""Unified-diff application with structural verification.

Machine-generated diffs fail in specific, recurring ways: the model quotes context
that does not exist, indents its hunk differently from the file, omits the hunk
header, or produces a change that parses as a diff but destroys the file's syntax.
Each of those is a distinct outcome here rather than a generic boolean, because
the verification loop feeds the reason back to the model and a precise reason
produces a better next attempt.

Two rules are load-bearing and must not be relaxed:

* A patch that leaves the file byte-identical is a failure, never a success. It
  means the removal lines matched nothing. Reporting success would let a flaky
  test pass on unmodified code and be credited as a repair.
* A patch that leaves the file unparseable is a failure. Verification would catch
  it a minute later via a collection error; catching it here costs nothing and
  reports the actual cause.
"""

import ast
import logging
import re
from enum import Enum
from typing import List, Optional, Tuple

from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)


class PatchFailureReason(str, Enum):
    """Why a patch could not be applied. Fed back to the model on retry."""

    MALFORMED_DIFF = "malformed_diff"
    CONTEXT_NOT_FOUND = "context_not_found"
    NO_CHANGE = "no_change"
    SYNTAX_ERROR = "syntax_error"
    IO_ERROR = "io_error"


class ApplyPatchResult(BaseModel):
    """Outcome of applying a unified diff."""

    success: bool = Field(..., description="True if the patch applied and passed structural checks")
    patched_code: Optional[str] = Field(None, description="Full patched source if successful")
    error_message: Optional[str] = Field(None, description="Operator-facing failure detail")
    reason: Optional[PatchFailureReason] = Field(None, description="Machine-readable failure category")
    lines_added: int = Field(0, description="Count of added lines")
    lines_removed: int = Field(0, description="Count of removed lines")

    @classmethod
    def failed(cls, reason: PatchFailureReason, message: str) -> "ApplyPatchResult":
        return cls(success=False, patched_code=None, error_message=message, reason=reason)


class Hunk(BaseModel):
    """One ``@@`` block: where it claims to apply, and the lines it expects."""

    old_start: int = Field(..., description="1-based start line in the original file")
    old_lines: List[str] = Field(..., description="Context + removed lines, in order")
    new_lines: List[str] = Field(..., description="Context + added lines, in order")
    added: int = 0
    removed: int = 0


_HUNK_HEADER = re.compile(r"^@@\s+-(\d+)(?:,\d+)?\s+\+(\d+)(?:,\d+)?\s+@@")
_FILE_HEADER = ("---", "+++", "diff ", "index ", "\\ No newline")


class PatchApplicator:
    """Applies unified diffs to Python source and verifies the result structurally."""

    def apply_diff_to_text(
        self, original_text: str, diff_text: str, file_path: str = "patched.py"
    ) -> ApplyPatchResult:
        """Apply a unified diff to source text.

        ``file_path`` selects the syntax gate: the applicator validates the result
        with the toolchain owning that extension, so a TypeScript patch is checked
        by a TypeScript parser rather than by ``ast.parse``.
        """
        if not diff_text or not diff_text.strip():
            return ApplyPatchResult.failed(
                PatchFailureReason.MALFORMED_DIFF, "The patch was empty."
            )

        hunks = self._parse(diff_text)
        if not hunks:
            return ApplyPatchResult.failed(
                PatchFailureReason.MALFORMED_DIFF,
                "No applicable hunks were found. A patch must contain at least one "
                "'@@' header, or lines prefixed with '-' and '+'.",
            )

        original_lines = original_text.splitlines()
        ends_with_newline = original_text.endswith("\n")

        patched_lines = list(original_lines)
        offset = 0
        added = removed = 0

        for index, hunk in enumerate(hunks, start=1):
            location = self._locate(patched_lines, hunk.old_lines, hunk.old_start - 1 + offset)
            if location is None:
                preview = next((line for line in hunk.old_lines if line.strip()), "")
                return ApplyPatchResult.failed(
                    PatchFailureReason.CONTEXT_NOT_FOUND,
                    f"Hunk {index} of {len(hunks)} does not match the file. Its context "
                    f"was not found near line {hunk.old_start}"
                    + (f", starting {preview.strip()!r}." if preview else ".")
                    + " The quoted lines must be reproduced exactly as they appear in the source.",
                )

            start, matched_exactly = location
            existing = patched_lines[start : start + len(hunk.old_lines)]
            replacement = (
                hunk.new_lines
                if matched_exactly
                else self._reindent(existing, hunk.old_lines, hunk.new_lines)
            )

            patched_lines[start : start + len(hunk.old_lines)] = replacement
            offset += len(replacement) - len(hunk.old_lines)
            added += hunk.added
            removed += hunk.removed

        patched_text = "\n".join(patched_lines)
        if ends_with_newline:
            patched_text += "\n"

        normalized_original = "\n".join(original_lines) + ("\n" if ends_with_newline else "")
        if patched_text == normalized_original:
            return ApplyPatchResult.failed(
                PatchFailureReason.NO_CHANGE,
                "The patch applied but changed nothing. Its removal lines matched no "
                "code in the file, so the file is byte-identical to the original. A "
                "patch must modify the source to be considered a fix.",
            )

        issue = self._syntax_issue(patched_text, file_path)
        if issue is not None:
            return ApplyPatchResult.failed(
                PatchFailureReason.SYNTAX_ERROR,
                f"{issue.describe()}. The patch left the file unparseable -- check "
                f"indentation and block structure.",
            )

        return ApplyPatchResult(
            success=True,
            patched_code=patched_text,
            error_message=None,
            reason=None,
            lines_added=added,
            lines_removed=removed,
        )

    def apply_patch_to_file(self, file_path: str, diff_text: str) -> ApplyPatchResult:
        """Apply a unified diff to a file, writing it back only on success."""
        try:
            with open(file_path, "r", encoding="utf-8") as handle:
                original = handle.read()
        except Exception as exc:
            return ApplyPatchResult.failed(
                PatchFailureReason.IO_ERROR, f"Could not read {file_path}: {exc}"
            )

        result = self.apply_diff_to_text(original, diff_text, file_path=file_path)
        if not (result.success and result.patched_code is not None):
            return result

        try:
            with open(file_path, "w", encoding="utf-8") as handle:
                handle.write(result.patched_code)
        except Exception as exc:
            return ApplyPatchResult.failed(
                PatchFailureReason.IO_ERROR, f"Could not write {file_path}: {exc}"
            )

        logger.info(
            "Applied patch to %s (+%d/-%d lines).", file_path, result.lines_added, result.lines_removed
        )
        return result

    def _parse(self, diff_text: str) -> List[Hunk]:
        """Parse a unified diff into hunks.

        Tolerates a missing ``@@`` header by treating a bare run of +/- lines as a
        single hunk anchored by search rather than by line number -- small models
        omit the header often enough that rejecting those outright wastes attempts,
        and the content still has to match the file exactly to apply.
        """
        hunks: List[Hunk] = []
        old_lines: List[str] = []
        new_lines: List[str] = []
        added = removed = 0
        old_start: Optional[int] = None
        in_hunk = False

        def flush() -> None:
            nonlocal old_lines, new_lines, added, removed, old_start
            if old_lines or new_lines:
                hunks.append(
                    Hunk(
                        old_start=old_start or 1,
                        old_lines=old_lines,
                        new_lines=new_lines,
                        added=added,
                        removed=removed,
                    )
                )
            old_lines, new_lines = [], []
            added = removed = 0
            old_start = None

        for line in diff_text.splitlines():
            header = _HUNK_HEADER.match(line)
            if header:
                flush()
                old_start = int(header.group(1))
                in_hunk = True
                continue

            if line.startswith(_FILE_HEADER):
                continue

            marker, content = line[:1], line[1:]
            if marker == "-":
                old_lines.append(content)
                removed += 1
                in_hunk = True
            elif marker == "+":
                new_lines.append(content)
                added += 1
                in_hunk = True
            elif marker == " ":
                old_lines.append(content)
                new_lines.append(content)
            elif in_hunk and not line.strip():
                # A blank line inside a hunk is context whose marker was trimmed,
                # which is common when diffs round-trip through JSON or markdown.
                old_lines.append("")
                new_lines.append("")

        flush()
        return [h for h in hunks if h.old_lines or h.new_lines]

    def _locate(
        self, lines: List[str], pattern: List[str], preferred: int
    ) -> Optional[Tuple[int, bool]]:
        """Find where a hunk's expected lines sit. Returns (index, matched_exactly).

        Tries the header's own position first so that repeated code (identical
        getters, repeated ``return None``) resolves to the hunk's declared location
        instead of the file's first coincidental match.
        """
        if not pattern:
            return (max(0, min(preferred, len(lines))), True)

        span = len(lines) - len(pattern) + 1
        if span <= 0:
            return None

        order: List[int] = []
        if 0 <= preferred < span:
            order.append(preferred)
        order.extend(i for i in range(span) if i != preferred)

        for index in order:
            if lines[index : index + len(pattern)] == pattern:
                return (index, True)

        # Fall back to ignoring leading/trailing whitespace: models frequently
        # re-indent a quoted block relative to the file it came from.
        stripped = [line.strip() for line in pattern]
        for index in order:
            if [line.strip() for line in lines[index : index + len(pattern)]] == stripped:
                return (index, False)

        return None

    def _reindent(
        self, existing: List[str], old_block: List[str], new_block: List[str]
    ) -> List[str]:
        """Rewrite a replacement block into the file's indentation style.

        Used only when the hunk matched with whitespace ignored, meaning the diff's
        own indentation is known-wrong. Each line is re-expressed by *nesting depth*
        rather than by character count: a tab-indented file and a space-indented
        diff have no meaningful numeric offset between them, and shifting by
        characters yields lines like ``\\t    if x:`` that mix both styles and can
        raise TabError. Measuring depth in the diff's own unit and re-emitting it in
        the file's unit keeps the replacement internally nested and stylistically
        consistent with its surroundings.
        """
        base_target = self._indent_of(next((line for line in existing if line.strip()), ""))
        base_source = self._indent_of(next((line for line in old_block if line.strip()), ""))
        if base_target == base_source:
            return new_block

        unit_source = self._indent_unit(old_block + new_block) or "    "
        unit_target = self._indent_unit(existing) or unit_source

        adjusted: List[str] = []
        for line in new_block:
            if not line.strip():
                adjusted.append(line)
                continue
            indent = self._indent_of(line)
            extra = indent[len(base_source) :] if indent.startswith(base_source) else ""
            depth = len(extra) if unit_source == "\t" else len(extra) // len(unit_source)
            adjusted.append(base_target + unit_target * depth + line.lstrip())
        return adjusted

    @staticmethod
    def _indent_of(line: str) -> str:
        """Return the literal leading-whitespace prefix of a line."""
        return line[: len(line) - len(line.lstrip())]

    @classmethod
    def _indent_unit(cls, lines: List[str]) -> Optional[str]:
        """Infer one indentation level from a block: a tab, or the smallest indent."""
        indents = [cls._indent_of(line) for line in lines if line.strip()]
        if any(indent.startswith("\t") for indent in indents):
            return "\t"
        widths = {len(indent) for indent in indents if indent}
        return " " * min(widths) if widths else None

    @staticmethod
    def _syntax_issue(source: str, file_path: str):
        """Validate patched source with the toolchain owning its extension.

        Falls back to the Python grammar when the extension is unrecognized, since
        that is the engine's primary language and a missing gate is worse than an
        occasionally mismatched one.
        """
        from fixate.languages import registry

        toolchain = registry.for_file(file_path) or registry.by_name("python")
        if toolchain is None:
            return None

        issue = toolchain.syntax_error(source, file_path)
        if issue is not None:
            logger.warning("Patched source failed the %s syntax gate: %s", toolchain.name, issue.describe())
        return issue
