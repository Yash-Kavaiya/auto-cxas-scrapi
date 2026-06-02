"""
evaluate.py — Fixed evaluation harness for auto-cxas-scrapi.

THIS FILE IS READ-ONLY for the AI optimization agent. Do NOT let the agent modify it.
It contains the golden test runner, latency probes, and metric computation.
"""

from __future__ import annotations

import argparse
import concurrent.futures
import json
import os
import sys
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

EVAL_VERSION: str = "2"
EVAL_TIMEOUT_SECONDS: int = int(os.environ.get("AUTO_CXAS_EVAL_TIMEOUT_SECONDS", "180"))
MAX_PARALLEL_EVALS: int = int(os.environ.get("AUTO_CXAS_MAX_PARALLEL_EVALS", "3"))
GOLDEN_TEST_FILE: Path = Path(__file__).parent / "golden_tests.yaml"
GOLDEN_TEST_DIR: Path = Path(__file__).parent / "tests" / "golden"
STATE_DIR: Path = Path(os.environ.get("AUTO_CXAS_STATE_DIR", ".auto-cxas/state"))
MIN_INSTRUCTION_LENGTH: int = 50


@dataclass
class GoldenTest:
    test_id: str
    user_utterance: str
    expected_intent: str
    expected_response_contains: list[str] = field(default_factory=list)
    max_latency_ms: int = 3000
    session_variables: dict[str, Any] = field(default_factory=dict)
    persona: str = "default"
    multi_turn_context: list[dict] = field(default_factory=list)
    should_be_blocked: bool = False


@dataclass
class EvalResult:
    eval_score: float = 0.0
    eval_version: str = EVAL_VERSION
    task_success: float = 0.0
    turn_pass_rate: float = 0.0
    tool_pass_rate: float = 0.0
    guardrail_pass_rate: float = 1.0
    callback_pass_rate: float = 0.0
    latency_ms_p50: int = 0
    latency_ms_p95: int = 0
    tool_error_rate: float = 0.0
    golden_tests_run: int = 0
    golden_tests_pass: int = 0
    eval_seconds: float = 0.0
    error: str = ""
    metrics: dict = field(default_factory=dict)
    # Concrete per-test failures — the "fix what failed" signal for the planner
    # and the raw material harvested into the growing benchmark (golden_candidates.yaml).
    failed_tests: list = field(default_factory=list)

    def print_summary(self) -> None:
        print("---")
        print(f"eval_version:        {self.eval_version}")
        print(f"eval_score:          {self.eval_score:.6f}")
        print(f"task_success:        {self.task_success:.6f}")
        print(f"turn_pass_rate:      {self.turn_pass_rate:.6f}")
        print(f"tool_pass_rate:      {self.tool_pass_rate:.6f}")
        print(f"guardrail_pass_rate: {self.guardrail_pass_rate:.6f}")
        print(f"callback_pass_rate:  {self.callback_pass_rate:.6f}")
        print(f"latency_ms_p50:      {self.latency_ms_p50}")
        print(f"latency_ms_p95:      {self.latency_ms_p95}")
        print(f"tool_error_rate:     {self.tool_error_rate:.6f}")
        print(f"golden_tests_run:    {self.golden_tests_run}")
        print(f"golden_tests_pass:   {self.golden_tests_pass}")
        print(f"eval_seconds:        {self.eval_seconds:.1f}")
        if self.error:
            print(f"error:               {self.error}")


def _load_golden_tests() -> list[GoldenTest]:
    all_tests: list[GoldenTest] = []

    def _parse(raw: dict) -> list[GoldenTest]:
        out = []
        for t in raw.get("tests", []):
            out.append(GoldenTest(
                test_id=t["test_id"],
                user_utterance=t["user_utterance"],
                expected_intent=t["expected_intent"],
                expected_response_contains=t.get("expected_response_contains", []),
                max_latency_ms=t.get("max_latency_ms", 3000),
                session_variables=t.get("session_variables", {}),
                persona=t.get("persona", "default"),
                multi_turn_context=t.get("multi_turn_context", []),
                should_be_blocked=t.get("should_be_blocked", False),
            ))
        return out

    try:
        import yaml
        if GOLDEN_TEST_FILE.exists():
            all_tests.extend(_parse(yaml.safe_load(GOLDEN_TEST_FILE.read_text("utf-8"))))
        if GOLDEN_TEST_DIR.exists():
            for p in sorted(GOLDEN_TEST_DIR.glob("*.yaml")):
                try:
                    all_tests.extend(_parse(yaml.safe_load(p.read_text("utf-8"))))
                except Exception as exc:
                    print(f"[WARN] Could not load {p}: {exc}")
    except Exception as exc:
        print(f"[WARN] Could not load golden tests: {exc}")

    if not all_tests:
        all_tests = [
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
        ]
    return all_tests


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


