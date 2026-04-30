"""Tests for the ReportGenerator."""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from auto_cxas_scrapi.reporters.report_generator import ReportGenerator


@pytest.fixture()
def tmp_store(tmp_path: Path):
    runs = tmp_path / "runs"
    state = tmp_path / "state"
    runs.mkdir()
    state.mkdir()

    exp_dir = runs / "exp-abc12345"
    exp_dir.mkdir()

    (exp_dir / "candidate.json").write_text(json.dumps({
        "experiment_id": "exp-abc12345",
        "title": "Add clarity rule",
        "hypothesis": "Clarity improves task_success",
        "target_resource": "my-app",
        "mutation": {
            "type": "prompt_patch",
            "path": "SYSTEM_INSTRUCTION",
            "operation": "append",
            "value": "Be concise.",
            "rationale": "Reduces ambiguity",
        },
        "created_at": "2026-05-01T00:00:00+00:00",
    }), encoding="utf-8")

    (exp_dir / "result.json").write_text(json.dumps({
        "experiment_id": "exp-abc12345",
        "status": "passed",
        "artifacts": {},
        "started_at": "2026-05-01T00:01:00+00:00",
        "finished_at": "2026-05-01T00:02:30+00:00",
    }), encoding="utf-8")

    (exp_dir / "scorecard.json").write_text(json.dumps({
        "score": 0.872345,
        "metrics": {
            "task_success": 0.85,
            "latency_ms_p95": 1200,
            "tool_error_rate": 0.01,
        },
        "rationale": "0.85 x 0.60 + 0.76 x 0.25 + 0.99 x 0.15 = 0.872345",
    }), encoding="utf-8")

    return runs, state


def test_experiment_summary_contains_key_fields(tmp_store):
    runs, state = tmp_store
    rg = ReportGenerator(runs_dir=runs, state_dir=state)
    md = rg.experiment_summary("exp-abc12345")
    assert "Add clarity rule" in md
    assert "0.872345" in md
    assert "SYSTEM_INSTRUCTION" in md
    assert "passed" in md


def test_full_history_table_contains_experiment(tmp_store):
    runs, state = tmp_store
    rg = ReportGenerator(runs_dir=runs, state_dir=state)
    table = rg.full_history_table()
    assert "exp-abc12345" in table
    assert "Add clarity rule" in table


def test_build_json_summary(tmp_store):
    runs, state = tmp_store
    rg = ReportGenerator(runs_dir=runs, state_dir=state)
    summary = rg.build_json_summary()
    assert summary["total_experiments"] == 1
    exp = summary["experiments"][0]
    assert exp["score"] == pytest.approx(0.872345)
    assert exp["status"] == "passed"


def test_save_experiment_report(tmp_store):
    runs, state = tmp_store
    rg = ReportGenerator(runs_dir=runs, state_dir=state)
    path = rg.save_experiment_report("exp-abc12345")
    assert path.exists()
    assert path.read_text().startswith("# Experiment Report")


def test_save_history_report(tmp_store):
    runs, state = tmp_store
    rg = ReportGenerator(runs_dir=runs, state_dir=state)
    path = rg.save_history_report()
    assert path.exists()
    assert "exp-abc12345" in path.read_text()


def test_empty_history(tmp_path):
    rg = ReportGenerator(runs_dir=tmp_path / "empty", state_dir=tmp_path)
    assert rg.full_history_table() == "_No experiments found._"
    summary = rg.build_json_summary()
    assert summary["total_experiments"] == 0
