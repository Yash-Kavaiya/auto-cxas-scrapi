"""Production feedback ingestor — CX Agent Studio conversations → candidate tests.

This is the production half of the "failures become new test cases" arrow.
It pulls recent conversation history from CX Agent Studio (via ``ScrapiAdapter``),
keeps only the ones that show a failure signal (thumbs-down, low rating,
escalation, or no-match), and converts each into a benchmark candidate that
``BenchmarkManager`` can stage and (once reproduced) promote.
"""
from __future__ import annotations

import logging
from typing import Any

log = logging.getLogger(__name__)

# Below this explicit rating a conversation is treated as a failure.
_LOW_RATING_THRESHOLD = 3.0

# Maps a coarse failure signal to the intent we expect a healthy agent to hit.
_SIGNAL_INTENT = {
    "escalated": "escalation",
    "no_match": "fallback",
}


class FeedbackIngestor:
    """Turn real production failures into staged benchmark candidates."""

    def __init__(self, scrapi_adapter: Any) -> None:
        self.scrapi = scrapi_adapter

    def harvest(
        self,
        *,
        app_name: str = "",
        lookback_hours: int = 24,
        max_conversations: int = 200,
    ) -> list[dict[str, Any]]:
        """Fetch recent conversations and return failure candidates (GoldenTest-shaped)."""
        try:
            conversations = self.scrapi.list_recent_conversations(
                app_name,
                lookback_hours=lookback_hours,
                max_conversations=max_conversations,
            )
        except Exception as exc:
            log.warning("FeedbackIngestor.harvest: history fetch failed: %s", exc)
            return []

        candidates: list[dict[str, Any]] = []
        for conv in conversations:
            if not self._is_failure(conv):
                continue
            candidate = self._to_candidate(conv)
            if candidate is not None:
                candidates.append(candidate)
        log.info(
            "FeedbackIngestor: %d/%d conversations flagged as failures.",
            len(candidates), len(conversations),
        )
        return candidates

    # ------------------------------------------------------------------
    # Internals
    # ------------------------------------------------------------------

    @staticmethod
    def _is_failure(conv: dict[str, Any]) -> bool:
        if conv.get("thumbs_down") or conv.get("escalated") or conv.get("no_match"):
            return True
        rating = conv.get("rating")
        return isinstance(rating, (int | float)) and rating < _LOW_RATING_THRESHOLD

    @staticmethod
    def _to_candidate(conv: dict[str, Any]) -> dict[str, Any] | None:
        utterance = (conv.get("user_utterance") or "").strip()
        if not utterance:
            return None
        # Prefer the detected intent; otherwise infer from the failure signal.
        intent = (conv.get("intent") or "").strip()
        if not intent:
            for signal, mapped in _SIGNAL_INTENT.items():
                if conv.get(signal):
                    intent = mapped
                    break
        return {
            "user_utterance": utterance,
            "expected_intent": intent or "unknown",
            "expected_response_contains": [],
            "max_latency_ms": 3000,
            "source": "production",
        }
