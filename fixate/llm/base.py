"""Abstract base interface for swappable LLM providers."""

from abc import ABC, abstractmethod
from typing import Any, TypeVar, Type
from pydantic import BaseModel

T = TypeVar("T", bound=BaseModel)


class BaseLLMProvider(ABC):
    """Abstract interface defining standard LLM provider contracts."""

    @property
    @abstractmethod
    def name(self) -> str:
        """Return the provider identification name."""
        pass

    @abstractmethod
    def generate(
        self,
        prompt: str,
        system_instruction: str | None = None,
        temperature: float = 0.2,
        max_tokens: int = 2048,
    ) -> str:
        """Generate unstructured text response from the model.
        
        Args:
            prompt: User input prompt string.
            system_instruction: Optional system instruction prompt.
            temperature: Sampling temperature (0.0 to 1.0).
            max_tokens: Token generation ceiling.
            
        Returns:
            Generated text string response.
        """
        pass

    @abstractmethod
    def generate_structured(
        self,
        prompt: str,
        response_schema: Type[T],
        system_instruction: str | None = None,
        temperature: float = 0.1,
    ) -> T:
        """Generate a structured response adhering to a Pydantic schema model.
        
        Args:
            prompt: User input prompt string.
            response_schema: Target Pydantic model class.
            system_instruction: Optional system instruction prompt.
            temperature: Sampling temperature.
            
        Returns:
            Instance of the requested Pydantic schema model.
        """
        pass
