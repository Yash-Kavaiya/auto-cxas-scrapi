"""cxas-scrapi callback adapter — builds all 5 CXAS lifecycle callback types.

Callback hook points:
  before_model_callback  — intercept / skip LLM call
  after_model_callback   — modify LLM response
  before_tool_callback   — intercept / cache tool call
  after_tool_callback    — cache + post-process tool response
  after_agent_callback   — post-turn tracking

Usage::

    import agent_config as cfg
    adapter = CXASCallbackAdapter(
        callbacks_config=cfg.CALLBACKS,
        routing_rules=cfg.ROUTING_RULES,
        response_templates=cfg.RESPONSE_TEMPLATES,
    )
    adapter.register_all(agent, tool_cache_config=cfg.TOOL_CACHE_CONFIG)
"""
from __future__ import annotations

import logging
import re
import time
from typing import Any

log = logging.getLogger(__name__)

try:
    from cxas_scrapi.agents import (  # type: ignore[import-untyped]
        CallbackContext,
        LlmRequest,
        LlmResponse,
    )
except ImportError:
    CallbackContext = LlmRequest = LlmResponse = None  # type: ignore[assignment,misc]


_PII_PATTERNS: list[re.Pattern] = [
    re.compile(r"\b\d{3}[-.\s]?\d{2}[-.\s]?\d{4}\b"),  # SSN
    re.compile(r"\b4[0-9]{12}(?:[0-9]{3})?\b"),           # Visa
    re.compile(r"\b5[1-5][0-9]{14}\b"),                   # Mastercard
]


def _contains_pii(text: str) -> bool:
    return any(p.search(text) for p in _PII_PATTERNS)


