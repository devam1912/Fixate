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
from typing import List, Optional
from pydantic import BaseModel, Field

from fixate.graph.base_parser import BaseLanguageParser, SymbolType

logger = logging.getLogger(__name__)

_SKIP_DIRS = (
    ".git", "__pycache__", "venv", ".venv", "node_modules", "dist", "build",
    "chroma_db", ".pytest_cache", ".fixate_venv", "coverage",
)


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

    def __init__(self, parsers: Optional[List[BaseLanguageParser]] = None):
        if parsers is None:
            from fixate.languages import registry

            parsers = [toolchain.parser() for toolchain in registry.all_enabled()]
        self.parsers = parsers

    def parser_for(self, file_path: str) -> Optional[BaseLanguageParser]:
        """The extractor owning this file, or None if the language is unsupported."""
        return next((p for p in self.parsers if p.supports_file(file_path)), None)

    def chunk_file(self, file_path: str) -> List[CodeChunk]:
        """Chunk a source file into AST semantic chunks."""
        parser = self.parser_for(file_path)
        if parser is None:
            return []

        symbols = parser.parse_file(file_path)
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
        """Recursively chunk every supported source file along AST boundaries."""
        all_chunks: List[CodeChunk] = []

        for root, dirs, files in os.walk(root_dir):
            # Prune in place so os.walk never descends into vendored trees; the
            # previous substring test on `root` also rejected legitimate paths that
            # merely contained one of these names.
            dirs[:] = [d for d in dirs if d not in _SKIP_DIRS]
            for file in files:
                full_path = os.path.normpath(os.path.join(root, file))
                all_chunks.extend(self.chunk_file(full_path))

        logger.info(
            "Chunked directory %s: %d AST semantic chunks generated", root_dir, len(all_chunks)
        )
        return all_chunks
