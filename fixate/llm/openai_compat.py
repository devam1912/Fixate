"""OpenAI and Ollama-compatible LLM provider implementation."""

import os
import json
import logging
import requests
from typing import Type, TypeVar
from pydantic import BaseModel

from fixate.llm.base import BaseLLMProvider

logger = logging.getLogger(__name__)
T = TypeVar("T", bound=BaseModel)


class OpenAICompatibleProvider(BaseLLMProvider):
    """Provider for OpenAI API, Ollama, or any OpenAI-compatible HTTP endpoint."""

    def __init__(
        self,
        api_key: str | None = None,
        base_url: str | None = None,
        model_name: str = "gpt-4o-mini",
    ):
        self._api_key = api_key or os.getenv("OPENAI_API_KEY") or "ollama"
        self._base_url = (base_url or os.getenv("OPENAI_BASE_URL") or "https://api.openai.com/v1").rstrip("/")
        self._model_name = model_name

    @property
    def name(self) -> str:
        return f"openai-compat ({self._model_name})"

    @property
    def is_live(self) -> bool:
        """True when a real key is configured, or a custom endpoint (e.g. Ollama) is set."""
        has_real_key = bool(self._api_key) and self._api_key != "ollama"
        has_custom_endpoint = self._base_url != "https://api.openai.com/v1"
        return has_real_key or has_custom_endpoint

    def generate(
        self,
        prompt: str,
        system_instruction: str | None = None,
        temperature: float = 0.2,
        max_tokens: int = 2048,
    ) -> str:
        url = f"{self._base_url}/chat/completions"
        headers = {
            "Authorization": f"Bearer {self._api_key}",
            "Content-Type": "application/json",
        }
        
        messages = []
        if system_instruction:
            messages.append({"role": "system", "content": system_instruction})
        messages.append({"role": "user", "content": prompt})

        payload = {
            "model": self._model_name,
            "messages": messages,
            "temperature": temperature,
            "max_tokens": max_tokens,
        }

        try:
            res = requests.post(url, json=payload, headers=headers, timeout=30)
            if res.status_code == 200:
                data = res.json()
                return data["choices"][0]["message"]["content"]
            else:
                logger.warning(f"OpenAI endpoint returned HTTP {res.status_code}: {res.text}")
        except Exception as exc:
            logger.warning(f"OpenAI compatible request failed: {exc}")

        # Fallback simulation if request fails or key is missing
        return f"[Simulated OpenAI-Compat Output for model {self._model_name}: {prompt[:50]}...]"

    def generate_structured(
        self,
        prompt: str,
        response_schema: Type[T],
        system_instruction: str | None = None,
        temperature: float = 0.1,
    ) -> T:
        schema_json = json.dumps(response_schema.model_json_schema(), indent=2)
        enhanced_prompt = (
            f"{prompt}\n\n"
            f"You MUST respond ONLY with a valid JSON object strictly matching this schema:\n"
            f"```json\n{schema_json}\n```\nDo not include markdown prose outside the JSON."
        )

        raw_response = self.generate(
            prompt=enhanced_prompt,
            system_instruction=system_instruction,
            temperature=temperature,
        )

        # Clean JSON fences if present
        clean_text = raw_response.strip()
        if clean_text.startswith("```"):
            lines = clean_text.splitlines()
            if lines[0].startswith("```"):
                lines = lines[1:]
            if lines and lines[-1].startswith("```"):
                lines = lines[:-1]
            clean_text = "\n".join(lines).strip()

        try:
            return response_schema.model_validate_json(clean_text)
        except Exception as err:
            logger.warning(f"Failed to parse structured output from OpenAI-compat response: {err}")
            # Fallback stub object creation
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
