"""cxas-scrapi eval adapter — wraps all 5 eval types.

Eval classes (from cxas_scrapi.__init__):
  SimulationEvals(app_name)  — multi-turn goal-based LLM simulation
  ToolEvals(app_name)        — direct tool call evaluation
  GuardrailEvals(app_name)   — safety/guardrail policy evaluation
  TurnEvals(app_name)        — single-turn agent response evaluation
  CallbackEvals(app_name)    — webhook/callback evaluation
"""

from __future__ import annotations

import logging
from typing import Any

log = logging.getLogger(__name__)


class CXASEvalsAdapter:
    """Unified adapter that exposes all 5 cxas-scrapi eval types.

    All methods fall back gracefully when cxas-scrapi is not installed.
    """

    def __init__(self, *, full_app_name: str) -> None:
        """
        Args:
            full_app_name: Full CES resource name, e.g.
                ``projects/my-proj/locations/global/apps/my-app``
        """
        self.full_app_name = full_app_name

    # ------------------------------------------------------------------
    # Availability
    # ------------------------------------------------------------------

    def is_available(self) -> bool:
        try:
            from cxas_scrapi import SimulationEvals  # noqa: F401
            return True
        except ImportError:
            return False

    # ------------------------------------------------------------------
    # SimulationEvals
    # ------------------------------------------------------------------

    def run_simulation_evals(
        self,
        test_cases: list[dict],
        *,
        runs: int = 1,
        parallel: int = 1,
        model: str = "gemini-2.0-flash",
        verbose: bool = False,
    ) -> dict[str, Any]:
        """Run multi-turn LLM-simulated conversations.

        test_cases format::

            [{
              "name": "test_name",
              "steps": [
                  {"goal": "User asks about hours",
                   "success_criteria": "Agent gives correct hours"}
              ],
              "expectations": ["Response is polite"]
            }]
        """
        if not self.is_available():
            return self._unavailable_result("SimulationEvals")

        try:
            from cxas_scrapi import SimulationEvals  # type: ignore[import-untyped]
            client = SimulationEvals(app_name=self.full_app_name)
            results = client.run_simulations(
                test_cases=test_cases,
                runs=runs,
                parallel=parallel,
                model=model,
                verbose=verbose,
            )
            return self._aggregate_simulation(results)
        except Exception as exc:
            log.warning("SimulationEvals failed: %s", exc)
            return {"available": False, "error": str(exc)}

    @staticmethod
    def _aggregate_simulation(results: list[dict]) -> dict[str, Any]:
        if not results:
            return {"available": True, "pass_rate": 0.0, "total": 0}
        passed = sum(1 for r in results if r.get("passed", False))
        durations_ms = sorted(r.get("duration_s", 0) * 1000 for r in results)
        p95_idx = max(0, int(len(durations_ms) * 0.95) - 1)
        return {
            "available": True,
            "eval_type": "simulation",
            "total": len(results),
            "passed": passed,
            "pass_rate": round(passed / len(results), 4),
            "latency_ms_p95": int(durations_ms[p95_idx]) if durations_ms else 0,
            "raw": results,
        }

    # ------------------------------------------------------------------
    # ToolEvals
    # ------------------------------------------------------------------

    def run_tool_evals(
        self,
        eval_dataset: list[dict],
        *,
        parallel: int = 1,
        verbose: bool = False,
    ) -> dict[str, Any]:
        """Evaluate individual tool calls for correctness.

        eval_dataset format::

            [{
              "tool_name": "order_lookup",
              "args": {"order_id": "12345"},
              "expected_response": {"status": "shipped"}
            }]
        """
        if not self.is_available():
            return self._unavailable_result("ToolEvals")

        try:
            from cxas_scrapi import ToolEvals  # type: ignore[import-untyped]
            client = ToolEvals(app_name=self.full_app_name)
            results = client.run_evals(
                eval_dataset=eval_dataset,
                parallel=parallel,
                verbose=verbose,
            )
            return self._aggregate_generic(results, "tool")
        except Exception as exc:
            log.warning("ToolEvals failed: %s", exc)
            return {"available": False, "error": str(exc)}

    # ------------------------------------------------------------------
    # GuardrailEvals
    # ------------------------------------------------------------------

    def run_guardrail_evals(
        self,
        eval_dataset: list[dict],
        *,
        parallel: int = 1,
        verbose: bool = False,
    ) -> dict[str, Any]:
        """Evaluate guardrail behavior against policy test cases.

        eval_dataset format::

            [{
              "utterance": "How do I hack a website?",
              "expected_blocked": True
            }]
        """
        if not self.is_available():
            return self._unavailable_result("GuardrailEvals")

        try:
            from cxas_scrapi import GuardrailEvals  # type: ignore[import-untyped]
            client = GuardrailEvals(app_name=self.full_app_name)
            results = client.run_evals(
                eval_dataset=eval_dataset,
                parallel=parallel,
                verbose=verbose,
            )
            return self._aggregate_generic(results, "guardrail")
        except Exception as exc:
            log.warning("GuardrailEvals failed: %s", exc)
            return {"available": False, "error": str(exc)}

    # ------------------------------------------------------------------
    # TurnEvals
    # ------------------------------------------------------------------

    def run_turn_evals(
        self,
        eval_dataset: list[dict],
        *,
        parallel: int = 1,
        model: str = "gemini-2.0-flash",
        verbose: bool = False,
    ) -> dict[str, Any]:
        """Evaluate single agent turn quality.

        eval_dataset format::

            [{
              "user_utterance": "What are your hours?",
              "expected_response_contains": ["hours", "open"]
            }]
        """
        if not self.is_available():
            return self._unavailable_result("TurnEvals")

        try:
            from cxas_scrapi import TurnEvals  # type: ignore[import-untyped]
            client = TurnEvals(app_name=self.full_app_name)
            results = client.run_evals(
                eval_dataset=eval_dataset,
                parallel=parallel,
                model=model,
                verbose=verbose,
            )
            return self._aggregate_generic(results, "turn")
        except Exception as exc:
            log.warning("TurnEvals failed: %s", exc)
            return {"available": False, "error": str(exc)}

    # ------------------------------------------------------------------
    # CallbackEvals
    # ------------------------------------------------------------------

    def run_callback_evals(
        self,
        eval_dataset: list[dict],
        *,
        parallel: int = 1,
        verbose: bool = False,
    ) -> dict[str, Any]:
        """Evaluate webhook/callback correctness.

        eval_dataset format::

            [{
              "callback_name": "order_webhook",
              "payload": {"event": "order.shipped"},
              "expected_response_keys": ["order_id", "status"]
            }]
        """
        if not self.is_available():
            return self._unavailable_result("CallbackEvals")

        try:
            from cxas_scrapi import CallbackEvals  # type: ignore[import-untyped]
            client = CallbackEvals(app_name=self.full_app_name)
            results = client.run_evals(
                eval_dataset=eval_dataset,
                parallel=parallel,
                verbose=verbose,
            )
            return self._aggregate_generic(results, "callback")
        except Exception as exc:
            log.warning("CallbackEvals failed: %s", exc)
            return {"available": False, "error": str(exc)}

    # ------------------------------------------------------------------
    # Helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _aggregate_generic(results: list[dict], eval_type: str) -> dict[str, Any]:
        if not results:
            return {"available": True, "eval_type": eval_type, "pass_rate": 0.0, "total": 0}
        passed = sum(
            1 for r in results
            if r.get("passed", False) or r.get("result", "") == "PASS"
        )
        return {
            "available": True,
            "eval_type": eval_type,
            "total": len(results),
            "passed": passed,
            "pass_rate": round(passed / len(results), 4),
            "raw": results,
        }

    @staticmethod
    def _unavailable_result(cls_name: str) -> dict[str, Any]:
        return {
            "available": False,
            "eval_type": cls_name,
            "reason": "cxas-scrapi not installed",
        }
