"""Structured extraction of the first test failure from a pytest log.

pytest emits the same failure in several dialects depending on how it was invoked
(`--tb=long` sections, `--tb=native` Python tracebacks, and the terminal summary
line). Rather than trying regexes until one sticks, this parser recognizes each
dialect explicitly, collects every signal it finds, and then resolves them by
precedence. When no dialect matches at all it raises rather than emitting a
placeholder failure -- a fabricated "unknown.py:1 AssertionError" sends the whole
pipeline chasing a bug that was never described.
"""

import re
import logging
from typing import List, Optional, Tuple
from pydantic import BaseModel, Field

from fixate.errors import TracebackParseError

logger = logging.getLogger(__name__)


class StackFrame(BaseModel):
    file_path: str
    line_number: int
    function_name: str


class ParsedFailure(BaseModel):
    test_name: str
    failing_file: str
    failing_line: int
    exception_type: str
    exception_message: str
    stack_frames: List[StackFrame]
    raw_traceback: str


# ``______ test_name ______`` banner opening each failure section. Requires three
# consecutive underscores so pytest's ``_ _ _ _`` sub-separators never match.
_SECTION_BANNER = re.compile(r"^_{3,}\s*(?P<test>[\w.\[\]:<>-]+?)\s*_{3,}$")

# ``path/to/file.py:12: in function_name`` -- pytest long-form frame.
_FRAME_PYTEST = re.compile(r"^(?P<file>\S+\.py):(?P<line>\d+):\s+in\s+(?P<func>[\w<>]+)\s*$")

# ``File "path/to/file.py", line 12, in function_name`` -- native Python traceback.
_FRAME_NATIVE = re.compile(
    r'File\s+["\'](?P<file>[^"\']+)["\'],\s+line\s+(?P<line>\d+),\s+in\s+(?P<func>[\w<>]+)'
)

# ``path/to/file.py:12: ZeroDivisionError`` -- pytest's authoritative error location.
_ERROR_LOCATION = re.compile(
    r"^(?P<file>\S+\.py):(?P<line>\d+):\s+(?P<exc>[A-Za-z_]\w*(?:Error|Exception|Failure|Exit))\b"
)

# ``E   ZeroDivisionError: division by zero`` -- pytest's marked exception line.
_EXCEPTION_MARKED = re.compile(r"^E\s+(?P<exc>[A-Za-z_][\w.]*)\s*:\s*(?P<msg>.*)$")

# ``ZeroDivisionError: division by zero`` -- bare exception line in a native traceback.
_EXCEPTION_BARE = re.compile(r"^(?P<exc>[A-Za-z_]\w*(?:Error|Exception))\s*:\s*(?P<msg>.*)$")

# ``FAILED tests/test_x.py::test_name - ZeroDivisionError: division by zero``
_SUMMARY_LINE = re.compile(
    r"^(?:FAILED|ERROR)\s+(?P<file>\S+?)::(?P<test>[\w\[\].-]+)"
    r"(?:\s+-\s+(?P<exc>[A-Za-z_][\w.]*)\s*:\s*(?P<msg>.*))?$"
)


