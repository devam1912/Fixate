"""Root-cause localization over the AST dependency graph.

The previous design tried five candidate-extraction strategies in sequence and
returned whichever first produced a non-empty list -- so a weak signal (every
symbol in the repository) could win outright simply because the strong signals
came up empty, and nothing downstream could tell the two cases apart.

This implementation scores every symbol against all available evidence at once
and ranks by total score, carrying the evidence forward so both the operator and
the LLM can see *why* a candidate is suspected. An LLM, when one is available,
re-ranks the strongest candidates; when one is not, the static ranking stands and
is labelled as such. Static ranking is real analysis and is reported honestly --
what this module never does is invent reasoning it did not perform.
"""

import os
import re
import logging
from typing import Dict, List, Optional
from pydantic import BaseModel, Field

from fixate.errors import LocalizationError
from fixate.graph.base_parser import CodeSymbol
from fixate.graph.builder import CodebaseGraphBuilder
from fixate.graph.traversal import GraphTraversal
from fixate.llm.base import BaseLLMProvider
from fixate.llm.factory import get_llm_provider
from fixate.localization.parser import FailureTracebackParser, ParsedFailure

logger = logging.getLogger(__name__)

# How many candidates are shown to the LLM. Bounded to keep the prompt inside a
# single context window and the cost per incident predictable.
LLM_RANKING_POOL = 15

# How many suspects the pipeline carries forward.
MAX_SUSPECTS = 5


class SuspectFunction(BaseModel):
    symbol_id: str = Field(..., description="Unique symbol ID of suspect function")
    file_path: str = Field(..., description="File path containing suspect function")
    name: str = Field(..., description="Function or class name")
    code: str = Field(..., description="Full source code snippet of suspect candidate")
    rank: int = Field(..., description="1-indexed plausibility rank (1 = highest suspect)")
    plausibility_reason: str = Field(..., description="Why this symbol is suspected")
    ranking_source: str = Field(
        "static",
        description="'llm' if a model ranked this candidate, 'static' if graph evidence alone did",
    )
    evidence: List[str] = Field(
        default_factory=list, description="Concrete signals that put this symbol in the candidate set"
    )


class LocalizationResult(BaseModel):
    failing_test: str
    exception_type: str
    exception_message: str
    suspect_functions: List[SuspectFunction]
    ranking_source: str = Field(
        "static", description="Whether the final ordering came from an LLM or from static evidence"
    )


class CandidateRank(BaseModel):
    symbol_id: str
    rank: int
    plausibility_reason: str


class LLMRankingResponse(BaseModel):
    rankings: List[CandidateRank]


class ScoredCandidate:
    """A symbol plus the evidence that made it a suspect."""

    def __init__(self, symbol: CodeSymbol):
        self.symbol = symbol
        self.score = 0
        self.evidence: List[str] = []

    def add(self, points: int, reason: str) -> None:
        self.score += points
        self.evidence.append(reason)

    def summary(self) -> str:
        return "; ".join(self.evidence) if self.evidence else "No direct evidence"


def _paths_match(symbol_path: str, reported_path: str) -> bool:
    """Compare a graph symbol's path against a path quoted in a traceback.

    Tracebacks report paths relative to the pytest rootdir while the graph holds
    absolute on-disk paths, so neither is a prefix of the other. Suffix matching on
    normalized separators handles that, with a basename check as the last resort.
    """
    if not symbol_path or not reported_path:
        return False

    left = symbol_path.replace("\\", "/").lower()
    right = reported_path.replace("\\", "/").lower()
    if left.endswith(right) or right.endswith(left):
        return True
    return left.rsplit("/", 1)[-1] == right.rsplit("/", 1)[-1]


