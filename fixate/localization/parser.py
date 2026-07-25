"""Pytest and Python stack trace log parser."""

import re
import logging
from typing import List
from pydantic import BaseModel, Field

logger = logging.getLogger(__name__)


class StackFrame(BaseModel):
    file_path: str
    line_number: int
    function_name: str


class ParsedFailure(BaseModel):
    """Structured representation of a parsed CI build/test failure log."""
    failing_file: str = Field(..., description="File where failure occurred or assertion failed")
    failing_line: int = Field(..., description="Line number of failure")
    exception_type: str = Field(..., description="Exception class name, e.g. TypeError, AssertionError")
    exception_message: str = Field(..., description="Failure message or assertion error text")
    test_name: str = Field(..., description="Name of the executing test")
    raw_traceback: str = Field(..., description="Complete raw traceback log")
    stack_frames: List[StackFrame] = Field(default_factory=list, description="Extracted stack frames")


class FailureTracebackParser:
    """Parses raw pytest console output or Python stack traces into structured failure objects."""

    def parse_log(self, log_output: str) -> ParsedFailure:
        """Parse raw log text into a structured ParsedFailure object."""
        lines = log_output.splitlines()

        failing_file = "unknown.py"
        failing_line = 1
        exception_type = "AssertionError"
        exception_message = "Test failure detected"
        test_name = "test_unknown"
        stack_frames: List[StackFrame] = []

        # 1. Look for Pytest FAILED test header, e.g. "FAILED tests/test_app.py::test_tax - AssertionError: ..."
        pytest_failed_pattern = re.compile(r'FAILED\s+([^\s:]+)::([^\s\-]+)(?:\s*-\s*([A-Za-z0-9_]+Error|\w+):\s*(.*))?')
        for line in lines:
            m = pytest_failed_pattern.search(line)
            if m:
                failing_file = m.group(1)
                test_name = m.group(2)
                if m.group(3):
                    exception_type = m.group(3)
                if m.group(4):
                    exception_message = m.group(4).strip()

        # 2. Extract stack frames from standard Python Traceback lines OR Pytest frame lines
        # Pattern A: File "path/to/file.py", line 42, in function_name
        frame_pattern_std = re.compile(r'File\s+["\']([^"\']+)["\'],\s+line\s+(\d+),\s+in\s+([A-Za-z0-9_]+)')
        # Pattern B: path/to/file.py:42: in function_name
        frame_pattern_pytest = re.compile(r'^([^\s:]+\.py):(\d+):\s+in\s+([A-Za-z0-9_]+)')

        for line in lines:
            line_str = line.strip()
            m_std = frame_pattern_std.search(line_str)
            if m_std:
                fp = m_std.group(1)
                ln = int(m_std.group(2))
                fn = m_std.group(3)
                stack_frames.append(StackFrame(file_path=fp, line_number=ln, function_name=fn))
                continue

            m_pytest = frame_pattern_pytest.search(line_str)
            if m_pytest:
                fp = m_pytest.group(1)
                ln = int(m_pytest.group(2))
                fn = m_pytest.group(3)
                stack_frames.append(StackFrame(file_path=fp, line_number=ln, function_name=fn))

        # If stack frames found, set immediate failure point from the last frame
        if stack_frames:
            last_frame = stack_frames[-1]
            failing_file = last_frame.file_path
            failing_line = last_frame.line_number
            if test_name == "test_unknown" and stack_frames[0].function_name.startswith("test_"):
                test_name = stack_frames[0].function_name

        # 3. Extract Exception line if not yet captured
        exc_pattern = re.compile(r'^([A-Za-z0-9_]+Error|AssertionError|KeyError|TypeError|ValueError):\s*(.*)$')
        for line in reversed(lines):
            m_exc = exc_pattern.search(line.strip())
            if m_exc:
                exception_type = m_exc.group(1)
                exception_message = m_exc.group(2)
                break

        return ParsedFailure(
            failing_file=failing_file,
            failing_line=failing_line,
            exception_type=exception_type,
            exception_message=exception_message,
            test_name=test_name,
            raw_traceback=log_output,
            stack_frames=stack_frames,
        )
