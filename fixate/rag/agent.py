"""Context retrieval for the patch generator.

Gathers the three kinds of context that measurably improve a generated patch:
code the suspect actually interacts with, the tests that pin its behaviour, and
diffs that resolved similar failures before.

Retrieval is best-effort by design -- an empty index yields empty context, which
the patch generator handles by prompting from the suspect source alone. What this
module will not do is pad the result with unrelated chunks to look productive;
downstream prompt quality degrades faster from irrelevant context than from
missing context.
"""

import hashlib
import logging
import os
import re
from typing import List, Optional
from pydantic import BaseModel, Field

from fixate.localization.agent import SuspectFunction
from fixate.localization.parser import ParsedFailure
from fixate.rag.chunker import ASTCodeChunker, CodeChunk
from fixate.rag.fix_history import FixHistoryStore, FixRecord
from fixate.rag.store import CodeVectorStore

logger = logging.getLogger(__name__)

MAX_CODE_CHUNKS = 5
MAX_TEST_CHUNKS = 3


def repository_id(root_dir: str) -> str:
    """Stable partition key identifying a repository in the shared vector index.

    Prefers the git origin URL, because Fixate clones each incident into a fresh
    randomly-named temporary directory: keying on the path would mint a new
    partition per run and let the index grow without bound, while keying on the
    directory name alone would collapse every clone into one shared partition and
    reintroduce the cross-repository contamination this id exists to prevent.
    """
    normalized = os.path.normpath(os.path.abspath(root_dir)).replace("\\", "/")

    origin = _git_origin(normalized)
    if origin:
        slug = re.sub(r"[^A-Za-z0-9]+", "_", origin.rsplit("/", 2)[-1].removesuffix(".git"))
        return f"{slug}_{hashlib.sha1(origin.encode('utf-8')).hexdigest()[:8]}"

    name = os.path.basename(normalized) or "repo"
    return f"{name}_{hashlib.sha1(normalized.encode('utf-8')).hexdigest()[:8]}"


def _git_origin(root_dir: str) -> Optional[str]:
    """Read the origin remote URL from .git/config without invoking git."""
    config_path = os.path.join(root_dir, ".git", "config")
    if not os.path.isfile(config_path):
        return None
    try:
        with open(config_path, "r", encoding="utf-8", errors="replace") as handle:
            content = handle.read()
    except OSError:
        return None

    match = re.search(r'\[remote "origin"\](?:[^\[]*?)url\s*=\s*(\S+)', content, re.DOTALL)
    return match.group(1).strip() if match else None


class RAGContext(BaseModel):
    """Code, tests, and prior fixes assembled for one suspect symbol."""

    suspect_function: SuspectFunction
    related_code_chunks: List[CodeChunk] = Field(default_factory=list)
    related_tests: List[CodeChunk] = Field(default_factory=list)
    past_fixes: List[FixRecord] = Field(default_factory=list)

    @property
    def is_empty(self) -> bool:
        return not (self.related_code_chunks or self.related_tests or self.past_fixes)


class CodeRAGAgent:
    """Indexes a repository and retrieves context relevant to a specific failure."""

    def __init__(
        self,
        vector_store: Optional[CodeVectorStore] = None,
        fix_history: Optional[FixHistoryStore] = None,
    ):
        self.vector_store = vector_store or CodeVectorStore()
        self.fix_history = fix_history or FixHistoryStore()
        self.chunker = ASTCodeChunker()

    def index_repository(self, root_dir: str) -> int:
        """Chunk the repository on AST boundaries and index it. Returns chunk count."""
        chunks = self.chunker.chunk_directory(root_dir)
        if not chunks:
            logger.warning("No indexable Python symbols found under %s.", root_dir)
            return 0

        self.vector_store.index_chunks(chunks, repo_id=repository_id(root_dir))
        logger.info("Indexed %d AST chunks from %s.", len(chunks), root_dir)
        return len(chunks)

    def retrieve_context_for_suspect(
        self,
        suspect: SuspectFunction,
        failure: ParsedFailure,
    ) -> RAGContext:
        """Retrieve code, tests, and prior fixes relevant to this suspect."""
        chunks = self._query(suspect, failure)

        related_code: List[CodeChunk] = []
        related_tests: List[CodeChunk] = []
        for chunk in chunks:
            # The suspect's own source is already in the prompt; repeating it here
            # would crowd out genuinely new context.
            if chunk.chunk_id == suspect.symbol_id:
                continue
            if chunk.is_test:
                if len(related_tests) < MAX_TEST_CHUNKS:
                    related_tests.append(chunk)
            elif len(related_code) < MAX_CODE_CHUNKS:
                related_code.append(chunk)

        past_fixes = self._past_fixes(failure)

        context = RAGContext(
            suspect_function=suspect,
            related_code_chunks=related_code,
            related_tests=related_tests,
            past_fixes=past_fixes,
        )
        if context.is_empty:
            logger.info(
                "No supporting context retrieved for %s; the patch prompt will rely on "
                "the suspect source and traceback alone.",
                suspect.name,
            )
        else:
            logger.info(
                "Retrieved context for %s: %d code chunks, %d tests, %d prior fixes.",
                suspect.name,
                len(related_code),
                len(related_tests),
                len(past_fixes),
            )
        return context

    def _query(self, suspect: SuspectFunction, failure: ParsedFailure) -> List[CodeChunk]:
        """Search the vector store, de-duplicating across several framings.

        A single query string has to serve two different needs -- finding code that
        resembles the suspect, and finding code that resembles the error -- so both
        are issued and merged in order of specificity.
        """
        queries = [
            f"{suspect.name} {failure.exception_type} {failure.exception_message}".strip(),
            f"{failure.exception_type} {failure.exception_message}".strip(),
            suspect.name,
        ]

        seen: set[str] = set()
        merged: List[CodeChunk] = []
        for query in queries:
            if not query:
                continue
            try:
                results = self.vector_store.query_similar_code(query, n_results=MAX_CODE_CHUNKS)
            except Exception as exc:
                # Retrieval is an optimization; a vector-store outage must not take
                # down an incident that can still be patched from the suspect source.
                logger.warning("Vector store query failed for %r: %s", query, exc)
                continue

            for chunk in results:
                if chunk.chunk_id not in seen:
                    seen.add(chunk.chunk_id)
                    merged.append(chunk)

        return merged

    def _past_fixes(self, failure: ParsedFailure) -> List[FixRecord]:
        try:
            return self.fix_history.find_similar_fixes(
                exception_type=failure.exception_type,
                exception_message=failure.exception_message,
            )
        except Exception as exc:
            logger.warning("Fix-history lookup failed: %s", exc)
            return []
