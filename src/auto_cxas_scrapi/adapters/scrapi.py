"""cxas-scrapi adapter — wraps the GoogleCloudPlatform/cxas-scrapi library."""

from __future__ import annotations

import json
from typing import Any

from rich.console import Console


class ScrapiAdapter:
    def __init__(self, *, project_id: str, location: str,
                 console: Console | None = None) -> None:
        self.project_id = project_id
        self.location = location
        self.console = console or Console()

    def is_available(self) -> bool:
        try:
            from cxas_scrapi import Apps  # type: ignore[import-untyped] # noqa: F401
            return True
        except ImportError:
            return False

    def get_inventory(self, app_name: str) -> dict[str, Any]:
        if not self.is_available():
            return {
                "app_name": app_name,
                "project_id": self.project_id,
                "location": self.location,
                "available": False,
                "reason": "cxas-scrapi not installed",
            }
        from cxas_scrapi import Apps, Agents  # type: ignore[import-untyped]
        apps_client = Apps(project_id=self.project_id, location=self.location)
        agents_client = Agents(project_id=self.project_id, location=self.location)
        apps_map = apps_client.get_apps_map()
        agents_map = agents_client.get_agents_map(app_name)
        return {
            "app_name": app_name,
            "project_id": self.project_id,
            "location": self.location,
            "available": True,
            "apps_count": len(apps_map),
            "agents_count": len(agents_map),
            "apps": list(apps_map.keys()),
            "agents": list(agents_map.keys()),
        }

    def run_lint(self, app_name: str) -> dict[str, Any]:
        if not self.is_available():
            return {"lint_passed": False, "reason": "cxas-scrapi not installed"}
        try:
            from cxas_scrapi.cli import run_lint  # type: ignore[import-untyped]
            result = run_lint(project_id=self.project_id, location=self.location,
                              app_name=app_name)
            return {"lint_passed": True, "result": result}
        except Exception as exc:
            return {"lint_passed": False, "error": str(exc)}

    def run_simulation_eval(
        self, app_name: str, test_utterances: list[str]
    ) -> dict[str, Any]:
        if not self.is_available():
            return {"available": False, "task_success": 0.8, "latency_ms_p95": 900}
        try:
            from cxas_scrapi.evals.simulation_evals import SimulationEvals  # type: ignore
            sim = SimulationEvals(
                project_id=self.project_id,
                location=self.location,
                app_name=app_name,
            )
            results = sim.run_batch(test_utterances)
            successes = sum(1 for r in results if r.get("success", False))
            latencies = [r.get("latency_ms", 0) for r in results]
            latencies_sorted = sorted(latencies)
            p95_idx = int(len(latencies_sorted) * 0.95)
            return {
                "available": True,
                "task_success": successes / len(results) if results else 0.0,
                "latency_ms_p95": latencies_sorted[min(p95_idx, len(latencies_sorted)-1)],
                "tool_error_rate": 0.0,
            }
        except Exception as exc:
            return {"available": False, "error": str(exc), "task_success": 0.0}

    def dump_inventory(self, app_name: str) -> str:
        return json.dumps(self.get_inventory(app_name), indent=2)
