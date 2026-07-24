"""Unit tests for LLM provider abstraction and swappability."""

import pytest
from pydantic import BaseModel
from fixate.llm.base import BaseLLMProvider
from fixate.llm.gemini import GeminiProvider
from fixate.llm.openai_compat import OpenAICompatibleProvider
from fixate.llm.factory import get_llm_provider


class SampleSchema(BaseModel):
    suspect_functions: list[str]
    reasoning: str


def test_gemini_provider_instantiation():
    provider = GeminiProvider()
    assert isinstance(provider, BaseLLMProvider)
    assert "gemini" in provider.name.lower()


def test_openai_provider_instantiation():
    provider = OpenAICompatibleProvider()
    assert isinstance(provider, BaseLLMProvider)
    assert "openai-compat" in provider.name.lower()


def test_factory_swappability(monkeypatch):
    monkeypatch.setenv("FIXATE_LLM_PROVIDER", "gemini")
    provider1 = get_llm_provider()
    assert isinstance(provider1, GeminiProvider)

    monkeypatch.setenv("FIXATE_LLM_PROVIDER", "openai")
    provider2 = get_llm_provider()
    assert isinstance(provider2, OpenAICompatibleProvider)

    monkeypatch.setenv("FIXATE_LLM_PROVIDER", "ollama")
    provider3 = get_llm_provider()
    assert isinstance(provider3, OpenAICompatibleProvider)


def test_gemini_simulation_generation():
    provider = GeminiProvider(api_key=None)
    response = provider.generate("Test prompt")
    assert isinstance(response, str)
    assert len(response) > 0


def test_gemini_structured_generation():
    provider = GeminiProvider(api_key=None)
    result = provider.generate_structured("Analyze failure", SampleSchema)
    assert isinstance(result, SampleSchema)
    assert isinstance(result.suspect_functions, list)
    assert isinstance(result.reasoning, str)


def test_openai_simulation_generation():
    provider = OpenAICompatibleProvider()
    response = provider.generate("Test prompt")
    assert isinstance(response, str)
    assert len(response) > 0


def test_openai_structured_generation():
    provider = OpenAICompatibleProvider()
    result = provider.generate_structured("Analyze failure", SampleSchema)
    assert isinstance(result, SampleSchema)
    assert isinstance(result.suspect_functions, list)
    assert isinstance(result.reasoning, str)
