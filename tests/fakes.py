"""Test doubles for the LLM layer.

The production stages refuse to run without a live model, so exercising the happy
path needs a provider that reports itself live and returns a known answer. Keeping
these fakes in the test tree is the whole point: the previous design shipped the
equivalent behaviour inside the production patch generator, where it silently
substituted scripted edits for real reasoning on live repositories.
"""

from typing import Callable, Dict, List, Optional, Type, TypeVar

from pydantic import BaseModel

from fixate.llm.base import BaseLLMProvider

T = TypeVar("T", bound=BaseModel)


class FakeLLMProvider(BaseLLMProvider):
    """A live-reporting provider returning responses queued per schema.

    Args:
        responses: schema name -> a response instance, or a callable taking the
            prompt and returning one. Callables allow a fake to react to feedback
            from a previous attempt, which is how the retry loop is tested.
    """

    def __init__(self, responses: Optional[Dict[str, object]] = None, live: bool = True):
        self._responses = responses or {}
        self._live = live
        self.prompts: List[str] = []

    @property
    def name(self) -> str:
        return "fake"

    @property
    def is_live(self) -> bool:
        return self._live

    def generate(
        self,
        prompt: str,
        system_instruction: str | None = None,
        temperature: float = 0.2,
        max_tokens: int = 2048,
    ) -> str:
        self.prompts.append(prompt)
        return "fake response"

    def generate_structured(
        self,
        prompt: str,
        response_schema: Type[T],
        system_instruction: str | None = None,
        temperature: float = 0.1,
    ) -> T:
        self.prompts.append(prompt)
        queued = self._responses.get(response_schema.__name__)
        if queued is None:
            raise RuntimeError(
                f"FakeLLMProvider has no response queued for {response_schema.__name__}."
            )
        if isinstance(queued, Callable):
            return queued(prompt)
        return queued
