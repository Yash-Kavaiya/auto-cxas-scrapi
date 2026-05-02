"""Tests for auto_loop.py utility functions."""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent))

import auto_loop  # noqa: E402 (needed after sys.path insert)


def test_ensure_results_tsv_creates_file(tmp_path, monkeypatch) -> None:
    monkeypatch.setattr(auto_loop, "RESULTS_TSV", tmp_path / "results.tsv")
    auto_loop._ensure_results_tsv()
    content = (tmp_path / "results.tsv").read_text("utf-8")
    assert content.startswith("commit\teval_score\t")


def test_ensure_results_tsv_idempotent(tmp_path, monkeypatch) -> None:
    tsv = tmp_path / "results.tsv"
    monkeypatch.setattr(auto_loop, "RESULTS_TSV", tsv)
    auto_loop._ensure_results_tsv()
    auto_loop._ensure_results_tsv()
    lines = tsv.read_text("utf-8").splitlines()
    assert len(lines) == 1  # header only, not doubled


def test_append_tsv_writes_row(tmp_path, monkeypatch) -> None:
    tsv = tmp_path / "results.tsv"
    monkeypatch.setattr(auto_loop, "RESULTS_TSV", tsv)
    auto_loop._ensure_results_tsv()
    auto_loop._append_tsv(
        commit="abc1234",
        eval_score=0.876543,
        task_success=0.875,
        latency_p95=720,
        tool_error_rate=0.0,
        status="keep",
        description="test experiment",
    )
    rows = tsv.read_text("utf-8").splitlines()
    assert len(rows) == 2  # header + data
    cols = rows[1].split("\t")
    assert cols[0] == "abc1234"
    assert cols[1] == "0.876543"
    assert cols[5] == "keep"
    assert cols[6] == "test experiment"


def test_append_tsv_tag_in_description(tmp_path, monkeypatch) -> None:
    tsv = tmp_path / "results.tsv"
    monkeypatch.setattr(auto_loop, "RESULTS_TSV", tsv)
    auto_loop._ensure_results_tsv()
    auto_loop._append_tsv(
        commit="abc1234",
        eval_score=0.5,
        task_success=0.5,
        latency_p95=1000,
        tool_error_rate=0.1,
        status="discard",
        description="[sprint-42] lower thresholds",
    )
    row = tsv.read_text("utf-8").splitlines()[1]
    assert "[sprint-42]" in row
    assert "lower thresholds" in row


def test_append_tsv_multiple_rows(tmp_path, monkeypatch) -> None:
    tsv = tmp_path / "results.tsv"
    monkeypatch.setattr(auto_loop, "RESULTS_TSV", tsv)
    auto_loop._ensure_results_tsv()
    for i in range(3):
        auto_loop._append_tsv(
            commit=f"commit{i}",
            eval_score=float(i) / 10,
            task_success=float(i) / 10,
            latency_p95=700,
            tool_error_rate=0.0,
            status="keep",
            description=f"exp {i}",
        )
    lines = tsv.read_text("utf-8").splitlines()
    assert len(lines) == 4  # header + 3 rows


def test_run_evaluate_timeout_returns_zero(monkeypatch) -> None:
    import subprocess
    def fake_run(*args, **kwargs):
        raise subprocess.TimeoutExpired(cmd=args[0], timeout=180)
    monkeypatch.setattr(subprocess, "run", fake_run)
    result = auto_loop._run_evaluate(dry_run=True)
    assert result["eval_score"] == 0.0
    assert result.get("error") == "evaluate.py timed out"


def test_run_evaluate_reads_last_result(tmp_path, monkeypatch) -> None:
    import json
    import subprocess

    state_dir = tmp_path / ".auto-cxas" / "state"
    state_dir.mkdir(parents=True)
    expected = {"eval_score": 0.92, "task_success": 0.9, "latency_ms_p95": 750, "tool_error_rate": 0.05}
    (state_dir / "last_result.json").write_text(json.dumps(expected), "utf-8")

    monkeypatch.setattr(subprocess, "run", lambda *a, **kw: None)
    monkeypatch.chdir(tmp_path)

    result = auto_loop._run_evaluate(dry_run=True)
    assert result["eval_score"] == pytest.approx(0.92)
    assert result["task_success"] == pytest.approx(0.9)