def _compute_eval_score(metrics: dict[str, float], latency_ms_p95: int) -> float:
    """5-dimensional weighted score. Weights sum to 1.0.

    task_success (SimulationEvals)  0.35
    turn_pass_rate (TurnEvals)      0.20
    tool_pass_rate (ToolEvals)      0.20
    latency_score                   0.15
    guardrail_pass_rate             0.07
    callback_pass_rate              0.03
    """
    task      = metrics.get("task_success", 0.0)
    turn      = metrics.get("turn_pass_rate", task)
    tool      = metrics.get("tool_pass_rate", task)
    guardrail = metrics.get("guardrail_pass_rate", 1.0)
    callback  = metrics.get("callback_pass_rate", task)
    latency   = max(0.0, 1.0 - min(latency_ms_p95 / 5000.0, 1.0))
    return round(
        task * 0.35
        + turn * 0.20
        + tool * 0.20
        + latency * 0.15
        + guardrail * 0.07
        + callback * 0.03,
        6,
    )


def _percentile(values: list[float], p: int) -> int:
    if not values:
        return 0
    sv = sorted(values)
    idx = int(len(sv) * p / 100)
    return int(sv[min(idx, len(sv) - 1)])


# ---------------------------------------------------------------------------
# Dataset converters
# ---------------------------------------------------------------------------

def _golden_to_simulation_case(test: GoldenTest) -> dict[str, Any]:
    intent_label = test.expected_intent.replace("_", " ")
    success_criteria = (
        f"Agent handles the {intent_label} request and response includes: "
        f"{', '.join(test.expected_response_contains)}"
        if test.expected_response_contains
        else f"Agent correctly handles the {intent_label} request"
    )
    steps: list[dict] = []
    for ctx in test.multi_turn_context:
        steps.append({
            "goal": ctx.get("goal", ""),
            "static_utterance": ctx.get("utterance", ""),
            "max_turns": 2,
        })
    steps.append({
        "goal": f"Get help with: {intent_label}",
        "success_criteria": success_criteria,
        "static_utterance": test.user_utterance,
        "max_turns": 3,
    })
    case: dict[str, Any] = {
        "name": test.test_id,
        "steps": steps,
        "expectations": (
            [f"Response includes relevant information about: {', '.join(test.expected_response_contains)}"]
            if test.expected_response_contains else []
        ),
    }
    if test.session_variables:
        case["session_variables"] = test.session_variables
    if test.persona != "default":
        case["persona"] = test.persona
    return case


def _golden_to_tool_case(test: GoldenTest, routing: dict) -> dict[str, Any] | None:
    tool = routing.get(test.expected_intent, {}).get("tool")
    if not tool:
        return None
    case: dict[str, Any] = {
        "name": test.test_id,
        "utterance": test.user_utterance,
        "expected_tool_use": [{"name": tool}],
        "success_criteria": f"Agent invokes the {tool} tool to handle: {test.expected_intent}",
    }
    if test.session_variables:
        case["session_variables"] = test.session_variables
    return case


def _golden_to_turn_case(test: GoldenTest) -> dict[str, Any]:
    criteria = (
        f"Response includes relevant information about: {', '.join(test.expected_response_contains)}"
        if test.expected_response_contains
        else f"Response appropriately addresses the {test.expected_intent.replace('_', ' ')} request"
    )
    conversation: list[dict] = []
    for ctx in test.multi_turn_context:
        conversation.append({"role": "user", "content": ctx.get("utterance", "")})
        if "agent_response" in ctx:
            conversation.append({"role": "agent", "content": ctx["agent_response"]})
    conversation.append({"role": "user", "content": test.user_utterance})
    case: dict[str, Any] = {
        "name": test.test_id,
        "conversation": conversation,
        "success_criteria": criteria,
    }
    if test.session_variables:
        case["session_variables"] = test.session_variables
    return case


def _golden_to_guardrail_case(test: GoldenTest) -> dict[str, Any]:
    return {
        "name": test.test_id,
        "utterance": test.user_utterance,
        "should_be_blocked": test.should_be_blocked,
        "success_criteria": (
            "Utterance is correctly blocked by guardrail checks"
            if test.should_be_blocked
            else "Legitimate request passes guardrail checks"
        ),
    }


