"""Unit tests for AST Code Chunker, Vector Store, Fix History, and Code-RAG Agent."""

import os
import tempfile
from unittest import mock

import pytest
from fixate.rag.chunker import ASTCodeChunker, CodeChunk
from fixate.rag.store import CodeVectorStore, GeminiEmbeddingFunction
from fixate.rag.fix_history import FixHistoryStore
from fixate.rag.agent import CodeRAGAgent
from fixate.localization.agent import SuspectFunction
from fixate.localization.parser import ParsedFailure

SAMPLE_CODE = """
def process_data(items: list) -> list:
    \"\"\"Process data items.\"\"\"
    result = []
    for item in items:
        result.append(transform(item))
    return result

def transform(item: int) -> int:
    return item * 2

def test_process_data():
    assert process_data([1, 2]) == [2, 4]
"""


def test_ast_code_chunker():
    chunker = ASTCodeChunker()
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp_dir:
        file_path = os.path.join(tmp_dir, "processor.py")
        with open(file_path, "w", encoding="utf-8") as f:
            f.write(SAMPLE_CODE)

        chunks = chunker.chunk_file(file_path)
        assert len(chunks) >= 3
        chunk_names = {c.name for c in chunks}
        assert "process_data" in chunk_names
        assert "transform" in chunk_names
        assert "test_process_data" in chunk_names


def test_fix_history_store():
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp_dir:
        db_path = os.path.join(tmp_dir, "fix_history.json")
        store = FixHistoryStore(db_file=db_path)

        store.record_fix(
            exception_type="ZeroDivisionError",
            exception_message="division by zero",
            failing_symbol="tax.py::calculate_tax",
            applied_diff="--- a/tax.py\n+++ b/tax.py\n@@ -1 +1 @@\n-rate = 0\n+rate = 0.2",
        )

        matches = store.find_similar_fixes(
            exception_type="ZeroDivisionError",
            exception_message="division by zero",
        )
        assert len(matches) == 1
        assert matches[0].exception_type == "ZeroDivisionError"
        assert "rate = 0.2" in matches[0].applied_diff


def test_embedding_fallback_dimension_is_stable(monkeypatch):
    monkeypatch.delenv("GEMINI_API_KEY", raising=False)
    monkeypatch.delenv("GOOGLE_API_KEY", raising=False)

    embedding_func = GeminiEmbeddingFunction(api_key=None)
    vectors = embedding_func.embed_documents(["def example(): return 1"])

    assert len(vectors) == 1
    assert len(vectors[0]) == embedding_func.embedding_dimension


def test_vector_store_collection_is_dimension_versioned(tmp_path):
    store = CodeVectorStore(persist_dir=str(tmp_path / "chroma"))

    assert store.collection_name.endswith(f"_d{store.embedding_func.embedding_dimension}")


def test_code_rag_agent():
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp_dir:
        db_path = os.path.join(tmp_dir, "fix_history.json")
        fix_history = FixHistoryStore(db_file=db_path)
        vector_store = CodeVectorStore(persist_dir=os.path.join(tmp_dir, "chroma"))

        agent = CodeRAGAgent(vector_store=vector_store, fix_history=fix_history)

        file_path = os.path.join(tmp_dir, "processor.py")
        with open(file_path, "w", encoding="utf-8") as f:
            f.write(SAMPLE_CODE)

        agent.index_repository(tmp_dir)

        suspect = SuspectFunction(
            symbol_id=f"{file_path}::transform",
            file_path=file_path,
            name="transform",
            code="def transform(item: int) -> int:\n    return item * 2",
            rank=1,
            plausibility_reason="Test suspect",
        )

        failure = ParsedFailure(
            failing_file=file_path,
            failing_line=10,
            exception_type="TypeError",
            exception_message="unsupported operand type",
            test_name="test_process_data",
            raw_traceback="Traceback...",
            stack_frames=[],
        )

        context = agent.retrieve_context_for_suspect(suspect, failure)
        assert context.suspect_function.name == "transform"


class _FakeEmbedResponse:
    def __init__(self, count):
        self.embeddings = [type("V", (), {"values": [0.1] * 3072})() for _ in range(count)]


class _RecordingModels:
    """Counts embed_content calls and can fail a set number of times first."""

    def __init__(self, fail_times=0, error=None):
        self.calls = []
        self.fail_times = fail_times
        self.error = error or Exception("429 RESOURCE_EXHAUSTED 'retryDelay': '34s'")

    def embed_content(self, model, contents):
        self.calls.append(contents)
        if len(self.calls) <= self.fail_times:
            raise self.error
        return _FakeEmbedResponse(len(contents))


