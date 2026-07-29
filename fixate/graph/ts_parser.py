"""JavaScript and TypeScript symbol extraction via tree-sitter.

Replaces a line-regex stub that recorded a single line as a symbol's source, guessed
its end line, and never populated calls -- so JS symbols entered the graph with no
edges and reached the patch generator with one line of context.

tree-sitter gives real spans, real call edges, and error-tolerant parsing (partial
or invalid syntax still yields a tree), which also makes it usable as the syntax
gate for patched JS the way ``ast.parse`` is for Python.

Identifiers are qualified as ``file.ts::Class.method`` to match the Python parser;
unqualified ids collapse same-named methods in the graph builder's id-keyed store.
"""

import logging
import os
from typing import Dict, List, Optional, Set, Tuple

from fixate.graph.base_parser import BaseLanguageParser, CodeSymbol, SymbolType

logger = logging.getLogger(__name__)

_TEST_CALLEES = {"describe", "it", "test", "suite", "bench"}

# Node types that introduce a named, addressable unit of code.
_FUNCTION_NODES = {"function_declaration", "generator_function_declaration", "function_expression"}
_METHOD_NODES = {"method_definition"}
_CLASS_NODES = {"class_declaration", "class"}


class _Grammars:
    """Lazily loaded tree-sitter languages, cached per process.

    Grammar construction is expensive relative to parsing, and the graph builder
    re-parses whole repositories, so this must not happen per file.
    """

    _cache: Dict[str, object] = {}
    _unavailable = False

    @classmethod
    def get(cls, extension: str):
        if cls._unavailable:
            return None

        key = cls._key_for(extension)
        if key in cls._cache:
            return cls._cache[key]

        try:
            from tree_sitter import Language, Parser

            if key == "tsx":
                import tree_sitter_typescript as ts

                language = Language(ts.language_tsx())
            elif key == "typescript":
                import tree_sitter_typescript as ts

                language = Language(ts.language_typescript())
            else:
                import tree_sitter_javascript as js

                language = Language(js.language())

            parser = Parser(language)
            cls._cache[key] = parser
            return parser
        except Exception as exc:
            logger.warning(
                "tree-sitter grammars unavailable (%s); JavaScript/TypeScript symbols "
                "will not be extracted. Install tree-sitter, tree-sitter-javascript, "
                "and tree-sitter-typescript.",
                exc,
            )
            cls._unavailable = True
            return None

    @staticmethod
    def _key_for(extension: str) -> str:
        if extension == ".tsx":
            return "tsx"
        if extension == ".ts":
            return "typescript"
        return "javascript"


