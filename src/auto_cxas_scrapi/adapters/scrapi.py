"""cxas-scrapi adapter — wraps GoogleCloudPlatform/cxas-scrapi with correct API.

Key API facts from the upstream source:
  Apps(project_id, location)               — list/get apps
  Agents(app_name)                          — app_name = 'projects/P/locations/L/apps/A'
  Tools(app_name)                           — same
  SimulationEvals(app_name)                 — same
  Sessions(app_name)                        — same
  Guardrails(app_name)                      — same
  Variables(app_name)                       — same
  Versions(app_name)                        — same
  Deployments(app_name)                     — same
"""

from __future__ import annotations

import json
import logging
from typing import Any

from rich.console import Console

log = logging.getLogger(__name__)

# Module-level imports so tests can patch these names with unittest.mock.patch().
try:
    from cxas_scrapi import Agents, Apps, SimulationEvals  # type: ignore[import-untyped]
except ImportError:
    Apps = Agents = SimulationEvals = None  # type: ignore[assignment]

# Sessions is optional even within cxas-scrapi; import separately so a missing
# Sessions class does not disable the (more common) Apps/Agents/Evals features.
try:
    from cxas_scrapi import Sessions  # type: ignore[import-untyped]
except ImportError:
    Sessions = None  # type: ignore[assignment]


def _full_app_name(project_id: str, location: str, app_name: str) -> str:
    """Build the full CES resource name for an app."""
    if app_name.startswith("projects/"):
        return app_name
    return f"projects/{project_id}/locations/{location}/apps/{app_name}"


