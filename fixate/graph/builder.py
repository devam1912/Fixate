"""NetworkX directed dependency graph constructor for codebase symbols."""

import os
import logging
from typing import Dict, List, Optional
import networkx as nx

from fixate.graph.base_parser import BaseLanguageParser, CodeSymbol, SymbolType
from fixate.graph.python_parser import PythonASTParser
from fixate.graph.js_stub_parser import JavaScriptTSParser

logger = logging.getLogger(__name__)


class CodebaseGraphBuilder:
    """Constructs and maintains a directed graph of functions, classes, files, and tests.
    
    Nodes represent CodeSymbols; edges represent "calls", "imports", or "tests" relationships.
    """

    def __init__(self, parsers: Optional[List[BaseLanguageParser]] = None):
        self.parsers: List[BaseLanguageParser] = parsers or [
            PythonASTParser(),
            JavaScriptTSParser(),
        ]
        self.graph = nx.DiGraph()
        self.symbols: Dict[str, CodeSymbol] = {}

    def get_parser_for(self, file_path: str) -> Optional[BaseLanguageParser]:
        """Find matching language parser for given file path."""
        for parser in self.parsers:
            if parser.supports_file(file_path):
                return parser
        return None

    def build_from_directory(self, root_dir: str) -> nx.DiGraph:
        """Parse directory tree and construct directed dependency graph.
        
        Args:
            root_dir: Absolute or relative directory path to target repository.
            
        Returns:
            Constructed networkx.DiGraph instance.
        """
        self.graph.clear()
        self.symbols.clear()
        all_symbols: List[CodeSymbol] = []

        # 1. Parse all files in directory tree
        for root, _, files in os.walk(root_dir):
            if any(skip in root for skip in (".git", "__pycache__", "venv", ".venv", "node_modules", "dist", "chroma_db")):
                continue
            for file in files:
                full_path = os.path.normpath(os.path.join(root, file))
                parser = self.get_parser_for(full_path)
                if parser:
                    file_symbols = parser.parse_file(full_path)
                    all_symbols.extend(file_symbols)

        # 2. Add nodes to graph
        name_to_symbol_id: Dict[str, str] = {}
        for sym in all_symbols:
            self.symbols[sym.id] = sym
            name_to_symbol_id[sym.name] = sym.id
            self.graph.add_node(
                sym.id,
                name=sym.name,
                symbol_type=sym.symbol_type.value,
                file_path=sym.file_path,
                start_line=sym.start_line,
                end_line=sym.end_line,
                code=sym.code,
                docstring=sym.docstring or "",
                is_test=sym.is_test,
            )

        # 3. Add edges (calls, imports, and test relationships)
        for sym in all_symbols:
            for call_target in sym.calls:
                if call_target in name_to_symbol_id:
                    target_id = name_to_symbol_id[call_target]
                    if target_id != sym.id:
                        # Edge: caller -> callee
                        self.graph.add_edge(sym.id, target_id, relation="calls")
                        
                        # If sym is a test, mark edge relation as 'tests'
                        if sym.is_test:
                            self.graph.add_edge(sym.id, target_id, relation="tests")

        logger.info(f"Built codebase graph: {self.graph.number_of_nodes()} nodes, {self.graph.number_of_edges()} edges")
        return self.graph

    def get_symbol(self, symbol_id: str) -> Optional[CodeSymbol]:
        """Retrieve symbol metadata model by unique symbol ID."""
        return self.symbols.get(symbol_id)
