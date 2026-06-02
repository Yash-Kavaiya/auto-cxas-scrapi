"""cxas-scrapi eval adapter — wraps all 5 eval types with tenacity retry logic."""
from __future__ import annotations

import logging
from typing import Any

from tenacity import before_sleep_log, retry, stop_after_attempt, wait_exponential

log = logging.getLogger(__name__)

try:
    from cxas_scrapi import (  # type: ignore[import-untyped]
        CallbackEvals,
        GuardrailEvals,
        SimulationEvals,
        ToolEvals,
        TurnEvals,
    )
except ImportError:
    SimulationEvals = ToolEvals = GuardrailEvals = TurnEvals = CallbackEvals = None  # type: ignore[assignment]


def _retry_call(fn, *args, **kwargs) -> Any:  # type: ignore[no-untyped-def]
    """Call fn(*args, **kwargs) with 3-attempt exponential backoff (2s/4s/8s max 30s)."""
    @retry(
        stop=stop_after_attempt(3),
        wait=wait_exponential(multiplier=1, min=2, max=30),
        reraise=True,
        before_sleep=before_sleep_log(log, logging.WARNING),
    )
    def _inner() -> Any:
        return fn(*args, **kwargs)
    return _inner()


class CXASEvalsAdapter:
    """Unified adapter that exposes all 5 cxas-scrapi eval types."""

    def __init__(self, *, full_app_name: str) -> None:
        self.full_app_name = full_app_name

    def is_available(self) -> bool:
        return SimulationEvals is not None

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
        if not self.is_available():
            return self._unavailable_result("SimulationEvals")
        try:
            client = SimulationEvals(app_name=self.full_app_name)
            results = _retry_call(
                client.run_simulations,
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
            return {"available": True, "eval_type": "simulation", "pass_rate": 0.0, "total": 0}
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
        test_cases: list[dict],
        *,
        parallel: int = 1,
        verbose: bool = False,
    ) -> dict[str, Any]:
        if not self.is_available():
            return self._unavailable_result("ToolEvals")
        try:
            client = ToolEvals(app_name=self.full_app_name)
            results = _retry_call(
                client.run_evals,
                eval_dataset=test_cases,
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
        test_cases: list[dict],
        *,
        parallel: int = 1,
        verbose: bool = False,
    ) -> dict[str, Any]:
        if not self.is_available():
            return self._unavailable_result("GuardrailEvals")
        try:
            client = GuardrailEvals(app_name=self.full_app_name)
            results = _retry_call(
                client.run_evals,
                eval_dataset=test_cases,
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
        test_cases: list[dict],
        *,
        parallel: int = 1,
        model: str = "gemini-2.0-flash",
        verbose: bool = False,
    ) -> dict[str, Any]:
        if not self.is_available():
            return self._unavailable_result("TurnEvals")
        try:
            client = TurnEvals(app_name=self.full_app_name)
            results = _retry_call(
                client.run_evals,
                eval_dataset=test_cases,
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
        test_cases: list[dict],
        *,
        parallel: int = 1,
        verbose: bool = False,
    ) -> dict[str, Any]:
        if not self.is_available():
            return self._unavailable_result("CallbackEvals")
        try:
            client = CallbackEvals(app_name=self.full_app_name)
            results = _retry_call(
                client.run_evals,
                eval_dataset=test_cases,
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
        durations_ms = sorted(
            r.get("duration_s", 0) * 1000 for r in results if "duration_s" in r
        )
        p95_idx = max(0, int(len(durations_ms) * 0.95) - 1)
        return {
            "available": True,
            "eval_type": eval_type,
            "total": len(results),
            "passed": passed,
            "pass_rate": round(passed / len(results), 4),
            "latency_ms_p95": int(durations_ms[p95_idx]) if durations_ms else 0,
            "raw": results,
        }

    @staticmethod
    def _unavailable_result(cls_name: str) -> dict[str, Any]:
        return {
            "available": False,
            "eval_type": cls_name,
            "reason": "cxas-scrapi not installed",
        }
