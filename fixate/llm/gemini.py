"""Google Gemini LLM provider implementation with Gemini 3.5 Flash Lite & Rate Limiting."""

import os
import json
import logging
from typing import Type, TypeVar, get_origin, get_args
from pydantic import BaseModel

from fixate.llm.base import BaseLLMProvider
from fixate.llm.rate_limiter import LLM_RATE_LIMITER, estimate_tokens

logger = logging.getLogger(__name__)
T = TypeVar("T", bound=BaseModel)
_UNSET = object()


def _dummy_value_for_annotation(annotation):
    """Build a small valid value for simulation-mode structured responses."""
    origin = get_origin(annotation)
    args = get_args(annotation)

    if origin in (list, list) or annotation is list:
        return []
    if annotation is str:
        return "simulated_value"
    if annotation is int:
        return 1
    if annotation is float:
        return 1.0
    if annotation is bool:
        return False
    if isinstance(annotation, type) and issubclass(annotation, BaseModel):
        return _dummy_payload_for_schema(annotation)
    if origin is not None and args:
        return _dummy_value_for_annotation(args[0])
    return "simulated_value"


def _dummy_payload_for_schema(schema: Type[BaseModel]) -> dict:
    dummy_data = {}
    for field_name, field_info in schema.model_fields.items():
        if field_name == "suspect_functions":
            dummy_data[field_name] = ["target_function"]
        elif field_name == "reasoning":
            dummy_data[field_name] = "Simulated reasoning explanation."
        elif field_name == "rankings":
            dummy_data[field_name] = []
        else:
            dummy_data[field_name] = _dummy_value_for_annotation(field_info.annotation)
    return dummy_data


class GeminiProvider(BaseLLMProvider):
    """Google Gemini API Provider, configured for Gemini 3.5 Flash Lite with strict rate limiting."""

    def __init__(
        self,
        api_key: str | None | object = _UNSET,
        model_name: str = "gemini-3.5-flash-lite",
    ):
        if api_key is _UNSET:
            self._api_key = os.getenv("GEMINI_API_KEY") or os.getenv("GOOGLE_API_KEY")
        else:
            self._api_key = api_key
        self._model_name = os.getenv("GEMINI_LLM_MODEL") or model_name
        self._client = None

        if self._api_key and self._api_key != "your_gemini_api_key_here":
            try:
                from google import genai
                self._client = genai.Client(api_key=self._api_key)
            except Exception as exc:
                logger.warning(f"Could not initialize Google GenAI SDK: {exc}")

    @property
    def name(self) -> str:
        return f"gemini ({self._model_name})"

    @property
    def is_live(self) -> bool:
        """False when no API key is configured; generate_* then return placeholders."""
        return self._client is not None

    def generate(
        self,
        prompt: str,
        system_instruction: str | None = None,
        temperature: float = 0.2,
        max_tokens: int = 2048,
    ) -> str:
        est_tokens = estimate_tokens(prompt) + max_tokens
        LLM_RATE_LIMITER.acquire(estimated_tokens=est_tokens)

        if self._client:
            try:
                from google.genai import types
                config = types.GenerateContentConfig(
                    temperature=temperature,
                    max_output_tokens=max_tokens,
                    system_instruction=system_instruction,
                )
                response = self._client.models.generate_content(
                    model=self._model_name,
                    contents=prompt,
                    config=config,
                )
                return response.text or ""
            except Exception as err:
                logger.error(f"Gemini API generation failed: {err}")
                raise RuntimeError(f"Gemini API call error: {err}") from err

        logger.info("Using Gemini provider simulation mode (GEMINI_API_KEY not set)")
        return f"[Simulated Gemini Output for prompt: {prompt[:50]}...]"

    def generate_structured(
        self,
        prompt: str,
        response_schema: Type[T],
        system_instruction: str | None = None,
        temperature: float = 0.1,
    ) -> T:
        est_tokens = estimate_tokens(prompt) + 500
        LLM_RATE_LIMITER.acquire(estimated_tokens=est_tokens)

        if self._client:
            try:
                from google.genai import types
                config = types.GenerateContentConfig(
                    temperature=temperature,
                    response_mime_type="application/json",
                    response_schema=response_schema,
                    system_instruction=system_instruction,
                )
                response = self._client.models.generate_content(
                    model=self._model_name,
                    contents=prompt,
                    config=config,
                )
                raw_json = response.text or "{}"
                return response_schema.model_validate_json(raw_json)
            except Exception as err:
                logger.error(f"Gemini structured generation failed: {err}")
                raise RuntimeError(f"Gemini API structured generation failed: {err}") from err
        
        logger.info("Using Gemini structured simulation mode (GEMINI_API_KEY not set)")
        return response_schema.model_validate(_dummy_payload_for_schema(response_schema))
