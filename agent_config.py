"""
agent_config.py — Agent configuration target for auto-cxas-scrapi.

THE AI AGENT MODIFIES THIS FILE during autonomous experiments.
Every variable here is fair game. The agent edits this file, commits,
runs evaluate.py, and keeps or discards based on eval_score improvement.

Constraints:
- Keep all top-level variable names intact (evaluate.py reads them by name).
- Do not import external packages not already in pyproject.toml.
- ROUTING_RULES keys must match golden test expected_intent values.
"""

from __future__ import annotations

# System Instruction
SYSTEM_INSTRUCTION: str = """
You are a helpful, professional customer service agent.
Always greet users warmly and respond in a friendly tone.
When you cannot answer a question, be honest and offer to escalate.
Keep responses brief and relevant to the user's question.
Confirm understanding before taking any irreversible actions.
"""

# Tool Descriptions
TOOL_DESCRIPTIONS: dict[str, str] = {
    "order_lookup": "Retrieve order details, shipping status, and estimated delivery for a given order ID.",
    "account_reset": "Send a password reset email to the account associated with the provided email address.",
    "refund_initiate": "Submit a refund request for an eligible order. Requires order ID and reason.",
    "human_handoff": "Escalate the conversation to a live human agent when the user requests it or when the issue is unresolvable by AI.",
    "store_locator": "Find the nearest store locations given a zip code or city name.",
    "subscription_manager": "View, modify, or cancel a user subscription plan.",
}

# Routing Rules
ROUTING_RULES: dict[str, dict] = {
    "hours_inquiry": {"confidence_threshold": 0.70, "priority": 2, "tool": None, "response_template": "hours_template"},
    "escalation": {"confidence_threshold": 0.60, "priority": 10, "tool": "human_handoff", "response_template": "escalation_template"},
    "account_support": {"confidence_threshold": 0.72, "priority": 4, "tool": "account_reset", "response_template": "account_template"},
    "order_status": {"confidence_threshold": 0.75, "priority": 5, "tool": "order_lookup", "response_template": "order_template"},
    "end_conversation": {"confidence_threshold": 0.65, "priority": 1, "tool": None, "response_template": "farewell_template"},
    "refund_request": {"confidence_threshold": 0.73, "priority": 6, "tool": "refund_initiate", "response_template": "refund_template"},
    "store_locator": {"confidence_threshold": 0.70, "priority": 3, "tool": "store_locator", "response_template": "store_template"},
    "subscription_cancel": {"confidence_threshold": 0.75, "priority": 7, "tool": "subscription_manager", "response_template": "subscription_template"},
}

# Guardrail Parameters
GUARDRAIL_PARAMS: dict[str, float] = {
    "toxicity_threshold": 0.75,
    "pii_detection_threshold": 0.80,
    "off_topic_threshold": 0.70,
    "hallucination_threshold": 0.65,
    "irrelevance_penalty": 0.30,
}

# Response Templates
RESPONSE_TEMPLATES: dict[str, str] = {
    "hours_template": "Our business hours are {hours}. Is there anything else I can help you with?",
    "escalation_template": "I will transfer you to a live agent right away. Please hold for a moment.",
    "account_template": "I will send a password reset link to {email}. Please check your inbox within 5 minutes.",
    "order_template": "Your order {order_id} is currently {status}. Estimated delivery: {eta}.",
    "farewell_template": "Thank you for contacting us! Have a great day. Goodbye!",
    "refund_template": "Your refund request for order {order_id} has been submitted. Expect processing within {days} business days.",
    "store_template": "The nearest store to you is at {address}, open {hours}.",
    "subscription_template": "I can help you with your {plan} subscription. What would you like to do?",
    "fallback_template": "I am not sure I understood that. Could you please rephrase or let me connect you with a specialist?",
}

# Fallback Policy
FALLBACK_POLICY: dict[str, object] = {
    "action": "respond_and_escalate_offer",
    "max_fallback_turns": 2,
    "escalate_after_n_fallbacks": 2,
    "response_template": "fallback_template",
    "collect_feedback": True,
}
