"""
agent_config.py — Agent configuration target for auto-cxas-scrapi.

THE AI AGENT MODIFIES THIS FILE during autonomous experiments.
Every variable here is fair game. The agent edits this file, commits,
runs evaluate.py, and keeps or discards based on eval_score improvement.

Constraints:
- Keep all top-level variable names intact (evaluate.py reads them by name).
- Do not import external packages not already in pyproject.toml.
- ROUTING_RULES keys must match golden test expected_intent values.

Experiment dimensions (v2 additions):
  STATIC_VARIABLES   — {{var}} injected into system prompt (no per-turn history cost)
  VARIABLES          — {var} session-state tracked across turns
  CALLBACKS          — lifecycle hook config (before/after model, tool, agent)
  CALLBACK_CONFIG    — webhook endpoint and retry policy per tool
  TOOL_CACHE_CONFIG  — client-side cache TTL and key params per cacheable tool
"""

from __future__ import annotations

# ---------------------------------------------------------------------------
# System Instruction
# Uses {{static_var}} for large stable payloads; {dynamic_var} for session state.
# ---------------------------------------------------------------------------
SYSTEM_INSTRUCTION: str = """
Always confirm user intent before any irreversible action.
You are a helpful, professional customer service agent.
Always greet users warmly and respond in a friendly tone.
When you cannot answer a question, be honest and offer to escalate.
Keep responses brief and relevant to the user's question.
Confirm understanding before taking any irreversible actions.

Escalation procedure:
{{escalation_procedure}}

Refund policy:
{{refund_policy}}
"""

# ---------------------------------------------------------------------------
# Static Variables — compiled into system prompt before each LLM call.
# Use for large, infrequently-changing payloads ({{var}} syntax).
# ---------------------------------------------------------------------------
STATIC_VARIABLES: dict[str, str] = {
    "escalation_procedure": (
        "Human agents are available Monday–Friday 9 AM–6 PM PT. "
        "After hours, offer to schedule a callback or create a support ticket."
    ),
    "refund_policy": (
        "Refunds are processed within 5–7 business days for eligible orders placed "
        "within the last 30 days. Digital products are non-refundable after download."
    ),
    "data_privacy_notice": (
        "We collect only data necessary to fulfil your request. "
        "Do not ask users for SSNs, full credit card numbers, or passwords."
    ),
}

# ---------------------------------------------------------------------------
# Dynamic Variables — session-state tracked across turns ({var} syntax).
# Tools and callbacks update these; the agent references them in responses.
# ---------------------------------------------------------------------------
VARIABLES: dict[str, dict] = {
    "customer_tier":   {"scope": "session", "default": None,  "type": "string"},
    "order_id":        {"scope": "session", "default": None,  "type": "string"},
    "user_name":       {"scope": "session", "default": None,  "type": "string"},
    "email":           {"scope": "session", "default": None,  "type": "string"},
    "escalation_flag": {"scope": "turn",    "default": False, "type": "boolean"},
    "retry_count":     {"scope": "session", "default": 0,     "type": "integer"},
    "last_intent":     {"scope": "turn",    "default": None,  "type": "string"},
    "turn_count":      {"scope": "session", "default": 0,     "type": "integer"},
}

# ---------------------------------------------------------------------------
# Tool Descriptions
# ---------------------------------------------------------------------------
TOOL_DESCRIPTIONS: dict[str, str] = {
    "order_lookup":         "Retrieve order details, shipping status, and estimated delivery for a given order ID.",
    "account_reset":        "Send a password reset email to the account associated with the provided email address.",
    "refund_initiate":      "Submit a refund request for an eligible order. Requires order ID and reason.",
    "human_handoff":        "Escalate the conversation to a live human agent when the user requests it or the issue is unresolvable by AI.",
    "store_locator":        "Find the nearest store locations given a zip code or city name.",
    "subscription_manager": "View, modify, or cancel a user subscription plan.",
}

# ---------------------------------------------------------------------------
# Routing Rules
# ---------------------------------------------------------------------------
ROUTING_RULES: dict[str, dict] = {
    "hours_inquiry":       {"confidence_threshold": 0.55, "priority": 2,  "tool": None,                  "response_template": "hours_template"},
    "escalation":          {"confidence_threshold": 0.45, "priority": 10, "tool": "human_handoff",       "response_template": "escalation_template"},
    "account_support":     {"confidence_threshold": 0.57, "priority": 4,  "tool": "account_reset",       "response_template": "account_template"},
    "order_status":        {"confidence_threshold": 0.60, "priority": 5,  "tool": "order_lookup",        "response_template": "order_template"},
    "end_conversation":    {"confidence_threshold": 0.50, "priority": 1,  "tool": None,                  "response_template": "farewell_template"},
    "refund_request":      {"confidence_threshold": 0.58, "priority": 6,  "tool": "refund_initiate",     "response_template": "refund_template"},
    "store_locator":       {"confidence_threshold": 0.55, "priority": 3,  "tool": "store_locator",       "response_template": "store_template"},
    "subscription_cancel": {"confidence_threshold": 0.60, "priority": 7,  "tool": "subscription_manager", "response_template": "subscription_template"},
}