def _embedder(models):
    from fixate.rag.store import GeminiEmbeddingFunction

    fn = GeminiEmbeddingFunction(api_key="test-key")
    fn._client = type("C", (), {"models": models})()
    return fn


def test_embedding_batches_instead_of_one_request_per_text():
    """The quota bug: 200 texts previously meant 200 API calls charged as one slot."""
    models = _RecordingModels()
    vectors = _embedder(models)._embed([f"chunk {i}" for i in range(250)])

    assert len(vectors) == 250
    # 250 texts at batch size 100 -> 3 calls, not 250.
    assert len(models.calls) == 3
    assert [len(c) for c in models.calls] == [100, 100, 50]


def test_embedding_retries_on_quota_error_then_succeeds():
    models = _RecordingModels(fail_times=1)
    with mock.patch("fixate.rag.store.time.sleep") as slept:
        vectors = _embedder(models)._embed(["one", "two"])

    assert len(vectors) == 2
    assert len(models.calls) == 2  # first failed, second succeeded
    slept.assert_called_once()
    # The server asked for 34s; we must honour it rather than hammering.
    assert slept.call_args[0][0] >= 34.0


def test_embedding_raises_rather_than_returning_hash_vectors():
    """A quota outage must not silently mix incomparable vectors into the index."""
    from fixate.rag.store import EmbeddingUnavailableError

    models = _RecordingModels(fail_times=99)
    with mock.patch("fixate.rag.store.time.sleep"):
        with pytest.raises(EmbeddingUnavailableError):
            _embedder(models)._embed(["one"])


def test_does_not_retry_errors_that_are_not_quota_related():
    """A bad key fails identically no matter how long we wait."""
    from fixate.rag.store import EmbeddingUnavailableError

    models = _RecordingModels(fail_times=99, error=Exception("401 Unauthorized: invalid key"))
    with pytest.raises(EmbeddingUnavailableError):
        _embedder(models)._embed(["one"])
    assert len(models.calls) == 1  # no retries


def test_store_detaches_from_collection_on_embedding_outage():
    """Degrade to keyword retrieval; never write incompatible vectors to disk."""
    from fixate.rag.store import EmbeddingUnavailableError

    store = CodeVectorStore(persist_dir=None)
    store._collection = mock.Mock()
    store._collection.query.side_effect = EmbeddingUnavailableError("quota exhausted")
    store._memory_chunks = []

    store.query_similar_code("anything")

    assert store._collection is None


def test_collection_name_separates_vector_spaces():
    store = CodeVectorStore(persist_dir=None)
    assert store.embedding_func.space in store.collection_name
    assert store.collection_name.endswith(f"_d{store.embedding_func.embedding_dimension}")


def _mk_chunk(chunk_id, name, code):
    from fixate.graph.base_parser import SymbolType

    return CodeChunk(
        chunk_id=chunk_id, file_path=f"{name}.py", name=name,
        symbol_type=SymbolType.FUNCTION, code=code,
        start_line=1, end_line=5, is_test=False,
    )


def test_repositories_do_not_contaminate_each_others_retrieval(tmp_path):
    """Without partitioning, repo B's search returns only repo A's symbols."""
    persist = str(tmp_path / "chroma")

    store_a = CodeVectorStore(persist_dir=persist)
    store_a.index_chunks(
        [_mk_chunk(f"a.py::calc_{i}", f"calc_{i}", f"def calc_{i}(x): return x*{i}") for i in range(8)],
        repo_id="repo_a",
    )

    store_b = CodeVectorStore(persist_dir=persist)
    store_b.index_chunks(
        [_mk_chunk("b.py::only_b", "only_b", "def only_b(): return calc value multiply")],
        repo_id="repo_b",
    )

    results = store_b.query_similar_code("calc multiply", n_results=5)
    assert [c.chunk_id for c in results] == ["b.py::only_b"]
    assert all(not c.chunk_id.startswith("a.py") for c in results)

    # Repo A still sees its own symbols.
    assert all(c.chunk_id.startswith("a.py") for c in store_a.query_similar_code("calc", n_results=3))


