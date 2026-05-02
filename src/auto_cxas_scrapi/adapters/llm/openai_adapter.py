"""OpenAI / Codex adapter."""
from __future__ import annotations

import os

from auto_cxas_scrapi.adapters.llm.base import LLMAdapter, LLMResponse


class OpenAIAdapter(LLMAdapter):
    DEFAULT_MODEL = "gpt-4o"

    def __init__(self, *, model: str = "", api_key: str = "") -> None:
        self.model = model or self.DEFAULT_MODEL
        self.api_key = api_key or os.environ.get("OPENAI_API_KEY", "")
        self._client = None

    def is_available(self) -> bool:
        try:
            import openai  # noqa: F401
            return bool(self.api_key)
        except ImportError:
            return False

    def _get_client(self):
        if self._client is None:
            import openai
            self._client = openai.OpenAI(api_key=self.api_key)
        return self._client

    def complete(self, *, system: str, user: str, max_tokens: int = 2048) -> LLMResponse:
        client = self._get_client()
        response = client.chat.completions.create(
            model=self.model,
            max_tokens=max_tokens,
            messages=[
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
        )
        choice = response.choices[0]
        return LLMResponse(
            content=choice.message.content or "",
            model=self.model,
            prompt_tokens=response.usage.prompt_tokens,
            completion_tokens=response.usage.completion_tokens,
            finish_reason=choice.finish_reason or "stop",
        )
