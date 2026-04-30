"""Unit tests for ScrapiAdapter — no cxas-scrapi installation required."""

from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from auto_cxas_scrapi.adapters.scrapi import ScrapiAdapter, _full_app_name


# ---------------------------------------------------------------------------
# _full_app_name helper
# ---------------------------------------------------------------------------

def test_full_app_name_short() -> None:
    result = _full_app_name("my-proj", "global", "my-app")
    assert result == "projects/my-proj/locations/global/apps/my-app"


def test_full_app_name_already_full() -> None:
    full = "projects/my-proj/locations/global/apps/my-app"
    assert _full_app_name("x", "y", full) == full


# ---------------------------------------------------------------------------
# is_available — graceful degradation when cxas-scrapi is absent
# ---------------------------------------------------------------------------

def test_is_available_false_when_import_fails() -> None:
    adapter = ScrapiAdapter(project_id="proj", location="global", app_name="app")
    with patch.dict(sys.modules, {"cxas_scrapi": None}):
        # When the import raises ImportError, is_available must return False
        with patch("builtins.__import__", side_effect=ImportError):
            assert adapter.is_available() is False


# ---------------------------------------------------------------------------
# get_inventory — fallback when cxas-scrapi unavailable
# ---------------------------------------------------------------------------

def test_get_inventory_unavailable() -> None:
    adapter = ScrapiAdapter(project_id="proj", location="global", app_name="app")
    with patch.object(adapter, "is_available", return_value=False):
        inv = adapter.get_inventory()
    assert inv["available"] is False
    assert "not installed" in inv["reason"]


def test_get_inventory_available() -> None:
    adapter = ScrapiAdapter(project_id="proj", location="global", app_name="app")

    mock_apps = MagicMock()
    mock_apps.get_apps_map.return_value = {"projects/proj/locations/global/apps/app": "My App"}

    mock_agents = MagicMock()
    mock_agents.get_agents_map.return_value = {"projects/proj/locations/global/apps/app/agents/a1": "Agent 1"}

    with patch.object(adapter, "is_available", return_value=True):
        with patch("auto_cxas_scrapi.adapters.scrapi.Apps", return_value=mock_apps):
            with patch("auto_cxas_scrapi.adapters.scrapi.Agents", return_value=mock_agents):
                inv = adapter.get_inventory()

    assert inv["available"] is True
    assert inv["apps_count"] == 1
    assert inv["agents_count"] == 1
    assert "My App" in inv["apps"]


# ---------------------------------------------------------------------------
# run_lint — fallback
# ---------------------------------------------------------------------------

def test_run_lint_unavailable() -> None:
    adapter = ScrapiAdapter(project_id="proj", location="global", app_name="app")
    with patch.object(adapter, "is_available", return_value=False):
        result = adapter.run_lint()
    assert result["lint_passed"] is False


# ---------------------------------------------------------------------------
# run_simulation_eval — fallback + aggregation
# ---------------------------------------------------------------------------

def test_run_simulation_eval_no_cases() -> None:
    adapter = ScrapiAdapter(project_id="proj", location="global", app_name="app")
    with patch.object(adapter, "is_available", return_value=True):
        result = adapter.run_simulation_eval(test_cases=[])
    assert result["available"] is False


def test_run_simulation_eval_aggregates() -> None:
    adapter = ScrapiAdapter(project_id="proj", location="global", app_name="app")

    mock_sim = MagicMock()
    mock_sim.run_simulations.return_value = [
        {"name": "tc1", "passed": True, "duration_s": 1.2},
        {"name": "tc2", "passed": False, "duration_s": 2.5},
        {"name": "tc3", "passed": True, "duration_s": 0.9},
    ]

    test_cases = [{"name": "tc1"}, {"name": "tc2"}, {"name": "tc3"}]

    with patch.object(adapter, "is_available", return_value=True):
        with patch("auto_cxas_scrapi.adapters.scrapi.SimulationEvals", return_value=mock_sim):
            result = adapter.run_simulation_eval(test_cases=test_cases)

    assert result["available"] is True
    assert result["total"] == 3
    assert result["passed"] == 2
    assert abs(result["task_success"] - 2 / 3) < 0.001
