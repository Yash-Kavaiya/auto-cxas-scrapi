"""Abstract LLM adapter interface."""
from __future__ import annotations
from abc import ABC, abstractmethod
from dataclasses import dataclass


@dataclass
class LLMResponse:
    content: str
    model: str
    prompt_tokens: int = 0
    completion_tokens: int = 0
    finish_reason: str = "stop"


class LLMAdapter(ABC):
    @abstractmethod
    def complete(self, *, system: str, user: str, max_tokens: int = 2048) -> LLMResponse:
        raise NotImplementedError

    @abstractmethod
    def is_available(self) -> bool:
        raise NotImplementedError
