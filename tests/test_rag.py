"""Unit tests for AST Code Chunker, Vector Store, Fix History, and Code-RAG Agent."""

import os
import tempfile
import pytest
from fixate.rag.chunker import ASTCodeChunker
from fixate.rag.store import CodeVectorStore
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
