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
    # Concrete per-test failures — the "fix what failed" signal for the planner
    # and the raw material harvested into the growing benchmark (golden_candidates.yaml).
    failed_tests: list = field(default_factory=list)

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


# ---------------------------------------------------------------------------
# Dataset converters — one per eval type
# ---------------------------------------------------------------------------

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


def _golden_to_tool_case(test: GoldenTest, routing: dict) -> dict[str, Any] | None:
    """Convert to ToolEvals format; returns None if the intent has no tool."""
    tool = routing.get(test.expected_intent, {}).get("tool")
    if not tool:
        return None
    return {
        "name": test.test_id,
        "utterance": test.user_utterance,
        "expected_tool_use": [{"name": tool}],
        "success_criteria": f"Agent invokes the {tool} tool to handle: {test.expected_intent}",
    }


def _golden_to_turn_case(test: GoldenTest) -> dict[str, Any]:
    """Convert to TurnEvals single-turn format."""
    criteria = (
        f"Response includes relevant information about: {', '.join(test.expected_response_contains)}"
        if test.expected_response_contains
        else f"Response appropriately addresses the {test.expected_intent.replace('_', ' ')} request"
    )
    return {
        "name": test.test_id,
        "conversation": [{"role": "user", "content": test.user_utterance}],
        "success_criteria": criteria,
    }


def _golden_to_guardrail_case(test: GoldenTest) -> dict[str, Any]:
    """Convert to GuardrailEvals format — golden tests are legitimate and must NOT be blocked."""
    return {
        "name": test.test_id,
        "utterance": test.user_utterance,
        "should_be_blocked": False,
        "success_criteria": (
            f"Legitimate {test.expected_intent.replace('_', ' ')} request passes guardrail checks"
        ),
    }


def _golden_to_callback_case(test: GoldenTest, routing: dict) -> dict[str, Any] | None:
    """Convert to CallbackEvals format; returns None if the intent has no tool callback."""
    tool = routing.get(test.expected_intent, {}).get("tool")
    if not tool:
        return None
    return {
        "name": test.test_id,
        "trigger_utterance": test.user_utterance,
        "expected_callback": {"name": tool},
        "success_criteria": f"Callback {tool} correctly triggered for {test.expected_intent}",
    }


# ---------------------------------------------------------------------------
# Runners
# ---------------------------------------------------------------------------

# (total, passed, latencies, tool_error_rate, per-eval-type pass rates, failed tests)
_EvalTuple = tuple[int, int, list[float], float, dict[str, float], list[dict[str, Any]]]


def _failure_record(test: GoldenTest, dimensions: list[str]) -> dict[str, Any]:
    """Serialize a failed GoldenTest into the failed_tests payload.

    Shape mirrors the golden_tests.yaml schema so the harvester can turn it
    directly into a candidate test case, plus the dimensions that failed.
    """
    return {
        "test_id": test.test_id,
        "user_utterance": test.user_utterance,
        "expected_intent": test.expected_intent,
        "expected_response_contains": list(test.expected_response_contains),
        "max_latency_ms": test.max_latency_ms,
        "failed_dimensions": dimensions,
    }


def _failed_names(res: dict[str, Any]) -> set[str]:
    """Extract the set of test names that did NOT pass from an eval result's raw rows."""
    failed: set[str] = set()
    for row in res.get("raw", []) or []:
        name = row.get("name") or row.get("test_id") or row.get("case")
        if not name:
            continue
        passed = row.get("passed", None)
        if passed is None:
            passed = row.get("result", "") == "PASS"
        if not passed:
            failed.add(str(name))
    return failed


def _run_dry(tests: list[GoldenTest], cfg: dict[str, Any]) -> _EvalTuple:
    routing: dict = cfg.get("ROUTING_RULES", {})
    instruction: str = cfg.get("SYSTEM_INSTRUCTION", "")
    latencies: list[float] = []
    passed = 0
    failed_tests: list[dict[str, Any]] = []
    for test in tests:
        t = time.perf_counter()
        ok = (test.expected_intent in routing) and len(instruction) > MIN_INSTRUCTION_LENGTH
        latencies.append((time.perf_counter() - t) * 1000 + 700)
        if ok:
            passed += 1
        else:
            reason = (
                "intent_not_routed" if test.expected_intent not in routing
                else "system_instruction_too_short"
            )
            failed_tests.append(_failure_record(test, [reason]))
    ts = passed / len(tests) if tests else 0.0
    return len(tests), passed, latencies, 0.0, {
        "task_success": ts,
        "tool_pass_rate": ts,
        "turn_pass_rate": ts,
        "guardrail_pass_rate": ts,
        "callback_pass_rate": ts,
    }, failed_tests


