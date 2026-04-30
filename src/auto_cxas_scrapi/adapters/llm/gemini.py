"""Gemini / Vertex AI LLM adapter."""
from __future__ import annotations
from auto_cxas_scrapi.adapters.llm.base import LLMAdapter, LLMResponse


class GeminiAdapter(LLMAdapter):
    DEFAULT_MODEL = "gemini-2.0-flash"

    def __init__(self, *, model: str = "", project_id: str = "",
                 location: str = "us-central1") -> None:
        self.model = model or self.DEFAULT_MODEL
        self.project_id = project_id
        self.location = location
        self._client = None

    def is_available(self) -> bool:
        try:
            import google.generativeai  # noqa: F401
            return True
        except ImportError:
            return False

    def _get_client(self):
        if self._client is None:
            import google.generativeai as genai
            genai.configure()
            self._client = genai.GenerativeModel(self.model)
        return self._client

    def complete(self, *, system: str, user: str, max_tokens: int = 2048) -> LLMResponse:
        client = self._get_client()
        prompt = f"{system}\n\nUser: {user}"
        response = client.generate_content(
            prompt,
            generation_config={"max_output_tokens": max_tokens},
        )
        text = response.text or ""
        return LLMResponse(content=text, model=self.model, finish_reason="stop")
