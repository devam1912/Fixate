"""Lightweight C/C++ symbol extraction.

This parser intentionally stays conservative. It is not a full C++ frontend, but
it gives Fixate enough structure to localize ordinary functions, methods, and
test cases in small CMake/Make projects without adding a compiler dependency to
the graph layer.
"""

import os
import re
from typing import List

from fixate.graph.base_parser import BaseLanguageParser, CodeSymbol, SymbolType


_FUNCTION = re.compile(
    r"^\s*(?:(?:inline|static|constexpr|virtual|friend|extern)\s+)*"
    r"(?:[\w:<>,~*&\s]+\s+)?(?P<name>[A-Za-z_]\w*(?:::[A-Za-z_]\w*)?)"
    r"\s*\([^;{}]*\)\s*(?:const\s*)?(?:noexcept\s*)?(?:override\s*)?\{"
)
_CALL = re.compile(r"\b([A-Za-z_]\w*)\s*\(")
_TEST_MACRO = re.compile(r"^\s*(TEST|TEST_F|TEST_P|SCENARIO|TEMPLATE_TEST_CASE)\s*\(")


class CppParser(BaseLanguageParser):
    extensions = (".c", ".cc", ".cpp", ".cxx", ".h", ".hh", ".hpp", ".hxx")

    def supports_file(self, file_path: str) -> bool:
        return file_path.lower().endswith(self.extensions)

    def parse_file(self, file_path: str) -> List[CodeSymbol]:
        try:
            with open(file_path, "r", encoding="utf-8", errors="replace") as handle:
                return self.parse_code(handle.read(), file_path=file_path)
        except OSError:
            return []

    def parse_code(self, code_string: str, file_path: str = "virtual.cpp") -> List[CodeSymbol]:
        lines = code_string.splitlines()
        symbols: List[CodeSymbol] = []

        for index, line in enumerate(lines):
            match = _FUNCTION.match(line)
            test_match = _TEST_MACRO.match(line)
            if not match and not test_match:
                continue

            name = self._test_name(line) if test_match else match.group("name").split("::")[-1]
            start = index + 1
            end = self._find_block_end(lines, index)
            snippet = "\n".join(lines[index:end])
            calls = [
                call
                for call in _CALL.findall(snippet)
                if call not in {"if", "for", "while", "switch", "return", "sizeof", "TEST", "TEST_F", "TEST_P"}
            ]
            is_test = bool(test_match) or name.lower().startswith("test")

            symbols.append(
                CodeSymbol(
                    id=f"{os.path.normpath(file_path)}::{name}",
                    name=name,
                    symbol_type=SymbolType.TEST if is_test else SymbolType.FUNCTION,
                    file_path=os.path.normpath(file_path),
                    start_line=start,
                    end_line=end,
                    code=snippet,
                    calls=calls,
                    imports=[],
                    is_test=is_test,
                )
            )

        return symbols

    @staticmethod
    def _find_block_end(lines: List[str], start_index: int) -> int:
        depth = 0
        seen_open = False
        for index in range(start_index, len(lines)):
            depth += lines[index].count("{")
            if "{" in lines[index]:
                seen_open = True
            depth -= lines[index].count("}")
            if seen_open and depth <= 0:
                return index + 1
        return min(len(lines), start_index + 1)

    @staticmethod
    def _test_name(line: str) -> str:
        inside = line.split("(", 1)[1].rsplit(")", 1)[0]
        parts = [part.strip().strip('"') for part in inside.split(",") if part.strip()]
        return ".".join(parts[:2]) if parts else "cpp_test"
