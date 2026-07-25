"""ChromaDB vector store wrapper for indexing and retrieving code chunks."""

import os
import logging
from typing import List, Optional
from fixate.rag.chunker import CodeChunk

logger = logging.getLogger(__name__)


class FastSimpleEmbeddingFunction:
    """Lightweight deterministic embedding function to eliminate external ONNX model download delays."""
    def __call__(self, input: List[str]) -> List[List[float]]:
        return self._embed(input)

    def embed_query(self, input: str | List[str]) -> List[List[float]]:
        if isinstance(input, str):
            input = [input]
        return self._embed(input)

    def embed_documents(self, input: List[str]) -> List[List[float]]:
        return self._embed(input)

    def _embed(self, input: List[str]) -> List[List[float]]:
        embeddings = []
        for text in input:
            vec = [0.0] * 64
            for idx, char in enumerate(text[:500]):
                vec[ord(char) % 64] += 1.0
            norm = sum(x * x for x in vec) ** 0.5 or 1.0
            embeddings.append([x / norm for x in vec])
        return embeddings

    def name(self) -> str:
        return "fast_simple_embedding"


class CodeVectorStore:
    """Vector store for indexing AST code chunks and performing semantic code retrieval."""

    def __init__(self, collection_name: str = "fixate_codebase", persist_dir: Optional[str] = None):
        self.collection_name = collection_name
        self.persist_dir = persist_dir or os.path.join(os.getcwd(), "chroma_db")
        self._client = None
        self._collection = None
        self._memory_chunks: List[CodeChunk] = []  # Fallback in-memory store

        try:
            import chromadb
            self._client = chromadb.PersistentClient(path=self.persist_dir)
            embedding_func = FastSimpleEmbeddingFunction()
            self._collection = self._client.get_or_create_collection(
                name=self.collection_name,
                embedding_function=embedding_func,
            )
            logger.info(f"Initialized ChromaDB persistent vector store at {self.persist_dir}")
        except Exception as exc:
            logger.warning(f"Could not initialize ChromaDB vector store: {exc}. Using in-memory fallback store.")

    def index_chunks(self, chunks: List[CodeChunk]):
        """Index a list of CodeChunk objects into the vector database."""
        if not chunks:
            return

        self._memory_chunks.extend(chunks)

        if self._collection:
            try:
                documents = [c.code for c in chunks]
                ids = [c.chunk_id for c in chunks]
                metadatas = [
                    {
                        "file_path": c.file_path,
                        "name": c.name,
                        "symbol_type": c.symbol_type.value,
                        "is_test": str(c.is_test),
                    }
                    for c in chunks
                ]
                self._collection.upsert(documents=documents, ids=ids, metadatas=metadatas)
                logger.info(f"Indexed {len(chunks)} chunks into ChromaDB collection '{self.collection_name}'")
            except Exception as err:
                logger.error(f"ChromaDB indexing error: {err}")

    def query_similar_code(self, query_text: str, n_results: int = 3) -> List[CodeChunk]:
        """Query vector database for most semantically relevant code chunks matching query_text."""
        if self._collection:
            try:
                res = self._collection.query(query_texts=[query_text], n_results=n_results)
                retrieved: List[CodeChunk] = []
                if res and "ids" in res and res["ids"]:
                    retrieved_ids = res["ids"][0]
                    id_to_chunk = {c.chunk_id: c for c in self._memory_chunks}
                    for chunk_id in retrieved_ids:
                        if chunk_id in id_to_chunk:
                            retrieved.append(id_to_chunk[chunk_id])
                if retrieved:
                    return retrieved
            except Exception as exc:
                logger.error(f"ChromaDB query error: {exc}")

        # Fallback substring / keyword match across in-memory chunks
        query_words = set(query_text.lower().split())
        matched = []
        for chunk in self._memory_chunks:
            score = sum(1 for w in query_words if w in chunk.code.lower() or w in chunk.name.lower())
            if score > 0:
                matched.append((score, chunk))
        
        matched.sort(key=lambda x: x[0], reverse=True)
        return [chunk for _, chunk in matched[:n_results]]