# ---------------------------------------------------------------------------
# Callback Configuration — lifecycle hooks into CXAS agent execution.
# CXASCallbackAdapter reads this to build and register all 5 callback types.
# ---------------------------------------------------------------------------
CALLBACKS: dict[str, dict] = {
    "before_model": {
        "deterministic_intents":  ["end_conversation", "hours_inquiry"],
        "session_start_greeting": True,
        "pii_guardrail_enabled":  True,
    },
    "after_model": {
        "hallucination_check_enabled": False,
        "survey_prompt_on_end":        True,
    },
    "before_tool": {
        "cache_enabled":    True,
        "cache_ttl_seconds": 300,
        "cacheable_tools":  ["store_locator"],
    },
    "after_tool": {
        "state_sync_enabled":  True,
        "verified_flag_tools": [],
    },
    "after_agent": {
        "turn_count_tracking": True,
    },
}

# ---------------------------------------------------------------------------
# Tool Cache Configuration — TTL and cache-key params per cacheable tool.
# ---------------------------------------------------------------------------
TOOL_CACHE_CONFIG: dict[str, dict] = {
    "store_locator":        {"ttl_seconds": 3600, "cache_key_params": ["zip_code", "city"]},
    "order_lookup":         {"ttl_seconds": 60,   "cache_key_params": ["order_id"]},
    "subscription_manager": {"ttl_seconds": 300,  "cache_key_params": ["user_id"]},
}

# ---------------------------------------------------------------------------
# Callback Webhook Configuration — endpoint and retry policy per tool.
# ---------------------------------------------------------------------------
CALLBACK_CONFIG: dict[str, dict] = {
    "order_lookup":         {"endpoint": "${ORDER_LOOKUP_URL}",  "timeout_ms": 2000, "retries": 2},
    "account_reset":        {"endpoint": "${ACCOUNT_RESET_URL}", "timeout_ms": 3000, "retries": 1},
    "human_handoff":        {"endpoint": "${HANDOFF_URL}",       "timeout_ms": 5000, "retries": 0},
    "refund_initiate":      {"endpoint": "${REFUND_URL}",        "timeout_ms": 4000, "retries": 1},
    "store_locator":        {"endpoint": "${STORE_URL}",         "timeout_ms": 2000, "retries": 2},
    "subscription_manager": {"endpoint": "${SUB_URL}",           "timeout_ms": 3000, "retries": 1},
}

# ---------------------------------------------------------------------------
# Guardrail Parameters
# ---------------------------------------------------------------------------
GUARDRAIL_PARAMS: dict[str, float] = {
    "toxicity_threshold":      0.75,
    "pii_detection_threshold": 0.80,
    "off_topic_threshold":     0.70,
    "hallucination_threshold": 0.65,
    "irrelevance_penalty":     0.30,
}

# ---------------------------------------------------------------------------
# Response Templates
# ---------------------------------------------------------------------------
RESPONSE_TEMPLATES: dict[str, str] = {
    "greeting_template":     "Welcome! I'm your customer service assistant. How can I help you today?",
    "hours_template":        "Our business hours are Monday–Friday 9 AM–6 PM PT. Is there anything else I can help you with?",
    "escalation_template":   "I'll transfer you to a live agent right away. Please hold for a moment.",
    "account_template":      "I'll send a password reset link to {email}. Please check your inbox within 5 minutes.",
    "order_template":        "Your order {order_id} is currently {status}. Estimated delivery: {eta}.",
    "farewell_template":     "Thank you for contacting us! Have a great day. Goodbye!",
    "refund_template":       "Your refund request for order {order_id} has been submitted. Expect processing within {days} business days.",
    "store_template":        "The nearest store to you is at {address}, open {hours}.",
    "subscription_template": "I can help you with your {plan} subscription. What would you like to do?",
    "fallback_template":     "I'm not sure I understood that. Could you please rephrase or let me connect you with a specialist?",
    "survey_template":       " On a scale of 1–5, how satisfied were you with this interaction?",
}

# ---------------------------------------------------------------------------
# Fallback Policy
# ---------------------------------------------------------------------------
FALLBACK_POLICY: dict[str, object] = {
    "action":                     "respond_and_escalate_offer",
    "max_fallback_turns":         2,
    "escalate_after_n_fallbacks": 2,
    "response_template":          "fallback_template",
    "collect_feedback":           True,
}
