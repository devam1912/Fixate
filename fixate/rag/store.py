"""ChromaDB vector store wrapper supporting Gemini Embedding 2 with rate limiting."""

import hashlib
import os
import re
import time
import logging
from typing import List, Optional
from fixate.rag.chunker import CodeChunk
from fixate.llm.rate_limiter import EMBEDDING_RATE_LIMITER, estimate_tokens
from fixate.paths import PROJECT_ROOT

logger = logging.getLogger(__name__)

DEFAULT_EMBEDDING_DIMENSION = 3072

# Texts per embedding API call. Batching is what keeps a repository-sized index
# inside the free tier's per-minute request quota.
EMBED_BATCH_SIZE = 100

# ...but a count alone does not bound a *token* budget, and tokens are the binding
# limit. 100 chunks of real source is routinely tens of thousands of tokens, which
# is more than the entire per-minute allowance -- one such call would consume the
# whole minute and the provider would likely refuse it outright. Batches are
# therefore closed on whichever bound is reached first.
EMBED_MAX_BATCH_TOKENS = 8000

# No single chunk may exceed the per-request budget; one that does can never be
# embedded at any batch size, so it is truncated rather than allowed to wedge the
# index. Generous enough that real functions are unaffected.
EMBED_MAX_TEXT_TOKENS = 4000

EMBED_MAX_RETRIES = 3
EMBED_DEFAULT_BACKOFF_SECONDS = 35.0
EMBED_MAX_BACKOFF_SECONDS = 60.0


def _content_hash(code: str) -> str:
    """Identity of a chunk's content, used to skip re-embedding what has not changed."""
    return hashlib.sha256((code or "").encode("utf-8")).hexdigest()[:16]


def _truncate_to_tokens(text: str, max_tokens: int) -> str:
    """Trim a text to roughly ``max_tokens``, mirroring the limiter's estimate.

    Kept consistent with :func:`estimate_tokens` so the bound the batcher enforces
    is the same one the rate limiter later charges against.
    """
    if estimate_tokens(text) <= max_tokens:
        return text
    keep = int(max_tokens * 4 / 1.15)
    logger.debug("Truncating a %d-char chunk to %d chars for embedding.", len(text), keep)
    return text[:keep]


class EmbeddingUnavailableError(RuntimeError):
    """The embedding API could not serve a request and no valid vectors were produced.

    Raised rather than substituting hash vectors, because the two live in different
    vector spaces: mixing them inside one collection makes every later similarity
    score meaningless, and the collection is persisted to disk, so the damage
    outlives the incident that caused it.
    """


