"""AST-boundary semantic code chunker for Python code bases.

Architectural Design Note:
Naive character-count or line-count chunking cuts code arbitrarily across block boundaries,
splitting function definitions, variable scopes, and try/except blocks in half.
This corrupts Python AST syntax and destroys semantic context for code embeddings and LLM reasoning.
AST-boundary chunking respects semantic code units (functions, classes, methods), ensuring that
every chunk is a syntactically valid, self-contained code symbol.
"""

import os
import logging
from typing import List
from pydantic import BaseModel, Field

from fixate.graph.python_parser import PythonASTParser
from fixate.graph.base_parser import SymbolType

logger = logging.getLogger(__name__)


class CodeChunk(BaseModel):
    chunk_id: str = Field(..., description="Unique chunk identifier, e.g. file.py::function_name")
    file_path: str = Field(..., description="File path containing the code chunk")
    name: str = Field(..., description="Function, class, or module name")
    symbol_type: SymbolType = Field(..., description="Type of symbol represented")
    code: str = Field(..., description="Full self-contained code snippet")
    start_line: int = Field(..., description="Start line 1-indexed")
    end_line: int = Field(..., description="End line 1-indexed")
    is_test: bool = Field(False, description="Whether this chunk represents a test")


class ASTCodeChunker:
    """Chunks source code repositories along syntactic AST boundaries (functions and classes)."""

    def __init__(self):
        self.parser = PythonASTParser()

    def chunk_file(self, file_path: str) -> List[CodeChunk]:
        """Chunk a single Python file into AST semantic chunks."""
        symbols = self.parser.parse_file(file_path)
        chunks: List[CodeChunk] = []

        for sym in symbols:
            chunks.append(
                CodeChunk(
                    chunk_id=sym.id,
                    file_path=sym.file_path,
                    name=sym.name,
                    symbol_type=sym.symbol_type,
                    code=sym.code,
                    start_line=sym.start_line,
                    end_line=sym.end_line,
                    is_test=sym.is_test,
                )
            )

        return chunks

    def chunk_directory(self, root_dir: str) -> List[CodeChunk]:
        """Recursively chunk all Python files in a directory along AST boundaries."""
        all_chunks: List[CodeChunk] = []

        for root, _, files in os.walk(root_dir):
            if any(skip in root for skip in (".git", "__pycache__", "venv", ".venv", "node_modules", "dist", "chroma_db")):
                continue
            for file in files:
                if file.endswith(".py"):
                    full_path = os.path.normpath(os.path.join(root, file))
                    file_chunks = self.chunk_file(full_path)
                    all_chunks.extend(file_chunks)

        logger.info(f"Chunked directory {root_dir}: {len(all_chunks)} AST semantic chunks generated")
        return all_chunks
