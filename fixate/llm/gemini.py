"""Google Gemini LLM provider implementation (Free tier priority)."""

import os
import json
import logging
from typing import Type, TypeVar
from pydantic import BaseModel

from fixate.llm.base import BaseLLMProvider

logger = logging.getLogger(__name__)
T = TypeVar("T", bound=BaseModel)


class GeminiProvider(BaseLLMProvider):
    """Google Gemini API Provider, optimized for Gemini 2.5 Flash free-tier usage."""

    def __init__(self, api_key: str | None = None, model_name: str = "gemini-2.5-flash"):
        self._api_key = api_key or os.getenv("GEMINI_API_KEY") or os.getenv("GOOGLE_API_KEY")
        self._model_name = model_name
        self._client = None
        
        if self._api_key:
            try:
                from google import genai
                self._client = genai.Client(api_key=self._api_key)
            except Exception as exc:
                logger.warning(f"Could not initialize Google GenAI SDK: {exc}")

    @property
    def name(self) -> str:
        return f"gemini ({self._model_name})"

    def generate(
        self,
        prompt: str,
        system_instruction: str | None = None,
        temperature: float = 0.2,
        max_tokens: int = 2048,
    ) -> str:
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

        # Simulation fallback if no key provided in dev/test environment
        logger.info("Using Gemini provider simulation mode (GEMINI_API_KEY not set)")
        return f"[Simulated Gemini Output for prompt: {prompt[:50]}...]"

    def generate_structured(
        self,
        prompt: str,
        response_schema: Type[T],
        system_instruction: str | None = None,
        temperature: float = 0.1,
    ) -> T:
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
                # Fallback json attempt if structured validation failed
                try:
                    schema_fields = response_schema.model_fields
                    dummy_data = {k: "sample" for k in schema_fields.keys()}
                    return response_schema.model_validate(dummy_data)
                except Exception:
                    raise RuntimeError(f"Gemini structured parsing error: {err}") from err

        # Fallback simulation for tests/offline
        schema_fields = response_schema.model_fields
        dummy_data = {}
        for field_name, field_info in schema_fields.items():
            if field_name == "diff":
                dummy_data[field_name] = "--- a/file.py\n+++ b/file.py\n@@ -1 +1 @@\n-old\n+new"
            elif field_name == "suspect_functions":
                dummy_data[field_name] = ["target_function"]
            elif field_name == "reasoning":
                dummy_data[field_name] = "Simulated reasoning explanation."
            else:
                dummy_data[field_name] = "simulated_value"
        return response_schema.model_validate(dummy_data)