class TypeScriptParser(BaseLanguageParser):
    """Extracts functions, classes, methods, and tests from JS/TS sources."""

    extensions = (".js", ".jsx", ".mjs", ".cjs", ".ts", ".tsx", ".mts", ".cts")

    def supports_file(self, file_path: str) -> bool:
        return file_path.lower().endswith(self.extensions)

    def parse_file(self, file_path: str) -> List[CodeSymbol]:
        if not os.path.exists(file_path):
            return []
        try:
            with open(file_path, "r", encoding="utf-8", errors="replace") as handle:
                source = handle.read()
        except OSError as exc:
            logger.error("Error reading %s: %s", file_path, exc)
            return []
        return self.parse_code(source, file_path=file_path)

    def parse_code(self, code_string: str, file_path: str = "virtual.ts") -> List[CodeSymbol]:
        parser = _Grammars.get(os.path.splitext(file_path)[1].lower())
        if parser is None:
            return []

        source_bytes = code_string.encode("utf-8")
        try:
            tree = parser.parse(source_bytes)
        except Exception as exc:
            logger.error("tree-sitter parse failed for %s: %s", file_path, exc)
            return []

        imports = self._collect_imports(tree.root_node, source_bytes)
        is_test_file = self._is_test_file(file_path)

        symbols: List[CodeSymbol] = []
        self._walk(
            node=tree.root_node,
            scope=[],
            source=source_bytes,
            file_path=file_path,
            imports=imports,
            is_test_file=is_test_file,
            symbols=symbols,
        )
        return symbols

    def _walk(
        self,
        node,
        scope: List[str],
        source: bytes,
        file_path: str,
        imports: List[str],
        is_test_file: bool,
        symbols: List[CodeSymbol],
    ) -> None:
        for child in node.named_children:
            kind = child.type

            if kind in _CLASS_NODES:
                name = self._name_of(child, source) or "<anonymous class>"
                symbols.append(
                    self._symbol(child, scope, name, SymbolType.CLASS, source, file_path, imports, is_test_file)
                )
                body = child.child_by_field_name("body")
                if body is not None:
                    self._walk(body, scope + [name], source, file_path, imports, is_test_file, symbols)
                continue

            if kind in _METHOD_NODES:
                name = self._name_of(child, source) or "<anonymous method>"
                symbols.append(
                    self._symbol(child, scope, name, SymbolType.METHOD, source, file_path, imports, is_test_file)
                )
                continue

            if kind in _FUNCTION_NODES:
                name = self._name_of(child, source)
                if name:
                    symbols.append(
                        self._symbol(child, scope, name, SymbolType.FUNCTION, source, file_path, imports, is_test_file)
                    )
                    continue

            # `const handler = (x) => ...` and `const f = function () {}` are the
            # dominant declaration style in modern JS; without this they would be
            # invisible to the graph.
            if kind in ("lexical_declaration", "variable_declaration"):
                for declarator in child.named_children:
                    if declarator.type != "variable_declarator":
                        continue
                    value = declarator.child_by_field_name("value")
                    if value is None or value.type not in ("arrow_function", "function_expression", "function"):
                        continue
                    name = self._text(declarator.child_by_field_name("name"), source)
                    if name:
                        symbols.append(
                            self._symbol(child, scope, name, SymbolType.FUNCTION, source, file_path, imports, is_test_file)
                        )
                continue

            # Test blocks: describe("...", ...) / it("...", ...)
            if kind == "expression_statement":
                block = self._test_block(child, source)
                if block is not None:
                    test_name, body = block
                    symbols.append(
                        self._symbol(
                            child, scope, test_name, SymbolType.TEST, source, file_path, imports, True
                        )
                    )
                    # Recurse into the callback so nested `it` cases become symbols
                    # of their own. Verification targets individual cases by name,
                    # so a suite recorded only as its `describe` label cannot be run.
                    if body is not None:
                        self._walk(
                            body, scope + [test_name], source, file_path, imports, True, symbols
                        )
                    continue

            self._walk(child, scope, source, file_path, imports, is_test_file, symbols)

    def _symbol(
        self,
        node,
        scope: List[str],
        name: str,
        symbol_type: SymbolType,
        source: bytes,
        file_path: str,
        imports: List[str],
        is_test_file: bool,
    ) -> CodeSymbol:
        qualified = ".".join(scope + [name])
        is_test = is_test_file or symbol_type is SymbolType.TEST

        return CodeSymbol(
            id=f"{file_path}::{qualified}",
            name=name,
            symbol_type=SymbolType.TEST if is_test else symbol_type,
            file_path=file_path,
            # tree-sitter rows are 0-based; CodeSymbol line numbers are 1-based.
            start_line=node.start_point[0] + 1,
            end_line=node.end_point[0] + 1,
            code=self._text(node, source),
            docstring=None,
            calls=sorted(self._collect_calls(node, source)),
            imports=imports,
            is_test=is_test,
        )

    def _collect_calls(self, node, source: bytes) -> Set[str]:
        """Collect callee names inside a symbol, without descending into nested defs."""
        found: Set[str] = set()

        def visit(current, is_root: bool) -> None:
            if not is_root and current.type in (_FUNCTION_NODES | _METHOD_NODES | _CLASS_NODES):
                return
            if current.type == "call_expression":
                function = current.child_by_field_name("function")
                if function is not None:
                    if function.type == "identifier":
                        found.add(self._text(function, source))
                    elif function.type == "member_expression":
                        prop = function.child_by_field_name("property")
                        if prop is not None:
                            found.add(self._text(prop, source))
            for child in current.named_children:
                visit(child, False)

        visit(node, True)
        return {name for name in found if name and name not in _TEST_CALLEES}

    def _collect_imports(self, root, source: bytes) -> List[str]:
        names: Set[str] = set()
        for node in self._descend(root):
            if node.type == "import_statement":
                source_node = node.child_by_field_name("source")
                if source_node is not None:
                    names.add(self._text(source_node, source).strip("'\"`"))
            elif node.type == "call_expression":
                function = node.child_by_field_name("function")
                if function is not None and self._text(function, source) == "require":
                    args = node.child_by_field_name("arguments")
                    if args is not None and args.named_children:
                        names.add(self._text(args.named_children[0], source).strip("'\"`"))
        return sorted(names)

    def _test_block(self, statement, source: bytes) -> Optional[Tuple[str, Optional[object]]]:
        """Return (label, callback body) if this statement is a describe/it block.

        The body is handed back so the caller can descend into nested cases; the
        label alone is not enough, because runners select individual tests by name.
        """
        for node in self._descend(statement):
            if node.type != "call_expression":
                continue
            function = node.child_by_field_name("function")
            if function is None:
                continue
            # `it.each(...)` and `describe.skip(...)` still name a test block.
            callee = self._text(function, source).split(".")[0]
            if callee not in _TEST_CALLEES:
                continue
            args = node.child_by_field_name("arguments")
            if args is None or not args.named_children:
                continue

            first = args.named_children[0]
            if first.type not in ("string", "template_string"):
                continue

            body = None
            for argument in args.named_children[1:]:
                if argument.type in ("arrow_function", "function_expression", "function"):
                    body = argument.child_by_field_name("body")
                    break

            return self._text(first, source).strip("'\"`"), body
        return None

    def _descend(self, node):
        yield node
        for child in node.named_children:
            yield from self._descend(child)

    @staticmethod
    def _text(node, source: bytes) -> str:
        if node is None:
            return ""
        return source[node.start_byte : node.end_byte].decode("utf-8", errors="replace")

    def _name_of(self, node, source: bytes) -> Optional[str]:
        name_node = node.child_by_field_name("name")
        return self._text(name_node, source) if name_node is not None else None

    @staticmethod
    def _is_test_file(file_path: str) -> bool:
        normalized = file_path.replace("\\", "/").lower()
        base = normalized.rsplit("/", 1)[-1]
        return (
            ".test." in base
            or ".spec." in base
            or "/__tests__/" in normalized
            or normalized.startswith("__tests__/")
        )


def has_syntax_error(source: str, file_path: str) -> Optional[Tuple[str, int]]:
    """Return (message, line) if the source does not parse cleanly, else None.

    tree-sitter always produces a tree, marking unparseable regions with ERROR and
    MISSING nodes, so a well-formedness check means searching for those rather than
    catching an exception.
    """
    parser = _Grammars.get(os.path.splitext(file_path)[1].lower())
    if parser is None:
        return None  # Cannot validate without grammars; do not block the patch.

    tree = parser.parse(source.encode("utf-8"))
    if not tree.root_node.has_error:
        return None

    stack = [tree.root_node]
    while stack:
        node = stack.pop()
        if node.type == "ERROR" or node.is_missing:
            label = "missing syntax" if node.is_missing else "unexpected syntax"
            return (label, node.start_point[0] + 1)
        stack.extend(node.children)

    return ("invalid syntax", 1)