def _run_live(tests: list[GoldenTest], cfg: dict[str, Any]) -> _EvalTuple:
    try:
        from auto_cxas_scrapi.config.settings import get_settings
        settings = get_settings()
        project_id = settings.google_cloud_project
        app_name = settings.app_name
        location = settings.google_cloud_location
    except Exception:
        project_id = os.environ.get("GOOGLE_CLOUD_PROJECT", "")
        app_name = os.environ.get("AUTO_CXAS_APP_NAME", "")
        location = os.environ.get("GOOGLE_CLOUD_LOCATION", "global")

    if not project_id or not app_name:
        print("[WARN] Missing GOOGLE_CLOUD_PROJECT or AUTO_CXAS_APP_NAME -- dry-run fallback")
        return _run_dry(tests, cfg)

    try:
        from auto_cxas_scrapi.adapters.cxas_evals import CXASEvalsAdapter
    except ImportError:
        print("[WARN] auto-cxas-scrapi package unavailable -- dry-run fallback")
        return _run_dry(tests, cfg)

    full_app_name = f"projects/{project_id}/locations/{location}/apps/{app_name}"
    adapter = CXASEvalsAdapter(full_app_name=full_app_name)

    if not adapter.is_available():
        print("[WARN] cxas-scrapi unavailable -- dry-run fallback")
        return _run_dry(tests, cfg)

    routing: dict = cfg.get("ROUTING_RULES", {})

    # SimulationEvals — task_success and latency anchor
    sim_cases = [_golden_to_simulation_case(t) for t in tests]
    sim = adapter.run_simulation_evals(
        sim_cases, runs=1, parallel=min(4, len(sim_cases)), verbose=False
    )
    if not sim.get("available"):
        print(f"[WARN] SimulationEvals failed: {sim.get('error')} -- dry-run fallback")
        return _run_dry(tests, cfg)

    sim_pr = float(sim.get("pass_rate", 0.0))
    latencies = [r.get("duration_s", 0.0) * 1000 for r in sim.get("raw", [])]

    # ToolEvals — only for intents that map to a tool
    tool_cases = [c for t in tests if (c := _golden_to_tool_case(t, routing))]
    tool_res = adapter.run_tool_evals(tool_cases) if tool_cases else {}
    tool_pr = float(tool_res["pass_rate"]) if tool_res.get("available") else sim_pr

    # TurnEvals — all golden tests as single-turn conversations
    turn_res = adapter.run_turn_evals(
        [_golden_to_turn_case(t) for t in tests], model="gemini-2.0-flash"
    )
    turn_pr = float(turn_res["pass_rate"]) if turn_res.get("available") else sim_pr

    # GuardrailEvals — all golden tests must pass (none should be blocked)
    guardrail_res = adapter.run_guardrail_evals(
        [_golden_to_guardrail_case(t) for t in tests]
    )
    guardrail_pr = float(guardrail_res["pass_rate"]) if guardrail_res.get("available") else sim_pr

    # CallbackEvals — only for intents that trigger a callback tool
    callback_cases = [c for t in tests if (c := _golden_to_callback_case(t, routing))]
    callback_res = adapter.run_callback_evals(callback_cases) if callback_cases else {}
    callback_pr = float(callback_res["pass_rate"]) if callback_res.get("available") else sim_pr

    metrics: dict[str, float] = {
        "task_success": sim_pr,
        "tool_pass_rate": tool_pr,
        "turn_pass_rate": turn_pr,
        "guardrail_pass_rate": guardrail_pr,
        "callback_pass_rate": callback_pr,
    }

    # Per-test failures across every dimension — the "fix what failed" signal.
    failures_by_dim = {
        "simulation": _failed_names(sim),
        "tool": _failed_names(tool_res),
        "turn": _failed_names(turn_res),
        "guardrail": _failed_names(guardrail_res),
        "callback": _failed_names(callback_res),
    }
    failed_tests: list[dict[str, Any]] = []
    for test in tests:
        dims = [d for d, names in failures_by_dim.items() if test.test_id in names]
        if dims:
            failed_tests.append(_failure_record(test, dims))

    ter = 1.0 - tool_pr
    return sim.get("total", len(tests)), sim.get("passed", 0), latencies, ter, metrics, failed_tests


# ---------------------------------------------------------------------------
# Public grading helper — reused by the benchmark harvester to check whether a
# staged candidate still reproduces as a failure, WITHOUT polluting the official
# golden_tests.yaml score.
# ---------------------------------------------------------------------------

def grade_tests(tests: list[GoldenTest], *, dry_run: bool = False) -> list[dict[str, Any]]:
    """Grade an arbitrary list of GoldenTests and return only the failures.

    Uses the exact same runner the official eval uses, so a candidate that
    fails here is failing for the same reasons it would in the real benchmark.
    """
    if not tests:
        return []
    cfg = _load_agent_config()
    runner = _run_dry if dry_run else _run_live
    *_, failed_tests = runner(tests, cfg)
    return failed_tests


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

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
    total, passed, latencies, ter, eval_metrics, failed_tests = (
        _run_dry(tests, cfg) if dry_run else _run_live(tests, cfg)
    )

    result.golden_tests_run = total
    result.golden_tests_pass = passed
    result.task_success = passed / total if total else 0.0
    result.latency_ms_p50 = _percentile(latencies, 50)
    result.latency_ms_p95 = _percentile(latencies, 95)
    result.tool_error_rate = ter
    result.eval_seconds = time.perf_counter() - t0
    result.eval_score = _compute_eval_score(result.task_success, result.latency_ms_p95, ter)
    result.metrics = eval_metrics
    result.failed_tests = failed_tests

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