def test_reindexing_prunes_symbols_that_no_longer_exist(tmp_path):
    """A renamed or deleted function must not linger in the index forever."""
    persist = str(tmp_path / "chroma")

    store = CodeVectorStore(persist_dir=persist)
    store.index_chunks(
        [_mk_chunk(f"a.py::f{i}", f"f{i}", f"def f{i}(): pass") for i in range(6)], repo_id="repo_a"
    )
    assert len(store._collection.get(where={"repo_id": "repo_a"})["ids"]) == 6

    fresh = CodeVectorStore(persist_dir=persist)
    fresh.index_chunks([_mk_chunk("a.py::f0", "f0", "def f0(): pass")], repo_id="repo_a")
    assert len(fresh._collection.get(where={"repo_id": "repo_a"})["ids"]) == 1


def test_identical_paths_in_different_repos_do_not_collide(tmp_path):
    persist = str(tmp_path / "chroma")

    a = CodeVectorStore(persist_dir=persist)
    a.index_chunks([_mk_chunk("src/utils.py::parse", "parse", "def parse(): return 'A'")], repo_id="repo_a")
    b = CodeVectorStore(persist_dir=persist)
    b.index_chunks([_mk_chunk("src/utils.py::parse", "parse", "def parse(): return 'B'")], repo_id="repo_b")

    assert b._collection.count() == 2  # both survive; ids are namespaced


def test_repository_id_is_stable_across_reclones(tmp_path):
    """Fixate re-clones into a new temp dir each run; the partition must persist."""
    from fixate.rag.agent import repository_id

    def make_clone(dirname, origin):
        repo = tmp_path / dirname
        (repo / ".git").mkdir(parents=True)
        (repo / ".git" / "config").write_text(
            f'[remote "origin"]\n\turl = {origin}\n\tfetch = +refs/heads/*\n', encoding="utf-8"
        )
        return str(repo)

    origin = "https://github.com/devam1912/FinDocs-AI"
    first = repository_id(make_clone("fixate_github_repo_aaaa", origin))
    second = repository_id(make_clone("fixate_github_repo_bbbb", origin))
    other = repository_id(make_clone("fixate_github_repo_cccc", "https://github.com/pallets/flask"))

    assert first == second, "same upstream repo must reuse its partition"
    assert first != other, "different repos must not share a partition"
    assert "FinDocs" in first


def test_repository_id_falls_back_to_path_without_git():
    from fixate.rag.agent import repository_id

    assert repository_id("/tmp/plain_dir") != repository_id("/tmp/other_dir")


class _SingleVectorModels:
    """Mimics an SDK that treats a list of contents as one document."""

    def __init__(self):
        self.calls = []

    def embed_content(self, model, contents):
        self.calls.append(contents)
        # One vector regardless of how many inputs were sent.
        return _FakeEmbedResponse(1)


def test_falls_back_to_per_text_when_batching_returns_one_vector():
    """Batching is an optimization; losing embeddings to it is not acceptable."""
    models = _SingleVectorModels()
    vectors = _embedder(models)._embed(["a", "b", "c"])

    assert len(vectors) == 3
    # One batched attempt, then one call per text.
    assert models.calls[0] == ["a", "b", "c"]
    assert models.calls[1:] == ["a", "b", "c"]


# --------------------------------------------------------------------------
# Quota safety
# --------------------------------------------------------------------------


def test_a_batch_never_exceeds_the_per_minute_token_budget():
    """Count-only batching could send more tokens in one call than a minute allows."""
    from fixate.llm.rate_limiter import estimate_tokens
    from fixate.rag.store import (
        EMBED_MAX_BATCH_TOKENS,
        GeminiEmbeddingFunction,
    )

    # 100 realistic chunks: batching purely by count would put all of them in a
    # single call worth far more than the whole TPM allowance.
    chunks = ["def handler(request):\n    " + ("x = compute(request)\n    " * 60)] * 100
    assert estimate_tokens("".join(chunks)) > EMBED_MAX_BATCH_TOKENS

    for batch in GeminiEmbeddingFunction._batches(chunks):
        assert sum(estimate_tokens(t) for t in batch) <= EMBED_MAX_BATCH_TOKENS


def test_oversized_chunk_is_truncated_rather_than_wedging_the_index():
    """A chunk bigger than a whole request can never embed at any batch size."""
    from fixate.llm.rate_limiter import estimate_tokens
    from fixate.rag.store import EMBED_MAX_TEXT_TOKENS, GeminiEmbeddingFunction

    giant = "y = 1\n" * 200_000
    batches = GeminiEmbeddingFunction._batches([giant])

    assert len(batches) == 1
    assert estimate_tokens(batches[0][0]) <= EMBED_MAX_TEXT_TOKENS


