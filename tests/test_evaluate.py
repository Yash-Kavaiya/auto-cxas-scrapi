import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))


def _load_evaluate():
    import importlib.util
    spec = importlib.util.spec_from_file_location(
        "evaluate", Path(__file__).parent.parent / "evaluate.py"
    )
    assert spec and spec.loader
    mod = importlib.util.module_from_spec(spec)
    sys.modules["evaluate"] = mod  # required in Python 3.13 for @dataclass
    spec.loader.exec_module(mod)  # type: ignore[union-attr]
    return mod


def test_compute_eval_score_perfect() -> None:
    mod = _load_evaluate()
    metrics = {
        "task_success": 1.0,
        "turn_pass_rate": 1.0,
        "tool_pass_rate": 1.0,
        "guardrail_pass_rate": 1.0,
        "callback_pass_rate": 1.0,
    }
    score = mod._compute_eval_score(metrics, 0)
    assert score == 1.0


def test_compute_eval_score_zero() -> None:
    mod = _load_evaluate()
    # All eval dimensions fail and latency is maxed out. guardrail_pass_rate
    # defaults to 1.0 (an empty guardrail set is "nothing wrongly blocked"),
    # so the floor score is its 0.07 weight, not 0.0.
    metrics = {
        "task_success": 0.0,
        "turn_pass_rate": 0.0,
        "tool_pass_rate": 0.0,
        "guardrail_pass_rate": 0.0,
        "callback_pass_rate": 0.0,
    }
    score = mod._compute_eval_score(metrics, 5000)
    assert score == 0.0


def test_run_dry_returns_five_tuple() -> None:
    mod = _load_evaluate()
    cfg = {
        "ROUTING_RULES": {"hours_inquiry": {}, "escalation": {}},
        "SYSTEM_INSTRUCTION": "x" * 60,
    }
    tests = [
        mod.GoldenTest("t1", "hello", "hours_inquiry"),
        mod.GoldenTest("t2", "bye", "escalation"),
        mod.GoldenTest("t3", "unknown", "missing_intent"),
    ]
    total, passed, latencies, ter, metrics, failed_tests = mod._run_dry(tests, cfg)
    assert total == 3
    assert passed == 2
    assert len(latencies) == 3
    assert ter == 0.0
    assert set(metrics) == {"task_success", "tool_pass_rate", "turn_pass_rate",
                            "guardrail_pass_rate", "callback_pass_rate"}
    assert metrics["task_success"] == pytest.approx(2 / 3)
    # The one unrouted intent is captured as a concrete failure.
    assert [f["test_id"] for f in failed_tests] == ["t3"]
    assert failed_tests[0]["failed_dimensions"] == ["intent_not_routed"]


def test_golden_to_tool_case_no_tool() -> None:
    mod = _load_evaluate()
    test = mod.GoldenTest("t1", "hello", "hours_inquiry")
    routing = {"hours_inquiry": {"tool": None}}
    assert mod._golden_to_tool_case(test, routing) is None


def test_golden_to_tool_case_with_tool() -> None:
    mod = _load_evaluate()
    test = mod.GoldenTest("t1", "reset my password", "account_support")
    routing = {"account_support": {"tool": "account_reset"}}
    case = mod._golden_to_tool_case(test, routing)
    assert case is not None
    assert case["expected_tool_use"][0]["name"] == "account_reset"


def test_golden_to_guardrail_case_not_blocked() -> None:
    mod = _load_evaluate()
    test = mod.GoldenTest("t1", "What are your hours?", "hours_inquiry")
    case = mod._golden_to_guardrail_case(test)
    assert case["should_be_blocked"] is False
    assert case["utterance"] == test.user_utterance


def test_golden_to_callback_case_skips_no_tool() -> None:
    mod = _load_evaluate()
    test = mod.GoldenTest("t1", "goodbye", "end_conversation")
    assert mod._golden_to_callback_case(test, {"end_conversation": {}}) is None


def test_run_live_calls_all_five_adapters(tmp_path, monkeypatch) -> None:
    """_run_live delegates to CXASEvalsAdapter and returns real per-type metrics."""
    mod = _load_evaluate()

    monkeypatch.setenv("GOOGLE_CLOUD_PROJECT", "proj")
    monkeypatch.setenv("AUTO_CXAS_APP_NAME", "myapp")
    monkeypatch.setenv("GOOGLE_CLOUD_LOCATION", "us-central1")

    sim_result = {
        "available": True, "pass_rate": 0.8, "total": 5, "passed": 4,
        "raw": [{"duration_s": 1.0, "passed": True}] * 4 + [{"duration_s": 1.0, "passed": False}],
    }
    tool_result = {"available": True, "pass_rate": 0.75}
    turn_result = {"available": True, "pass_rate": 0.90}
    guardrail_result = {"available": True, "pass_rate": 1.0}
    callback_result = {"available": True, "pass_rate": 0.85}

    class FakeAdapter:
        def __init__(self, *, full_app_name): pass
        def is_available(self): return True
        def run_simulation_evals(self, cases, **kw): return sim_result
        def run_tool_evals(self, cases, **kw): return tool_result
        def run_turn_evals(self, cases, **kw): return turn_result
        def run_guardrail_evals(self, cases, **kw): return guardrail_result
        def run_callback_evals(self, cases, **kw): return callback_result

    import auto_cxas_scrapi.adapters.cxas_evals as cxas_mod
    monkeypatch.setattr(cxas_mod, "CXASEvalsAdapter", FakeAdapter)

    tests = [
        mod.GoldenTest("t1", "hello", "hours_inquiry"),
        mod.GoldenTest("t2", "reset pw", "account_support"),
    ]
    cfg = {
        "ROUTING_RULES": {
            "hours_inquiry": {"tool": None},
            "account_support": {"tool": "account_reset"},
        },
        "SYSTEM_INSTRUCTION": "x" * 60,
    }
    total, passed, latencies, ter, metrics, _failed = mod._run_live(tests, cfg)

    assert total == 5
    assert passed == 4
    assert metrics["task_success"] == pytest.approx(0.8)
    assert metrics["tool_pass_rate"] == pytest.approx(0.75)
    assert metrics["turn_pass_rate"] == pytest.approx(0.90)
    assert metrics["guardrail_pass_rate"] == pytest.approx(1.0)
    assert metrics["callback_pass_rate"] == pytest.approx(0.85)
    assert ter == pytest.approx(0.25)  # 1.0 - tool_pass_rate


def test_main_dry_run_end_to_end(tmp_path, monkeypatch) -> None:
    """main(dry_run=True) writes last_result.json with all 5 metric keys."""
    mod = _load_evaluate()
    monkeypatch.setattr(mod, "STATE_DIR", tmp_path / "state")

    result = mod.main(dry_run=True, output_json=True)

    assert result.error == ""
    assert result.eval_score > 0
    assert set(result.metrics) == {
        "task_success", "tool_pass_rate", "turn_pass_rate",
        "guardrail_pass_rate", "callback_pass_rate",
    }
    last = (tmp_path / "state" / "last_result.json").read_text("utf-8")
    data = __import__("json").loads(last)
    assert "metrics" in data
    assert "task_success" in data["metrics"]