class GeminiEmbeddingFunction:
    """Gemini embedding function with batching and quota-aware retries.

    Concrete limits live in :mod:`fixate.llm.rate_limiter` and are environment
    overridable; duplicating the numbers here is how the previous docstring came to
    claim a 90k TPM ceiling against an actual allowance of 30k.
    """

    def __init__(self, api_key: Optional[str] = None, model_name: str = "gemini-embedding-2"):
        self.api_key = api_key or os.getenv("GEMINI_API_KEY") or os.getenv("GOOGLE_API_KEY")
        self.model_name = os.getenv("GEMINI_EMBEDDING_MODEL") or model_name
        self.embedding_dimension = int(os.getenv("FIXATE_EMBEDDING_DIMENSION", str(DEFAULT_EMBEDDING_DIMENSION)))
        self._client = None

        if self.api_key:
            try:
                from google import genai
                self._client = genai.Client(api_key=self.api_key)
            except Exception as exc:
                logger.warning(f"Google GenAI SDK unavailable for embeddings: {exc}")

    def __call__(self, input: List[str]) -> List[List[float]]:
        return self._embed(input)

    def embed_query(self, input: str | List[str]) -> List[List[float]]:
        if isinstance(input, str):
            input = [input]
        return self._embed(input)

    def embed_documents(self, input: List[str]) -> List[List[float]]:
        return self._embed(input)

    @property
    def space(self) -> str:
        """Identifier of the vector space this instance produces.

        Hash vectors and Gemini vectors are not comparable, so the space is part of
        the collection name -- never let the two mix inside one index.
        """
        return "hash" if self._client is None else "gemini"

    def _embed(self, input: List[str]) -> List[List[float]]:
        if not input:
            return []

        if self._client is None:
            return [self._hash_embed(text) for text in input]

        # One API call per batch rather than per text. The previous implementation
        # charged the rate limiter a single slot and then issued len(input) requests
        # inside it, so a 200-chunk index looked like 1 request locally while
        # sending 200 to Google -- which is what exhausted the free-tier quota.
        embeddings: List[List[float]] = []
        for batch in self._batches(input):
            embeddings.extend(self._embed_batch(batch))
        return embeddings

    @staticmethod
    def _batches(input: List[str]) -> List[List[str]]:
        """Split texts into batches bounded by both count and estimated tokens."""
        batches: List[List[str]] = []
        current: List[str] = []
        current_tokens = 0

        for text in input:
            text = _truncate_to_tokens(text, EMBED_MAX_TEXT_TOKENS)
            tokens = estimate_tokens(text)
            over_tokens = current and current_tokens + tokens > EMBED_MAX_BATCH_TOKENS
            over_count = len(current) >= EMBED_BATCH_SIZE
            if over_tokens or over_count:
                batches.append(current)
                current, current_tokens = [], 0
            current.append(text)
            current_tokens += tokens

        if current:
            batches.append(current)
        return batches

    def _embed_batch(self, batch: List[str]) -> List[List[float]]:
        """Embed one batch, retrying on quota errors before giving up."""
        for attempt in range(1, EMBED_MAX_RETRIES + 1):
            EMBEDDING_RATE_LIMITER.acquire(
                estimated_tokens=sum(estimate_tokens(text) for text in batch)
            )
            try:
                res = self._client.models.embed_content(model=self.model_name, contents=batch)
                vectors = self._extract(res)
                if len(vectors) == len(batch):
                    return vectors

                # Some SDK/model combinations treat a list of contents as one
                # multi-part document and return a single vector. Batching is only
                # a quota optimization, so fall back to one call per text rather
                # than losing embeddings altogether.
                logger.info(
                    "Provider returned %d embedding(s) for %d inputs; falling back to "
                    "per-text embedding for this batch.",
                    len(vectors),
                    len(batch),
                )
                return self._embed_individually(batch)
            except EmbeddingUnavailableError:
                raise
            except Exception as err:
                delay = self._retry_delay(err)
                if delay is None or attempt == EMBED_MAX_RETRIES:
                    raise EmbeddingUnavailableError(
                        f"Gemini embedding failed after {attempt} attempt(s): {err}"
                    ) from err
                logger.warning(
                    "Gemini embedding quota hit (attempt %d/%d); the API asked for %.0fs. Waiting.",
                    attempt,
                    EMBED_MAX_RETRIES,
                    delay,
                )
                time.sleep(min(delay, EMBED_MAX_BACKOFF_SECONDS))

        raise EmbeddingUnavailableError("Gemini embedding retries exhausted.")

    def _embed_individually(self, batch: List[str]) -> List[List[float]]:
        """Embed one text per request, charging the limiter for each.

        Slower and more quota-hungry than batching, which is exactly why the
        accounting has to be per call here -- the original quota exhaustion came
        from issuing N requests while recording one.
        """
        vectors: List[List[float]] = []
        for text in batch:
            EMBEDDING_RATE_LIMITER.acquire(estimated_tokens=estimate_tokens(text))
            try:
                res = self._client.models.embed_content(model=self.model_name, contents=text)
            except Exception as err:
                raise EmbeddingUnavailableError(f"Gemini embedding failed: {err}") from err

            single = self._extract(res)
            if not single:
                raise EmbeddingUnavailableError("Gemini returned no embedding for a text.")
            vectors.append(single[0])
        return vectors

    def _extract(self, res) -> List[List[float]]:
        """Pull vectors out of either response shape the SDK returns."""
        if getattr(res, "embeddings", None):
            return [self._fit_dimension(item.values) for item in res.embeddings]
        if getattr(res, "embedding", None):
            return [self._fit_dimension(res.embedding.values)]
        return []

    @staticmethod
    def _retry_delay(err: Exception) -> Optional[float]:
        """Return the server-requested retry delay for a quota error, else None.

        Only quota errors are worth waiting on; a bad key or malformed request
        will fail identically no matter how long we sleep.
        """
        text = str(err)
        if "RESOURCE_EXHAUSTED" not in text and "429" not in text:
            return None
        match = re.search(r"[Rr]etry in (\d+(?:\.\d+)?)s", text) or re.search(
            r"'retryDelay':\s*'(\d+(?:\.\d+)?)s'", text
        )
        return float(match.group(1)) + 1.0 if match else EMBED_DEFAULT_BACKOFF_SECONDS

    def _hash_embed(self, text: str) -> List[float]:
        """Deterministic offline embedding, used only when no API client exists."""
        vec = [0.0] * self.embedding_dimension
        for idx, char in enumerate(text[:2000]):
            vec[(ord(char) + idx) % self.embedding_dimension] += 1.0
        norm = sum(x * x for x in vec) ** 0.5 or 1.0
        return [x / norm for x in vec]

    def _fit_dimension(self, values: List[float]) -> List[float]:
        """Normalize API embedding length so Chroma collection dimensions remain stable."""
        vector = list(values)
        if len(vector) == self.embedding_dimension:
            return vector
        if len(vector) > self.embedding_dimension:
            return vector[:self.embedding_dimension]
        return vector + [0.0] * (self.embedding_dimension - len(vector))

    def name(self) -> str:
        return f"gemini_embedding_{self.model_name}_{self.embedding_dimension}d"


