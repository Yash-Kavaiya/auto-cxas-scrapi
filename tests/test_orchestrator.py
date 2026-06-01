"""Unit tests for AutoCXASOrchestrator — mocked dependencies."""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from auto_cxas_scrapi.config.settings import Settings
from auto_cxas_scrapi.core.models import ExperimentCandidate, ExperimentStatus
from auto_cxas_scrapi.services.orchestrator import AutoCXASOrchestrator

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_settings(workspace: Path) -> Settings:
    """Create a Settings with paths isolated to `workspace`.

    Uses alias-style kwargs because pydantic-settings aliases can shadow
    field-name kwargs when a .env file is present (case_sensitive=False).
    """
    return Settings(
        AUTO_CXAS_RUNS_DIR=str(workspace / "runs"),
        AUTO_CXAS_STATE_DIR=str(workspace / "state"),
        GOOGLE_CLOUD_PROJECT="",
        AUTO_CXAS_APP_NAME="",
        AUTO_CXAS_LLM_PROVIDER="gemini",
        AUTO_CXAS_APPROVAL_MODE="auto",
        AUTO_CXAS_MIN_SCORE_DELTA=0.01,
    )


def _make_candidate(experiment_id: str = "exp-test-001") -> ExperimentCandidate:
    return ExperimentCandidate(
        experiment_id=experiment_id,
        title="Test experiment",
        hypothesis="Test hypothesis",
        target_resource="test-app",
        mutation={
            "type": "prompt_patch",
            "path": "SYSTEM_INSTRUCTION",
            "operation": "append",
            "value": "Be polite.",
        },
        new_agent_config_content='# mock agent_config\nSYSTEM_INSTRUCTION = "Be polite."\n',
    )


# ---------------------------------------------------------------------------
# get_baseline_score
# ---------------------------------------------------------------------------

def test_get_baseline_score_returns_zero_when_no_file(tmp_path) -> None:
    settings = _make_settings(tmp_path)
    orch = AutoCXASOrchestrator(settings)
    assert orch.get_baseline_score() == 0.0


def test_get_baseline_score_reads_file(tmp_path) -> None:
    settings = _make_settings(tmp_path)
    settings.state_dir.mkdir(parents=True, exist_ok=True)
    (settings.state_dir / "baseline.json").write_text(
        json.dumps({"eval_score": 0.8765}), encoding="utf-8"
    )
    orch = AutoCXASOrchestrator(settings)
    assert orch.get_baseline_score() == pytest.approx(0.8765)


# ---------------------------------------------------------------------------
# propose
# ---------------------------------------------------------------------------

def test_propose_returns_candidates(tmp_path) -> None:
    settings = _make_settings(tmp_path)
    orch = AutoCXASOrchestrator(settings)

    candidates = orch.propose()
    assert len(candidates) >= 1
    candidate = candidates[0]
    assert candidate.experiment_id.startswith("exp-")
    assert candidate.title
    assert candidate.mutation

    # Candidate should be persisted to store
    data = json.loads(
        (settings.runs_dir / candidate.experiment_id / "candidate.json").read_text("utf-8")
    )
    assert data["experiment_id"] == candidate.experiment_id


# ---------------------------------------------------------------------------
# run_experiment
# ---------------------------------------------------------------------------

def test_run_experiment_with_dry_runner(tmp_path) -> None:
    settings = _make_settings(tmp_path)
    orch = AutoCXASOrchestrator(settings)  # No GCP creds → DryRunExperimentRunner

    candidate = _make_candidate("exp-test-run-001")
    orch.store.save_candidate(candidate)

    result = orch.run_experiment("exp-test-run-001")
    assert result.experiment_id == "exp-test-run-001"
    assert result.status == ExperimentStatus.passed
    assert result.artifacts["mode"] == "dry-run"


def test_run_experiment_persists_result(tmp_path) -> None:
    settings = _make_settings(tmp_path)
    orch = AutoCXASOrchestrator(settings)

    candidate = _make_candidate("exp-test-persist-001")
    orch.store.save_candidate(candidate)
    orch.run_experiment("exp-test-persist-001")

    loaded = json.loads(
        (settings.runs_dir / "exp-test-persist-001" / "result.json").read_text("utf-8")
    )
    assert loaded["experiment_id"] == "exp-test-persist-001"
    assert loaded["status"] == "passed"


# ---------------------------------------------------------------------------
# score_experiment
# ---------------------------------------------------------------------------

def test_score_experiment_returns_scorecard(tmp_path) -> None:
    settings = _make_settings(tmp_path)
    orch = AutoCXASOrchestrator(settings)

    candidate = _make_candidate("exp-test-score-001")
    orch.store.save_candidate(candidate)
    orch.run_experiment("exp-test-score-001")

    scorecard = orch.score_experiment("exp-test-score-001")
    assert scorecard["experiment_id"] == "exp-test-score-001"
    assert "score" in scorecard
    assert "delta" in scorecard
    assert "policy" in scorecard
    assert "allowed" in scorecard["policy"]

    # Scorecard should be persisted
    sc_path = settings.runs_dir / "exp-test-score-001" / "scorecard.json"
    assert sc_path.exists()
    assert json.loads(sc_path.read_text("utf-8"))["score"] == scorecard["score"]


def test_score_experiment_policy_allows_sufficient_delta(tmp_path) -> None:
    """When baseline=0 and dry-run produces ~0.83, the policy should allow it."""
    settings = _make_settings(tmp_path)
    orch = AutoCXASOrchestrator(settings)

    candidate = _make_candidate("exp-test-allowed-001")
    orch.store.save_candidate(candidate)
    orch.run_experiment("exp-test-allowed-001")

    scorecard = orch.score_experiment("exp-test-allowed-001")
    assert scorecard["policy"]["allowed"] is True
    # Score from dry-run should be positive
    assert scorecard["score"] > 0.0


def test_score_experiment_policy_blocks_insufficient_delta(tmp_path) -> None:
    """Set a very high min_score_delta to trigger policy blocking."""
    settings = _make_settings(tmp_path)
    settings.min_score_delta = 0.999  # Very high threshold — no dry-run score can reach this
    orch = AutoCXASOrchestrator(settings)

    candidate = _make_candidate("exp-test-blocked-001")
    orch.store.save_candidate(candidate)
    orch.run_experiment("exp-test-blocked-001")

    scorecard = orch.score_experiment("exp-test-blocked-001")
    assert scorecard["policy"]["allowed"] is False
    assert any("delta" in r.lower() for r in scorecard["policy"]["reasons"])


# ---------------------------------------------------------------------------
# print_history (smoke test)
# ---------------------------------------------------------------------------

def test_print_history_no_experiments(tmp_path, capsys) -> None:
    settings = _make_settings(tmp_path)
    orch = AutoCXASOrchestrator(settings)
    orch.print_history()
    captured = capsys.readouterr()
    assert "No experiments found" in captured.out


def test_print_history_shows_experiments(tmp_path, capsys) -> None:
    settings = _make_settings(tmp_path)
    orch = AutoCXASOrchestrator(settings)

    candidate = _make_candidate("exp-test-history-001")
    orch.store.save_candidate(candidate)
    orch.run_experiment("exp-test-history-001")
    orch.score_experiment("exp-test-history-001")

    orch.print_history()
    captured = capsys.readouterr()
    assert "exp-test-history-001" in captured.out
    assert "passed" in captured.out
