"""cxas-scrapi variables adapter — syncs agent_config VARIABLES to CXAS app.

Supports both variable types from the CXAS PS Variables API:
  Static  — {{var}} compiled into system prompt before each LLM call
  Dynamic — {var}  appended to conversation history on change

Usage::

    import agent_config as cfg
    adapter = CXASVariablesAdapter(full_app_name=full_app_name)
    adapter.sync_from_config(
        static_variables=cfg.STATIC_VARIABLES,
        variables=cfg.VARIABLES,
    )
"""
from __future__ import annotations

import logging
from typing import Any

log = logging.getLogger(__name__)

try:
    from cxas_scrapi import Variables  # type: ignore[import-untyped]
except ImportError:
    Variables = None  # type: ignore[assignment,misc]


class CXASVariablesAdapter:
    """Adapter for the CXAS Variables API."""

    def __init__(self, *, full_app_name: str) -> None:
        self.full_app_name = full_app_name

    def is_available(self) -> bool:
        return Variables is not None

    def list_variables(self) -> dict[str, Any]:
        if not self.is_available():
            return {"available": False, "reason": "cxas-scrapi not installed"}
        try:
            client = Variables(app_name=self.full_app_name)
            vars_map = client.get_variables_map()
            return {"available": True, "count": len(vars_map), "variables": vars_map}
        except Exception as exc:
            log.warning("list_variables failed: %s", exc)
            return {"available": False, "error": str(exc)}

    def set_static_variable(self, name: str, value: str) -> dict[str, Any]:
        """Set a static variable ({{name}} in instructions)."""
        if not self.is_available():
            return {"available": False, "reason": "cxas-scrapi not installed"}
        try:
            client = Variables(app_name=self.full_app_name)
            client.set_static_variable(name=name, value=value)
            return {"available": True, "name": name, "type": "static", "set": True}
        except Exception as exc:
            log.warning("set_static_variable(%s) failed: %s", name, exc)
            return {"available": False, "error": str(exc)}

    def set_dynamic_variable_default(
        self, name: str, default: Any, var_type: str = "string"
    ) -> dict[str, Any]:
        """Register a dynamic variable ({name} in instructions) with a default."""
        if not self.is_available():
            return {"available": False, "reason": "cxas-scrapi not installed"}
        try:
            client = Variables(app_name=self.full_app_name)
            client.set_variable_default(name=name, default=default, type=var_type)
            return {"available": True, "name": name, "type": "dynamic", "set": True}
        except Exception as exc:
            log.warning("set_dynamic_variable_default(%s) failed: %s", name, exc)
            return {"available": False, "error": str(exc)}

    def sync_from_config(
        self,
        static_variables: dict[str, str],
        variables: dict[str, dict],
    ) -> dict[str, Any]:
        """Sync STATIC_VARIABLES and VARIABLES dicts from agent_config to the CXAS app.

        static_variables: {name: value_str}  → {{name}} in instructions
        variables:        {name: {scope, default, type}}  → {name} in instructions
        """
        if not self.is_available():
            return {"available": False, "reason": "cxas-scrapi not installed"}
        results: dict[str, Any] = {"static": {}, "dynamic": {}}
        for name, value in static_variables.items():
            results["static"][name] = self.set_static_variable(name, value)
        for name, meta in variables.items():
            results["dynamic"][name] = self.set_dynamic_variable_default(
                name=name,
                default=meta.get("default"),
                var_type=meta.get("type", "string"),
            )
        return {"available": True, "synced": results}
