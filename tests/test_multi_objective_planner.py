"""Tests for MultiObjectivePlanner utility functions."""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from auto_cxas_scrapi.planners.multi_objective_planner import (
    MultiObjectivePlanner,
    load_last_metrics,
    rank_eval_types,
)


@pytest.fixture()
def state_with_metrics(tmp_path: Path) -> Path:
    state = tmp_path / "state"
    state.mkdir()
    (state / "last_result.json").write_text(json.dumps({
        "metrics": {
            "task_success": 0.90,
            "tool_pass_rate": 0.40,
            "turn_pass_rate": 0.80,
            "guardrail_pass_rate": 0.95,
            "callback_pass_rate": 0.98,
        }
    }), encoding="utf-8")
    return state


@pytest.fixture()
def state_empty(tmp_path: Path) -> Path:
    state = tmp_path / "state"
    state.mkdir()
    return state


def test_top_priority_eval(state_with_metrics: Path) -> None:
    planner = MultiObjectivePlanner(state_dir=state_with_metrics)
    assert planner.top_priority_eval() == "tool"  # lowest score (0.40)


def test_score_summary_all_keys(state_with_metrics: Path) -> None:
    planner = MultiObjectivePlanner(state_dir=state_with_metrics)
    summary = planner.score_summary()
    expected_keys = {
        "task_success", "tool_pass_rate", "turn_pass_rate",
        "guardrail_pass_rate", "callback_pass_rate"
    }
    assert expected_keys == set(summary.keys())


def test_rank_eval_types_worst_first(state_with_metrics: Path) -> None:
    metrics = load_last_metrics(state_with_metrics)
    ranked = rank_eval_types(metrics)
    assert ranked[0][0] == "tool"  # tool_pass_rate=0.40 is worst
    assert ranked[0][2] == pytest.approx(0.40)


def test_rank_eval_types_no_metrics() -> None:
    ranked = rank_eval_types({})
    assert len(ranked) == 5
    # All default to 0.0
    for _, _, score in ranked:
        assert score == 0.0


def test_load_last_metrics_missing_file(tmp_path: Path) -> None:
    state = tmp_path / "state"
    state.mkdir()
    assert load_last_metrics(state) == {}


def test_load_last_metrics_returns_values(state_with_metrics: Path) -> None:
    metrics = load_last_metrics(state_with_metrics)
    assert metrics["tool_pass_rate"] == pytest.approx(0.40)
    assert metrics["task_success"] == pytest.approx(0.90)
