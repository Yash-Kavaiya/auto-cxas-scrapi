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
    score = mod._compute_eval_score(1.0, 0, 0.0)
    assert score == 1.0


def test_compute_eval_score_zero() -> None:
    mod = _load_evaluate()
    score = mod._compute_eval_score(0.0, 5000, 1.0)
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
    total, passed, latencies, ter, metrics = mod._run_dry(tests, cfg)
    assert total == 3
    assert passed == 2
    assert len(latencies) == 3
    assert ter == 0.0
    assert set(metrics) == {"task_success", "tool_pass_rate", "turn_pass_rate",
                            "guardrail_pass_rate", "callback_pass_rate"}
    assert metrics["task_success"] == pytest.approx(2 / 3)


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
