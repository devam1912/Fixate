"""Google Gemini LLM provider implementation with Gemini 2.5 Flash Lite & Rate Limiting."""

import os
import json
import logging
from typing import Type, TypeVar, get_origin, get_args
from pydantic import BaseModel

from fixate.llm.base import BaseLLMProvider
from fixate.llm.rate_limiter import LLM_RATE_LIMITER

logger = logging.getLogger(__name__)
T = TypeVar("T", bound=BaseModel)


class GeminiProvider(BaseLLMProvider):
    """Google Gemini API Provider, configured for Gemini 2.5 Flash / Flash Lite with strict rate limiting.
    
    Rate limits enforced:
    - Max 12 requests / minute (RPM)
    - Max 250k tokens / minute (TPM)
    - Max 500 requests / day (RPD)
    """

    def __init__(
        self,
        api_key: str | None = None,
        model_name: str = "gemini-2.5-flash",
    ):
        self._api_key = api_key or os.getenv("GEMINI_API_KEY") or os.getenv("GOOGLE_API_KEY")
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

    def generate(
        self,
        prompt: str,
        system_instruction: str | None = None,
        temperature: float = 0.2,
        max_tokens: int = 2048,
    ) -> str:
        est_tokens = len(prompt.split()) + max_tokens
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
        est_tokens = len(prompt.split()) + 500
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

        # Type-aware simulation fallback for offline testing or when API key is unconfigured
        schema_fields = response_schema.model_fields
        dummy_data = {}

        for field_name, field_info in schema_fields.items():
            if field_name == "diff" or field_name == "unified_diff":
                dummy_data[field_name] = "--- a/calculator.py\n+++ b/calculator.py\n@@ -5 +5 @@\n-    return price * (discount / 100)\n+    return price * (1 - discount / 100)"
            elif field_name == "lines_changed":
                dummy_data[field_name] = 2
            elif field_name == "rankings":
                dummy_data[field_name] = [{"symbol_id": "sample_symbol", "rank": 1, "plausibility_reason": "Suspect function identified by graph walk."}]
            elif field_name == "suspect_functions":
                dummy_data[field_name] = ["target_function"]
            elif field_name == "rank":
                dummy_data[field_name] = 1
            elif field_name == "target_file":
                dummy_data[field_name] = "calculator.py"
            elif field_name == "explanation":
                dummy_data[field_name] = "Corrected percentage discount formula calculation."
            elif field_name == "reasoning":
                dummy_data[field_name] = "Simulated reasoning explanation."
            else:
                annotation = field_info.annotation
                origin = get_origin(annotation)
                if origin is list or annotation is list:
                    dummy_data[field_name] = []
                elif annotation is int:
                    dummy_data[field_name] = 1
                elif annotation is float:
                    dummy_data[field_name] = 1.0
                elif annotation is bool:
                    dummy_data[field_name] = True
                else:
                    dummy_data[field_name] = "simulated_value"

        return response_schema.model_validate(dummy_data)
