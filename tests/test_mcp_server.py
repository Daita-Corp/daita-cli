"""Tests for MCP server tool handlers."""

import json
import pytest
import respx
import httpx

from daita_cli.mcp_server import call_tool, list_tools


@pytest.mark.asyncio
async def test_list_tools_returns_all():
    tools = await list_tools()
    names = {t.name for t in tools}
    assert "list_agents" in names
    assert "run_agent" in names
    assert "get_trace" in names
    assert "list_secrets" in names
    assert "init_project" in names


@pytest.mark.asyncio
async def test_list_agents_tool(monkeypatch):
    monkeypatch.setenv("DAITA_API_KEY", "test-key")
    with respx.mock(base_url="https://api.daita-tech.io") as mock:
        mock.get("/api/v1/agents/agents").mock(
            return_value=httpx.Response(200, json={"agents": [{"id": "a1", "name": "my_agent"}]})
        )
        result = await call_tool("list_agents", {})
    assert len(result) == 1
    data = json.loads(result[0].text)
    assert "agents" in data


@pytest.mark.asyncio
async def test_missing_api_key_returns_error():
    import os
    old = os.environ.pop("DAITA_API_KEY", None)
    try:
        result = await call_tool("list_agents", {})
        data = json.loads(result[0].text)
        assert data.get("error") is True
    finally:
        if old:
            os.environ["DAITA_API_KEY"] = old


@pytest.mark.asyncio
async def test_unknown_tool_returns_error(monkeypatch):
    monkeypatch.setenv("DAITA_API_KEY", "test-key")
    with respx.mock(base_url="https://api.daita-tech.io"):
        result = await call_tool("nonexistent_tool", {})
    data = json.loads(result[0].text)
    assert data.get("error") is True


@pytest.mark.asyncio
async def test_local_tool_without_framework(monkeypatch):
    """test_agent should return a clear error when daita-agents is not installed."""
    import daita_cli.mcp_server as mcp

    # Patch _require_framework_mcp to simulate absence of daita-agents
    monkeypatch.setattr(mcp, "_require_framework_mcp", lambda: False)
    result = await call_tool("test_agent", {})
    data = json.loads(result[0].text)
    assert data.get("error") is True
    assert "daita-agents" in data.get("detail", "")