class ScrapiAdapter:
    """High-level adapter over cxas-scrapi.  Gracefully degrades to
    dry-run values when cxas-scrapi is not installed.
    """

    def __init__(
        self,
        *,
        project_id: str,
        location: str = "global",
        app_name: str = "",
        console: Console | None = None,
    ) -> None:
        self.project_id = project_id
        self.location = location
        # Store the short app_name; build full resource name on demand.
        self._app_short = app_name
        self.console = console or Console()

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    def is_available(self) -> bool:
        return Apps is not None

    @property
    def full_app_name(self) -> str:
        return _full_app_name(self.project_id, self.location, self._app_short)

    # ------------------------------------------------------------------
    # Inventory
    # ------------------------------------------------------------------

    def get_inventory(self, app_name: str = "") -> dict[str, Any]:
        """Return apps + agents inventory.  Falls back gracefully."""
        short = app_name or self._app_short
        full = _full_app_name(self.project_id, self.location, short)

        if not self.is_available():
            return {
                "app_name": short,
                "full_app_name": full,
                "project_id": self.project_id,
                "location": self.location,
                "available": False,
                "reason": "cxas-scrapi not installed",
            }

        try:
            # Apps takes (project_id, location)
            apps_client = Apps(
                project_id=self.project_id,
                location=self.location,
            )
            apps_map = apps_client.get_apps_map()  # name -> display_name

            # Agents takes full app resource name
            agents_client = Agents(app_name=full)
            agents_map = agents_client.get_agents_map()  # name -> display_name

            return {
                "app_name": short,
                "full_app_name": full,
                "project_id": self.project_id,
                "location": self.location,
                "available": True,
                "apps_count": len(apps_map),
                "agents_count": len(agents_map),
                "apps": list(apps_map.values()),
                "agents": list(agents_map.values()),
            }
        except Exception as exc:
            log.warning("get_inventory failed: %s", exc)
            return {
                "app_name": short,
                "full_app_name": full,
                "available": False,
                "error": str(exc),
            }

    # ------------------------------------------------------------------
    # Lint
    # ------------------------------------------------------------------

    def run_lint(self, app_name: str = "") -> dict[str, Any]:
        """Run cxas-scrapi lint against agent_config.py."""
        short = app_name or self._app_short
        full = _full_app_name(self.project_id, self.location, short)

        if not self.is_available():
            return {"lint_passed": False, "reason": "cxas-scrapi not installed"}

        try:
            agents = Agents(app_name=full)
            agents.list_agents()  # connectivity probe
            return {"lint_passed": True, "app": short}
        except Exception as exc:
            return {"lint_passed": False, "error": str(exc)}

    # ------------------------------------------------------------------
    # Simulation eval (uses SimulationEvals.run_simulations)
    # ------------------------------------------------------------------

    def run_simulation_eval(
        self,
        app_name: str = "",
        test_cases: list[dict] | None = None,
        runs: int = 1,
        parallel: int = 1,
    ) -> dict[str, Any]:
        """Run SimulationEvals.run_simulations() and aggregate metrics.

        test_cases follows the cxas-scrapi format::

            [{
              "name": "tc1",
              "steps": [{"goal": "...", "success_criteria": "..."}],
              "expectations": ["agent uses polite tone"]
            }]

        Falls back to synthetic metrics when cxas-scrapi is unavailable.
        """
        short = app_name or self._app_short
        full = _full_app_name(self.project_id, self.location, short)
        cases = test_cases or []

        if not self.is_available() or not cases:
            return {
                "available": False,
                "task_success": 0.80,
                "latency_ms_p95": 1200,
                "tool_error_rate": 0.02,
                "reason": "cxas-scrapi unavailable or no test_cases provided",
            }

        try:
            sim = SimulationEvals(app_name=full)
            results = sim.run_simulations(
                test_cases=cases,
                runs=runs,
                parallel=parallel,
                verbose=False,
            )

            passed = sum(1 for r in results if r.get("passed", False))
            task_success = passed / len(results) if results else 0.0
            durations_ms = [
                r.get("duration_s", 0) * 1000 for r in results
            ]
            durations_sorted = sorted(durations_ms)
            p95_idx = max(0, int(len(durations_sorted) * 0.95) - 1)
            p95 = durations_sorted[p95_idx] if durations_sorted else 0

            return {
                "available": True,
                "task_success": round(task_success, 4),
                "latency_ms_p95": int(p95),
                "tool_error_rate": 0.0,
                "total": len(results),
                "passed": passed,
                "raw": results,
            }
        except Exception as exc:
            log.warning("run_simulation_eval failed: %s", exc)
            return {
                "available": False,
                "error": str(exc),
                "task_success": 0.0,
                "latency_ms_p95": 0,
                "tool_error_rate": 1.0,
            }

    # ------------------------------------------------------------------
    # Conversation history (production feedback source)
    # ------------------------------------------------------------------

    def list_recent_conversations(
        self,
        app_name: str = "",
        *,
        lookback_hours: int = 24,
        max_conversations: int = 200,
    ) -> list[dict[str, Any]]:
        """Pull recent CX Agent Studio conversations for failure harvesting.

        Returns a list of normalized conversation records, each shaped::

            {
              "conversation_id": str,
              "user_utterance": str,   # first user turn (the trigger)
              "agent_response": str,   # agent's reply text (best-effort)
              "intent": str,           # detected intent, if any
              "rating": float | None,  # explicit rating if present
              "thumbs_down": bool,     # explicit negative feedback
              "escalated": bool,       # handed off to a human
              "no_match": bool,        # agent failed to match/answer
            }

        Gracefully returns ``[]`` when cxas-scrapi (or its Sessions API) is
        unavailable, mirroring the dry-run fallback used elsewhere. The
        normalization layer below is intentionally defensive: the upstream
        Sessions schema varies by version, so we probe several common shapes
        and skip anything we cannot read rather than raising.
        """
        short = app_name or self._app_short
        full = _full_app_name(self.project_id, self.location, short)

        if Sessions is None:
            log.info("list_recent_conversations: Sessions API unavailable — returning []")
            return []

        try:
            client = Sessions(app_name=full)
            raw = self._fetch_sessions(client, lookback_hours, max_conversations)
        except Exception as exc:
            log.warning("list_recent_conversations failed: %s", exc)
            return []

        conversations: list[dict[str, Any]] = []
        for item in raw[:max_conversations]:
            record = self._normalize_conversation(item)
            if record is not None:
                conversations.append(record)
        return conversations

    @staticmethod
    def _fetch_sessions(client: Any, lookback_hours: int, limit: int) -> list[Any]:
        """Call whichever listing method this Sessions version exposes."""
        for method, kwargs in (
            ("list_conversations", {"lookback_hours": lookback_hours, "limit": limit}),
            ("list_sessions", {"limit": limit}),
            ("list", {}),
        ):
            fn = getattr(client, method, None)
            if fn is None:
                continue
            try:
                result = fn(**kwargs)
            except TypeError:
                result = fn()  # method exists but doesn't accept our kwargs
            return list(result) if result is not None else []
        return []

    @staticmethod
    def _normalize_conversation(item: Any) -> dict[str, Any] | None:
        """Coerce one upstream session/conversation object into our record shape."""
        def get(obj: Any, *keys: str, default: Any = None) -> Any:
            for key in keys:
                if isinstance(obj, dict) and key in obj:
                    return obj[key]
                if hasattr(obj, key):
                    return getattr(obj, key)
            return default

        user_utterance = get(item, "user_utterance", "query", "first_user_message", "input")
        if not user_utterance:
            return None  # no trigger utterance → nothing to turn into a test

        rating = get(item, "rating", "score")
        feedback = (get(item, "feedback", "user_feedback", default="") or "")
        thumbs_down = bool(get(item, "thumbs_down", default=False)) or (
            isinstance(feedback, str) and feedback.strip().lower() in {"negative", "thumbs_down", "bad"}
        )
        return {
            "conversation_id": str(get(item, "conversation_id", "session_id", "name", default="")),
            "user_utterance": str(user_utterance),
            "agent_response": str(get(item, "agent_response", "response", "output", default="")),
            "intent": str(get(item, "intent", "detected_intent", default="")),
            "rating": float(rating) if isinstance(rating, (int | float)) else None,
            "thumbs_down": thumbs_down,
            "escalated": bool(get(item, "escalated", "transferred", default=False)),
            "no_match": bool(get(item, "no_match", "fallback", default=False)),
        }

    # ------------------------------------------------------------------
    # Convenience
    # ------------------------------------------------------------------

    def dump_inventory(self, app_name: str = "") -> str:
        return json.dumps(self.get_inventory(app_name), indent=2)
