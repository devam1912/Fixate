"""Parsing Jest and Vitest output into the pipeline's shared failure model.

Both runners describe a failure the same way in outline -- a marked test header, an
assertion block, and a stack of source locations -- but neither resembles a Python
traceback, and both colorize by default, so raw output is full of ANSI escapes that
break naive line matching.

The result is a :class:`ParsedFailure`, the same structure the Python toolchain
produces, so every downstream stage stays language-agnostic.
"""

import logging
import re
from typing import List, Optional, Tuple

from fixate.errors import TracebackParseError
from fixate.localization.parser import ParsedFailure, StackFrame

logger = logging.getLogger(__name__)

_ANSI = re.compile(r"\x1B\[[0-?]*[ -/]*[@-~]")

# Jest: "  ● cart › applies discount correctly"
# Vitest uses the same bullet, and both may use › or > as the separator.
_TEST_HEADER = re.compile(r"^\s*●\s+(?P<name>.+?)\s*$")

# Vitest: "FAIL  src/cart.test.ts > cart > applies discount correctly"
_VITEST_FAIL = re.compile(r"^\s*FAIL\s+(?P<file>\S+?)\s*[>›]\s*(?P<name>.+?)\s*$")

# Stack frames: "at Object.<anonymous> (src/cart.ts:14:22)" or "at src/cart.ts:14:22"
_FRAME = re.compile(
    r"^\s*at\s+(?:(?P<func>[^\s(]+)\s+\()?(?P<file>[^\s():]+\.[jt]sx?):(?P<line>\d+):(?P<col>\d+)\)?"
)

# "❯ src/cart.ts:14:22" -- Vitest's own frame marker.
_VITEST_FRAME = re.compile(r"^\s*[❯>]\s+(?P<file>\S+?\.[jt]sx?):(?P<line>\d+):(?P<col>\d+)")

# Assertion kinds, mapped to an exception-style label so risk scoring and prompts
# read the same across languages.
_ERROR_LINE = re.compile(r"^\s*(?P<type>[A-Z][A-Za-z]*(?:Error|Exception))\s*:\s*(?P<msg>.*)$")

_ASSERTION_MARKERS = (
    "expect(",
    "Expected:",
    "Received:",
    "AssertionError",
    "toBe",
    "toEqual",
)

_RUNNER_MARKERS = (
    "Test Suites:",
    "Tests:",
    "● ",
    "jest",
    "vitest",
    "Vitest",
    "RUN  v",
    "toBeTruthy",
    "toEqual",
)


def strip_ansi(text: str) -> str:
    """Remove terminal colour escapes. Both runners colorize by default."""
    return _ANSI.sub("", text or "")


def owns_log(log: str) -> bool:
    """Whether this output came from a JavaScript test runner."""
    clean = strip_ansi(log)
    if any(marker in clean for marker in ("Test Suites:", "RUN  v", "vitest", "Vitest")):
        return True
    # A Jest bullet header plus a JS/TS file reference is conclusive.
    has_bullet = bool(_TEST_HEADER.search(clean))
    has_js_file = bool(re.search(r"\.[jt]sx?:\d+", clean))
    return has_bullet and has_js_file


