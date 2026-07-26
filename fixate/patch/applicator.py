"""Unified diff applicator and syntax validation engine for python files."""

import ast
import re
import logging
from typing import Optional
from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)


class ApplyPatchResult(BaseModel):
    """Result object returned after applying a unified diff patch."""
    success: bool = Field(..., description="True if patch applied cleanly and passed syntax check")
    patched_code: Optional[str] = Field(None, description="Full patched code string if successful")
    error_message: Optional[str] = Field(None, description="Error details if patch application failed")


class PatchApplicator:
    """Applies machine-generated unified diffs to source files and validates syntax."""

    def apply_diff_to_text(self, original_text: str, diff_text: str) -> ApplyPatchResult:
        """Apply a unified diff string to an original text content string."""
        lines = original_text.splitlines()

        # Extract hunk blocks from unified diff
        hunk_header_pattern = re.compile(r'^@@\s+-\d+(?:,\d+)?\s+\+(\d+)(?:,(\d+))?\s+@@')
        diff_lines = diff_text.splitlines()

        # Find line changes in unified diff
        adds = []
        removes = []
        in_hunk = False

        for dline in diff_lines:
            if dline.startswith("---") or dline.startswith("+++"):
                continue
            if hunk_header_pattern.match(dline):
                in_hunk = True
                continue
            if in_hunk:
                if dline.startswith("+"):
                    adds.append(dline[1:])
                elif dline.startswith("-"):
                    removes.append(dline[1:])

        # Simple line replacement strategy for minimal targeted diffs
        patched_lines = list(lines)
        if removes:
            remove_block = "\n".join(removes)
            add_block = "\n".join(adds)
            full_orig = "\n".join(lines)

            if remove_block in full_orig:
                patched_full = full_orig.replace(remove_block, add_block, 1)
            else:
                # Line-by-line fallback
                new_lines = []
                skip = False
                for line in lines:
                    if line in removes:
                        if not skip:
                            for a in adds:
                                new_lines.append(a)
                            skip = True
                    else:
                        new_lines.append(line)
                patched_full = "\n".join(new_lines)
        else:
            # Append additions if no explicit removes
            patched_full = original_text + "\n" + "\n".join(adds)

        # Validate Python AST syntax of patched code
        try:
            ast.parse(patched_full)
        except SyntaxError as syn_err:
            logger.warning(f"Patched code failed AST syntax check: {syn_err}")
            return ApplyPatchResult(
                success=False,
                patched_code=None,
                error_message=f"SyntaxError in generated patch at line {syn_err.lineno}: {syn_err.msg}",
            )
        except Exception as exc:
            return ApplyPatchResult(
                success=False,
                patched_code=None,
                error_message=f"AST parse validation error: {exc}",
            )

        return ApplyPatchResult(
            success=True,
            patched_code=patched_full,
            error_message=None,
        )

    def apply_patch_to_file(self, file_path: str, diff_text: str) -> ApplyPatchResult:
        """Apply a unified diff directly to a target file on disk."""
        try:
            with open(file_path, "r", encoding="utf-8") as f:
                original_content = f.read()

            result = self.apply_diff_to_text(original_content, diff_text)
            if result.success and result.patched_code is not None:
                with open(file_path, "w", encoding="utf-8") as f:
                    f.write(result.patched_code)
                logger.info(f"Successfully applied patch to {file_path}")

            return result
        except Exception as exc:
            logger.error(f"Failed to apply patch to file {file_path}: {exc}")
            return ApplyPatchResult(
                success=False,
                patched_code=None,
                error_message=f"File I/O error applying patch: {exc}",
            )