class CXASCallbackAdapter:
    """Builds and registers the 5 CXAS callback types from agent_config.CALLBACKS."""

    def __init__(
        self,
        *,
        callbacks_config: dict,
        routing_rules: dict,
        response_templates: dict,
    ) -> None:
        self.cfg       = callbacks_config
        self.routing   = routing_rules
        self.templates = response_templates
        self._cache: dict[str, dict] = {}

    def is_available(self) -> bool:
        return CallbackContext is not None

    # ------------------------------------------------------------------
    # before_model_callback
    # ------------------------------------------------------------------

    def make_before_model_callback(self):
        deterministic: set[str] = set(self.cfg.get("before_model", {}).get("deterministic_intents", []))
        greeting: bool          = self.cfg.get("before_model", {}).get("session_start_greeting", False)
        pii_guard: bool         = self.cfg.get("before_model", {}).get("pii_guardrail_enabled", False)
        templates = self.templates
        routing   = self.routing

        def before_model_callback(callback_context: Any, llm_request: Any) -> Any:
            if not self.is_available():
                return None

            if greeting:
                turn = callback_context.variables.get("turn_count", 0)
                if turn == 0:
                    callback_context.variables["turn_count"] = 1
                    return LlmResponse(text=templates.get(
                        "greeting_template", "Welcome! How can I help you today?"
                    ))

            intent = callback_context.variables.get("detected_intent", "")
            if intent in deterministic:
                tmpl_key = routing.get(intent, {}).get("response_template", "")
                if tmpl_key and tmpl_key in templates:
                    return LlmResponse(text=templates[tmpl_key])

            if pii_guard and llm_request is not None:
                try:
                    contents = getattr(llm_request, "contents", []) or []
                    last = str(contents[-1]) if contents else ""
                    if _contains_pii(last):
                        log.warning("PII pattern detected in request; blocking LLM call")
                        return LlmResponse(
                            text="I can't process that request. "
                                 "Please avoid sharing sensitive personal information."
                        )
                except Exception as exc:
                    log.debug("PII check error (non-blocking): %s", exc)

            return None

        return before_model_callback

    # ------------------------------------------------------------------
    # after_model_callback
    # ------------------------------------------------------------------

    def make_after_model_callback(self):
        survey: bool = self.cfg.get("after_model", {}).get("survey_prompt_on_end", False)
        templates    = self.templates
        _FAREWELL    = {"goodbye", "bye", "farewell", "have a great day", "talk soon"}

        def after_model_callback(callback_context: Any, llm_response: Any) -> Any:
            if not self.is_available() or not survey:
                return None
            try:
                text = getattr(llm_response, "text", "") or ""
                if any(w in text.lower() for w in _FAREWELL):
                    suffix = templates.get("survey_template", "")
                    if suffix:
                        llm_response.text = text + suffix
                        return llm_response
            except Exception as exc:
                log.debug("Survey append error: %s", exc)
            return None

        return after_model_callback

    # ------------------------------------------------------------------
    # before_tool_callback
    # ------------------------------------------------------------------

    def make_before_tool_callback(self, tool_cache_config: dict):
        cache_enabled: bool   = self.cfg.get("before_tool", {}).get("cache_enabled", False)
        cacheable: set[str]   = set(self.cfg.get("before_tool", {}).get("cacheable_tools", []))
        store                 = self._cache

        def before_tool_callback(tool: Any, input_data: dict, callback_context: Any) -> Any:
            if not self.is_available() or not cache_enabled:
                return None
            name = getattr(tool, "name", "") if tool else ""
            if name not in cacheable:
                return None
            cfg = tool_cache_config.get(name, {})
            ttl = cfg.get("ttl_seconds", 300)
            key_params = cfg.get("cache_key_params", [])
            cache_key = name + ":" + ":".join(str(input_data.get(p, "")) for p in sorted(key_params))
            entry = store.get(cache_key)
            if entry and (time.time() - entry["ts"]) < ttl:
                log.debug("Cache hit: %s", cache_key)
                return entry["val"]
            return None

        return before_tool_callback

    # ------------------------------------------------------------------
    # after_tool_callback
    # ------------------------------------------------------------------

    def make_after_tool_callback(self, tool_cache_config: dict):
        cache_enabled: bool         = self.cfg.get("before_tool", {}).get("cache_enabled", False)
        cacheable: set[str]         = set(self.cfg.get("before_tool", {}).get("cacheable_tools", []))
        state_sync: bool            = self.cfg.get("after_tool", {}).get("state_sync_enabled", False)
        verified_tools: set[str]    = set(self.cfg.get("after_tool", {}).get("verified_flag_tools", []))
        store                       = self._cache

        def after_tool_callback(
            tool: Any, input_data: dict, callback_context: Any, tool_response: dict
        ) -> Any:
            if not self.is_available():
                return None
            name = getattr(tool, "name", "") if tool else ""
            if cache_enabled and name in cacheable:
                cfg = tool_cache_config.get(name, {})
                key_params = cfg.get("cache_key_params", [])
                cache_key = name + ":" + ":".join(str(input_data.get(p, "")) for p in sorted(key_params))
                store[cache_key] = {"val": tool_response, "ts": time.time()}
            if state_sync and name in verified_tools:
                tool_response = dict(tool_response)
                tool_response["verified"] = True
                return tool_response
            return None

        return after_tool_callback

    # ------------------------------------------------------------------
    # after_agent_callback
    # ------------------------------------------------------------------

    def make_after_agent_callback(self):
        track: bool = self.cfg.get("after_agent", {}).get("turn_count_tracking", False)

        def after_agent_callback(callback_context: Any) -> Any:
            if not self.is_available() or not track:
                return None
            try:
                n = callback_context.variables.get("turn_count", 0)
                callback_context.variables["turn_count"] = n + 1
            except Exception as exc:
                log.debug("turn_count update failed: %s", exc)
            return None

        return after_agent_callback

    # ------------------------------------------------------------------
    # Registration
    # ------------------------------------------------------------------

    def register_all(self, agent: Any, tool_cache_config: dict | None = None) -> None:
        """Attach all 5 callbacks to a cxas-scrapi Agent instance."""
        if not self.is_available() or agent is None:
            return
        tcc = tool_cache_config or {}
        try:
            agent.before_model_callback = self.make_before_model_callback()
            agent.after_model_callback  = self.make_after_model_callback()
            agent.before_tool_callback  = self.make_before_tool_callback(tcc)
            agent.after_tool_callback   = self.make_after_tool_callback(tcc)
            agent.after_agent_callback  = self.make_after_agent_callback()
            log.info("Registered 5 CXAS callbacks on agent %s", getattr(agent, "name", "?"))
        except Exception as exc:
            log.warning("Callback registration failed: %s", exc)
