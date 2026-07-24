"""Abstract base parser interface for multi-language AST symbol extraction."""

from abc import ABC, abstractmethod
from enum import Enum
from typing import List, Optional
from pydantic import BaseModel, Field


class SymbolType(str, Enum):
    FUNCTION = "function"
    CLASS = "class"
    METHOD = "method"
    FILE = "file"
    TEST = "test"


class CodeSymbol(BaseModel):
    """Data model representing a extracted codebase symbol (function/class/test)."""
    id: str = Field(..., description="Unique qualified identifier, e.g. file.py::function_name")
    name: str = Field(..., description="Short name of the symbol")
    symbol_type: SymbolType = Field(..., description="Type of symbol")
    file_path: str = Field(..., description="Absolute or relative file path")
    start_line: int = Field(..., description="Start line number 1-indexed")
    end_line: int = Field(..., description="End line number 1-indexed")
    code: str = Field(..., description="Raw code snippet contents")
    docstring: Optional[str] = Field(None, description="Extracted docstring if present")
    calls: List[str] = Field(default_factory=list, description="List of called symbol names")
    imports: List[str] = Field(default_factory=list, description="List of imported module/symbol names")
    is_test: bool = Field(False, description="Whether this symbol represents a test")


class BaseLanguageParser(ABC):
    """Extensible language parser interface for multi-language AST extraction."""

    @abstractmethod
    def supports_file(self, file_path: str) -> bool:
        """Check if parser handles the given file path extension."""
        pass

    @abstractmethod
    def parse_file(self, file_path: str) -> List[CodeSymbol]:
        """Parse source file into a list of CodeSymbol instances."""
        pass

    @abstractmethod
    def parse_code(self, code_string: str, file_path: str = "virtual.py") -> List[CodeSymbol]:
        """Parse source code string directly into CodeSymbol instances."""
        pass
