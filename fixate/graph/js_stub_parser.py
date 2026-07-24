"""JavaScript and TypeScript language parser extension stub implementing BaseLanguageParser."""

import os
import re
import logging
from typing import List

from fixate.graph.base_parser import BaseLanguageParser, CodeSymbol, SymbolType

logger = logging.getLogger(__name__)


class JavaScriptTSParser(BaseLanguageParser):
    """Extension parser stub for JavaScript (.js, .jsx) and TypeScript (.ts, .tsx) files.
    
    Note: Designed to plug into ts-morph or @babel/parser node bridge for full AST parsing.
    Includes fallback regex-based symbol extractor for JS/TS functions and tests.
    """

    def supports_file(self, file_path: str) -> bool:
        return file_path.endswith((".js", ".jsx", ".ts", ".tsx"))

    def parse_file(self, file_path: str) -> List[CodeSymbol]:
        if not os.path.exists(file_path):
            return []
        try:
            with open(file_path, "r", encoding="utf-8") as f:
                code_content = f.read()
            return self.parse_code(code_content, file_path=file_path)
        except Exception as exc:
            logger.error(f"Failed reading JS/TS file {file_path}: {exc}")
            return []

    def parse_code(self, code_string: str, file_path: str = "virtual.ts") -> List[CodeSymbol]:
        symbols: List[CodeSymbol] = []
        lines = code_string.splitlines()
        
        # Regex patterns for function definitions and describe/test blocks
        func_pattern = re.compile(r'(?:export\s+)?(?:async\s+)?function\s+([A-Za-z0-9_]+)\s*\(')
        const_func_pattern = re.compile(r'(?:export\s+)?const\s+([A-Za-z0-9_]+)\s*=\s*(?:async\s*)?\(')
        test_pattern = re.compile(r'(?:it|test|describe)\s*\(\s*[\'"`]([^\'"`]+)[\'"`]')

        for idx, line in enumerate(lines, start=1):
            m_func = func_pattern.search(line) or const_func_pattern.search(line)
            if m_func:
                name = m_func.group(1)
                is_test = "test" in file_path.lower() or name.startswith("test")
                sym_id = f"{file_path}::{name}"
                symbols.append(
                    CodeSymbol(
                        id=sym_id,
                        name=name,
                        symbol_type=SymbolType.TEST if is_test else SymbolType.FUNCTION,
                        file_path=file_path,
                        start_line=idx,
                        end_line=min(idx + 10, len(lines)),
                        code=line,
                        docstring=None,
                        calls=[],
                        imports=[],
                        is_test=is_test,
                    )
                )
            
            m_test = test_pattern.search(line)
            if m_test:
                test_name = m_test.group(1)
                sym_id = f"{file_path}::test::{test_name}"
                symbols.append(
                    CodeSymbol(
                        id=sym_id,
                        name=test_name,
                        symbol_type=SymbolType.TEST,
                        file_path=file_path,
                        start_line=idx,
                        end_line=min(idx + 15, len(lines)),
                        code=line,
                        docstring=None,
                        calls=[],
                        imports=[],
                        is_test=True,
                    )
                )

        return symbols
