"""Python AST parser implementing BaseLanguageParser for symbol extraction."""

import ast
import os
import logging
from typing import List, Optional, Set

from fixate.graph.base_parser import BaseLanguageParser, CodeSymbol, SymbolType

logger = logging.getLogger(__name__)


class CallVisitor(ast.NodeVisitor):
    """AST node visitor to extract function call names within a scope."""

    def __init__(self):
        self.calls: Set[str] = set()

    def visit_Call(self, node: ast.Call):
        if isinstance(node.func, ast.Name):
            self.calls.add(node.func.id)
        elif isinstance(node.func, ast.Attribute):
            self.calls.add(node.func.attr)
        self.generic_visit(node)


class PythonASTParser(BaseLanguageParser):
    """Python AST parser for extracting functions, classes, calls, imports, and tests."""

    def supports_file(self, file_path: str) -> bool:
        return file_path.endswith(".py")

    def parse_file(self, file_path: str) -> List[CodeSymbol]:
        if not os.path.exists(file_path):
            logger.warning(f"File path does not exist: {file_path}")
            return []
        try:
            with open(file_path, "r", encoding="utf-8") as f:
                code_content = f.read()
            return self.parse_code(code_content, file_path=file_path)
        except Exception as exc:
            logger.error(f"Error reading file {file_path}: {exc}")
            return []

    def parse_code(self, code_string: str, file_path: str = "virtual.py") -> List[CodeSymbol]:
        symbols: List[CodeSymbol] = []
        try:
            tree = ast.parse(code_string, filename=file_path)
        except Exception as parse_err:
            logger.error(f"AST parsing failed for {file_path}: {parse_err}")
            return symbols

        lines = code_string.splitlines()
        
        # Gather top-level imports
        file_imports: Set[str] = set()
        for node in ast.iter_child_nodes(tree):
            if isinstance(node, ast.Import):
                for alias in node.names:
                    file_imports.add(alias.name)
            elif isinstance(node, ast.ImportFrom):
                module = node.module or ""
                for alias in node.names:
                    file_imports.add(f"{module}.{alias.name}" if module else alias.name)

        is_test_file = "test_" in os.path.basename(file_path) or os.path.basename(file_path).endswith("_test.py")

        for node in ast.walk(tree):
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                start_line = getattr(node, "lineno", 1)
                end_line = getattr(node, "end_lineno", start_line)
                code_snippet = "\n".join(lines[start_line - 1 : end_line])
                docstring = ast.get_docstring(node)

                # Extract calls inside function
                call_visitor = CallVisitor()
                call_visitor.visit(node)

                name = node.name
                is_test = is_test_file or name.startswith("test_")
                sym_type = SymbolType.TEST if is_test else SymbolType.FUNCTION

                symbol_id = f"{file_path}::{name}"
                symbols.append(
                    CodeSymbol(
                        id=symbol_id,
                        name=name,
                        symbol_type=sym_type,
                        file_path=file_path,
                        start_line=start_line,
                        end_line=end_line,
                        code=code_snippet,
                        docstring=docstring,
                        calls=list(call_visitor.calls),
                        imports=list(file_imports),
                        is_test=is_test,
                    )
                )

            elif isinstance(node, ast.ClassDef):
                start_line = getattr(node, "lineno", 1)
                end_line = getattr(node, "end_lineno", start_line)
                code_snippet = "\n".join(lines[start_line - 1 : end_line])
                docstring = ast.get_docstring(node)

                name = node.name
                is_test = is_test_file or name.startswith("Test")
                sym_type = SymbolType.TEST if is_test else SymbolType.CLASS

                symbol_id = f"{file_path}::{name}"
                symbols.append(
                    CodeSymbol(
                        id=symbol_id,
                        name=name,
                        symbol_type=sym_type,
                        file_path=file_path,
                        start_line=start_line,
                        end_line=end_line,
                        code=code_snippet,
                        docstring=docstring,
                        calls=[],
                        imports=list(file_imports),
                        is_test=is_test,
                    )
                )

        return symbols