def _golden_to_callback_case(test: GoldenTest, routing: dict) -> dict[str, Any] | None:
    tool = routing.get(test.expected_intent, {}).get("tool")
    if not tool:
        return None
    case: dict[str, Any] = {
        "name": test.test_id,
        "trigger_utterance": test.user_utterance,
        "expected_callback": {"name": tool},
        "success_criteria": f"Callback {tool} correctly triggered for {test.expected_intent}",
    }
    if test.session_variables:
        case["session_variables"] = test.session_variables
    return case


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
        if test.should_be_blocked:
            passed += 1
            latencies.append(50.0)
            continue
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
        "task_success":       ts,
        "tool_pass_rate":     ts,
        "turn_pass_rate":     ts,
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
    sim_cases   = [_golden_to_simulation_case(t) for t in tests]
    tool_cases  = [c for t in tests if (c := _golden_to_tool_case(t, routing))]
    turn_cases  = [_golden_to_turn_case(t) for t in tests]
    guard_cases = [_golden_to_guardrail_case(t) for t in tests]
    cb_cases    = [c for t in tests if (c := _golden_to_callback_case(t, routing))]

    parallel = min(MAX_PARALLEL_EVALS, 5)
    with concurrent.futures.ThreadPoolExecutor(max_workers=parallel) as ex:
        sim_fut   = ex.submit(
            adapter.run_simulation_evals, sim_cases,
            runs=1, parallel=min(4, len(sim_cases)), verbose=False,
        )
        turn_fut  = ex.submit(
            adapter.run_turn_evals, turn_cases,
            model="gemini-2.0-flash", verbose=False,
        )
        tool_fut  = ex.submit(adapter.run_tool_evals, tool_cases) if tool_cases else None
        guard_fut = ex.submit(adapter.run_guardrail_evals, guard_cases)
        cb_fut    = ex.submit(adapter.run_callback_evals, cb_cases) if cb_cases else None

        sim       = sim_fut.result()
        turn_res  = turn_fut.result()
        tool_res  = tool_fut.result() if tool_fut else {}
        guard_res = guard_fut.result()
        cb_res    = cb_fut.result() if cb_fut else {}

    if not sim.get("available"):
        print(f"[WARN] SimulationEvals failed: {sim.get('error')} -- dry-run fallback")
        return _run_dry(tests, cfg)

    sim_pr       = float(sim.get("pass_rate", 0.0))
    latencies    = [r.get("duration_s", 0.0) * 1000 for r in sim.get("raw", [])]
    tool_pr      = float(tool_res["pass_rate"]) if tool_res.get("available") else sim_pr
    turn_pr      = float(turn_res["pass_rate"]) if turn_res.get("available") else sim_pr
    guardrail_pr = float(guard_res["pass_rate"]) if guard_res.get("available") else 1.0
    callback_pr  = float(cb_res["pass_rate"]) if cb_res.get("available") else sim_pr

    metrics: dict[str, float] = {
        "task_success":        sim_pr,
        "tool_pass_rate":      tool_pr,
        "turn_pass_rate":      turn_pr,
        "guardrail_pass_rate": guardrail_pr,
        "callback_pass_rate":  callback_pr,
    }

    # Per-test failures across every dimension — the "fix what failed" signal.
    failures_by_dim = {
        "simulation": _failed_names(sim),
        "tool": _failed_names(tool_res),
        "turn": _failed_names(turn_res),
        "guardrail": _failed_names(guard_res),
        "callback": _failed_names(cb_res),
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

    result.golden_tests_run    = total
    result.golden_tests_pass   = passed
    result.task_success        = passed / total if total else 0.0
    result.latency_ms_p50      = _percentile(latencies, 50)
    result.latency_ms_p95      = _percentile(latencies, 95)
    result.tool_error_rate     = ter
    result.eval_seconds        = time.perf_counter() - t0
    result.turn_pass_rate      = eval_metrics.get("turn_pass_rate", result.task_success)
    result.tool_pass_rate      = eval_metrics.get("tool_pass_rate", result.task_success)
    result.guardrail_pass_rate = eval_metrics.get("guardrail_pass_rate", 1.0)
    result.callback_pass_rate  = eval_metrics.get("callback_pass_rate", result.task_success)
    result.eval_score          = _compute_eval_score(eval_metrics, result.latency_ms_p95)
    result.metrics             = eval_metrics
    result.failed_tests        = failed_tests

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
