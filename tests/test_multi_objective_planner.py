"""Tests for MultiObjectivePlanner."""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from auto_cxas_scrapi.planners.multi_objective_planner import MultiObjectivePlanner


@pytest.fixture()
def planner_with_metrics(tmp_path: Path) -> MultiObjectivePlanner:
    state = tmp_path / "state"
    state.mkdir()
    # tool_pass_rate is 0 -> should be proposed first
    (state / "last_result.json").write_text(json.dumps({
        "metrics": {
            "task_success": 0.90,
            "tool_pass_rate": 0.40,
            "turn_pass_rate": 0.80,
            "guardrail_pass_rate": 0.95,
            "callback_pass_rate": 0.98,
        }
    }), encoding="utf-8")
    return MultiObjectivePlanner(state_dir=state)


@pytest.fixture()
def planner_no_metrics(tmp_path: Path) -> MultiObjectivePlanner:
    state = tmp_path / "state"
    state.mkdir()
    return MultiObjectivePlanner(state_dir=state)


def test_propose_returns_candidates(planner_with_metrics) -> None:
    candidates = planner_with_metrics.propose(n=3)
    assert len(candidates) == 3


def test_propose_worst_first(planner_with_metrics) -> None:
    candidates = planner_with_metrics.propose(n=5)
    # tool_pass_rate=0.40 is worst -> should be priority 1
    assert candidates[0].target_eval == "tool"
    assert candidates[0].priority == 1


def test_propose_respects_n(planner_with_metrics) -> None:
    candidates = planner_with_metrics.propose(n=1)
    assert len(candidates) == 1


def test_propose_excludes_eval_type(planner_with_metrics) -> None:
    candidates = planner_with_metrics.propose(n=5, exclude_eval_types=["tool"])
    types = [c.target_eval for c in candidates]
    assert "tool" not in types


def test_candidate_has_required_fields(planner_with_metrics) -> None:
    candidate = planner_with_metrics.propose(n=1)[0]
    assert candidate.experiment_id.startswith("exp-")
    assert candidate.title
    assert candidate.hypothesis
    assert candidate.mutation
    assert isinstance(candidate.current_score, float)
    assert candidate.priority >= 1


def test_top_priority_eval(planner_with_metrics) -> None:
    top = planner_with_metrics.top_priority_eval()
    assert top == "tool"  # lowest score


def test_score_summary_all_keys(planner_with_metrics) -> None:
    summary = planner_with_metrics.score_summary()
    expected_keys = {
        "task_success", "tool_pass_rate", "turn_pass_rate",
        "guardrail_pass_rate", "callback_pass_rate"
    }
    assert expected_keys == set(summary.keys())


def test_no_metrics_defaults_to_zero(planner_no_metrics) -> None:
    candidates = planner_no_metrics.propose(n=1)
    # All metrics 0.0 -> sorted order depends on _EVAL_WEIGHTS definition
    assert len(candidates) == 1
    assert candidates[0].current_score == 0.0


def test_candidate_to_dict(planner_with_metrics) -> None:
    candidate = planner_with_metrics.propose(n=1)[0]
    d = candidate.to_dict()
    for key in ("experiment_id", "title", "hypothesis", "mutation",
                "target_eval", "target_metric", "priority"):
        assert key in d
