"""C/C++: CMake/CTest or Makefile based build and test support."""

import os
import re
import shutil
import subprocess
import tempfile
from typing import List, Optional, Tuple

from fixate.graph.base_parser import BaseLanguageParser
from fixate.graph.cpp_parser import CppParser
from fixate.languages.base import InstallResult, LanguageToolchain, SyntaxIssue, TestSelection
from fixate.localization.parser import ParsedFailure, StackFrame


_COMPILER_ERROR = re.compile(
    r"(?P<file>\S+\.(?:c|cc|cpp|cxx|h|hh|hpp|hxx)):(?P<line>\d+):(?:(?P<col>\d+):)?\s+"
    r"(?P<kind>fatal error|error|warning):\s+(?P<msg>.+)"
)
_GTEST_FAILURE = re.compile(r"^\[\s+FAILED\s+\]\s+(?P<name>[A-Za-z0-9_./:-]+)")
_CTEST_FAIL = re.compile(r"^\s*\d+/\d+\s+Test\s+#\d+:\s+(?P<name>\S+)\s+\.+\*\*\*Failed", re.M)


class CppToolchain(LanguageToolchain):
    name = "cpp"
    extensions = (".c", ".cc", ".cpp", ".cxx", ".h", ".hh", ".hpp", ".hxx")
    manifests = ("CMakeLists.txt", "Makefile", "makefile")
    no_tests_markers = ("No tests were found", "0 tests")

    def __init__(self) -> None:
        self._parser = CppParser()

    def parser(self) -> BaseLanguageParser:
        return self._parser

    def owns_log(self, log: str) -> bool:
        clean = log or ""
        return bool(_COMPILER_ERROR.search(clean) or _GTEST_FAILURE.search(clean) or _CTEST_FAIL.search(clean))

    def parse_failure(self, log: str) -> ParsedFailure:
        clean = log or ""
        compiler = _COMPILER_ERROR.search(clean)
        if compiler:
            return ParsedFailure(
                test_name="c++ build",
                failing_file=compiler.group("file"),
                failing_line=int(compiler.group("line")),
                exception_type="CompilerError",
                exception_message=compiler.group("msg").strip(),
                stack_frames=[
                    StackFrame(
                        file_path=compiler.group("file"),
                        line_number=int(compiler.group("line")),
                        function_name="compile",
                    )
                ],
                raw_traceback=clean,
            )

        test_name = "c++ test"
        for line in clean.splitlines():
            match = _GTEST_FAILURE.match(line.strip())
            if match:
                test_name = match.group("name")
                break
        else:
            match = _CTEST_FAIL.search(clean)
            if match:
                test_name = match.group("name")

        return ParsedFailure(
            test_name=test_name,
            failing_file="",
            failing_line=0,
            exception_type="AssertionError",
            exception_message="C++ test failed",
            stack_frames=[],
            raw_traceback=clean,
        )

    def syntax_error(self, source: str, file_path: str) -> Optional[SyntaxIssue]:
        compiler = shutil.which("g++") or shutil.which("clang++")
        if compiler is None or file_path.lower().endswith((".h", ".hh", ".hpp", ".hxx")):
            return None

        suffix = os.path.splitext(file_path)[1] or ".cpp"
        with tempfile.NamedTemporaryFile("w", suffix=suffix, delete=False, encoding="utf-8") as handle:
            handle.write(source)
            temp_path = handle.name
        try:
            result = subprocess.run(
                [compiler, "-std=c++17", "-fsyntax-only", temp_path],
                capture_output=True,
                text=True,
                timeout=30,
            )
        finally:
            try:
                os.unlink(temp_path)
            except OSError:
                pass

        if result.returncode == 0:
            return None
        match = _COMPILER_ERROR.search(result.stderr or result.stdout or "")
        if match:
            return SyntaxIssue(message=match.group("msg").strip(), line=int(match.group("line")))
        return SyntaxIssue(message=(result.stderr or result.stdout or "C++ syntax error").strip()[:300])

    def has_test_setup(self, repo_dir: str) -> bool:
        return any(os.path.exists(os.path.join(repo_dir, name)) for name in self.manifests)

    def install_dependencies(self, repo_dir: str) -> InstallResult:
        if os.path.exists(os.path.join(repo_dir, "CMakeLists.txt")):
            if shutil.which("cmake") is None:
                return InstallResult(False, "cmake is not available; cannot build C++ project.")
            build_dir = os.path.join(repo_dir, "build")
            configured = self._run(["cmake", "-S", ".", "-B", "build"], repo_dir)
            if configured.returncode != 0:
                return InstallResult(False, self._detail("cmake configure failed", configured))
            built = self._run(["cmake", "--build", "build"], repo_dir)
            if built.returncode != 0:
                return InstallResult(False, self._detail("cmake build failed", built))
            return InstallResult(True, f"Configured and built CMake project in {build_dir}.")

        if os.path.exists(os.path.join(repo_dir, "Makefile")) or os.path.exists(os.path.join(repo_dir, "makefile")):
            if shutil.which("make") is None:
                return InstallResult(False, "make is not available; cannot build C++ project.")
            built = self._run(["make"], repo_dir)
            if built.returncode != 0:
                return InstallResult(False, self._detail("make failed", built))
            return InstallResult(True, "Built Makefile project.")

        return InstallResult(True, "No C++ build manifest present.")

    def test_command(self, workspace_dir: str, target: TestSelection) -> List[str]:
        if os.path.exists(os.path.join(workspace_dir, "CMakeLists.txt")):
            command = ["ctest", "--test-dir", "build", "--output-on-failure"]
            if target.test_name:
                command += ["-R", target.test_name]
            return command
        return ["make", "test"]

    def ran_nothing(self, exit_code: int, output: str) -> bool:
        return self.collected_nothing(output)

    @staticmethod
    def _run(command: List[str], cwd: str):
        return subprocess.run(command, cwd=cwd, capture_output=True, text=True, timeout=600)

    @staticmethod
    def _detail(prefix: str, result) -> str:
        body = f"{result.stdout}\n{result.stderr}".strip()
        return f"{prefix}: {body[:2000]}"
