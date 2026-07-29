"""Per-language toolchains.

Each stage of the pipeline asks a toolchain how to do the language-specific part of
its job -- parse symbols, read a failure log, validate patched syntax, install
dependencies, run a subset of tests -- so the stages themselves stay generic.
"""

from fixate.languages.base import (
    InstallResult,
    LanguageToolchain,
    SyntaxIssue,
    TestSelection,
)

__all__ = ["LanguageToolchain", "SyntaxIssue", "InstallResult", "TestSelection"]
