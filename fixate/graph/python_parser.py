"""Python symbol extraction for the dependency graph.

Symbols are identified by their *qualified* name -- ``file.py::Class.method``, not
``file.py::method``. The distinction is load-bearing: the graph builder stores
symbols in a dict keyed by id, so unqualified ids silently discard every method
but the last when a file defines the same method name on several classes. A
handler-chain module where each class implements ``process`` would lose all but
one of them, and localization would then be searching a graph that no longer
contains the defect.

Extraction walks with an explicit scope stack rather than ``ast.walk``, which
flattens nesting and cannot tell a method from a module-level function.
"""

import ast
import logging
import os
from typing import List, Optional, Set

from fixate.graph.base_parser import BaseLanguageParser, CodeSymbol, SymbolType

logger = logging.getLogger(__name__)


class _CallCollector(ast.NodeVisitor):
    """Collect called names within one symbol, without descending into nested defs.

    Nested functions own their own calls; attributing them to the enclosing symbol
    would create call edges that do not exist.
    """

    def __init__(self, skip: Optional[ast.AST] = None):
        self.calls: Set[str] = set()
        self._root = skip

    def visit_Call(self, node: ast.Call) -> None:
        func = node.func
        if isinstance(func, ast.Name):
            self.calls.add(func.id)
        elif isinstance(func, ast.Attribute):
            self.calls.add(func.attr)
        self.generic_visit(node)

    def _skip_nested(self, node: ast.AST) -> None:
        if node is self._root:
            self.generic_visit(node)

    visit_FunctionDef = _skip_nested
    visit_AsyncFunctionDef = _skip_nested
    visit_ClassDef = _skip_nested


class PythonASTParser(BaseLanguageParser):
    """Extracts functions, classes, and methods with qualified identifiers."""

    def supports_file(self, file_path: str) -> bool:
        return file_path.endswith(".py")

    def parse_file(self, file_path: str) -> List[CodeSymbol]:
        if not os.path.exists(file_path):
            logger.warning("File path does not exist: %s", file_path)
            return []
        try:
            with open(file_path, "r", encoding="utf-8", errors="replace") as handle:
                source = handle.read()
        except OSError as exc:
            logger.error("Error reading file %s: %s", file_path, exc)
            return []
        return self.parse_code(source, file_path=file_path)

    def parse_code(self, code_string: str, file_path: str = "virtual.py") -> List[CodeSymbol]:
        try:
            tree = ast.parse(code_string, filename=file_path)
        except SyntaxError as exc:
            logger.error("AST parsing failed for %s: %s", file_path, exc)
            return []

        lines = code_string.splitlines()
        imports = self._module_imports(tree)
        is_test_file = self._is_test_file(file_path)

        symbols: List[CodeSymbol] = []
        self._visit_body(
            body=tree.body,
            scope=[],
            lines=lines,
            file_path=file_path,
            imports=imports,
            is_test_file=is_test_file,
            symbols=symbols,
        )
        return symbols

    def _visit_body(
        self,
        body: List[ast.stmt],
        scope: List[str],
        lines: List[str],
        file_path: str,
        imports: List[str],
        is_test_file: bool,
        symbols: List[CodeSymbol],
    ) -> None:
        """Walk one block, tracking the enclosing class scope."""
        for node in body:
            if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
                symbols.append(
                    self._build_symbol(
                        node=node,
                        scope=scope,
                        lines=lines,
                        file_path=file_path,
                        imports=imports,
                        is_test_file=is_test_file,
                        # A def inside a class is a method; at module level it is a
                        # function. SymbolType.METHOD was previously never emitted,
                        # so the localization scorer could never match on it.
                        symbol_type=SymbolType.METHOD if scope else SymbolType.FUNCTION,
                    )
                )
                # Recurse so nested helpers become symbols in their own right.
                self._visit_body(
                    node.body, scope + [node.name], lines, file_path, imports, is_test_file, symbols
                )

            elif isinstance(node, ast.ClassDef):
                symbols.append(
                    self._build_symbol(
                        node=node,
                        scope=scope,
                        lines=lines,
                        file_path=file_path,
                        imports=imports,
                        is_test_file=is_test_file,
                        symbol_type=SymbolType.CLASS,
                    )
                )
                self._visit_body(
                    node.body, scope + [node.name], lines, file_path, imports, is_test_file, symbols
                )

    def _build_symbol(
        self,
        node: ast.AST,
        scope: List[str],
        lines: List[str],
        file_path: str,
        imports: List[str],
        is_test_file: bool,
        symbol_type: SymbolType,
    ) -> CodeSymbol:
        name = getattr(node, "name", "<anonymous>")
        qualified = ".".join(scope + [name])

        start_line = getattr(node, "lineno", 1)
        end_line = getattr(node, "end_lineno", start_line)
        code = "\n".join(lines[start_line - 1 : end_line])

        is_test = is_test_file or name.startswith("test_") or name.startswith("Test")

        calls: List[str] = []
        if symbol_type is not SymbolType.CLASS:
            collector = _CallCollector(skip=node)
            collector.visit(node)
            calls = sorted(collector.calls)

        return CodeSymbol(
            id=f"{file_path}::{qualified}",
            name=name,
            symbol_type=SymbolType.TEST if is_test else symbol_type,
            file_path=file_path,
            start_line=start_line,
            end_line=end_line,
            code=code,
            docstring=ast.get_docstring(node) if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef, ast.ClassDef)) else None,
            calls=calls,
            imports=imports,
            is_test=is_test,
        )

    @staticmethod
    def _module_imports(tree: ast.Module) -> List[str]:
        names: Set[str] = set()
        for node in ast.iter_child_nodes(tree):
            if isinstance(node, ast.Import):
                names.update(alias.name for alias in node.names)
            elif isinstance(node, ast.ImportFrom):
                module = node.module or ""
                names.update(
                    f"{module}.{alias.name}" if module else alias.name for alias in node.names
                )
        return sorted(names)

    @staticmethod
    def _is_test_file(file_path: str) -> bool:
        base = os.path.basename(file_path)
        return base.startswith("test_") or base.endswith("_test.py")
