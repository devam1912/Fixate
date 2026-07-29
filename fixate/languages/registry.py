"""Toolchain lookup.

Resolution is deterministic and ordered: the first registered toolchain that claims
a file, log, or repository wins. Python is registered first because it is the
engine's primary target and its log format is the one most callers supply.
"""

import logging
import os
from typing import List, Optional

from fixate.languages.base import LanguageToolchain
from fixate.languages.javascript import JavaScriptToolchain
from fixate.languages.python import PythonToolchain

logger = logging.getLogger(__name__)

_TOOLCHAINS: List[LanguageToolchain] = [
    PythonToolchain(),
    JavaScriptToolchain(),
]


def all_enabled() -> List[LanguageToolchain]:
    """Every registered toolchain, in resolution order."""
    return list(_TOOLCHAINS)


def by_name(name: str) -> Optional[LanguageToolchain]:
    """Look up a toolchain by its stable identifier."""
    return next((t for t in _TOOLCHAINS if t.name == name), None)


def for_file(file_path: str) -> Optional[LanguageToolchain]:
    """The toolchain owning a source file's extension."""
    if not file_path:
        return None
    return next((t for t in _TOOLCHAINS if t.owns_file(file_path)), None)


def for_log(log: str) -> Optional[LanguageToolchain]:
    """The toolchain whose test runner produced this output.

    This is the primary router for mixed-language repositories: a repository may
    contain both Python and TypeScript, but the failing log came from exactly one
    runner, and that is the language the incident is about.
    """
    if not log or not log.strip():
        return None
    return next((t for t in _TOOLCHAINS if t.owns_log(log)), None)


def for_repo(repo_dir: str) -> List[LanguageToolchain]:
    """Every toolchain whose language appears in the repository.

    Falls back to extension scanning when no manifest is present, so a directory of
    loose scripts is still recognized.
    """
    if not repo_dir or not os.path.isdir(repo_dir):
        return []

    detected = [t for t in _TOOLCHAINS if t.detects(repo_dir)]
    if detected:
        return detected

    seen: set[str] = set()
    for root, dirs, files in os.walk(repo_dir):
        dirs[:] = [d for d in dirs if d not in _SKIP_DIRS]
        for filename in files:
            toolchain = for_file(filename)
            if toolchain is not None:
                seen.add(toolchain.name)
        if len(seen) == len(_TOOLCHAINS):
            break

    return [t for t in _TOOLCHAINS if t.name in seen]


def resolve(repo_dir: str, log: str = "", suspect_path: str = "") -> Optional[LanguageToolchain]:
    """Pick the toolchain for an incident.

    Precedence follows how much each signal narrows the question: the failing log
    names the runner that actually broke, the suspect file names the language being
    repaired, and repository detection is the last resort.
    """
    from_log = for_log(log)
    if from_log is not None:
        return from_log

    from_file = for_file(suspect_path)
    if from_file is not None:
        return from_file

    detected = for_repo(repo_dir)
    return detected[0] if detected else None


_SKIP_DIRS = {
    ".git",
    "__pycache__",
    "node_modules",
    "venv",
    ".venv",
    "dist",
    "build",
    ".pytest_cache",
    "chroma_db",
    ".mypy_cache",
    "coverage",
}