class CodeVectorStore:
    """Vector store for indexing AST code chunks and performing semantic code retrieval."""

    def __init__(self, collection_name: str = "fixate_codebase", persist_dir: Optional[str] = None):
        self.embedding_func = GeminiEmbeddingFunction()
        # The vector space is part of the identity of the collection: an index built
        # from hash vectors must never be queried with Gemini vectors, or vice versa.
        self.collection_name = (
            f"{collection_name}_{self.embedding_func.space}"
            f"_d{self.embedding_func.embedding_dimension}"
        )
        self.persist_dir = persist_dir or str(PROJECT_ROOT / "chroma_db")
        self._client = None
        self._collection = None
        self._memory_chunks: List[CodeChunk] = []
        self._repo_id = "default"

        try:
            import chromadb
            self._client = chromadb.PersistentClient(path=self.persist_dir)
            self._collection = self._client.get_or_create_collection(
                name=self.collection_name,
                embedding_function=self.embedding_func,
            )
            logger.info(
                f"Initialized ChromaDB vector store with collection '{self.collection_name}' "
                f"({self.embedding_func.embedding_dimension} dimensions)"
            )
        except Exception as exc:
            logger.warning(f"Could not initialize ChromaDB vector store: {exc}. Using memory store.")

    def index_chunks(self, chunks: List[CodeChunk], repo_id: Optional[str] = None):
        """Index CodeChunk objects, partitioned by repository.

        The collection is shared across repositories, so every chunk carries a
        ``repo_id`` and every query filters on it. Without that partition the
        nearest neighbours of a query are drawn from every repository ever indexed;
        the ids that come back do not resolve against the current session's chunks
        and are silently dropped, so retrieval quietly returns nothing.
        """
        if not chunks:
            return

        if repo_id:
            self._repo_id = repo_id

        # Deduplicate by id so repeated indexing cannot inflate the memory store.
        merged = {c.chunk_id: c for c in self._memory_chunks}
        merged.update({c.chunk_id: c for c in chunks})
        self._memory_chunks = list(merged.values())

        if self._collection:
            try:
                dedup_chunks = list({c.chunk_id: c for c in chunks}.values())

                # Only embed what actually changed. Re-indexing was previously a
                # clear-then-upsert of the whole repository on every incident, so
                # the same unchanged source was re-embedded from scratch each run
                # -- which is what pushed embedding tokens-per-minute to the edge
                # of the quota. Content hashes make a repeat incident on an
                # unchanged repository cost nothing.
                existing = self._existing_hashes()
                stale = set(existing)
                new_chunks = []
                for chunk in dedup_chunks:
                    scoped = self._scoped_id(chunk.chunk_id)
                    stale.discard(scoped)
                    if existing.get(scoped) != _content_hash(chunk.code):
                        new_chunks.append(chunk)

                # Symbols renamed or deleted upstream must not linger in the index
                # and keep surfacing as retrieval hits.
                if stale:
                    self._collection.delete(ids=sorted(stale))

                if not new_chunks:
                    logger.info(
                        "All %d chunks already indexed and unchanged for '%s'; "
                        "no embedding requests issued.",
                        len(dedup_chunks),
                        self._repo_id,
                    )
                    return

                documents = [c.code for c in new_chunks]
                ids = [self._scoped_id(c.chunk_id) for c in new_chunks]
                metadatas = [
                    {
                        "repo_id": self._repo_id,
                        "chunk_id": c.chunk_id,
                        "file_path": c.file_path,
                        "name": c.name,
                        "symbol_type": c.symbol_type.value,
                        "is_test": str(c.is_test),
                        "content_hash": _content_hash(c.code),
                    }
                    for c in new_chunks
                ]
                self._collection.upsert(documents=documents, ids=ids, metadatas=metadatas)
                logger.info(
                    "Indexed %d changed chunk(s) into '%s' (%d unchanged, %d removed).",
                    len(new_chunks),
                    self.collection_name,
                    len(dedup_chunks) - len(new_chunks),
                    len(stale),
                )
            except Exception as err:
                if self._is_embedding_outage(err):
                    self._degrade(err, "indexing")
                    return
                logger.error(f"ChromaDB indexing error: {err}")
                if "dimension" in str(err).lower():
                    self._reset_collection()

    def query_similar_code(self, query_text: str, n_results: int = 3) -> List[CodeChunk]:
        """Query vector database for most semantically relevant code chunks matching query_text."""
        if self._collection:
            try:
                res = self._collection.query(
                    query_texts=[query_text],
                    n_results=n_results,
                    where={"repo_id": self._repo_id},
                )
                retrieved: List[CodeChunk] = []
                metadatas = (res.get("metadatas") or [[]])[0]
                id_to_chunk = {c.chunk_id: c for c in self._memory_chunks}
                for meta in metadatas:
                    chunk = id_to_chunk.get((meta or {}).get("chunk_id"))
                    if chunk is not None:
                        retrieved.append(chunk)
                if retrieved:
                    return retrieved
                logger.info(
                    "Vector search matched no chunks for %r in partition '%s'; "
                    "falling back to keyword retrieval.",
                    query_text[:60],
                    self._repo_id,
                )
            except Exception as exc:
                if self._is_embedding_outage(exc):
                    self._degrade(exc, "querying")
                else:
                    logger.error(f"ChromaDB query error: {exc}")
                    if "dimension" in str(exc).lower():
                        self._reset_collection()

        # Fallback substring / keyword match across in-memory chunks
        query_words = set(query_text.lower().split())
        matched = []
        for chunk in self._memory_chunks:
            score = sum(1 for w in query_words if w in chunk.code.lower() or w in chunk.name.lower())
            if score > 0:
                matched.append((score, chunk))
        
        matched.sort(key=lambda x: x[0], reverse=True)
        return [chunk for _, chunk in matched[:n_results]]

    def _scoped_id(self, chunk_id: str) -> str:
        """Namespace a chunk id by repository so identical paths cannot collide.

        Two repositories both containing ``src/utils.py::parse`` would otherwise
        overwrite each other's vectors in the shared collection.
        """
        return f"{self._repo_id}::{chunk_id}"

    def _existing_hashes(self) -> dict:
        """Map scoped id -> content hash for rows already in this partition.

        A row indexed before content hashing existed has no hash and compares
        unequal to everything, so it is re-embedded once and then stays cached.
        """
        if not self._collection:
            return {}
        try:
            res = self._collection.get(where={"repo_id": self._repo_id}, include=["metadatas"])
        except Exception as exc:
            logger.warning("Could not read the existing index partition: %s", exc)
            return {}
        return {
            row_id: (meta or {}).get("content_hash", "")
            for row_id, meta in zip(res.get("ids") or [], res.get("metadatas") or [])
        }

    def _clear_partition(self) -> None:
        """Remove all rows belonging to the current repository."""
        if not self._collection:
            return
        try:
            self._collection.delete(where={"repo_id": self._repo_id})
        except Exception as exc:
            logger.warning("Could not clear index partition '%s': %s", self._repo_id, exc)

    @staticmethod
    def _is_embedding_outage(err: Exception) -> bool:
        """Whether this error means the embedding backend is unavailable."""
        if isinstance(err, EmbeddingUnavailableError):
            return True
        # Chroma wraps the embedding function's exception, so inspect the chain.
        cause = err.__cause__ or err.__context__
        if isinstance(cause, EmbeddingUnavailableError):
            return True
        return "EmbeddingUnavailableError" in str(err)

    def _degrade(self, err: Exception, phase: str) -> None:
        """Stop using the vector index for the rest of this session.

        Retrieval falls back to in-memory keyword matching, which is weaker but
        stays in one consistent space. Detaching is the point: it prevents a quota
        outage from writing incomparable vectors into a collection that persists on
        disk and would degrade every future incident.
        """
        if self._collection is not None:
            logger.warning(
                "Embedding backend unavailable while %s (%s). Detaching from collection "
                "'%s' and falling back to keyword retrieval for this session; the vector "
                "index is left intact rather than filled with incompatible vectors.",
                phase,
                err,
                self.collection_name,
            )
        self._collection = None

    def _reset_collection(self):
        """Drop and recreate the current collection after an embedding dimension mismatch."""
        if not self._client:
            return
        try:
            self._client.delete_collection(self.collection_name)
        except Exception:
            pass
        try:
            self._collection = self._client.get_or_create_collection(
                name=self.collection_name,
                embedding_function=self.embedding_func,
            )
            logger.info(f"Recreated ChromaDB collection '{self.collection_name}' after dimension mismatch")
        except Exception as exc:
            logger.warning(f"Could not recreate ChromaDB collection '{self.collection_name}': {exc}")
            self._collection = None
