"""Code-RAG Agent for retrieving code context, tests, and past fix history."""

import logging
from typing import List, Optional
from pydantic import BaseModel, Field

from fixate.rag.chunker import ASTCodeChunker, CodeChunk
from fixate.rag.store import CodeVectorStore
from fixate.rag.fix_history import FixHistoryStore, FixRecord
from fixate.localization.agent import SuspectFunction
from fixate.localization.parser import ParsedFailure

logger = logging.getLogger(__name__)


class RAGContext(BaseModel):
    """Context object returned by CodeRAGAgent containing code, tests, and past fix history."""
    suspect_function: SuspectFunction
    related_code_chunks: List[CodeChunk] = Field(default_factory=list)
    related_tests: List[CodeChunk] = Field(default_factory=list)
    past_fixes: List[FixRecord] = Field(default_factory=list)


class CodeRAGAgent:
    """Agent responsible for gathering all relevant code context, tests, and historical fix patterns."""

    def __init__(
        self,
        vector_store: Optional[CodeVectorStore] = None,
        fix_history: Optional[FixHistoryStore] = None,
    ):
        self.vector_store = vector_store or CodeVectorStore()
        self.fix_history = fix_history or FixHistoryStore()
        self.chunker = ASTCodeChunker()

    def index_repository(self, root_dir: str):
        """Chunk and index the target repository into the vector store."""
        chunks = self.chunker.chunk_directory(root_dir)
        self.vector_store.index_chunks(chunks)

    def retrieve_context_for_suspect(
        self,
        suspect: SuspectFunction,
        failure: ParsedFailure,
    ) -> RAGContext:
        """Retrieve full code context, related code chunks, tests, and past fixes for a suspect function."""
        # 1. Query vector store for related code
        query_str = f"{suspect.name} {failure.exception_type} {failure.exception_message}"
        similar_chunks = self.vector_store.query_similar_code(query_str, n_results=5)

        related_code = [c for c in similar_chunks if not c.is_test and c.chunk_id != suspect.symbol_id]
        related_tests = [c for c in similar_chunks if c.is_test]

        # 2. Retrieve past fixes matching exception signature
        past_fixes = self.fix_history.find_similar_fixes(
            exception_type=failure.exception_type,
            exception_message=failure.exception_message,
        )

        logger.info(
            f"Retrieved context for {suspect.name}: "
            f"{len(related_code)} code chunks, {len(related_tests)} tests, {len(past_fixes)} past fixes"
        )

        return RAGContext(
            suspect_function=suspect,
            related_code_chunks=related_code,
            related_tests=related_tests,
            past_fixes=past_fixes,
        )
