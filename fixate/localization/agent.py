"""Failure Localization Agent combining AST graph traversal with LLM reasoning."""

import logging
from typing import List, Optional
from pydantic import BaseModel, Field

from fixate.graph.builder import CodebaseGraphBuilder
from fixate.graph.traversal import GraphTraversal
from fixate.graph.base_parser import CodeSymbol
from fixate.localization.parser import ParsedFailure
from fixate.llm.base import BaseLLMProvider
from fixate.llm.factory import get_llm_provider

logger = logging.getLogger(__name__)


class SuspectFunction(BaseModel):
    symbol_id: str = Field(..., description="Unique symbol ID of suspect function")
    file_path: str = Field(..., description="File path containing suspect function")
    name: str = Field(..., description="Function or class name")
    code: str = Field(..., description="Full source code snippet of suspect candidate")
    rank: int = Field(..., description="1-indexed plausibility rank (1 = highest suspect)")
    plausibility_reason: str = Field(..., description="LLM explanation of why this function is the root cause")


class LocalizationResult(BaseModel):
    failing_test: str
    exception_type: str
    exception_message: str
    suspect_functions: List[SuspectFunction]


class FailureLocalizationAgent:
    """Localization Agent that uses AST dependency graph traversal to gather candidate functions,
    then uses an LLM to rank plausibility of root causes.
    """

    def __init__(
        self,
        graph_builder: CodebaseGraphBuilder,
        llm_provider: Optional[BaseLLMProvider] = None,
    ):
        self.builder = graph_builder
        self.traversal = GraphTraversal(graph_builder)
        self.llm = llm_provider or get_llm_provider()

    def get_deterministic_candidates(self, failure: ParsedFailure) -> List[CodeSymbol]:
        """Extract candidate root-cause functions using deterministic graph backward traversal.
        
        Guarantees candidate list originates strictly from AST static analysis, not LLM hallucination.
        """
        # 1. Resolve failing symbol from file & line
        start_symbol = self.traversal.find_symbol_by_file_line(
            failure.failing_file, failure.failing_line
        )

        candidates: List[CodeSymbol] = []
        if start_symbol:
            # Backward walk to find functions called by or calling the failure point
            candidates = self.traversal.backward_trace(start_symbol.id, max_depth=3)

        # Fallback: if graph traversal yields no non-test functions, search stack frames
        if not candidates and failure.stack_frames:
            for frame in failure.stack_frames:
                sym = self.traversal.find_symbol_by_file_line(frame.file_path, frame.line_number)
                if sym and not sym.is_test and sym not in candidates:
                    candidates.append(sym)

        # Fallback 2: if graph still empty, collect all non-test code symbols in the failing file
        if not candidates:
            for sym_id, sym in self.builder.symbols.items():
                if not sym.is_test and failure.failing_file in sym.file_path:
                    candidates.append(sym)

        return candidates
