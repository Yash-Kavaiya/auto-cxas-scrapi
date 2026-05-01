"""Anthropic Claude adapter — supports Claude Code workflow."""
from __future__ import annotations
import os
from auto_cxas_scrapi.adapters.llm.base import LLMAdapter, LLMResponse


class AnthropicAdapter(LLMAdapter):
    DEFAULT_MODEL = "claude-sonnet-4-6"

    def __init__(self, *, model: str = "", api_key: str = "") -> None:
        self.model = model or self.DEFAULT_MODEL
        self.api_key = api_key or os.environ.get("ANTHROPIC_API_KEY", "")
        self._client = None

    def is_available(self) -> bool:
        try:
            import anthropic  # noqa: F401
            return bool(self.api_key)
        except ImportError:
            return False

    def _get_client(self):
        if self._client is None:
            import anthropic
            self._client = anthropic.Anthropic(api_key=self.api_key)
        return self._client

    def complete(self, *, system: str, user: str, max_tokens: int = 2048) -> LLMResponse:
        client = self._get_client()
        msg = client.messages.create(
            model=self.model,
            max_tokens=max_tokens,
            system=system,
            messages=[{"role": "user", "content": user}],
        )
        content = msg.content[0].text if msg.content else ""
        return LLMResponse(
            content=content,
            model=self.model,
            prompt_tokens=msg.usage.input_tokens,
            completion_tokens=msg.usage.output_tokens,
            finish_reason=msg.stop_reason or "stop",
        )
