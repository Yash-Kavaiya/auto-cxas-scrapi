"""Unit tests for CXASEvalsAdapter — mocked, no live GCP."""

from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from auto_cxas_scrapi.adapters.cxas_evals import CXASEvalsAdapter

_APP = "projects/p/locations/global/apps/a"


# ------------------------------------------------------------------
# Availability
# ------------------------------------------------------------------

def test_is_unavailable_returns_false() -> None:
    adapter = CXASEvalsAdapter(full_app_name=_APP)
    with patch.object(adapter, "is_available", return_value=False):
        assert adapter.run_simulation_evals([])["available"] is False
        assert adapter.run_tool_evals([])["available"] is False
        assert adapter.run_guardrail_evals([])["available"] is False
        assert adapter.run_turn_evals([])["available"] is False
        assert adapter.run_callback_evals([])["available"] is False


# ------------------------------------------------------------------
# SimulationEvals
# ------------------------------------------------------------------

def test_simulation_evals_pass_rate() -> None:
    adapter = CXASEvalsAdapter(full_app_name=_APP)
    mock_client = MagicMock()
    mock_client.run_simulations.return_value = [
        {"name": "tc1", "passed": True,  "duration_s": 1.0},
        {"name": "tc2", "passed": True,  "duration_s": 2.0},
        {"name": "tc3", "passed": False, "duration_s": 3.0},
    ]
    with (
        patch.object(adapter, "is_available", return_value=True),
        patch("auto_cxas_scrapi.adapters.cxas_evals.SimulationEvals", return_value=mock_client),
    ):
        result = adapter.run_simulation_evals([{"name": "tc1"}, {"name": "tc2"}, {"name": "tc3"}])

    assert result["available"] is True
    assert result["total"] == 3
    assert result["passed"] == 2
    assert result["pass_rate"] == pytest.approx(2 / 3, rel=1e-3)
    assert result["eval_type"] == "simulation"


def test_simulation_evals_p95_latency() -> None:
    adapter = CXASEvalsAdapter(full_app_name=_APP)
    mock_client = MagicMock()
    mock_client.run_simulations.return_value = [
        {"passed": True, "duration_s": i * 0.1} for i in range(1, 21)
    ]
    with (
        patch.object(adapter, "is_available", return_value=True),
        patch("auto_cxas_scrapi.adapters.cxas_evals.SimulationEvals", return_value=mock_client),
    ):
        result = adapter.run_simulation_evals([{"name": f"tc{i}"} for i in range(20)])

    assert result["latency_ms_p95"] > 0


# ------------------------------------------------------------------
# ToolEvals
# ------------------------------------------------------------------

def test_tool_evals_aggregation() -> None:
    adapter = CXASEvalsAdapter(full_app_name=_APP)
    mock_client = MagicMock()
    mock_client.run_evals.return_value = [
        {"result": "PASS"},
        {"result": "PASS"},
        {"result": "FAIL"},
    ]
    with (
        patch.object(adapter, "is_available", return_value=True),
        patch("auto_cxas_scrapi.adapters.cxas_evals.ToolEvals", return_value=mock_client),
    ):
        result = adapter.run_tool_evals([{"tool_name": "t"}])

    assert result["eval_type"] == "tool"
    assert result["passed"] == 2
    assert result["pass_rate"] == pytest.approx(2 / 3, rel=1e-3)


# ------------------------------------------------------------------
# GuardrailEvals
# ------------------------------------------------------------------

def test_guardrail_evals_aggregation() -> None:
    adapter = CXASEvalsAdapter(full_app_name=_APP)
    mock_client = MagicMock()
    mock_client.run_evals.return_value = [
        {"passed": True}, {"passed": True}, {"passed": True},
    ]
    with (
        patch.object(adapter, "is_available", return_value=True),
        patch("auto_cxas_scrapi.adapters.cxas_evals.GuardrailEvals", return_value=mock_client),
    ):
        result = adapter.run_guardrail_evals([{"utterance": "u"}])

    assert result["eval_type"] == "guardrail"
    assert result["pass_rate"] == 1.0


# ------------------------------------------------------------------
# TurnEvals
# ------------------------------------------------------------------

def test_turn_evals_aggregation() -> None:
    adapter = CXASEvalsAdapter(full_app_name=_APP)
    mock_client = MagicMock()
    mock_client.run_evals.return_value = [{"passed": True}, {"passed": False}]
    with (
        patch.object(adapter, "is_available", return_value=True),
        patch("auto_cxas_scrapi.adapters.cxas_evals.TurnEvals", return_value=mock_client),
    ):
        result = adapter.run_turn_evals([{}])

    assert result["eval_type"] == "turn"
    assert result["pass_rate"] == 0.5


# ------------------------------------------------------------------
# CallbackEvals
# ------------------------------------------------------------------

def test_callback_evals_aggregation() -> None:
    adapter = CXASEvalsAdapter(full_app_name=_APP)
    mock_client = MagicMock()
    mock_client.run_evals.return_value = [{"result": "PASS"}, {"result": "PASS"}]
    with (
        patch.object(adapter, "is_available", return_value=True),
        patch("auto_cxas_scrapi.adapters.cxas_evals.CallbackEvals", return_value=mock_client),
    ):
        result = adapter.run_callback_evals([{}])

    assert result["eval_type"] == "callback"
    assert result["pass_rate"] == 1.0


# ------------------------------------------------------------------
# Empty datasets
# ------------------------------------------------------------------

def test_empty_dataset_returns_zero_pass_rate() -> None:
    adapter = CXASEvalsAdapter(full_app_name=_APP)
    mock_client = MagicMock()
    mock_client.run_simulations.return_value = []
    with (
        patch.object(adapter, "is_available", return_value=True),
        patch("auto_cxas_scrapi.adapters.cxas_evals.SimulationEvals", return_value=mock_client),
    ):
        result = adapter.run_simulation_evals([{"name": "tc1"}])
    assert result["pass_rate"] == 0.0
    assert result["total"] == 0