class FailureLocalizationAgent:
    """Ranks the codebase symbols most likely to contain the defect."""

    def __init__(
        self,
        graph_builder: CodebaseGraphBuilder,
        llm_provider: Optional[BaseLLMProvider] = None,
    ):
        self.builder = graph_builder
        self.traversal = GraphTraversal(graph_builder)
        self.llm = llm_provider or get_llm_provider()
        self.parser = FailureTracebackParser()

    def localize_failure(self, raw_pytest_log: str) -> LocalizationResult:
        """Parse the log, score candidates, and return ranked suspects."""
        failure = self.parser.parse_log(raw_pytest_log)
        return self.localize_parsed_failure(failure)

    def localize_parsed_failure(self, failure: ParsedFailure) -> LocalizationResult:
        """Rank suspects for an already-parsed failure.

        Kept separate so the orchestrator can parse the log once and reuse the
        result across stages instead of re-parsing per stage.
        """
        candidates = self.score_candidates(failure)
        if not candidates:
            raise LocalizationError(
                f"No application symbols could be linked to the failure in "
                f"{failure.failing_file or 'the traceback'}. The dependency graph "
                f"holds {len(self.builder.symbols)} symbols, none of which matched.",
                remedy=(
                    "Confirm the traceback refers to files inside this repository -- a "
                    "failure raised inside an installed dependency or a test runner has "
                    "no application symbol to attribute it to -- and that the repository "
                    "contains parseable source outside its test directory."
                ),
            )

        suspects, source = self._rank(failure, candidates)
        logger.info(
            "Localized %d suspects for %s (ranking: %s); top candidate %s",
            len(suspects),
            failure.test_name,
            source,
            suspects[0].name if suspects else "none",
        )
        return LocalizationResult(
            failing_test=failure.test_name,
            exception_type=failure.exception_type,
            exception_message=failure.exception_message,
            suspect_functions=suspects,
            ranking_source=source,
        )

    def score_candidates(self, failure: ParsedFailure) -> List[ScoredCandidate]:
        """Score every non-test symbol against all evidence in the traceback.

        Weights are ordered by how directly each signal implicates a symbol: an
        exact file+line hit from pytest's own error marker is near-conclusive,
        while merely sharing a file with the failure is weak corroboration.
        """
        scored: Dict[str, ScoredCandidate] = {}

        def candidate_for(symbol: CodeSymbol) -> ScoredCandidate:
            if symbol.id not in scored:
                scored[symbol.id] = ScoredCandidate(symbol)
            return scored[symbol.id]

        traceback_text = failure.raw_traceback or ""

        # 1. The symbol enclosing pytest's reported error location.
        if failure.failing_file and failure.failing_line:
            site = self._symbol_at(failure.failing_file, failure.failing_line)
            if site is not None:
                candidate_for(site).add(
                    100, f"encloses the error site {failure.failing_file}:{failure.failing_line}"
                )

        # 2. Symbols enclosing each stack frame. Deeper frames sit closer to the
        #    raise, so they weigh more than the outer test-harness frames.
        total_frames = len(failure.stack_frames)
        for depth, frame in enumerate(failure.stack_frames):
            symbol = self._symbol_at(frame.file_path, frame.line_number)
            if symbol is None or symbol.is_test:
                continue
            weight = 30 + int(20 * (depth / max(total_frames - 1, 1)))
            candidate_for(symbol).add(
                weight, f"appears in the traceback at {frame.file_path}:{frame.line_number}"
            )

        # 3. Symbols named anywhere in the traceback text.
        for symbol in self.builder.symbols.values():
            if symbol.is_test or not symbol.name or len(symbol.name) < 3:
                continue
            if re.search(rf"\b{re.escape(symbol.name)}\b", traceback_text):
                candidate_for(symbol).add(25, "named in the traceback")

        # 4. Symbols sharing the failing file.
        if failure.failing_file:
            for symbol in self.builder.symbols.values():
                if symbol.is_test:
                    continue
                if _paths_match(symbol.file_path, failure.failing_file):
                    candidate_for(symbol).add(15, "defined in the failing file")

        # 5. Immediate call-graph neighbours of everything implicated so far. A
        #    correct call can still fail because of a defect one hop away.
        for symbol_id in list(scored):
            for neighbour in self.traversal.get_callees(symbol_id) + self.traversal.get_callers(symbol_id):
                if neighbour.is_test or neighbour.id in scored:
                    continue
                candidate_for(neighbour).add(
                    10, f"adjacent in the call graph to {self.builder.symbols[symbol_id].name}"
                )

        # 6. Prefer executable symbols; a bug lives in a body, not in a class header.
        for candidate in scored.values():
            symbol_type = getattr(candidate.symbol.symbol_type, "value", str(candidate.symbol.symbol_type))
            if symbol_type in ("function", "method"):
                candidate.add(5, "is an executable function or method")

        ranked = [c for c in scored.values() if not c.symbol.is_test]
        ranked.sort(key=lambda c: (-c.score, c.symbol.file_path, c.symbol.name))
        logger.info(
            "Scored %d candidate symbols; strongest evidence: %s",
            len(ranked),
            ranked[0].summary() if ranked else "none",
        )
        return ranked

    def _symbol_at(self, file_path: str, line_number: int) -> Optional[CodeSymbol]:
        """Find the innermost symbol spanning a file/line, preferring the tightest span."""
        matches = [
            symbol
            for symbol in self.builder.symbols.values()
            if _paths_match(symbol.file_path, file_path)
            and symbol.start_line <= line_number <= symbol.end_line
        ]
        if not matches:
            return None
        # A method inside a class matches both; the narrower span is the real site.
        return min(matches, key=lambda s: s.end_line - s.start_line)

    def _rank(
        self, failure: ParsedFailure, candidates: List[ScoredCandidate]
    ) -> tuple[List[SuspectFunction], str]:
        """Order candidates, using the LLM when one is genuinely available."""
        pool = candidates[:LLM_RANKING_POOL]

        if not self.llm.is_live:
            logger.info(
                "No live LLM provider (%s); ranking suspects on static graph evidence alone.",
                self.llm.name,
            )
            return self._static_suspects(pool), "static"

        try:
            ranked = self._llm_suspects(failure, pool)
            if ranked:
                return ranked, "llm"
            logger.warning("LLM returned no usable ranking; falling back to static evidence order.")
        except Exception as exc:
            logger.warning("LLM ranking failed (%s); falling back to static evidence order.", exc)

        return self._static_suspects(pool), "static"

    def _static_suspects(self, pool: List[ScoredCandidate]) -> List[SuspectFunction]:
        return [
            SuspectFunction(
                symbol_id=candidate.symbol.id,
                file_path=candidate.symbol.file_path,
                name=candidate.symbol.name,
                code=candidate.symbol.code,
                rank=index,
                plausibility_reason=(
                    f"Ranked by static graph evidence (score {candidate.score}): {candidate.summary()}"
                ),
                ranking_source="static",
                evidence=candidate.evidence,
            )
            for index, candidate in enumerate(pool[:MAX_SUSPECTS], start=1)
        ]

    def _llm_suspects(
        self, failure: ParsedFailure, pool: List[ScoredCandidate]
    ) -> List[SuspectFunction]:
        by_id = {c.symbol.id: c for c in pool}
        blocks = [
            f"Candidate [ID: {c.symbol.id}] "
            f"({getattr(c.symbol.symbol_type, 'value', c.symbol.symbol_type)} "
            f"'{c.symbol.name}' in {os.path.basename(c.symbol.file_path)})\n"
            f"Static evidence: {c.summary()}\n"
            f"```python\n{c.symbol.code}\n```"
            for c in pool
        ]

        prompt = (
            "A test failed. Identify which candidate function contains the root-cause defect.\n\n"
            f"Failing test: {failure.test_name}\n"
            f"Error location: {failure.failing_file}:{failure.failing_line}\n"
            f"Exception: {failure.exception_type}: {failure.exception_message}\n\n"
            f"Traceback:\n```\n{failure.raw_traceback}\n```\n\n"
            "Candidates, pre-filtered by AST dependency-graph analysis:\n\n"
            + "\n\n".join(blocks)
            + "\n\nRank the candidates by how likely each is to contain the defect "
            "(rank 1 = most likely). Return only candidates you can justify, using their "
            "exact ID. Explain each in one sentence, citing the specific line or "
            "expression that is wrong."
        )

        response: LLMRankingResponse = self.llm.generate_structured(
            prompt=prompt,
            response_schema=LLMRankingResponse,
            system_instruction=(
                "You are a debugging specialist performing root-cause analysis. "
                "Reason from the traceback and the code as given; never invent symbols "
                "or files that do not appear in the candidate list."
            ),
            temperature=0.1,
        )

        suspects: List[SuspectFunction] = []
        for item in sorted(response.rankings, key=lambda r: r.rank):
            candidate = by_id.get(item.symbol_id)
            if candidate is None:
                logger.warning("LLM ranked unknown symbol '%s'; discarding.", item.symbol_id)
                continue
            suspects.append(
                SuspectFunction(
                    symbol_id=candidate.symbol.id,
                    file_path=candidate.symbol.file_path,
                    name=candidate.symbol.name,
                    code=candidate.symbol.code,
                    rank=len(suspects) + 1,
                    plausibility_reason=item.plausibility_reason,
                    ranking_source="llm",
                    evidence=candidate.evidence,
                )
            )

        return suspects[:MAX_SUSPECTS]
