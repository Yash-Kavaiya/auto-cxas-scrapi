"""LLM adapter factory — selects backend from AUTO_CXAS_LLM_PROVIDER."""
from __future__ import annotations
from auto_cxas_scrapi.adapters.llm.base import LLMAdapter


def get_llm_adapter(provider: str = "gemini", model: str = "") -> LLMAdapter:
    if provider == "gemini":
        from auto_cxas_scrapi.adapters.llm.gemini import GeminiAdapter
        return GeminiAdapter(model=model)
    elif provider == "anthropic":
        from auto_cxas_scrapi.adapters.llm.anthropic import AnthropicAdapter
        return AnthropicAdapter(model=model)
    elif provider == "openai":
        from auto_cxas_scrapi.adapters.llm.openai_adapter import OpenAIAdapter
        return OpenAIAdapter(model=model)
    else:
        raise ValueError(f"Unknown LLM provider: {provider!r}. Use gemini|anthropic|openai.")
