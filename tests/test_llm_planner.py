"""Tests for LLMOptimizationPlanner."""

from __future__ import annotations

import json
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from auto_cxas_scrapi.adapters.llm.base import LLMResponse
from auto_cxas_scrapi.planners.llm_planner import LLMOptimizationPlanner


def _make_llm_response(data: dict) -> LLMResponse:
    return LLMResponse(
        content=json.dumps(data),
        model="claude-sonnet-4-6",
        prompt_tokens=100,
        completion_tokens=200,
        finish_reason="end_turn",
    )


def _valid_llm_payload(new_content: str = "# new content") -> dict:
    return {
        "title": "Add clarity rule",
        "hypothesis": "Explicit instructions reduce errors.",
        "target_eval": "simulation",
        "target_metric": "task_success",
        "mutation": {
            "type": "prompt_patch",
            "path": "SYSTEM_INSTRUCTION",
            "operation": "append",
            "value": "Be concise.",
            "rationale": "Improves task success.",
        },
        "new_agent_config_content": new_content,
    }


@pytest.fixture()
def state_dir_with_metrics(tmp_path: Path) -> Path:
    state = tmp_path / "state"
    state.mkdir()
    (state / "last_result.json").write_text(json.dumps({
        "metrics": {
            "task_success": 0.90,
            "tool_pass_rate": 0.30,
            "turn_pass_rate": 0.80,
            "guardrail_pass_rate": 0.95,
            "callback_pass_rate": 0.98,
        }
    }), encoding="utf-8")
    return state


def test_propose_returns_candidate_with_new_content(tmp_path: Path, state_dir_with_metrics: Path) -> None:
    llm = MagicMock()
    llm.is_available.return_value = True
    llm.complete.return_value = _make_llm_response(_valid_llm_payload("# generated content"))

    planner = LLMOptimizationPlanner(llm=llm, repo_root=tmp_path, state_dir=state_dir_with_metrics)
    (tmp_path / "agent_config.py").write_text("# original", encoding="utf-8")

    candidates = planner.propose(context={"app_name": "my-app"})

    assert len(candidates) == 1
    assert candidates[0].new_agent_config_content == "# generated content"
    assert candidates[0].title == "Add clarity rule"


def test_propose_fallback_when_llm_unavailable(tmp_path: Path, state_dir_with_metrics: Path) -> None:
    llm = MagicMock()
    llm.is_available.return_value = False

    planner = LLMOptimizationPlanner(llm=llm, repo_root=tmp_path, state_dir=state_dir_with_metrics)
    (tmp_path / "agent_config.py").write_text(
        'SYSTEM_INSTRUCTION: str = """\nHello.\n"""', encoding="utf-8"
    )

    candidates = planner.propose(context={"app_name": "my-app"})

    assert len(candidates) == 1
    assert candidates[0].new_agent_config_content != ""
    llm.complete.assert_not_called()


def test_propose_fallback_on_invalid_json(tmp_path: Path, state_dir_with_metrics: Path) -> None:
    llm = MagicMock()
    llm.is_available.return_value = True
    llm.complete.return_value = LLMResponse(
        content="not valid json {{",
        model="claude-sonnet-4-6",
        prompt_tokens=10,
        completion_tokens=5,
        finish_reason="end_turn",
    )

    planner = LLMOptimizationPlanner(llm=llm, repo_root=tmp_path, state_dir=state_dir_with_metrics)
    (tmp_path / "agent_config.py").write_text(
        'SYSTEM_INSTRUCTION: str = """\nHello.\n"""', encoding="utf-8"
    )

    candidates = planner.propose(context={"app_name": "my-app"})

    assert len(candidates) == 1
    # Fallback should still populate new_agent_config_content
    assert candidates[0].new_agent_config_content != ""


def test_weakest_eval_injected_into_llm_prompt(tmp_path: Path, state_dir_with_metrics: Path) -> None:
    llm = MagicMock()
    llm.is_available.return_value = True
    llm.complete.return_value = _make_llm_response(_valid_llm_payload())

    planner = LLMOptimizationPlanner(llm=llm, repo_root=tmp_path, state_dir=state_dir_with_metrics)
    (tmp_path / "agent_config.py").write_text("# config", encoding="utf-8")

    planner.propose(context={"app_name": "my-app"})

    call_kwargs = llm.complete.call_args[1]
    # tool_pass_rate=0.30 is worst, so "tool" should be in the user prompt
    assert "tool" in call_kwargs["user"]
