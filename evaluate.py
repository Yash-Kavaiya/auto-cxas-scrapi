"""
evaluate.py — Fixed evaluation harness for auto-cxas-scrapi.

THIS FILE IS READ-ONLY for the AI optimization agent. Do NOT let the agent modify it.
It contains the golden test runner, latency probes, and metric computation.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

EVAL_TIMEOUT_SECONDS: int = int(os.environ.get("AUTO_CXAS_EVAL_TIMEOUT_SECONDS", "120"))
GOLDEN_TEST_FILE: Path = Path(__file__).parent / "golden_tests.yaml"
STATE_DIR: Path = Path(os.environ.get("AUTO_CXAS_STATE_DIR", ".auto-cxas/state"))
MIN_INSTRUCTION_LENGTH: int = 50


@dataclass
class GoldenTest:
    test_id: str
    user_utterance: str
    expected_intent: str
    expected_response_contains: list[str] = field(default_factory=list)
    max_latency_ms: int = 3000


@dataclass
class EvalResult:
    eval_score: float = 0.0
    task_success: float = 0.0
    latency_ms_p50: int = 0
    latency_ms_p95: int = 0
    tool_error_rate: float = 0.0
    golden_tests_run: int = 0
    golden_tests_pass: int = 0
    eval_seconds: float = 0.0
    error: str = ""
    # Per-eval-type pass rates read by LLMOptimizationPlanner to pick the weakest dimension.
    metrics: dict = field(default_factory=dict)

    def print_summary(self) -> None:
        print("---")
        print(f"eval_score:         {self.eval_score:.6f}")
        print(f"task_success:       {self.task_success:.6f}")
        print(f"latency_ms_p50:     {self.latency_ms_p50}")
        print(f"latency_ms_p95:     {self.latency_ms_p95}")
        print(f"tool_error_rate:    {self.tool_error_rate:.6f}")
        print(f"golden_tests_run:   {self.golden_tests_run}")
        print(f"golden_tests_pass:  {self.golden_tests_pass}")
        print(f"eval_seconds:       {self.eval_seconds:.1f}")
        if self.error:
            print(f"error:              {self.error}")


def _load_golden_tests() -> list[GoldenTest]:
    if GOLDEN_TEST_FILE.exists():
        try:
            import yaml
            raw = yaml.safe_load(GOLDEN_TEST_FILE.read_text("utf-8"))
            return [GoldenTest(**t) for t in raw.get("tests", [])]
        except Exception as exc:
            print(f"[WARN] Could not load {GOLDEN_TEST_FILE}: {exc}")
    return [
        GoldenTest("gt_001", "What are your business hours?", "hours_inquiry",
                   expected_response_contains=["hours", "open"]),
        GoldenTest("gt_002", "I need to speak to a human agent", "escalation",
                   expected_response_contains=["transfer", "agent"]),
        GoldenTest("gt_003", "Can you reset my password?", "account_support",
                   expected_response_contains=["password", "reset", "email"]),
        GoldenTest("gt_004", "What is the status of my order?", "order_status",
                   expected_response_contains=["order", "status", "track"]),
        GoldenTest("gt_005", "Thank you, goodbye", "end_conversation",
                   expected_response_contains=["thank", "goodbye", "help"]),
        GoldenTest("gt_006", "How do I cancel my subscription?", "subscription_cancel",
                   expected_response_contains=["cancel", "subscription"]),
        GoldenTest("gt_007", "Where is my nearest store?", "store_locator",
                   expected_response_contains=["store", "location", "near"]),
        GoldenTest("gt_008", "I want a refund", "refund_request",
                   expected_response_contains=["refund", "process", "days"]),
    ]


def _load_agent_config() -> dict[str, Any]:
    import importlib.util
    spec = importlib.util.spec_from_file_location(
        "agent_config", Path(__file__).parent / "agent_config.py"
    )
    if spec is None or spec.loader is None:
        raise ImportError("Cannot find agent_config.py")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)  # type: ignore[union-attr]
    return {k: getattr(module, k) for k in dir(module) if not k.startswith("_")}


def _compute_eval_score(task_success: float, latency_ms_p95: int, tool_error_rate: float) -> float:
    latency_score = max(0.0, 1.0 - min(latency_ms_p95 / 5000.0, 1.0))
    reliability_score = max(0.0, 1.0 - min(tool_error_rate, 1.0))
    return round(task_success * 0.60 + latency_score * 0.25 + reliability_score * 0.15, 6)


def _percentile(values: list[float], p: int) -> int:
    if not values:
        return 0
    sv = sorted(values)
    idx = int(len(sv) * p / 100)
    return int(sv[min(idx, len(sv) - 1)])


def _run_dry(tests: list[GoldenTest], cfg: dict[str, Any]) -> tuple[int, int, list[float], float]:
    routing: dict = cfg.get("ROUTING_RULES", {})
    instruction: str = cfg.get("SYSTEM_INSTRUCTION", "")
    latencies: list[float] = []
    passed = 0
    for test in tests:
        t = time.perf_counter()
        ok = (test.expected_intent in routing) and len(instruction) > MIN_INSTRUCTION_LENGTH
        latencies.append((time.perf_counter() - t) * 1000 + 700)
        if ok:
            passed += 1
    return len(tests), passed, latencies, 0.0


def _golden_to_simulation_case(test: GoldenTest) -> dict[str, Any]:
    """Convert a GoldenTest to the SimulationEvals test case format."""
    intent_label = test.expected_intent.replace("_", " ")
    success_criteria = (
        f"Agent handles the {intent_label} request and response includes: "
        f"{', '.join(test.expected_response_contains)}"
        if test.expected_response_contains
        else f"Agent correctly handles the {intent_label} request"
    )
    return {
        "name": test.test_id,
        "steps": [
            {
                "goal": f"Get help with: {intent_label}",
                "success_criteria": success_criteria,
                "static_utterance": test.user_utterance,
                "max_turns": 3,
            }
        ],
        "expectations": (
            [f"Response includes relevant information about: {', '.join(test.expected_response_contains)}"]
            if test.expected_response_contains
            else []
        ),
    }


def _run_live(tests: list[GoldenTest], cfg: dict[str, Any]) -> tuple[int, int, list[float], float]:
    project_id = os.environ.get("GOOGLE_CLOUD_PROJECT", "")
    app_name = os.environ.get("AUTO_CXAS_APP_NAME", "")
    location = os.environ.get("GOOGLE_CLOUD_LOCATION", "global")

    if not project_id or not app_name:
        print("[WARN] Missing GOOGLE_CLOUD_PROJECT or AUTO_CXAS_APP_NAME -- dry-run fallback")
        return _run_dry(tests, cfg)

    try:
        from cxas_scrapi import SimulationEvals  # type: ignore[import-untyped]
    except ImportError:
        print("[WARN] cxas-scrapi unavailable -- dry-run fallback")
        return _run_dry(tests, cfg)

    # Full CES resource name required by SimulationEvals
    full_app_name = f"projects/{project_id}/locations/{location}/apps/{app_name}"
    test_cases = [_golden_to_simulation_case(t) for t in tests]

    t_start = time.perf_counter()
    try:
        sim = SimulationEvals(app_name=full_app_name)
        results = sim.run_simulations(
            test_cases=test_cases,
            runs=1,
            parallel=min(4, len(test_cases)),
            verbose=False,
        )
    except Exception as exc:
        print(f"[WARN] SimulationEvals failed: {exc} -- dry-run fallback")
        return _run_dry(tests, cfg)

    passed = sum(1 for r in results if r.get("passed", False))
    latencies = [r.get("duration_s", 0.0) * 1000 for r in results]

    # Probe tool error rate from detailed traces when available
    tool_errors = sum(
        1 for r in results
        if any("error" in str(chunk).lower() for chunk in r.get("detailed_trace", []))
    )
    ter = tool_errors / len(results) if results else 0.0

    _ = time.perf_counter() - t_start
    return len(results), passed, latencies, ter


def main(dry_run: bool = False, output_json: bool = False) -> EvalResult:
    t0 = time.perf_counter()
    result = EvalResult()

    try:
        cfg = _load_agent_config()
    except Exception as exc:
        result.error = str(exc)
        result.print_summary()
        return result

    tests = _load_golden_tests()
    total, passed, latencies, ter = _run_dry(tests, cfg) if dry_run else _run_live(tests, cfg)

    result.golden_tests_run = total
    result.golden_tests_pass = passed
    result.task_success = passed / total if total else 0.0
    result.latency_ms_p50 = _percentile(latencies, 50)
    result.latency_ms_p95 = _percentile(latencies, 95)
    result.tool_error_rate = ter
    result.eval_seconds = time.perf_counter() - t0
    result.eval_score = _compute_eval_score(result.task_success, result.latency_ms_p95, ter)

    # Per-eval-type metrics consumed by LLMOptimizationPlanner to target the weakest dimension.
    # In dry-run all 5 types share the same simulation-based proxy score.
    # In live mode, only simulation is exercised here; extend this block to run
    # ToolEvals / TurnEvals / GuardrailEvals / CallbackEvals for full coverage.
    result.metrics = {
        "task_success": result.task_success,
        "tool_pass_rate": result.task_success,
        "turn_pass_rate": result.task_success,
        "guardrail_pass_rate": result.task_success,
        "callback_pass_rate": result.task_success,
    }

    result.print_summary()

    STATE_DIR.mkdir(parents=True, exist_ok=True)
    baseline_path = STATE_DIR / "baseline.json"
    if not baseline_path.exists():
        baseline_path.write_text(json.dumps(asdict(result), indent=2), encoding="utf-8")
        print(f"\n[INFO] Baseline saved to {baseline_path}")

    if output_json:
        p = STATE_DIR / "last_result.json"
        p.write_text(json.dumps(asdict(result), indent=2), encoding="utf-8")
        print(f"[INFO] JSON written to {p}")

    return result


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description="auto-cxas-scrapi evaluation harness")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--output-json", action="store_true")
    args = ap.parse_args()
    res = main(dry_run=args.dry_run, output_json=args.output_json)
    sys.exit(0 if not res.error else 1)
