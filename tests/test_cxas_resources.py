"""Unit tests for CXASResourcesAdapter — mocked, no live GCP."""

from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from auto_cxas_scrapi.adapters.cxas_resources import CXASResourcesAdapter

_APP = "projects/p/locations/global/apps/a"


def test_is_available_false_when_no_package() -> None:
    adapter = CXASResourcesAdapter(full_app_name=_APP)
    with patch.object(adapter, "is_available", return_value=False):
        assert adapter.list_tools() == []
        assert adapter.list_variables() == []
        assert adapter.list_guardrails() == []
        assert adapter.list_versions() == []
        assert adapter.list_deployments() == []


def test_list_tools_mocked() -> None:
    adapter = CXASResourcesAdapter(full_app_name=_APP)
    mock_tool = MagicMock()
    mock_tool.name = f"{_APP}/tools/tool1"
    mock_tool.display_name = "Order Lookup"
    mock_client = MagicMock()
    mock_client.list_tools.return_value = [mock_tool]

    with (
        patch.object(adapter, "is_available", return_value=True),
        patch("auto_cxas_scrapi.adapters.cxas_resources.Tools", return_value=mock_client),
    ):
        tools = adapter.list_tools()

    assert len(tools) == 1
    assert tools[0]["display_name"] == "Order Lookup"


def test_execute_tool_unavailable() -> None:
    adapter = CXASResourcesAdapter(full_app_name=_APP)
    with patch.object(adapter, "is_available", return_value=False):
        result = adapter.execute_tool("order_lookup", args={"id": "123"})
    assert result["available"] is False


def test_snapshot_structure() -> None:
    adapter = CXASResourcesAdapter(full_app_name=_APP)
    with patch.object(adapter, "is_available", return_value=False):
        snap = adapter.snapshot()
    assert "tools" in snap
    assert "variables" in snap
    assert "guardrails" in snap
    assert "versions" in snap
    assert "deployments" in snap
