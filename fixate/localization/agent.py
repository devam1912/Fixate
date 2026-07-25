"""Failure Localization Agent combining AST graph traversal with LLM reasoning."""

import logging
from typing import List, Optional
from pydantic import BaseModel, Field

from fixate.graph.builder import CodebaseGraphBuilder
from fixate.graph.traversal import GraphTraversal
from fixate.graph.base_parser import CodeSymbol
from fixate.localization.parser import FailureTracebackParser, ParsedFailure
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


class CandidateRank(BaseModel):
    symbol_id: str
    rank: int
    plausibility_reason: str


class LLMRankingResponse(BaseModel):
    rankings: List[CandidateRank]


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
        self.parser = FailureTracebackParser()

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

    def rank_candidates_with_llm(
        self, failure: ParsedFailure, candidates: List[CodeSymbol]
    ) -> List[SuspectFunction]:
        """Use LLM to reason about root-cause plausibility given the failure error and candidate code."""
        if not candidates:
            logger.warning("No candidate functions provided for LLM ranking.")
            return []

        # Build context prompt listing candidate functions
        candidate_snippets = []
        id_map = {}
        for idx, cand in enumerate(candidates, start=1):
            id_map[cand.id] = cand
            candidate_snippets.append(
                f"Candidate #{idx} [ID: {cand.id}] (File: {cand.file_path}, Lines {cand.start_line}-{cand.end_line}):\n"
                f"```python\n{cand.code}\n```\n"
            )

        prompt = (
            f"You are a Root Cause Failure Localization Agent.\n"
            f"A test failure occurred:\n"
            f"- Failing Test: {failure.test_name}\n"
            f"- Error File/Line: {failure.failing_file}:{failure.failing_line}\n"
            f"- Exception Type: {failure.exception_type}\n"
            f"- Exception Message: {failure.exception_message}\n\n"
            f"Below is a list of candidate root-cause functions extracted strictly via codebase dependency graph traversal:\n\n"
            + "\n".join(candidate_snippets) +
            f"\nAnalyze the exception and candidate source code.\n"
            f"Rank the top candidate functions (1 to {min(3, len(candidates))}) by root-cause plausibility.\n"
            f"Explain clearly why the function contains the root bug rather than just being a downstream symptom."
        )

        sys_instruction = (
            "You are a senior static analysis & debugging engineer. Distinguish root cause from symptoms."
        )

        try:
            llm_response: LLMRankingResponse = self.llm.generate_structured(
                prompt=prompt,
                response_schema=LLMRankingResponse,
                system_instruction=sys_instruction,
            )
            
            suspects: List[SuspectFunction] = []
            seen_ids = set()
            for item in llm_response.rankings:
                if item.symbol_id in id_map and item.symbol_id not in seen_ids:
                    seen_ids.add(item.symbol_id)
                    cand_sym = id_map[item.symbol_id]
                    suspects.append(
                        SuspectFunction(
                            symbol_id=cand_sym.id,
                            file_path=cand_sym.file_path,
                            name=cand_sym.name,
                            code=cand_sym.code,
                            rank=item.rank,
                            plausibility_reason=item.plausibility_reason,
                        )
                    )
            
            # Sort by rank ascending
            suspects.sort(key=lambda s: s.rank)
            if suspects:
                return suspects[:3]
        except Exception as exc:
            logger.error(f"LLM ranking failed, falling back to graph distance order: {exc}")

        # Fallback if LLM fails: rank by order returned by graph traversal
        fallback_suspects = []
        for rank_idx, cand in enumerate(candidates[:3], start=1):
            fallback_suspects.append(
                SuspectFunction(
                    symbol_id=cand.id,
                    file_path=cand.file_path,
                    name=cand.name,
                    code=cand.code,
                    rank=rank_idx,
                    plausibility_reason="Ranked via AST graph backward walk proximity.",
                )
            )
        return fallback_suspects

    def localize_failure(self, log_output: str) -> LocalizationResult:
        """Main end-to-end entry point for failure localization.
        
        Args:
            log_output: Raw string output from pytest or exception traceback.
            
        Returns:
            LocalizationResult with ranked suspect functions and failure details.
        """
        # 1. Parse raw log
        failure = self.parser.parse_log(log_output)
        logger.info(f"Parsed failure: {failure.failing_file}:{failure.failing_line} ({failure.exception_type})")

        # 2. Extract graph candidates
        candidates = self.get_deterministic_candidates(failure)
        logger.info(f"Extracted {len(candidates)} deterministic candidates via graph traversal")

        # 3. LLM plausibility ranking
        suspects = self.rank_candidates_with_llm(failure, candidates)

        return LocalizationResult(
            failing_test=failure.test_name,
            exception_type=failure.exception_type,
            exception_message=failure.exception_message,
            suspect_functions=suspects,
        )
