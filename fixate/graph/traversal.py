"""Graph traversal utilities for backward failure tracing and call graph queries."""

from typing import List, Set, Optional
import networkx as nx
from fixate.graph.base_parser import CodeSymbol
from fixate.graph.builder import CodebaseGraphBuilder


class GraphTraversal:
    """Traversal helper class for analyzing upstream callers, downstream callees, and test associations."""

    def __init__(self, builder: CodebaseGraphBuilder):
        self.builder = builder
        self.graph = builder.graph

    def find_symbol_by_file_line(self, file_path: str, line_number: int) -> Optional[CodeSymbol]:
        """Find the enclosing CodeSymbol at a given file path and line number."""
        norm_target = file_path.replace("\\", "/").lower()

        for sym_id, sym in self.builder.symbols.items():
            norm_sym_file = sym.file_path.replace("\\", "/").lower()
            if norm_sym_file.endswith(norm_target) or norm_target.endswith(norm_sym_file):
                if sym.start_line <= line_number <= sym.end_line:
                    return sym

        # Fallback: match by file basename
        target_base = norm_target.split("/")[-1]
        for sym_id, sym in self.builder.symbols.items():
            norm_sym_file = sym.file_path.replace("\\", "/").lower()
            if norm_sym_file.split("/")[-1] == target_base:
                if sym.start_line <= line_number <= sym.end_line:
                    return sym

        return None

    def get_callers(self, symbol_id: str) -> List[CodeSymbol]:
        """Retrieve upstream functions/classes that call the given symbol (predecessors)."""
        if not self.graph.has_node(symbol_id):
            return []
        preds = self.graph.predecessors(symbol_id)
        return [self.builder.symbols[p] for p in preds if p in self.builder.symbols]

    def get_callees(self, symbol_id: str) -> List[CodeSymbol]:
        """Retrieve downstream functions/classes called by the given symbol (successors)."""
        if not self.graph.has_node(symbol_id):
            return []
        succs = self.graph.successors(symbol_id)
        return [self.builder.symbols[s] for s in succs if s in self.builder.symbols]

    def get_tests_for_symbol(self, symbol_id: str) -> List[CodeSymbol]:
        """Find test symbols that exercise or call the given target symbol."""
        callers = self.get_callers(symbol_id)
        return [c for c in callers if c.is_test]

    def backward_trace(self, start_symbol_id: str, max_depth: int = 3) -> List[CodeSymbol]:
        """Walk backward through call hierarchy from start symbol up to max_depth.
        
        Args:
            start_symbol_id: Failure entry symbol ID.
            max_depth: Maximum recursion depth for upstream traversal.
            
        Returns:
            Ranked list of suspect candidate CodeSymbols encountered along the path.
        """
        visited: Set[str] = set()
        candidates: List[CodeSymbol] = []

        def _walk(curr_id: str, current_depth: int):
            if current_depth > max_depth or curr_id in visited:
                return
            visited.add(curr_id)

            if curr_id in self.builder.symbols:
                sym = self.builder.symbols[curr_id]
                # Non-test code symbols are suspect root cause candidates
                if not sym.is_test and curr_id != start_symbol_id:
                    candidates.append(sym)

            # Traverse upstream callers
            for caller in self.get_callers(curr_id):
                _walk(caller.id, current_depth + 1)
            
            # Also traverse callees (downstream functions)
            for callee in self.get_callees(curr_id):
                _walk(callee.id, current_depth + 1)

        # Include start symbol if it's non-test code
        if start_symbol_id in self.builder.symbols:
            start_sym = self.builder.symbols[start_symbol_id]
            if not start_sym.is_test:
                candidates.append(start_sym)

        _walk(start_symbol_id, 0)
        return candidates