class JavaScriptFailureParser:
    """Extracts the first failing test from Jest or Vitest output."""

    def parse_log(self, log: str) -> ParsedFailure:
        if not log or not log.strip():
            raise TracebackParseError(
                "The supplied test log was empty.",
                remedy="Run the target test suite and pass its combined stdout/stderr.",
            )

        clean = strip_ansi(log)
        lines = clean.splitlines()

        test_name, section = self._first_failure_section(lines)
        frames = self._parse_frames(section)
        error_type, error_message = self._parse_error(section, clean)
        failing_file, failing_line = self._resolve_site(frames, section)

        if not any((test_name, frames, error_type)):
            raise TracebackParseError(
                "No failing test could be identified in the JavaScript test output. "
                "The run may have failed to start, or every test passed.",
                remedy=(
                    "Confirm the log contains a failure block (Jest '●' or Vitest 'FAIL'). "
                    "Build or module-resolution errors must be resolved before the "
                    "self-healing pipeline can localize a defect."
                ),
            )

        failure = ParsedFailure(
            test_name=test_name or "unknown_test",
            failing_file=failing_file or "",
            failing_line=failing_line or 0,
            exception_type=error_type or "AssertionError",
            exception_message=error_message,
            stack_frames=frames,
            raw_traceback="\n".join(section),
        )
        logger.info(
            "Parsed JS failure: %s raised %s at %s:%s (%d frames)",
            failure.test_name,
            failure.exception_type,
            failure.failing_file or "?",
            failure.failing_line or "?",
            len(failure.stack_frames),
        )
        return failure

    def _first_failure_section(self, lines: List[str]) -> Tuple[Optional[str], List[str]]:
        """Isolate the first failure block and the name of the test that produced it."""
        start: Optional[int] = None
        name: Optional[str] = None

        for index, line in enumerate(lines):
            vitest = _VITEST_FAIL.match(line)
            if vitest:
                start, name = index, self._leaf_name(vitest.group("name"))
                break
            header = _TEST_HEADER.match(line)
            if header and not self._is_summary_bullet(header.group("name")):
                start, name = index, self._leaf_name(header.group("name"))
                break

        if start is None:
            return None, lines

        # The block ends at the next failure header or the run summary.
        end = len(lines)
        for index in range(start + 1, len(lines)):
            line = lines[index]
            if _VITEST_FAIL.match(line):
                end = index
                break
            header = _TEST_HEADER.match(line)
            if header and not self._is_summary_bullet(header.group("name")):
                end = index
                break
            if line.startswith(("Test Suites:", "Tests:", " Test Files ")):
                end = index
                break

        return name, lines[start:end]

    def _parse_frames(self, section: List[str]) -> List[StackFrame]:
        frames: List[StackFrame] = []
        for line in section:
            match = _FRAME.match(line)
            if match:
                frames.append(
                    StackFrame(
                        file_path=match.group("file"),
                        line_number=int(match.group("line")),
                        function_name=match.group("func") or "unknown",
                    )
                )
                continue
            match = _VITEST_FRAME.match(line)
            if match:
                frames.append(
                    StackFrame(
                        file_path=match.group("file"),
                        line_number=int(match.group("line")),
                        function_name="unknown",
                    )
                )
        return frames

    def _parse_error(self, section: List[str], full_log: str) -> Tuple[Optional[str], str]:
        """Determine the error kind and message."""
        for line in section:
            match = _ERROR_LINE.match(line.strip())
            if match:
                return match.group("type"), match.group("msg").strip()

        expected = received = None
        for line in section:
            stripped = line.strip()
            if stripped.startswith("Expected:"):
                expected = stripped.split(":", 1)[1].strip()
            elif stripped.startswith("Received:"):
                received = stripped.split(":", 1)[1].strip()

        if expected is not None or received is not None:
            return "AssertionError", f"expected {expected}, received {received}"

        if any(marker in "\n".join(section) for marker in _ASSERTION_MARKERS):
            return "AssertionError", "Assertion failed"

        return None, ""

    def _resolve_site(
        self, frames: List[StackFrame], section: List[str]
    ) -> Tuple[Optional[str], Optional[int]]:
        """Pick where the defect most likely lives.

        The deepest non-test frame is preferred: the defect is normally in the code
        under test, not in the spec that caught it.
        """
        for frame in frames:
            if not self._looks_like_test(frame.file_path):
                return frame.file_path, frame.line_number
        if frames:
            return frames[0].file_path, frames[0].line_number
        return None, None

    @staticmethod
    def _looks_like_test(file_path: str) -> bool:
        normalized = file_path.replace("\\", "/").lower()
        base = normalized.rsplit("/", 1)[-1]
        return ".test." in base or ".spec." in base or "__tests__/" in normalized

    @staticmethod
    def _leaf_name(header: str) -> str:
        """Take the individual case name from a 'suite > case' header.

        Runners select by the leaf name, so keeping the full path would produce a
        target that matches nothing.
        """
        parts = re.split(r"\s*[>›]\s*", header.strip())
        return parts[-1].strip() if parts else header.strip()

    @staticmethod
    def _is_summary_bullet(text: str) -> bool:
        """Filter Jest's non-failure bullets (e.g. '● Console')."""
        return text.strip().lower() in {"console", "deprecation warning", "validation error"}
