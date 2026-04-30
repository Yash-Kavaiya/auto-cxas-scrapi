"""cxas-scrapi resource adapter — Tools, Variables, Guardrails, Versions, Deployments.

All classes in upstream cxas-scrapi that take ``app_name`` expect the
full CES resource name:  projects/{proj}/locations/{loc}/apps/{app}
"""

from __future__ import annotations

import logging
from typing import Any

log = logging.getLogger(__name__)


class CXASResourcesAdapter:
    """Adapter for CXAS resource management (Tools, Variables, Guardrails,
    Versions, Deployments).

    Degrades gracefully when cxas-scrapi is not installed.
    """

    def __init__(self, *, full_app_name: str) -> None:
        self.full_app_name = full_app_name

    def is_available(self) -> bool:
        try:
            from cxas_scrapi import Tools  # noqa: F401
            return True
        except ImportError:
            return False

    # ------------------------------------------------------------------
    # Tools
    # ------------------------------------------------------------------

    def list_tools(self) -> list[dict[str, Any]]:
        """Return a list of tools and toolsets in the app."""
        if not self.is_available():
            return []
        try:
            from cxas_scrapi import Tools  # type: ignore[import-untyped]
            client = Tools(app_name=self.full_app_name)
            raw = client.list_tools()
            return [
                {
                    "name": getattr(t, "name", ""),
                    "display_name": getattr(t, "display_name", ""),
                }
                for t in raw
            ]
        except Exception as exc:
            log.warning("list_tools failed: %s", exc)
            return []

    def get_tools_map(self, reverse: bool = False) -> dict[str, str]:
        """Return a display_name->name (or name->display_name) map."""
        if not self.is_available():
            return {}
        try:
            from cxas_scrapi import Tools  # type: ignore[import-untyped]
            return Tools(app_name=self.full_app_name).get_tools_map(reverse=reverse)
        except Exception as exc:
            log.warning("get_tools_map failed: %s", exc)
            return {}

    def execute_tool(
        self,
        tool_display_name: str,
        args: dict[str, Any] | None = None,
        variables: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        """Execute a tool by display name and return its JSON response."""
        if not self.is_available():
            return {"available": False, "reason": "cxas-scrapi not installed"}
        try:
            from cxas_scrapi import Tools  # type: ignore[import-untyped]
            client = Tools(app_name=self.full_app_name)
            result = client.execute_tool(
                tool_display_name=tool_display_name,
                args=args or {},
                variables=variables,
            )
            return {"available": True, "result": result}
        except Exception as exc:
            log.warning("execute_tool(%s) failed: %s", tool_display_name, exc)
            return {"available": False, "error": str(exc)}

    # ------------------------------------------------------------------
    # Variables
    # ------------------------------------------------------------------

    def list_variables(self) -> list[dict[str, Any]]:
        """Return all session variables defined in the app."""
        if not self.is_available():
            return []
        try:
            from cxas_scrapi import Variables  # type: ignore[import-untyped]
            client = Variables(app_name=self.full_app_name)
            raw = client.list_variables()
            out = []
            for v in raw:
                out.append({
                    "name": getattr(v, "name", ""),
                    "display_name": getattr(v, "display_name", ""),
                })
            return out
        except Exception as exc:
            log.warning("list_variables failed: %s", exc)
            return []

    def get_variables_map(self) -> dict[str, Any]:
        """Return {variable_name: default_value} dict."""
        if not self.is_available():
            return {}
        try:
            from cxas_scrapi import Variables  # type: ignore[import-untyped]
            client = Variables(app_name=self.full_app_name)
            raw = client.list_variables()
            result: dict[str, Any] = {}
            for v in raw:
                name = getattr(v, "name", "")
                if name:
                    result[name] = getattr(v, "value", None)
            return result
        except Exception as exc:
            log.warning("get_variables_map failed: %s", exc)
            return {}

    # ------------------------------------------------------------------
    # Guardrails
    # ------------------------------------------------------------------

    def list_guardrails(self) -> list[dict[str, Any]]:
        """Return guardrail configurations for the app."""
        if not self.is_available():
            return []
        try:
            from cxas_scrapi import Guardrails  # type: ignore[import-untyped]
            client = Guardrails(app_name=self.full_app_name)
            raw = client.list_guardrails()
            return [
                {
                    "name": getattr(g, "name", ""),
                    "display_name": getattr(g, "display_name", ""),
                }
                for g in raw
            ]
        except Exception as exc:
            log.warning("list_guardrails failed: %s", exc)
            return []

    # ------------------------------------------------------------------
    # Versions
    # ------------------------------------------------------------------

    def list_versions(self) -> list[dict[str, Any]]:
        """Return agent versions in the app."""
        if not self.is_available():
            return []
        try:
            from cxas_scrapi import Versions  # type: ignore[import-untyped]
            client = Versions(app_name=self.full_app_name)
            raw = client.list_versions()
            return [
                {
                    "name": getattr(v, "name", ""),
                    "display_name": getattr(v, "display_name", ""),
                    "state": str(getattr(v, "state", "")),
                }
                for v in raw
            ]
        except Exception as exc:
            log.warning("list_versions failed: %s", exc)
            return []

    # ------------------------------------------------------------------
    # Deployments
    # ------------------------------------------------------------------

    def list_deployments(self) -> list[dict[str, Any]]:
        """Return deployments for the app."""
        if not self.is_available():
            return []
        try:
            from cxas_scrapi import Deployments  # type: ignore[import-untyped]
            client = Deployments(app_name=self.full_app_name)
            raw = client.list_deployments()
            return [
                {
                    "name": getattr(d, "name", ""),
                    "display_name": getattr(d, "display_name", ""),
                    "state": str(getattr(d, "state", "")),
                }
                for d in raw
            ]
        except Exception as exc:
            log.warning("list_deployments failed: %s", exc)
            return []

    # ------------------------------------------------------------------
    # Full resource snapshot
    # ------------------------------------------------------------------

    def snapshot(self) -> dict[str, Any]:
        """Return a complete resource inventory dict."""
        return {
            "full_app_name": self.full_app_name,
            "tools": self.list_tools(),
            "variables": self.list_variables(),
            "guardrails": self.list_guardrails(),
            "versions": self.list_versions(),
            "deployments": self.list_deployments(),
        }