def test_oversized_request_is_clamped_instead_of_crashing_the_limiter():
    """An estimate above the whole budget used to raise IndexError on an empty window."""
    from fixate.llm.rate_limiter import RateLimiter

    limiter = RateLimiter(max_rpm=80, max_tpm=24000, max_rpd=900, name="probe")

    # No sleeping: the point is that this returns at all.
    limiter.acquire(estimated_tokens=40000)

    # It is charged at the ceiling, not at its own inflated estimate, so the
    # accounting cannot go permanently negative on headroom.
    assert sum(tok for _, tok in limiter._token_timestamps) == 24000


def test_embedding_tpm_ceiling_leaves_real_headroom():
    """Observed usage peaked at 28.3K against a 30K provider limit."""
    from fixate.llm.rate_limiter import EMBEDDING_RATE_LIMITER

    provider_ceiling = 30000
    assert EMBEDDING_RATE_LIMITER.max_tpm <= provider_ceiling * 0.85


def test_unchanged_repository_costs_no_embedding_requests():
    """Re-indexing identical source must not re-embed it."""
    from fixate.rag.chunker import CodeChunk, SymbolType
    from fixate.rag.store import CodeVectorStore, _content_hash

    chunk = CodeChunk(
        chunk_id="app.py::handler",
        file_path="app.py",
        name="handler",
        code="def handler():\n    return 1\n",
        symbol_type=SymbolType.FUNCTION,
        start_line=1,
        end_line=2,
        is_test=False,
    )

    store = CodeVectorStore.__new__(CodeVectorStore)
    store._repo_id = "repo"
    store._memory_chunks = []
    store.collection_name = "c"

    class _Collection:
        def __init__(self):
            self.upserts = 0
            self.rows = {}

        def get(self, where=None, include=None):
            return {"ids": list(self.rows), "metadatas": list(self.rows.values())}

        def upsert(self, documents, ids, metadatas):
            self.upserts += 1
            self.rows.update(dict(zip(ids, metadatas)))

        def delete(self, ids=None, where=None):
            for row_id in ids or []:
                self.rows.pop(row_id, None)

    store._collection = _Collection()

    store.index_chunks([chunk], repo_id="repo")
    assert store._collection.upserts == 1
    assert store._collection.rows["repo::app.py::handler"]["content_hash"] == _content_hash(chunk.code)

    # Same source again: nothing to embed.
    store.index_chunks([chunk], repo_id="repo")
    assert store._collection.upserts == 1

    # Edited source: re-embedded.
    edited = chunk.model_copy(update={"code": "def handler():\n    return 2\n"})
    store.index_chunks([edited], repo_id="repo")
    assert store._collection.upserts == 2


def test_deleted_symbols_are_still_evicted_from_the_index():
    """Incremental indexing must not let renamed or removed symbols linger."""
    from fixate.rag.chunker import CodeChunk, SymbolType
    from fixate.rag.store import CodeVectorStore

    def _chunk(name):
        return CodeChunk(
            chunk_id=f"app.py::{name}",
            file_path="app.py",
            name=name,
            code=f"def {name}():\n    return 1\n",
            symbol_type=SymbolType.FUNCTION,
            start_line=1,
            end_line=2,
            is_test=False,
        )

    store = CodeVectorStore.__new__(CodeVectorStore)
    store._repo_id = "repo"
    store._memory_chunks = []
    store.collection_name = "c"

    class _Collection:
        def __init__(self):
            self.rows = {}

        def get(self, where=None, include=None):
            return {"ids": list(self.rows), "metadatas": list(self.rows.values())}

        def upsert(self, documents, ids, metadatas):
            self.rows.update(dict(zip(ids, metadatas)))

        def delete(self, ids=None, where=None):
            for row_id in ids or []:
                self.rows.pop(row_id, None)

    store._collection = _Collection()

    store.index_chunks([_chunk("old_name"), _chunk("kept")], repo_id="repo")
    assert set(store._collection.rows) == {"repo::app.py::old_name", "repo::app.py::kept"}

    store.index_chunks([_chunk("new_name"), _chunk("kept")], repo_id="repo")
    assert set(store._collection.rows) == {"repo::app.py::new_name", "repo::app.py::kept"}