class FailureTracebackParser:
    """Parses raw pytest output into a structured :class:`ParsedFailure`."""

    def parse_log(self, log_output: str) -> ParsedFailure:
        """Extract the first reported failure from a pytest log.

        Raises:
            TracebackParseError: if the log describes no identifiable failure.
        """
        if not log_output or not log_output.strip():
            raise TracebackParseError(
                "The supplied pytest log was empty.",
                remedy="Run the target test suite and pass its combined stdout/stderr.",
            )

        summary = self._parse_summary_line(log_output)
        section_test, section = self._first_failure_section(log_output)

        frames = self._parse_frames(section)
        error_location = self._parse_error_location(section)
        exception = self._parse_exception(section) or self._parse_exception(log_output)

        # Resolve the test name: the section banner is the most specific, then the
        # terminal summary line.
        test_name = section_test or (summary.get("test") if summary else None)

        # Resolve the exception: a marked/bare exception line carries the message,
        # the summary line is the fallback, and the error-location line at least
        # names the type.
        if exception:
            exception_type, exception_message = exception
        elif summary and summary.get("exc"):
            exception_type = summary["exc"]
            exception_message = (summary.get("msg") or "").strip()
        elif error_location:
            exception_type = error_location[2]
            exception_message = ""
        else:
            exception_type, exception_message = None, ""

        failing_file, failing_line = self._resolve_failure_site(
            error_location, frames, summary
        )

        if not any((test_name, exception_type, frames, failing_file)):
            raise TracebackParseError(
                "No test failure could be identified in the supplied pytest log. "
                "The run may have errored during collection, or passed entirely.",
                remedy=(
                    "Confirm the log contains a FAILURES section. Collection errors "
                    "(import failures, missing dependencies) must be resolved before "
                    "the self-healing pipeline can localize a defect."
                ),
            )

        failure = ParsedFailure(
            test_name=test_name or "unknown_test",
            failing_file=failing_file or "",
            failing_line=failing_line or 0,
            exception_type=exception_type or "UnknownError",
            exception_message=exception_message,
            stack_frames=frames,
            raw_traceback=section,
        )
        logger.info(
            "Parsed failure: %s raised %s at %s:%s (%d frames)",
            failure.test_name,
            failure.exception_type,
            failure.failing_file or "?",
            failure.failing_line or "?",
            len(failure.stack_frames),
        )
        return failure

    def _first_failure_section(self, log_output: str) -> Tuple[Optional[str], str]:
        """Return (test name, text) for the first failure section in the log."""
        lines = log_output.splitlines()
        banners: List[Tuple[int, str]] = []
        for idx, line in enumerate(lines):
            match = _SECTION_BANNER.match(line.strip())
            if match:
                banners.append((idx, match.group("test")))

        if not banners:
            return None, log_output

        start, test_name = banners[0]
        end = banners[1][0] if len(banners) > 1 else len(lines)
        return test_name, "\n".join(lines[start:end])

    def _parse_frames(self, section: str) -> List[StackFrame]:
        """Collect stack frames in both pytest and native traceback dialects."""
        frames: List[StackFrame] = []
        for raw_line in section.splitlines():
            line = raw_line.strip()

            pytest_frame = _FRAME_PYTEST.match(line)
            if pytest_frame:
                frames.append(
                    StackFrame(
                        file_path=pytest_frame.group("file"),
                        line_number=int(pytest_frame.group("line")),
                        function_name=pytest_frame.group("func"),
                    )
                )
                continue

            native_frame = _FRAME_NATIVE.search(line)
            if native_frame:
                frames.append(
                    StackFrame(
                        file_path=native_frame.group("file"),
                        line_number=int(native_frame.group("line")),
                        function_name=native_frame.group("func"),
                    )
                )
        return frames

    def _parse_error_location(self, section: str) -> Optional[Tuple[str, int, str]]:
        """Return the last ``file.py:line: ExceptionType`` marker in the section."""
        found: Optional[Tuple[str, int, str]] = None
        for raw_line in section.splitlines():
            match = _ERROR_LOCATION.match(raw_line.strip())
            if match:
                found = (
                    match.group("file"),
                    int(match.group("line")),
                    match.group("exc"),
                )
        return found

    def _parse_exception(self, text: str) -> Optional[Tuple[str, str]]:
        """Return (type, message) from the last exception line in the text."""
        marked: Optional[Tuple[str, str]] = None
        bare: Optional[Tuple[str, str]] = None

        for raw_line in text.splitlines():
            line = raw_line.strip()
            if line.startswith(("FAILED", "ERROR")):
                continue

            match = _EXCEPTION_MARKED.match(line)
            if match:
                marked = (match.group("exc"), match.group("msg").strip())
                continue

            match = _EXCEPTION_BARE.match(line)
            if match:
                bare = (match.group("exc"), match.group("msg").strip())

        # pytest marks the assertion that actually failed with "E"; prefer it.
        return marked or bare

    def _parse_summary_line(self, log_output: str) -> Optional[dict]:
        """Parse the terminal ``FAILED path::test - Error: msg`` summary line."""
        for raw_line in log_output.splitlines():
            match = _SUMMARY_LINE.match(raw_line.strip())
            if match:
                return match.groupdict()
        return None

    def _resolve_failure_site(
        self,
        error_location: Optional[Tuple[str, int, str]],
        frames: List[StackFrame],
        summary: Optional[dict],
    ) -> Tuple[Optional[str], Optional[int]]:
        """Pick the file/line where the defect most likely lives.

        Precedence: pytest's own error-location marker, then the deepest frame that
        is not test code (the defect is usually in the code under test, not in the
        assertion that caught it), then the deepest frame of any kind.
        """
        if error_location:
            return error_location[0], error_location[1]

        for frame in reversed(frames):
            if not self._looks_like_test_path(frame.file_path):
                return frame.file_path, frame.line_number

        if frames:
            return frames[-1].file_path, frames[-1].line_number

        if summary and summary.get("file"):
            return summary["file"], 0

        return None, None

    @staticmethod
    def _looks_like_test_path(file_path: str) -> bool:
        normalized = file_path.replace("\\", "/").lower()
        basename = normalized.rsplit("/", 1)[-1]
        return (
            basename.startswith("test_")
            or basename.endswith("_test.py")
            or "/tests/" in normalized
            or normalized.startswith("tests/")
        )
