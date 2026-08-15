"""Factory module for instantiating and swapping LLM provider instances."""

import os
import logging
from fixate.llm.base import BaseLLMProvider
from fixate.llm.gemini import GeminiProvider
from fixate.llm.openai_compat import OpenAICompatibleProvider

try:
    from dotenv import load_dotenv
except Exception:  # pragma: no cover - dotenv is optional at runtime
    load_dotenv = None

logger = logging.getLogger(__name__)


def get_llm_provider(provider_type: str | None = None) -> BaseLLMProvider:
    """Instantiate and return an LLM provider instance based on environment config or explicit type.
    
    Args:
        provider_type: Provider identifier ("gemini", "openai", "ollama"). Defaults to FIXATE_LLM_PROVIDER env var.
        
    Returns:
        Instance implementing BaseLLMProvider.
    """
    if load_dotenv is not None:
        load_dotenv()

    selected = (provider_type or os.getenv("FIXATE_LLM_PROVIDER") or "gemini").lower().strip()

    if selected in ("gemini", "google"):
        logger.info("Initializing Gemini LLM Provider (Free Tier Priority)")
        return GeminiProvider(api_key=os.getenv("GEMINI_API_KEY") or os.getenv("GOOGLE_API_KEY"))

    elif selected in ("openai", "gpt"):
        logger.info("Initializing OpenAI LLM Provider")
        return OpenAICompatibleProvider()

    elif selected in ("ollama", "local"):
        logger.info("Initializing Ollama Local LLM Provider")
        base_url = os.getenv("OLLAMA_BASE_URL", "http://localhost:11434/v1")
        model_name = os.getenv("OLLAMA_MODEL", "llama3")
        return OpenAICompatibleProvider(base_url=base_url, model_name=model_name)

    else:
        logger.warning(f"Unknown LLM provider '{selected}', defaulting to GeminiProvider")
        return GeminiProvider()
